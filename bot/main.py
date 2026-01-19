from __future__ import annotations

import asyncio
import asyncpg
import re
import logging
import random
import time

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReactionTypeEmoji

from .settings import settings
from .ai import generate_reply
from .reactions import pick_reaction, should_react_only

from .services.giphy import search_gif

_pg_pool: asyncpg.Pool | None = None
_last_reply_ts: dict[int, float] = {}

logging.basicConfig(level=logging.INFO)


async def save_and_index(message: Message) -> None:
    return


def _keywords(s: str) -> str:
    ws = re.findall(r"[A-Za-zА-Яа-яЁё0-9_]{3,}", s.lower())
    return " ".join(ws[:8])


async def build_context(user_text: str) -> str:
    global _pg_pool
    if _pg_pool is None:
        return ""

    q = _keywords(user_text)
    if not q:
        return ""

    rows = await _pg_pool.fetch(
        """
        SELECT dt, from_name, text
        FROM tg_history
        WHERE chat_id = $1
          AND to_tsvector('russian', coalesce(text,'')) @@ plainto_tsquery('russian', $2)
        ORDER BY dt DESC
        LIMIT 20
        """,
        settings.TARGET_GROUP_ID,
        q,
    )

    if not rows:
        rows = await _pg_pool.fetch(
            """
            SELECT dt, from_name, text
            FROM tg_history
            WHERE chat_id = $1
              AND text ILIKE '%' || $2 || '%'
            ORDER BY dt DESC
            LIMIT 10
            """,
            settings.TARGET_GROUP_ID,
            user_text[:64],
        )

    parts = []
    for r in rows:
        dt = r["dt"].isoformat() if r["dt"] else ""
        frm = r["from_name"] or "кто-то"
        txt = (r["text"] or "").strip()[:300]
        parts.append(f"{dt} — {frm}: {txt}")

    return "\n".join(parts)


async def react(bot: Bot, message: Message, emoji: str) -> None:
    try:
        await bot.set_message_reaction(
            chat_id=message.chat.id,
            message_id=message.message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception as e:
        logging.debug(f"reaction error: {e}")


async def on_text(message: Message, bot: Bot) -> None:
    text = (message.text or "").strip()
    if not text:
        return

    uid = message.from_user.id if message.from_user else None
    is_owner = (uid == settings.OWNER_USER_ID)

    text_l = text.lower()

    owner_mentioned = False
    if settings.OWNER_DEFENSE_MODE and settings.DEFEND_ON_MENTION:
        owner_mentioned = any(h.lower() in text_l for h in getattr(settings, "OWNER_HANDLES", []))

    reply_to_owner = False
    if settings.OWNER_DEFENSE_MODE and settings.DEFEND_ON_REPLY_TO_OWNER:
        if message.reply_to_message and message.reply_to_message.from_user:
            reply_to_owner = (message.reply_to_message.from_user.id == settings.OWNER_USER_ID)

    target_owner = owner_mentioned or reply_to_owner

    mode = "normal"
    if is_owner:
        mode = "owner"
    elif target_owner:
        mode = "defend_owner"

    await save_and_index(message)

    # ---- proper "mention": mention bot OR reply-to-bot ----
    me = await bot.get_me()
    bot_username = (me.username or "").lower()
    bot_id = me.id

    mention_bot = bool(bot_username) and (f"@{bot_username}" in text_l)

    reply_to_bot = False
    if message.reply_to_message and message.reply_to_message.from_user:
        reply_to_bot = (message.reply_to_message.from_user.id == bot_id)

    is_mention = mention_bot or reply_to_bot

    # ---- gate: bot chooses when to reply ----
    must_reply = False
    if is_mention:
        must_reply = True
    if mode == "owner" and settings.ALWAYS_REPLY_OWNER:
        must_reply = True
    if mode == "defend_owner" and settings.ALWAYS_REPLY_DEFEND_OWNER:
        must_reply = True

    now = time.time()
    chat_id = message.chat.id
    emoji = pick_reaction(text)

    if not must_reply:
        last = _last_reply_ts.get(chat_id, 0.0)
        # cooldown gate
        if now - last < float(settings.REPLY_COOLDOWN_SEC):
            if random.random() < float(settings.REACT_PROB_WHEN_SILENT):
                await react(bot, message, emoji)
            return

        # probability gate
        if random.random() > float(settings.REPLY_PROB_NORMAL):
            if random.random() < float(settings.REACT_PROB_WHEN_SILENT):
                await react(bot, message, emoji)
            return

    # мы решили отвечать
    _last_reply_ts[chat_id] = now

    ctx = await build_context(text)

    # ---- optional: sometimes react-only when directly pinged ----
    if should_react_only(is_mention):
        await react(bot, message, emoji)
        return

    # ---- try send GIF (never crash update) ----
    if getattr(settings, "GIPHY_API_KEY", ""):
        p = float(getattr(settings, "GIPHY_PROB", 0.18))
        if mode == "defend_owner":
            p = min(0.45, p * 2.0)

        if random.random() < p:
            q = " ".join(text.split()[:5]) or "reaction"
            gif_url = await search_gif(q)  # inside giphy.py errors become None
            if gif_url:
                try:
                    await bot.send_animation(
                        chat_id=message.chat.id,
                        animation=gif_url,
                        reply_to_message_id=message.message_id,
                    )
                    return
                except Exception as e:
                    logging.debug(f"send_animation error: {e}")

    # ---- text reply ----
    raw = generate_reply(user_text=text, context_snippets=ctx, mode=mode).get("_raw", "")
    out_text = raw

    # if model returns ```json {...}``` extract
    try:
        import json as _json, re as _re
        m = _re.search(r"```json\s*(\{.*?\})\s*```", raw, flags=_re.S)
        if m:
            obj = _json.loads(m.group(1))
            out_text = obj.get("content") or obj.get("text") or raw
    except Exception:
        pass

    try:
        await message.reply(out_text)
    except Exception as e:
        logging.error(f"send error: {e}")


async def spontaneous_loop(bot: Bot) -> None:
    while True:
        await asyncio.sleep(
            random.randint(
                settings.SPONTANEOUS_MIN_SEC,
                settings.SPONTANEOUS_MAX_SEC,
            )
        )

        if random.random() > settings.SPONTANEOUS_PROB:
            continue

        try:
            text = generate_reply(user_text="", context_snippets="", mode="normal").get("_raw", "")
            if text:
                await bot.send_message(settings.TARGET_GROUP_ID, text)
        except Exception as e:
            logging.debug(f"spontaneous error: {e}")


async def main() -> None:
    bot = Bot(token=settings.BOT_TOKEN)

    global _pg_pool
    _pg_pool = await asyncpg.create_pool(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        min_size=1,
        max_size=5,
    )

    dp = Dispatcher()
    dp.message.register(on_text, F.text)

    logging.info("Balbes автономный стартанул")

    asyncio.create_task(spontaneous_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
