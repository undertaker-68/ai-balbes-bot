from __future__ import annotations

import asyncio
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


async def build_context(user_text: str) -> str:
    """
    Временно без памяти.
    """
    return ""


# =========================
# REACTIONS
# =========================

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

    ok = decide_reply(
        last_text=text,
        is_mention=is_mention,
        context_snippets=ctx,
    )

    if not ok:
        return

    emoji = pick_reaction(text)

    # 1) иногда ТОЛЬКО реакция
    if should_react_only(is_mention):
        await react(bot, message, emoji)
        return

    # 2) генерим ответ
    ctx = await build_context(text)
    raw = generate_reply(
        user_text=text,
        context_snippets=ctx,
    ).get("_raw", "")

    # отправка
    try:
        await message.reply(raw)
    except Exception as e:
        logging.error(f"send error: {e}")

    # 3) иногда реакция ПОСЛЕ текста
    if should_react_alongside_text(is_mention):
        await react(bot, message, emoji)


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
    dp = Dispatcher()

    dp.message.register(on_text, F.text)

    logging.info("Balbes автономный стартанул")

    asyncio.create_task(spontaneous_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
