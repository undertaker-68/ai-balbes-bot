from __future__ import annotations

import asyncio
import asyncpg
import logging
import random
import time
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReactionTypeEmoji
from aiogram.types import BufferedInputFile

from .settings import settings
from .ai import generate_reply, analyze_image, clean_llm_output, is_garbage_text
from .reactions import pick_reaction, should_react_only
from .services.giphy import search_gif
from .services.tts import tts_to_ogg_opus_random
from .services.image_gen import generate_image_bytes

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

_pg_pool: asyncpg.Pool | None = None

_last_reply_ts: dict[int, float] = {}
_dialog_state: dict[tuple[int, int], tuple[float, int]] = {}

_last_spontaneous_ts: dict[int, float] = {}
_last_seen_chat_activity_ts: dict[int, float] = {}


async def save_and_index(message: Message) -> None:
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

        text = (message.text or "").strip()
        if not text and getattr(message, "caption", None):
            text = (message.caption or "").strip()

        if not text:
            if getattr(message, "photo", None):
                text = "[photo]"
            elif getattr(message, "animation", None):
                text = "[gif]"
            elif getattr(message, "video", None):
                text = "[video]"
            elif getattr(message, "voice", None):
                text = "[voice]"
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
        log.debug(f"save_and_index error: {e}")


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
        log.debug(f"build_context_24h db error: {e}")
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


async def build_user_context_24h(chat_id: int, user_id: int) -> str:
    global _pg_pool
    if _pg_pool is None:
        return ""

    try:
        rows = await _pg_pool.fetch(
            """
            SELECT dt, from_name, text
            FROM tg_history
            WHERE chat_id = $1
              AND from_id = $2
              AND dt >= (NOW() - INTERVAL '24 hours')
            ORDER BY dt DESC
            LIMIT 18
            """,
            int(chat_id),
            str(user_id),
        )
    except Exception as e:
        log.debug(f"build_user_context_24h db error: {e}")
        return ""

    if not rows:
        return ""

    rows = list(reversed(rows))
    max_chars = 1200

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


def _dialog_is_active(chat_id: int, user_id: int) -> bool:
    key = (chat_id, user_id)
    v = _dialog_state.get(key)
    if not v:
        return False
    until_ts, _ = v
    if time.time() > until_ts:
        _dialog_state.pop(key, None)
        return False
    return True


def _dialog_touch(chat_id: int, user_id: int, *, extend_sec: int = 220, max_turns: int = 6) -> None:
    key = (chat_id, user_id)
    until_ts, streak = _dialog_state.get(key, (0.0, 0))
    streak = min(max_turns, streak + 1)
    _dialog_state[key] = (time.time() + extend_sec, streak)


