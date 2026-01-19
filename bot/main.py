from __future__ import annotations

import asyncio
import asyncpg
import re
import logging
import random
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReactionTypeEmoji

from .settings import settings
from .ai import decide_reply, generate_reply
from .reactions import (
    pick_reaction,
    should_react_only,
    should_react_alongside_text,
)

_pg_pool: asyncpg.Pool | None = None

logging.basicConfig(level=logging.INFO)


# =========================
# DB / MEMORY (ВРЕМЕННО ВЫКЛЮЧЕНО)
# =========================

async def save_and_index(message: Message) -> None:
    """
    Временно отключено.
    Оставлено для совместимости архитектуры.
    """
    return


def _keywords(s: str) -> str:
    # берём слова длиннее 2 символов, ограничим 8
    ws = re.findall(r"[A-Za-zА-Яа-яЁё0-9_]{3,}", s.lower())
    ws = ws[:8]
    return " ".join(ws)

async def build_context(user_text: str) -> str:
    global _pg_pool
    if _pg_pool is None:
        return ""

    q = _keywords(user_text)
    if not q:
        return ""

    # FTS: ищем топ релевантных
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
        # запасной вариант: ILIKE по фразе (если FTS ничего не нашёл)
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

    # форматируем “воспоминания”
    parts = []
    for r in rows:
        dt = r["dt"].isoformat() if r["dt"] else ""
        frm = r["from_name"] or "кто-то"
        txt = (r["text"] or "").strip()
        txt = txt[:300]
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


# =========================
# MESSAGE HANDLER
# =========================

async def on_text(message: Message, bot: Bot) -> None:
    text = (message.text or "").strip()
    if not text:
        return

    # сохраняем сообщение (пока пустышка)
    await save_and_index(message)

    is_mention = (
        message.from_user
        and message.from_user.username
        and f"@{message.from_user.username}" in text
    )

    ctx = await build_context(text)
    
    ok = True
    #ok = decide_reply(
    #    last_text=text,
    #    is_mention=is_mention,
    #    context_snippets=ctx,
   # )

  #  if not ok:
   #     return

    emoji = pick_reaction(text)

    # 1) иногда ТОЛЬКО реакция
    if should_react_only(is_mention):
        await react(bot, message, emoji)
        return

   # 2) генерим ответ
    ctx = await build_context(text)
    raw = generate_reply(user_text=text, context_snippets=ctx).get("_raw", "")

    # ✅ нормализуем: если пришёл JSON-блок — достаём content
    out_text = raw
    try:
        import json, re
        m = re.search(r"```json\s*(\{.*?\})\s*```", raw, flags=re.S)
        if m:
            obj = json.loads(m.group(1))
            out_text = obj.get("content") or obj.get("text") or raw
    except Exception:
        pass

    # отправка
    try:
        await message.reply(out_text)
    except Exception as e:
        logging.error(f"send error: {e}")


# =========================
# SPONTANEOUS MODE
# =========================

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
            text = generate_reply(
                user_text="",
                context_snippets="",
            ).get("_raw", "")

            if text:
                await bot.send_message(settings.TARGET_GROUP_ID, text)
        except Exception as e:
            logging.debug(f"spontaneous error: {e}")


# =========================
# MAIN
# =========================

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
