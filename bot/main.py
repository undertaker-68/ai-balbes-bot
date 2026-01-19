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

# кеш инфы о боте (username/id), чтобы не дергать get_me на каждое сообщение
_bot_cached = {"id": None, "username": None}

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


async def _get_bot_identity(bot: Bot) -> tuple[int, str]:
    if _bot_cached["id"] and _bot_cached["username"] is not None:
        return _bot_cached["id"], _bot_cached["username"]

    me = await bot.get_me()
    _bot_cached["id"] = me.id
    _bot_cached["username"] = (me.username or "").lower()
    return _bot_cached["id"], _bot_cached["username"]


async def on_text(message: Message, bot: Bot) -> None:
    text = (message.text or "").strip()
    if not text:
        return

    uid = message.from_user.id if message.from_user else None
    is_owner = (uid == settings.OWNER_USER_ID)

    text_l = text.lower()

    # owner mention/reply detect
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

    # mention/reply to BOT (fixed)
    bot_id, bot_username = await _get_bot_identity(bot)
    mention_bot = bool(bot_username) and (f"@{bot_username}" in text_l)

    reply_to_bot = False
    if message.reply_to_message and message.reply_to_message.from_user:
        reply_to_bot = (message.reply_to_message.from_user.id == bot_id)

    is_mention = mention_bot or reply_to_bot

    # must reply if bot is addressed or owner/defense involved
    must_reply = is_mention or (mode in ("owner", "defend_owner"))

    emoji = pick_reaction(text)

    # if not must_reply: apply cooldown + probability
    now = time.time()
    chat_id = message.chat.id

    if not must_reply:
        last = _last_reply_ts.get(chat_id, 0.0)
        cooldown = float(getattr(settings, "REPLY_COOLDOWN_SEC", 25))

        # cooldown: maybe react and exit
        if now - last < cooldown:
            if random.random() < float(getattr(settings, "REACT_PROB_NORMAL", 0.12)):
                await react(bot, message, emoji)
            return

        # probabilistic reply
        if random.random() > float(getattr(settings, "REPLY_PROB_NORMAL", 0.08)):
            if random.random() < float(getattr(settings, "REACT_PROB_NORMAL", 0.12)):
                await react(bot, message, emoji)
            return

    # OPTIONAL: sometimes react-only even when mentioned (your old logic)
    if should_react_only(is_mention_
