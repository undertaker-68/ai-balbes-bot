from __future__ import annotations

import os
from typing import Dict, Any

from openai import OpenAI
from .settings import settings

_client = OpenAI(api_key=settings.OPENAI_API_KEY)

BASE_SYSTEM = """Ты — участник телеграм-чата. Пиши естественно, без официоза.
Тон: слегка ироничный/подъёбистый. Не изображай "ассистента", не пиши канцеляритом.
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
            "- Если наезд — отвечай жёстко/иронично.\n"
        )
    return "РЕЖИМ: ОБЫЧНЫЙ.\n"


def generate_reply(*, user_text: str, context_snippets: str = "", mode: str = "normal") -> Dict[str, Any]:
    system = BASE_SYSTEM + "\n" + _mode_rules(mode)

    # подмешиваем стиль чата (если есть)
    try:
        p = os.path.join("artifacts", "system_style.txt")
        if os.path.exists(p):
            system += "\n\n" + open(p, "r", encoding="utf-8").read().strip()
    except Exception:
        pass

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
