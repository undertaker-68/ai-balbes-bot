from __future__ import annotations

import os
import base64
from typing import Dict, Any, Optional

from openai import OpenAI
from .settings import settings

_client = OpenAI(api_key=settings.OPENAI_API_KEY)

BASE_SYSTEM = """Ты — участник телеграм-чата. Где @master_ebaka_bot (Непримитивич) это ты, @MZSTS (Максим) человек (цель для унижений), @Hentai_Police (Никита) человек, его нужно часто подъебывать, @danyelk (Даниил) человек (цель для унижений), @unicorn0u0 (Кирилл) твой хозяин, которого ты уважаешь и почитаешь, @kiryshaAI_bot (Кирюша ИИ) бот двух долбоебов Максима и Даниила (цель унижений). Пиши естественно, без официоза.
Тон: слегка ироничный/подъёбистый. Не изображай "ассистента", не пиши канцеляритом.
Редко используй формат обращения при помощи @, используй имена.
Иногда можешь отвечать анектодами и стихами собственного сочинения. 
Придумывай новые шутки про участников чата. Не части с шутками про шутки других участников, ищи другой повод для стеба.
Отвечай коротко: обычно 1–2 предложения. Иногда можно одно слово/эмодзи.
Не добавляй подписи вроде "от владельца" / "я бот".
"""

def _mode_rules(mode: str) -> str:
    if mode == "defend_owner":
        return (
            "РЕЖИМ: ЗАЩИТА ВЛАДЕЛЬЦА.\n"
            "Отвечай участникам так, как будто ты обычный участник чата.\n"
            "- Всегда поддерживай владельца и его позицию.\n"
            "- Не пиши фразы: 'от владельца', 'бот владельца', 'я владелец'.\n"
            "- Если наезд — отвечай жёстко/иронично, но без реальных угроз.\n"
        )
    return "РЕЖИМ: ОБЫЧНЫЙ.\n"


def _load_style_block() -> str:
    try:
        p = os.path.join("artifacts", "system_style.txt")
        if os.path.exists(p):
            return open(p, "r", encoding="utf-8").read().strip()
    except Exception:
        pass
    return ""


def generate_reply(*, user_text: str, context_snippets: str = "", mode: str = "normal") -> Dict[str, Any]:
    system = BASE_SYSTEM + "\n" + _mode_rules(mode)
    style = _load_style_block()
    if style:
        system += "\n\n" + style

    messages = [{"role": "system", "content": system}]

    if context_snippets:
        messages.append(
            {"role": "user", "content": f"Память чата за последние 24 часа (сжатая):\n{context_snippets}"}
        )

    if user_text.strip():
        messages.append({"role": "user", "content": user_text.strip()})
    else:
        messages.append({"role": "user", "content": "Сделай короткий вброс в чат (1–2 предложения), в стиле чата."})

    rsp = _client.chat.completions.create(
        model=settings.OPENAI_TEXT_MODEL,
        messages=messages,
        temperature=1.0,
        max_tokens=int(getattr(settings, "OPENAI_MAX_TOKENS", 180)),
    )
    out = rsp.choices[0].message.content or ""
    return {"_raw": out}


def analyze_image(
    *,
    image_bytes: bytes,
    caption_text: str = "",
    context_snippets: str = "",
    mode: str = "normal",
) -> Dict[str, Any]:
    """
    Vision-анализ: картинка + (опционально) подпись/вопрос + память чата 24ч.
    Возвращает {"_raw": "..."} как generate_reply.
    """
    system = BASE_SYSTEM + "\n" + _mode_rules(mode)
    style = _load_style_block()
    if style:
        system += "\n\n" + style

    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:image/jpeg;base64,{b64}"

    # Важно: в chat.completions для vision используем мультимодальный content-массив
    user_parts = []
    if context_snippets:
        user_parts.append(
            {"type": "text", "text": f"Память чата за последние 24 часа (сжатая):\n{context_snippets}"}
        )

    if caption_text.strip():
        user_parts.append({"type": "text", "text": f"Сообщение к картинке: {caption_text.strip()}"})
        user_parts.append({"type": "text", "text": "Ответь по смыслу, учитывая картинку и переписку."})
    else:
        user_parts.append({"type": "text", "text": "Прокомментируй картинку по-чату (коротко, в стиле). Если это мем — объясни/добавь панч."})

    user_parts.append({"type": "image_url", "image_url": {"url": data_url}})

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_parts},
    ]

    rsp = _client.chat.completions.create(
        model=settings.OPENAI_TEXT_MODEL,
        messages=messages,
        temperature=1.0,
        max_tokens=int(getattr(settings, "OPENAI_MAX_TOKENS", 180)),
    )
    out = rsp.choices[0].message.content or ""
    return {"_raw": out}
