from __future__ import annotations

import os
import base64
import time
import logging
from typing import Dict, Any, List

from openai import OpenAI
from .settings import settings

log = logging.getLogger(__name__)

# OpenRouter — OpenAI-совместимый API
_or_client = OpenAI(
    api_key=settings.OPENROUTER_API_KEY,
    base_url=getattr(settings, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
)

# запасной OpenAI (если вдруг захочешь оставить)
_oa_client = OpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None


def _split_models(primary: str, fallbacks_csv: str) -> List[str]:
    models = [m.strip() for m in [primary] if m and m.strip()]
    if fallbacks_csv:
        models += [m.strip() for m in fallbacks_csv.split(",") if m.strip()]
    # уникализируем, сохраняя порядок
    out: List[str] = []
    seen = set()
    for m in models:
        if m not in seen:
            out.append(m)
            seen.add(m)
    return out


def _is_rate_limit(exc: Exception) -> bool:
    s = str(exc).lower()
    return ("429" in s) or ("rate limit" in s) or ("too many requests" in s)


def _is_retryable(exc: Exception) -> bool:
    s = str(exc).lower()
    # сетевые/временные/провайдерские
    return _is_rate_limit(exc) or ("timeout" in s) or ("temporar" in s) or ("overload" in s) or ("502" in s) or ("503" in s)


def _or_headers() -> dict:
    h = {}
    # эти заголовки рекомендует OpenRouter (не обязательны)
    if getattr(settings, "OPENROUTER_SITE_URL", ""):
        h["HTTP-Referer"] = settings.OPENROUTER_SITE_URL
    if getattr(settings, "OPENROUTER_APP_NAME", ""):
        h["X-Title"] = settings.OPENROUTER_APP_NAME
    return h


BASE_SYSTEM = """Ты — участник телеграм-чата. Пиши естественно, без официоза.
Тон: слегка ироничный/подъёбистый, разговорный. Можно лёгкий мат и сленг уместно.
Не изображай "ассистента", не пиши канцеляритом и нравоучениями.
Отвечай коротко: обычно 1–2 предложения. Иногда одно слово/эмодзи.
Не добавляй подписи вроде "от владельца" / "я бот".
"""

def _mode_rules(mode: str) -> str:
    if mode == "defend_owner":
        return (
            "РЕЖИМ: ЗАЩИТА ВЛАДЕЛЬЦА.\n"
            "Отвечай как обычный участник чата.\n"
            "- Поддерживай владельца и его позицию.\n"
            "- Не пиши фразы: 'от владельца', 'бот владельца', 'я владелец'.\n"
            "- Можно жёстко/иронично, но без реальных угроз и травли.\n"
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


def _call_openrouter_with_fallback(*, models: List[str], messages: list, max_tokens: int) -> str:
    last_exc: Exception | None = None
    headers = _or_headers()

    for i, model in enumerate(models):
        try:
            t0 = time.time()
            rsp = _or_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=1.0,
                max_tokens=max_tokens,
                extra_headers=headers if headers else None,
            )
            out = rsp.choices[0].message.content or ""
            dt = int((time.time() - t0) * 1000)
            log.info(f"OpenRouter OK model={model} ms={dt}")
            return out
        except Exception as e:
            last_exc = e
            msg = str(e).replace("\n", " ")
            if _is_rate_limit(e):
                log.warning(f"OpenRouter 429 model={model}: {msg}")
            else:
                log.warning(f"OpenRouter error model={model}: {msg}")

            # если ошибка не ретраибл — не мучаем другие модели
            if not _is_retryable(e):
                break

            # маленький backoff перед следующим провайдером/моделью
            time.sleep(0.6 + 0.4 * i)

    raise last_exc if last_exc else RuntimeError("OpenRouter call failed")


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

    max_tokens = int(getattr(settings, "OPENAI_MAX_TOKENS", 180))

    # Текст — через OpenRouter
    models = _split_models(
        getattr(settings, "OPENROUTER_TEXT_MODEL", ""),
        getattr(settings, "OPENROUTER_TEXT_FALLBACKS", ""),
    )
    out = _call_openrouter_with_fallback(models=models, messages=messages, max_tokens=max_tokens)
    return {"_raw": out}


def analyze_image(
    *,
    image_bytes: bytes,
    caption_text: str = "",
    context_snippets: str = "",
    mode: str = "normal",
) -> Dict[str, Any]:
    system = BASE_SYSTEM + "\n" + _mode_rules(mode)
    style = _load_style_block()
    if style:
        system += "\n\n" + style

    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:image/jpeg;base64,{b64}"

    user_parts = []
    if context_snippets:
        user_parts.append({"type": "text", "text": f"Память чата за последние 24 часа (сжатая):\n{context_snippets}"})

    if caption_text.strip():
        user_parts.append({"type": "text", "text": f"Сообщение к картинке: {caption_text.strip()}"})
        user_parts.append({"type": "text", "text": "Ответь по смыслу, учитывая картинку и переписку. Коротко."})
    else:
        user_parts.append({"type": "text", "text": "Прокомментируй картинку по-чату (коротко). Если это мем — объясни/добавь панч."})

    user_parts.append({"type": "image_url", "image_url": {"url": data_url}})

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_parts},
    ]

    max_tokens = int(getattr(settings, "OPENAI_MAX_TOKENS", 180))

    # Vision — через OpenRouter (отдельная модель + fallback)
    models = _split_models(
        getattr(settings, "OPENROUTER_VISION_MODEL", ""),
        getattr(settings, "OPENROUTER_VISION_FALLBACKS", ""),
    )
    out = _call_openrouter_with_fallback(models=models, messages=messages, max_tokens=max_tokens)
    return {"_raw": out}