async def react(bot: Bot, message: Message, emoji: str) -> None:
    try:
        await bot.set_message_reaction(
            chat_id=message.chat.id,
            message_id=message.message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception as e:
        log.debug(f"reaction error: {e}")


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


async def _compute_is_mention(bot: Bot, message: Message, text: str) -> tuple[bool, int, str]:
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
    return (mention_bot or reply_to_bot), bot_id, bot_username


def _strip_self_mention(text: str, bot_username_lower: str) -> str:
    if not text or not bot_username_lower:
        return text
    handle = "@" + bot_username_lower
    out = text.replace(handle, "")
    while handle in out.lower():
        i = out.lower().find(handle)
        out = out[:i] + out[i + len(handle):]
    return " ".join(out.split()).strip()


def _soft_address_prefix(message: Message) -> str:
    if not message.from_user:
        return ""
    if random.random() < 0.55:
        return ""
    name = (message.from_user.first_name or message.from_user.full_name or "").strip()
    if not name:
        return ""
    return f"{name}, "


async def _gate_reply(
    *,
    bot: Bot,
    message: Message,
    mode: str,
    is_mention: bool,
    emoji: str,
    bot_id: int,
) -> bool:
    uid = message.from_user.id if message.from_user else None
    is_owner = (uid == settings.OWNER_USER_ID)

    if uid is not None and uid == bot_id:
        return False

    chat_id = int(message.chat.id)
    now = time.time()

    # диалог-окно: отвечаем, но на "угу/ок/ну" реже
    if uid is not None and _dialog_is_active(chat_id, uid):
        t = (message.text or "").strip().lower()
        if t in {"угу", "ага", "вот", "ваще", "ок", "ясно", "пон", "ну"} or len(t) <= 3:
            if random.random() < 0.70:
                if random.random() < 0.45:
                    await react(bot, message, emoji)
                return False
        return True

    # владелец: молчим, но если позвал — отвечаем
    if is_owner and not bool(getattr(settings, "REPLY_TO_OWNER", False)) and not is_mention:
        return False

    must_reply = is_mention or (mode == "defend_owner")
    if must_reply:
        return True

    last = _last_reply_ts.get(chat_id, 0.0)
    if now - last < float(getattr(settings, "REPLY_COOLDOWN_SEC", 8)):
        if random.random() < float(getattr(settings, "REACT_PROB_WHEN_SILENT", 0.20)):
            await react(bot, message, emoji)
        return False

    if random.random() > float(getattr(settings, "REPLY_PROB_NORMAL", 0.60)):
        if random.random() < float(getattr(settings, "REACT_PROB_WHEN_SILENT", 0.20)):
            await react(bot, message, emoji)
        return False

    return True


def wants_voice(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(k in t for k in ["голосом", "озвуч", "озвучь", "войсом", "войс", "запиши войс", "voice"])


def wants_image(user_text: str) -> bool:
    t = (user_text or "").lower()
    keys = [
        "нарисуй", "сгенерируй", "создай картинку", "сделай картинку",
        "сделай изображение", "создай изображение", "нарисуешь",
        "draw", "generate an image", "make an image",
    ]
    return any(k in t for k in keys)


async def on_text(message: Message, bot: Bot) -> None:
    if int(message.chat.id) != int(settings.TARGET_GROUP_ID):
        return

    _last_seen_chat_activity_ts[int(message.chat.id)] = time.time()

    text = (message.text or "").strip()
    if not text:
        return

    await save_and_index(message)

    is_mention, bot_id, bot_username_lower = await _compute_is_mention(bot, message, text)

    uid = message.from_user.id if message.from_user else None
    if uid is not None and uid == bot_id:
        return

    mode = _owner_defense_mode_for_text(text, message)
    emoji = pick_reaction(text)

    should = await _gate_reply(
        bot=bot,
        message=message,
        mode=mode,
        is_mention=is_mention,
        emoji=emoji,
        bot_id=bot_id,
    )
    if not should:
        return

    _last_reply_ts[int(message.chat.id)] = time.time()

    ctx = await build_context_24h(int(message.chat.id))
    user_ctx = ""
    if uid is not None:
        user_ctx = await build_user_context_24h(int(message.chat.id), uid)
    if user_ctx:
        ctx = ctx + "\n\n[ЛИЧНЫЙ КОНТЕКСТ ЭТОГО УЧАСТНИКА ЗА 24Ч]\n" + user_ctx

    # ✅ картинка по запросу
    if wants_image(text):
        prompt = text.replace("@" + bot_username_lower, "").strip()
        img = await asyncio.to_thread(generate_image_bytes, prompt)
            if img:
                photo = BufferedInputFile(img, filename="image.png")
                await bot.send_photo(chat_id=message.chat.id, photo=photo)
                if uid is not None:
                    _dialog_touch(int(message.chat.id), uid)
                return
            if uid is not None:
                _dialog_touch(int(message.chat.id), uid)
            return
        # если токена нет/ошибка — продолжим обычным текстом

    # mention/reply — никогда react-only
    if (not is_mention) and should_react_only(is_mention, mode):
        await react(bot, message, emoji)
        if uid is not None:
            _dialog_touch(int(message.chat.id), uid)
        return

    # иногда гифка (без reply)
    if getattr(settings, "GIPHY_API_KEY", ""):
        p = float(getattr(settings, "GIPHY_PROB", 0.22))
        if mode == "defend_owner":
            p = min(0.40, p * 1.4)

        if random.random() < p:
            q = " ".join(text.split()[:5]) or "reaction"
            try:
                gif_url = await search_gif(q)
            except Exception as e:
                log.debug(f"giphy error: {e}")
                gif_url = None

            if gif_url:
                try:
                    await bot.send_animation(chat_id=message.chat.id, animation=gif_url)
                    if uid is not None:
                        _dialog_touch(int(message.chat.id), uid)
                    return
                except Exception as e:
                    log.debug(f"send_animation error: {e}")

    # если владелец позвал — защита + цель
    if uid == settings.OWNER_USER_ID and is_mention:
        mode = "defend_owner"
        ctx = ctx + "\n\n[ЦЕЛЬ]\nПоддержи владельца и усиливай его линию. Держи тему 2-4 реплики."

    raw = generate_reply(user_text=text, context_snippets=ctx, mode=mode).get("_raw", "").strip()
    raw = clean_llm_output(raw)
    raw = _strip_self_mention(raw, bot_username_lower)

    # если мусор — один ретрай “без мусора”
    if (not raw) or is_garbage_text(raw):
        raw2 = generate_reply(
            user_text=f"{text}\n\n(Ответь по-человечески, без мусорных слов и без латиницы внутри русских слов.)",
            context_snippets=ctx,
            mode=mode,
        ).get("_raw", "").strip()
        raw2 = clean_llm_output(raw2)
        raw2 = _strip_self_mention(raw2, bot_username_lower)
        if (not raw2) or is_garbage_text(raw2):
            if random.random() < 0.45:
                await react(bot, message, emoji)
            return
        raw = raw2

    # ✅ voice по запросу (или редко “сам”)
    do_voice = wants_voice(text)
    if (not do_voice) and _dialog_is_active(int(message.chat.id), uid or -1):
        if random.random() < float(getattr(settings, "AUTO_VOICE_PROB", 0.03)):
            do_voice = True

    if do_voice:
        try:
            ogg_bytes, preset, voice = await tts_to_ogg_opus_random(raw)
            vf = BufferedInputFile(ogg_bytes, filename="voice.ogg")
            await bot.send_voice(chat_id=message.chat.id, voice=vf)
            if uid is not None:
                _dialog_touch(int(message.chat.id), uid)
            return
        except Exception as e:
            log.debug(f"tts error: {e}")
            # если tts упал — просто текстом

    prefix = _soft_address_prefix(message)
    try:
        await bot.send_message(chat_id=message.chat.id, text=(prefix + raw).strip())
        if uid is not None:
            _dialog_touch(int(message.chat.id), uid)
    except Exception as e:
        log.error(f"send_message error: {e}")


async def on_photo(message: Message, bot: Bot) -> None:
    if int(message.chat.id) != int(settings.TARGET_GROUP_ID):
        return
    if not message.photo:
        return

    _last_seen_chat_activity_ts[int(message.chat.id)] = time.time()

    await save_and_index(message)

    caption = (message.caption or "").strip()
    is_mention, bot_id, bot_username_lower = await _compute_is_mention(bot, message, caption or "")

    uid = message.from_user.id if message.from_user else None
    if uid is not None and uid == bot_id:
        return

    if uid == settings.OWNER_USER_ID and not bool(getattr(settings, "REPLY_TO_OWNER", False)) and not is_mention:
        return

    mode = _owner_defense_mode_for_text(caption, message) if caption else "normal"
    if uid == settings.OWNER_USER_ID and is_mention:
        mode = "defend_owner"

    emoji = pick_reaction(caption or "photo")
    _last_reply_ts[int(message.chat.id)] = time.time()

    ctx = await build_context_24h(int(message.chat.id))
    user_ctx = ""
    if uid is not None:
        user_ctx = await build_user_context_24h(int(message.chat.id), uid)
    if user_ctx:
        ctx = ctx + "\n\n[ЛИЧНЫЙ КОНТЕКСТ ЭТОГО УЧАСТНИКА ЗА 24Ч]\n" + user_ctx

    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        buf = await bot.download_file(file.file_path)
        image_bytes = buf.read()
    except Exception as e:
        log.debug(f"download photo error: {e}")
        await react(bot, message, emoji)
        return

    try:
        raw = analyze_image(
            image_bytes=image_bytes,
            caption_text=caption,
            context_snippets=ctx,
            mode=mode,
        ).get("_raw", "").strip()
    except Exception as e:
        log.debug(f"vision error: {e}")
        raw = ""

    raw = clean_llm_output(raw)
    raw = _strip_self_mention(raw, bot_username_lower)

    if (not raw) or is_garbage_text(raw):
        await react(bot, message, emoji)
        return

    prefix = _soft_address_prefix(message)
    await bot.send_message(chat_id=message.chat.id, text=(prefix + raw).strip())
    if uid is not None:
        _dialog_touch(int(message.chat.id), uid)


async def spontaneous_loop(bot: Bot) -> None:
    chat_id = int(settings.TARGET_GROUP_ID)

    while True:
        await asyncio.sleep(
            random.randint(
                int(getattr(settings, "SPONTANEOUS_MIN_SEC", 600)),
                int(getattr(settings, "SPONTANEOUS_MAX_SEC", 1200)),
            )
        )

        if random.random() > float(getattr(settings, "SPONTANEOUS_PROB", 0.12)):
            continue

        now = time.time()

        cooldown = int(getattr(settings, "SPONTANEOUS_COOLDOWN_SEC", 3600))
        last_sp = _last_spontaneous_ts.get(chat_id, 0.0)
        if now - last_sp < cooldown:
            continue

        silent_need = int(getattr(settings, "SPONTANEOUS_ONLY_IF_SILENT_SEC", 600))
        last_act = _last_seen_chat_activity_ts.get(chat_id, 0.0)
        if last_act and (now - last_act) < silent_need:
            continue

        try:
            ctx = await build_context_24h(chat_id)
            text = generate_reply(user_text="", context_snippets=ctx, mode="normal").get("_raw", "").strip()

            me = await bot.get_me()
            bot_username_lower = (me.username or "").lower()

            text = clean_llm_output(text)
            text = _strip_self_mention(text, bot_username_lower)

            if (not text) or is_garbage_text(text):
                continue

            await bot.send_message(chat_id, text)
            _last_spontaneous_ts[chat_id] = now

        except Exception as e:
            log.debug(f"spontaneous error: {e}")


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

    log.info("Balbes автономный стартанул")

    asyncio.create_task(spontaneous_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
