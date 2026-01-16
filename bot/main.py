from __future__ import annotations

import asyncio
import json
import logging
import random

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from sqlalchemy import select

from aiogram.types import ReactionTypeEmoji
from .reactions import pick_reaction, should_react_only, should_react_alongside_text

from .settings import settings
from .db import engine, SessionLocal
from .models import Base, MessageRow
from .ai import embed, decide_reply, generate_reply
from .rag import ensure_collection, upsert, search as rag_search
from .generator import (
    send_generated_image,
    send_generated_voice,
    send_generated_animation,
    send_generated_video,
    send_generated_video_note,
)

logging.basicConfig(level=logging.INFO)


def _is_target_group(m: Message) -> bool:
    return bool(m.chat and m.chat.id == settings.TARGET_GROUP_ID)


def _is_owner(m: Message) -> bool:
    return bool(m.from_user and m.from_user.id == settings.OWNER_USER_ID)


def _mentioned(bot_username: str | None, text: str) -> bool:
    return bool(bot_username and f"@{bot_username}" in (text or ""))


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def save_and_index(message: Message):
    text = (message.text or "").strip()
    if not text:
        return

    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None

    async with SessionLocal() as session:
        row = MessageRow(chat_id=message.chat.id, user_id=user_id, username=username, text=text)
        session.add(row)
        await session.flush()
        row_id = row.id
        await session.commit()

    vec = embed(text)
    ensure_collection(vector_size=len(vec))
    upsert(point_id=row_id, vector=vec, payload={"text": text, "user_id": user_id, "username": username})


async def build_context(user_text: str) -> str:
    vec = embed(user_text)
    hits = rag_search(vec, limit=8)
    lines = []
    for h in hits:
        t = (h.get("text") or "").strip()
        if not t:
            continue
        who = h.get("username") or h.get("user_id") or "someone"
        lines.append(f"- {who}: {t}")
    return "\n".join(lines).strip()


def _parse_action(raw: str) -> dict:
    raw = (raw or "").strip()
    # иногда модель оборачивает в ```json ... ```
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # fallback
    return {"type": "text", "text": raw or "…"}


async def act(bot: Bot, chat_id: int, action: dict):
    t = (action.get("type") or "text").lower()

    if t == "image":
        prompt = action.get("prompt") or action.get("text") or "мемная картинка про чат друзей"
        await send_generated_image(bot, chat_id, str(prompt))
        return

    if t == "voice":
        txt = action.get("text") or "угу"
        await send_generated_voice(bot, chat_id, str(txt))
        return

    if t == "gif" or t == "animation":
        prompt = action.get("prompt") or action.get("text") or "мемная анимация про чат друзей"
        await send_generated_animation(bot, chat_id, str(prompt))
        return

    if t == "video":
        prompt = action.get("prompt") or "короткое мемное видео про чат друзей"
        narration = action.get("text")  # если есть текст — используем как озвучку
        await send_generated_video(bot, chat_id, str(prompt), narration_text=narration)
        return

    if t == "video_note" or t == "circle":
        prompt = action.get("prompt") or "кружок-реакция, мемный стиль, про чат друзей"
        narration = action.get("text")
        await send_generated_video_note(bot, chat_id, str(prompt), narration_text=narration)
        return

    # text default
    txt = action.get("text") or action.get("_raw") or "…"
    await bot.send_message(chat_id, str(txt))


async def spontaneous_loop(bot: Bot):
    # Самостоятельные “вбросы” бота
    while True:
        await asyncio.sleep(random.randint(settings.SPONTANEOUS_MIN_SEC, settings.SPONTANEOUS_MAX_SEC))
        if not settings.AUTONOMY_ENABLED:
            continue
        if random.random() > settings.SPONTANEOUS_PROB:
            continue

        # Берём немного последних сообщений, чтобы было “в тему”
        async with SessionLocal() as session:
            q = (
                select(MessageRow)
                .where(MessageRow.chat_id == settings.TARGET_GROUP_ID)
                .order_by(MessageRow.id.desc())
                .limit(25)
            )
            rows = (await session.execute(q)).scalars().all()

        seed = "\n".join([f"{r.username or r.user_id}: {r.text}" for r in reversed(rows)])
        prompt = (
            "Ты сейчас сам решил написать в чат друзей.\n"
            "Скажи что-то уместное по последним сообщениям.\n"
            "Если нечего сказать — можешь вообще не писать.\n\n"
            f"Последнее:\n{seed}"
        )

        ctx = await build_context(seed[-500:] if seed else "чат")
        raw = generate_reply(user_text=prompt, context_snippets=ctx).get("_raw", "")
        action = _parse_action(raw)

        # если модель “решила молчать” — пусть вернёт пустой text
        if (action.get("type") == "text") and not (action.get("text") or "").strip():
            continue

        await act(bot, settings.TARGET_GROUP_ID, action)


async def main():
    if not settings.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN пустой")
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY пустой")

    await init_db()

    bot = Bot(settings.BOT_TOKEN)
    dp = Dispatcher()

    me = await bot.get_me()
    bot_username = me.username

    # фоновая автономия
    asyncio.create_task(spontaneous_loop(bot))

    @dp.message(F.text)
    async def on_text(message: Message):
        if not _is_target_group(message):
            return

        # всегда сохраняем/индексируем всех (память чата)
        try:
            await save_and_index(message)
        except Exception as e:
            logging.error(f"save/index error: {e}")

        if not settings.AUTONOMY_ENABLED:
            return

        # owner-only: бот “видит” всех, но отвечает только owner
        if settings.OWNER_ONLY_MODE and not _is_owner(message):
            # но упоминания всё равно могут “разбудить” решалку — без ответа
            return

        text = (message.text or "").strip()
        is_mention = _mentioned(bot_username, text)

        base_prob = settings.MENTION_REPLY_PROB if is_mention else settings.REPLY_PROB
        if random.random() > base_prob:
            return

        ctx = await build_context(text)

        try:
            ok = decide_reply(last_text=text, is_mention=is_mention, context_snippets=ctx)
        except Exception as e:
            logging.error(f"decide_reply error: {e}")
            return
        if not ok:
            return

        raw = generate_reply(user_text=text, context_snippets=ctx).get("_raw", "")
        action = _parse_action(raw)

        try:
            await act(bot, message.chat.id, action)
        except Exception as e:
            logging.error(f"act error: {e}")
            # fallback text
            await message.reply("У меня чё-то с мультимедиа залипло. Ща оклемаюсь.")

    logging.info("Balbes автономный стартанул")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
