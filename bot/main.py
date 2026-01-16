import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from sqlalchemy import select

from .settings import settings
from .filters import InTargetGroupFilter, OwnerOnlyFilter
from .db import SessionLocal, engine
from .models import Base, MessageRow
from .ai import chat, embed
from .rag import qdrant_client, ensure_collection, upsert_points, search
from qdrant_client.http import models as qm
from .utils import clamp_text

logging.basicConfig(level=logging.INFO)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def build_context(user_text: str) -> str:
    qc = qdrant_client()
    qvec = embed(user_text)
    hits = search(qc, qvec, limit=settings.RAG_TOP_K)

    # собираем контекст компактно
    chunks = []
    total = 0
    for h in hits:
        line = f"- {h.get('username') or h.get('user_id')}: {h.get('text','')}".strip()
        if not line:
            continue
        if total + len(line) > settings.RAG_MAX_CHARS:
            break
        chunks.append(line)
        total += len(line) + 1

    return "\n".join(chunks).strip()

async def save_message_and_vector(message: Message):
    if not message.text:
        return

    text = clamp_text(message.text, 8000)
    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None

    async with SessionLocal() as session:
        row = MessageRow(chat_id=message.chat.id, user_id=user_id, username=username, text=text)
        session.add(row)
        await session.flush()

        vec = embed(text)
        qc = qdrant_client()
        upsert_points(qc, [
            qm.PointStruct(
                id=row.id,
                vector=vec,
                payload={"text": text, "user_id": user_id, "username": username}
            )
        ])

        await session.commit()

async def main():
    if not settings.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN пустой")
    if not settings.OPENAI_API_KEY:
        logging.warning("OPENAI_API_KEY пустой — ответы работать не будут, только логирование/сохранение.")

    await init_db()

    # ensure qdrant collection
    qc = qdrant_client()
    try:
        vec = embed("ping")
        await ensure_collection(qc, vector_size=len(vec))
    except Exception as e:
        logging.error(f"Qdrant init failed: {e}")

    bot = Bot(settings.BOT_TOKEN)
    dp = Dispatcher()

    # ========= handlers =========
    @dp.message(InTargetGroupFilter(), F.text, OwnerOnlyFilter())
    async def handle_text(message: Message):
        # Сохраняем любое сообщение (даже от owner) в память
        try:
            await save_message_and_vector(message)
        except Exception as e:
            logging.error(f"save_message_and_vector error: {e}")

        # Отвечаем только если:
        # - упомянули бота, или
        # - ответили на сообщение бота, или
        # - owner написал команду /ask ...
        txt = message.text or ""
        me = await bot.get_me()
        mentioned = (me.username and f"@{me.username}" in txt)

        replied_to_bot = bool(message.reply_to_message and message.reply_to_message.from_user
                              and message.reply_to_message.from_user.id == me.id)

        is_ask = txt.strip().startswith("/ask ")

        if not (mentioned or replied_to_bot or is_ask):
            return

        user_prompt = txt.replace(f"@{me.username}", "").strip()
        if is_ask:
            user_prompt = txt.strip()[5:].strip()

        if not settings.OPENAI_API_KEY:
            await message.reply("OPENAI_API_KEY не задан. Я пока только сохраняю сообщения в память.")
            return

        context = await build_context(user_prompt)
        try:
            answer = chat(user_prompt, context_snippets=context)
        except Exception as e:
            logging.error(f"OpenAI chat error: {e}")
            await message.reply("Что-то сломалось при запросе к мозгам. Попробуй ещё раз.")
            return

        if not answer:
            answer = "…"

        await message.reply(answer)

    @dp.message(InTargetGroupFilter(), F.text, OwnerOnlyFilter(), F.text.startswith("/ping"))
    async def ping(message: Message):
        await message.reply("pong")

    @dp.message(InTargetGroupFilter(), F.text, OwnerOnlyFilter(), F.text.startswith("/last"))
    async def last_messages(message: Message):
        async with SessionLocal() as session:
            q = select(MessageRow).where(MessageRow.chat_id == message.chat.id).order_by(MessageRow.id.desc()).limit(5)
            rows = (await session.execute(q)).scalars().all()
        lines = [f"{r.id}: {r.username or r.user_id} — {clamp_text(r.text, 200)}" for r in rows]
        await message.reply("\n".join(lines) if lines else "Пусто")

    logging.info("Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
