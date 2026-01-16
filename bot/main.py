from __future__ import annotations
import asyncio, logging, os, random, json
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from sqlalchemy import select

from .settings import settings
from .db import engine, SessionLocal
from .models import Base, MessageRow
from .ai import embed, decide_reply, generate_reply
from .rag import ensure_collection, upsert, search as rag_search
from .media import send_gif, send_image, send_voice, send_video, send_video_note

logging.basicConfig(level=logging.INFO)

def _is_owner(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id == settings.OWNER_USER_ID)

def _is_target_group(message: Message) -> bool:
    return bool(message.chat and message.chat.id == settings.TARGET_GROUP_ID)

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
        msg_id = row.id
        await session.commit()

    vec = embed(text)
    ensure_collection(vector_size=len(vec))
    upsert(
        point_id=msg_id,
        vector=vec,
        payload={"text": text, "user_id": user_id, "username": username},
    )

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

def _try_parse_json(raw: str) -> dict:
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except Exception:
        # часто модель может завернуть в ```json ... ```
        raw2 = raw.strip().strip("`")
        if raw2.lower().startswith("json"):
            raw2 = raw2[4:].strip()
        try:
            return json.loads(raw2)
        except Exception:
            return {"type": "text", "text": raw or "…"}

async def act(bot: Bot, chat_id: int, action: dict):
    t = (action.get("type") or "text").lower()

    if t == "gif":
        q = action.get("gif_query") or action.get("text") or "funny meme"
        await send_gif(bot, chat_id, str(q))
        return

    if t == "image":
        p = action.get("prompt") or action.get("text") or "мемная картинка про чат друзей"
        await send_image(bot, chat_id, str(p))
        return

    if t == "voice":
        txt = action.get("text") or "угу"
        await send_voice(bot, chat_id, str(txt))
        return

    if t == "video_note":
        await send_video_note(bot, chat_id)
        return

    if t == "video":
        await send_video(bot, chat_id)
        return

    # default text
    txt = action.get("text") or action.get("_raw") or "…"
    await bot.send_message(chat_id, str(txt))

async def spontaneous_loop(bot: Bot):
    # Бот сам иногда пишет, даже если его не трогают
    while True:
        await asyncio.sleep(random.randint(settings.SPONTANEOUS_MIN_SEC, settings.SPONTANEOUS_MAX_SEC))
        if not settings.AUTONOMY_ENABLED:
            continue
        if random.random() > settings.SPONTANEOUS_PROB:
            continue

        # Берём последние сообщения из БД (чтобы “в тему”)
        async with SessionLocal() as session:
            q = select(MessageRow).where(MessageRow.chat_id == settings.TARGET_GROUP_ID).order_by(MessageRow.id.desc()).limit(20)
            rows = (await session.execute(q)).scalars().all()

        seed = "\n".join([f"{r.username or r.user_id}: {r.text}" for r in reversed(rows)])
        user_text = f"Последнее в чате:\n{seed}\n\nСкажи что-нибудь уместное от себя (можешь и промолчать, но если пишешь — коротко)."

        ctx = await build_context(seed[-400:] if seed else "чат")
        # Для “самостоятельного” поста: просто генерим действие и отправляем
        raw = generate_reply(user_text=user_text, context_snippets=ctx).get("_raw", "")
        action = _try_parse_json(raw)
        # ещё слой “может передумать”
        if action.get("type") == "text" and (not action.get("text") or len(action.get("text","").strip()) < 1):
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

    # запускаем автономный фон
    asyncio.create_task(spontaneous_loop(bot))

    @dp.message(F.text)
    async def on_text(message: Message):
        if not _is_target_group(message):
            return

        if settings.OWNER_ONLY_MODE and not _is_owner(message):
            # owner-only: не реагируем, но можем сохранять? (оставим: сохраняем всех, но отвечаем по owner-only)
            pass

        # Всегда сохраняем и индексируем (чтобы память росла)
        try:
            await save_and_index(message)
        except Exception as e:
            logging.error(f"save/index error: {e}")

        if not settings.AUTONOMY_ENABLED:
            return

        text = (message.text or "").strip()
        is_mention = _mentioned(bot_username, text)

        # Вероятность реагирования (упоминание повышает шанс)
        base_prob = settings.MENTION_REPLY_PROB if is_mention else settings.REPLY_PROB
        if random.random() > base_prob:
            return

        ctx = await build_context(text)

        # Волевое решение модели (отдельный запрос)
        try:
            ok = decide_reply(last_text=text, is_mention=is_mention, context_snippets=ctx)
        except Exception as e:
            logging.error(f"decide_reply error: {e}")
            return
        if not ok:
            return

        # Owner-only: отвечаем только владельцу, НО сохраняем всех (как выше)
        if settings.OWNER_ONLY_MODE and not _is_owner(message):
            return

        raw = generate_reply(user_text=text, context_snippets=ctx).get("_raw", "")
        action = _try_parse_json(raw)
        await act(bot, message.chat.id, action)

    logging.info("Balbes started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
