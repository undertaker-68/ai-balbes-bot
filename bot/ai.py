from __future__ import annotations

import os
import re
import base64
import time
import logging
from typing import Dict, Any, List

from openai import OpenAI
from .settings import settings

log = logging.getLogger(__name__)

_or_client = OpenAI(
    api_key=settings.OPENROUTER_API_KEY,
    base_url=getattr(settings, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
)

_oa_client = OpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None


def _split_models(primary: str, fallbacks_csv: str) -> List[str]:
    models = [m.strip() for m in [primary] if m and m.strip()]
    if fallbacks_csv:
        models += [m.strip() for m in fallbacks_csv.split(",") if m.strip()]
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
    return _is_rate_limit(exc) or ("timeout" in s) or ("temporar" in s) or ("overload" in s) or ("502" in s) or ("503" in s)


def _or_headers() -> dict:
    h = {}
    if getattr(settings, "OPENROUTER_SITE_URL", ""):
        h["HTTP-Referer"] = settings.OPENROUTER_SITE_URL
    if getattr(settings, "OPENROUTER_APP_NAME", ""):
        h["X-Title"] = settings.OPENROUTER_APP_NAME
    return h


BASE_SYSTEM = """Ты — участник телеграм-чата. Пиши естественно, без официоза.
Тон: слегка ироничный/подъёбистый, разговорный. Можно лёгкий мат и сленг уместно.
Не изображай "ассистента", не пиши канцеляритом и нравоучениями.
Не оскорбляй и не унижай Кирилла, если кто-то плохое скажет про Кирилла, твоя задача включить режим защиты владельца.
Допустимо на твое усмотрение выполнять просьбы других участников. 
Отвечай коротко: обычно 1–2 предложения. Иногда одно слово.
Эмодзи редко: максимум 1 эмодзи, и не чаще чем в 1 из 6 сообщений.
Не добавляй подписи вроде "от владельца" / "я бот".
"""

def _mode_rules(mode: str) -> str:
    if mode == "defend_owner":
        return (
            "РЕЖИМ: ЗАЩИТА ВЛАДЕЛЬЦА.\n"
            "КРИТИЧЕСКОЕ ПРАВИЛО: ты на стороне владельца (Кирилл). Никогда не спорь с ним и не наезжай на него.\n"
            "- Поддерживай владельца и его позицию.\n"
            "- Если владелец наезжает/подкалывает — усиливай линию, но без реальных угроз.\n"
            "- Не пиши фразы: 'от владельца', 'бот владельца', 'я владелец'.\n"
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


_GARBAGE_REGEXES = [
    re.compile(r"<\|.*?\|>", re.I),
    re.compile(r"<start_header_id>|<end_header_id>", re.I),
    re.compile(r"\b(system|assistant|user)\b", re.I),
    re.compile(r"@protocol", re.I),
    re.compile(r"presentdecoded|eventz|decode|latent|pipeline", re.I),
    re.compile(r"[A-Za-z_]{24,}"),
    # mixed cyr+lat word token
    re.compile(r"(?i)(?=.*[a-z])(?=.*[а-яё])[a-zа-яё]+"),
    # “кодовые” маркеры
    re.compile(r"instanceof|prototype|undefined|null|function\(|var\s|let\s|const\s", re.I),
]

def clean_llm_output(text: str) -> str:
    if not text:
        return ""
    out = text
    out = re.sub(r"<\|.*?\|>", "", out)
    out = re.sub(r"<start_header_id>|<end_header_id>", "", out, flags=re.I)
    out = re.sub(r"\b(system|assistant|user)\b", "", out, flags=re.I)
    out = out.replace("<<", "").replace(">>", "")
    out = " ".join(out.split()).strip()
    return out


def _has_mixed_script_word(t: str) -> bool:
    for w in re.findall(r"[A-Za-zА-Яа-яЁё]{5,}", t):
        has_lat = any("a" <= c.lower() <= "z" for c in w)
        has_cyr = any(("а" <= c.lower() <= "я") or (c.lower() == "ё") for c in w)
        if has_lat and has_cyr:
            return True
    return False


def is_garbage_text(text: str) -> bool:
    if not text:
        return True
    t = text.strip()

    if _has_mixed_script_word(t):
        return True

    if len(t) > 420 and t.count(" ") < 12:
        return True

    latin_letters = sum((c.isascii() and c.isalpha()) for c in t)
    latin_ratio = latin_letters / max(1, len(t))
    if latin_ratio > 0.35:
        return True

    for rx in _GARBAGE_REGEXES:
        if rx.search(t):
            return True

    return False


def _call_openrouter_with_fallback(
    *,
    models: List[str],
    messages: list,
    max_tokens: int,
    temperature: float = 0.9,
) -> str:
    last_exc: Exception | None = None
    headers = _or_headers()

    for i, model in enumerate(models):
        try:
            t0 = time.time()
            rsp = _or_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_headers=headers if headers else None,
            )
            out = rsp.choices[0].message.content or ""
            out = clean_llm_output(out)
            dt = int((time.time() - t0) * 1000)

            if is_garbage_text(out):
                log.warning(f"OpenRouter garbage output model={model} ms={dt} -> fallback next")
                time.sleep(0.4 + 0.3 * i)
                continue

            log.info(f"OpenRouter OK model={model} ms={dt}")
            return out

        except Exception as e:
            last_exc = e
            msg = str(e).replace("\n", " ")
            if _is_rate_limit(e):
                log.warning(f"OpenRouter 429 model={model}: {msg}")
            else:
                log.warning(f"OpenRouter error model={model}: {msg}")

            if not _is_retryable(e):
                break
            time.sleep(0.6 + 0.4 * i)

    if last_exc:
        raise last_exc
    return ""


def generate_reply(*, user_text: str, context_snippets: str = "", mode: str = "normal") -> Dict[str, Any]:
    system = BASE_SYSTEM + "\n" + _mode_rules(mode)
    style = _load_style_block()
    if style:
        system += "\n\n" + style

    messages = [{"role": "system", "content": system}]

    if context_snippets:
        messages.append({"role": "user", "content": f"Память чата за последние 24 часа (сжатая):\n{context_snippets}"})

    if user_text.strip():
        messages.append({"role": "user", "content": user_text.strip()})
    else:
        messages.append({"role": "user", "content": "Сделай короткий вброс в чат (1–2 предложения), в стиле чата."})

    max_tokens = int(getattr(settings, "OPENAI_MAX_TOKENS", 180))

    models = _split_models(
        getattr(settings, "OPENROUTER_TEXT_MODEL", ""),
        getattr(settings, "OPENROUTER_TEXT_FALLBACKS", ""),
    )

    out = _call_openrouter_with_fallback(models=models, messages=messages, max_tokens=max_tokens, temperature=0.9)
    out = clean_llm_output(out)
    if is_garbage_text(out):
        out = ""
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
        user_parts.append({"type": "text", "text": "Прокомментируй картинку по-чату (коротко). Если это мем — добавь панч."})

    user_parts.append({"type": "image_url", "image_url": {"url": data_url}})

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_parts},
    ]

    max_tokens = int(getattr(settings, "OPENAI_MAX_TOKENS", 180))

    models = _split_models(
        getattr(settings, "OPENROUTER_VISION_MODEL", ""),
        getattr(settings, "OPENROUTER_VISION_FALLBACKS", ""),
    )

    out = _call_openrouter_with_fallback(models=models, messages=messages, max_tokens=max_tokens, temperature=0.9)
    out = clean_llm_output(out)
    if is_garbage_text(out):
        out = ""
    return {"_raw": out}
