from __future__ import annotations

import asyncio
import asyncpg
import logging
import random
import time
from datetime import datetime, timezone

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
    """Пишем входящее сообщение в tg_history (как в твоём импортере)."""
    global _pg_pool
    if _pg_pool is None:
        return

    try:
        chat_id = int(message.chat.id)
        msg_id = int(message.message_id)

        # aiogram Message.date обычно datetime с tz, но на всякий:
        dt = message.date
        if isinstance(dt, datetime) and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        from_name = None
        from_id = None
        if message.from_user:
            from_id = str(message.from_user.id)
            from_name = (message.from_user.full_name or message.from_user.username or "").strip() or None

        text = (message.text or "").strip()
        if not text:
            return

        await _pg_pool.execute(
            """
            INSERT INTO tg_history (chat_id, msg_id, dt, from_name, from_id, text)
            VALUES ($1,$2,$3,$4,$5,$6)
            ON CONFLICT (chat_id, msg_id) DO NOTHING
            """,
            chat_id, msg_id, dt, from_name, from_id, text
        )
    except Exception as e:
        logging.debug(f"save_and_index error: {e}")


async def build_context_24h(chat_id: int) -> str:
    """Память: последние сообщения за 24 часа, обрезанные по длине."""
    global _pg_pool
    if _pg_pool is None:
        return ""

    try:
        rows = await _pg_pool.fetch(
            """
            SELECT dt, from_name, text
            FROM tg_history
            WHERE chat_id = $1
              AND dt >= (NOW() - INTERVAL '24 hours')
            ORDER BY dt DESC
            LIMIT $2
            """,
            int(chat_id),
            int(getattr(settings, "MEMORY_24H_LIMIT", 70)),
        )
    except Exception as e:
        logging.debug(f"build_context_24h db error: {e}")
        return ""

    if not rows:
        return ""

    # хотим хронологию: старое -> новое
    rows = list(reversed(rows))

    max_chars = int(getattr(settings, "MEMORY_24H_MAX_CHARS", 6500))
    parts: list[str] = []
    cur = 0

    for r in rows:
        frm = (r["from_name"] or "кто-то").strip()
        txt = (r["text"] or "").strip().replace("\n", " ")
        if not txt:
            continue
        line = f"{frm}: {txt}"
        if cur + len(line) + 1 > max_chars:
            break
        parts.append(line)
        cur += len(line) + 1

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
    # работаем только в целевой группе
    if int(message.chat.id) != int(settings.TARGET_GROUP_ID):
        return

    text = (message.text or "").strip()
    if not text:
        return

    uid = message.from_user.id if message.from_user else None
    is_owner = (uid == settings.OWNER_USER_ID)

    # сохраняем ВСЁ в память
    await save_and_index(message)

    # владелец пишет — бот молчит (по твоему требованию)
    if is_owner and not bool(getattr(settings, "REPLY_TO_OWNER", False)):
        return

    text_l = text.lower()

    # режим защиты владельца
    owner_mentioned = False
    if settings.OWNER_DEFENSE_MODE and settings.DEFEND_ON_MENTION:
        owner_mentioned = any(h.lower() in text_l for h in getattr(settings, "OWNER_HANDLES", []))

    reply_to_owner = False
    if settings.OWNER_DEFENSE_MODE and settings.DEFEND_ON_REPLY_TO_OWNER:
        if message.reply_to_message and message.reply_to_message.from_user:
            reply_to_owner = (message.reply_to_message.from_user.id == settings.OWNER_USER_ID)

    mode = "defend_owner" if (owner_mentioned or reply_to_owner) else "normal"

    # упоминание бота / reply-to-bot => отвечаем всегда
    me = await bot.get_me()
    bot_username = (me.username or "").lower()
    bot_id = me.id

    mention_bot = bool(bot_username) and (f"@{bot_username}" in text_l)
    reply_to_bot = bool(message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == bot_id)
    is_mention = mention_bot or reply_to_bot

    # антиспам + вероятность (но почти всегда)
    now = time.time()
    chat_id = int(message.chat.id)
    emoji = pick_reaction(text)

    must_reply = is_mention or (mode == "defend_owner")

    if not must_reply:
        last = _last_reply_ts.get(chat_id, 0.0)
        if now - last < float(getattr(settings, "REPLY_COOLDOWN_SEC", 8)):
            if random.random() < float(getattr(settings, "REACT_PROB_WHEN_SILENT", 0.35)):
                await react(bot, message, emoji)
            return

        if random.random() > float(getattr(settings, "REPLY_PROB_NORMAL", 0.92)):
            if random.random() < float(getattr(settings, "REACT_PROB_WHEN_SILENT", 0.35)):
                await react(bot, message, emoji)
            return

    _last_reply_ts[chat_id] = now

    # память за 24 часа
    ctx = await build_context_24h(chat_id)

    # иногда только реакция (как человек), особенно если тегнули бота
    if should_react_only(is_mention, mode):
        await react(bot, message, emoji)
        return

    # иногда гифка
    if getattr(settings, "GIPHY_API_KEY", ""):
        p = float(getattr(settings, "GIPHY_PROB", 0.22))
        if mode == "defend_owner":
            p = min(0.55, p * 1.8)

        if random.random() < p:
            q = " ".join(text.split()[:5]) or "reaction"
            gif_url = await search_gif(q)  # у тебя giphy.py уже “не падает”
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

    # текстовый ответ
    raw = generate_reply(user_text=text, context_snippets=ctx, mode=mode).get("_raw", "")
    out_text = raw

    try:
        await message.reply(out_text)
    except Exception as e:
        logging.error(f"send error: {e}")


async def spontaneous_loop(bot: Bot) -> None:
    """Иногда сам начинает разговор (в пределах заданной вероятности)."""
    while True:
        await asyncio.sleep(
            random.randint(
                int(getattr(settings, "SPONTANEOUS_MIN_SEC", 180)),
                int(getattr(settings, "SPONTANEOUS_MAX_SEC", 540)),
            )
        )

        if random.random() > float(getattr(settings, "SPONTANEOUS_PROB", 0.12)):
            continue

        try:
            text = generate_reply(user_text="", context_snippets=await build_context_24h(int(settings.TARGET_GROUP_ID)), mode="normal").get("_raw", "")
            if text:
                await bot.send_message(int(settings.TARGET_GROUP_ID), text)
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
