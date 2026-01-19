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
from .ai import generate_reply, analyze_image
from .reactions import pick_reaction, should_react_only
from .services.giphy import search_gif

_pg_pool: asyncpg.Pool | None = None
_last_reply_ts: dict[int, float] = {}

logging.basicConfig(level=logging.INFO)


async def save_and_index(message: Message) -> None:
    """Пишем входящее сообщение в tg_history."""
    global _pg_pool
    if _pg_pool is None:
        return

    try:
        chat_id = int(message.chat.id)
        msg_id = int(message.message_id)

        dt = message.date
        if isinstance(dt, datetime) and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        from_name = None
        from_id = None
        if message.from_user:
            from_id = str(message.from_user.id)
            from_name = (message.from_user.full_name or message.from_user.username or "").strip() or None

        # сохраняем текст/подпись; если фото без подписи — отметим, что было фото
        text = (message.text or "").strip()
        if not text and getattr(message, "caption", None):
            text = (message.caption or "").strip()
        if not text:
            if getattr(message, "photo", None):
                text = "[photo]"
            else:
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


def _owner_defense_mode_for_text(text: str, message: Message) -> str:
    text_l = (text or "").lower()

    owner_mentioned = False
    if settings.OWNER_DEFENSE_MODE and settings.DEFEND_ON_MENTION:
        owner_mentioned = any(h.lower() in text_l for h in getattr(settings, "OWNER_HANDLES", []))

    reply_to_owner = False
    if settings.OWNER_DEFENSE_MODE and settings.DEFEND_ON_REPLY_TO_OWNER:
        if message.reply_to_message and message.reply_to_message.from_user:
            reply_to_owner = (message.reply_to_message.from_user.id == settings.OWNER_USER_ID)

    return "defend_owner" if (owner_mentioned or reply_to_owner) else "normal"


async def _compute_is_mention(bot: Bot, message: Message, text: str) -> bool:
    me = await bot.get_me()
    bot_username = (me.username or "").lower()
    bot_id = me.id

    text_l = (text or "").lower()
    mention_bot = bool(bot_username) and (f"@{bot_username}" in text_l)
    reply_to_bot = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id == bot_id
    )
    return mention_bot or reply_to_bot


async def _gate_reply(bot: Bot, message: Message, mode: str, is_mention: bool, emoji: str) -> bool:
    """
    Возвращает True если надо отвечать (текст/гиф/vision).
    Если False — иногда ставит реакцию и молчит.
    """
    uid = message.from_user.id if message.from_user else None
    is_owner = (uid == settings.OWNER_USER_ID)

    # владелец пишет — бот молчит (по твоему требованию)
    if is_owner and not bool(getattr(settings, "REPLY_TO_OWNER", False)):
        return False

    now = time.time()
    chat_id = int(message.chat.id)

    must_reply = is_mention or (mode == "defend_owner")
    if must_reply:
        return True

    last = _last_reply_ts.get(chat_id, 0.0)
    if now - last < float(getattr(settings, "REPLY_COOLDOWN_SEC", 8)):
        if random.random() < float(getattr(settings, "REACT_PROB_WHEN_SILENT", 0.35)):
            await react(bot, message, emoji)
        return False

    if random.random() > float(getattr(settings, "REPLY_PROB_NORMAL", 0.92)):
        if random.random() < float(getattr(settings, "REACT_PROB_WHEN_SILENT", 0.35)):
            await react(bot, message, emoji)
        return False

    return True


async def on_text(message: Message, bot: Bot) -> None:
    if int(message.chat.id) != int(settings.TARGET_GROUP_ID):
        return

    text = (message.text or "").strip()
    if not text:
        return

    await save_and_index(message)

    mode = _owner_defense_mode_for_text(text, message)
    emoji = pick_reaction(text)
    is_mention = await _compute_is_mention(bot, message, text)

    should = await _gate_reply(bot, message, mode, is_mention, emoji)
    if not should:
        return

    _last_reply_ts[int(message.chat.id)] = time.time()

    ctx = await build_context_24h(int(message.chat.id))

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
            gif_url = await search_gif(q)
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

    raw = generate_reply(user_text=text, context_snippets=ctx, mode=mode).get("_raw", "")
    try:
        await message.reply(raw)
    except Exception as e:
        logging.error(f"send error: {e}")


async def on_photo(message: Message, bot: Bot) -> None:
    # вариант A: если есть подпись — анализируем всегда; если нет — иногда
    if int(message.chat.id) != int(settings.TARGET_GROUP_ID):
        return
    if not message.photo:
        return

    await save_and_index(message)

    caption = (message.caption or "").strip()
    mode = _owner_defense_mode_for_text(caption, message) if caption else "normal"
    emoji = pick_reaction(caption or "photo")
    is_mention = await _compute_is_mention(bot, message, caption or "")

    # владелец прислал фото — молчим (но в память записали)
    uid = message.from_user.id if message.from_user else None
    if uid == settings.OWNER_USER_ID and not bool(getattr(settings, "REPLY_TO_OWNER", False)):
        return

    should = await _gate_reply(bot, message, mode, is_mention, emoji)
    if not should:
        return

    # Если подписи нет — комментим только иногда (чтобы не быть навязчивым)
    if not caption:
        if random.random() > 0.35:
            # иногда просто реакция
            if random.random() < float(getattr(settings, "REACT_PROB_WHEN_SILENT", 0.35)):
                await react(bot, message, emoji)
            return

    _last_reply_ts[int(message.chat.id)] = time.time()

    ctx = await build_context_24h(int(message.chat.id))

    # скачиваем картинку
    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        buf = await bot.download_file(file.file_path)
        image_bytes = buf.read()
    except Exception as e:
        logging.debug(f"download photo error: {e}")
        # fallback: хотя бы текстом
        raw = generate_reply(
            user_text=(caption or "на фотке что-то, но я не смог скачать"),
            context_snippets=ctx,
            mode=mode,
        ).get("_raw", "")
        await message.reply(raw)
        return

    # анализ vision
    try:
        raw = analyze_image(
            image_bytes=image_bytes,
            caption_text=caption,
            context_snippets=ctx,
            mode=mode,
        ).get("_raw", "")
    except Exception as e:
        logging.debug(f"vision error: {e}")
        raw = generate_reply(
            user_text=(caption or "чё за картинка вообще"),
            context_snippets=ctx,
            mode=mode,
        ).get("_raw", "")

    try:
        await message.reply(raw)
    except Exception as e:
        logging.error(f"send error: {e}")


async def spontaneous_loop(bot: Bot) -> None:
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
            ctx = await build_context_24h(int(settings.TARGET_GROUP_ID))
            text = generate_reply(user_text="", context_snippets=ctx, mode="normal").get("_raw", "")
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
    dp.message.register(on_photo, F.photo)

    logging.info("Balbes автономный стартанул")

    asyncio.create_task(spontaneous_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
