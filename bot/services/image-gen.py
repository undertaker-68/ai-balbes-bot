from __future__ import annotations

import base64
import logging
from typing import Optional

from openai import OpenAI

from ..settings import settings

log = logging.getLogger(__name__)


def _client() -> OpenAI:
    return OpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=getattr(settings, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
    )


def _or_headers() -> dict:
    h = {}
    if getattr(settings, "OPENROUTER_SITE_URL", ""):
        h["HTTP-Referer"] = settings.OPENROUTER_SITE_URL
    if getattr(settings, "OPENROUTER_APP_NAME", ""):
        h["X-Title"] = settings.OPENROUTER_APP_NAME
    return h


def _extract_image_b64_from_text(text: str) -> Optional[bytes]:
    """
    Ожидаем, что модель вернет что-то вида:
    data:image/png;base64,AAAA...
    или просто base64 (реже)
    """
    if not text:
        return None

    t = text.strip()

    # data-url
    if "base64," in t and t.lower().startswith("data:image"):
        try:
            b64 = t.split("base64,", 1)[1].strip()
            return base64.b64decode(b64)
        except Exception:
            return None

    # иногда может прийти "только base64" (без префикса)
    # пробуем декоднуть, но осторожно (короткое/мусор — не декодим)
    if len(t) > 2000 and all(c.isalnum() or c in "+/=\n\r" for c in t[:500]):
        try:
            return base64.b64decode(t)
        except Exception:
            return None

    return None


def generate_image_bytes(prompt: str, *, timeout_sec: int = 90) -> Optional[bytes]:
    """
    Генерим картинку через OpenRouter image-модель.
    Возвращаем bytes PNG/JPEG (готово для Telegram send_photo).
    """
    if not settings.OPENROUTER_API_KEY:
        return None

    model = getattr(settings, "OPENROUTER_IMAGE_MODEL", "google/gemini-2.5-flash-image")

    sys = (
        "Ты генерируешь изображение по запросу для телеграм-чата.\n"
        "Верни ТОЛЬКО картинку (image) без лишнего текста.\n"
        "Если нужно, можешь вернуть одно короткое слово в тексте, но лучше без текста.\n"
    )

    # Важно: modalities = ["image", "text"] — чтобы модель вернула image-выход
    # Некоторые провайдеры кладут base64 в message.content (как data-url)
    # Поэтому ниже забираем из message.content
    try:
        client = _client()
        headers = _or_headers()

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": prompt.strip()},
            ],
            # ключевая штука:
            modalities=["image", "text"],
            timeout=timeout_sec,
            extra_headers=headers if headers else None,
        )

        msg = resp.choices[0].message

        # чаще всего тут data-url строкой:
        content = (msg.content or "").strip()
        img_bytes = _extract_image_b64_from_text(content)
        if img_bytes:
            return img_bytes

        # fallback: иногда провайдер кладет в "message" другие поля.
        # Но OpenAI SDK типизирует не одинаково для всех — поэтому только лог.
        log.warning("OpenRouter image: no image data found in message.content")
        return None

    except Exception as e:
        log.warning(f"OpenRouter image gen error: {e}")
        return None
