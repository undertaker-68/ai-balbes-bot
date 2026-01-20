from __future__ import annotations
import os
import asyncio
import logging
from typing import Optional, Any, Dict

import aiohttp

log = logging.getLogger(__name__)

REPLICATE_API = "https://api.replicate.com/v1/predictions"

def _token() -> str:
    return os.getenv("REPLICATE_API_TOKEN", "").strip()

def _model() -> str:
    return os.getenv("REPLICATE_MODEL", "black-forest-labs/flux-schnell").strip()

async def generate_image_url(prompt: str, timeout_sec: int = 90) -> Optional[str]:
    token = _token()
    if not token:
        return None

    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }

    # endpoint вида /models/{owner}/{name}/predictions
    url = f"https://api.replicate.com/v1/models/{_model()}/predictions"

    payload: Dict[str, Any] = {
        "input": {
            "prompt": prompt,
        }
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_sec)) as s:
        # старт
        async with s.post(url, headers=headers, json=payload) as r:
            if r.status >= 300:
                txt = await r.text()
                log.warning(f"replicate start error {r.status}: {txt[:200]}")
                return None
            data = await r.json()

        pred_id = data.get("id")
        if not pred_id:
            return None

        poll_url = f"{REPLICATE_API}/{pred_id}"
        t0 = asyncio.get_event_loop().time()

        while True:
            await asyncio.sleep(1.2)
            async with s.get(poll_url, headers=headers) as r:
                if r.status >= 300:
                    return None
                p = await r.json()

            status = p.get("status")
            if status == "succeeded":
                out = p.get("output")
                if isinstance(out, str):
                    return out
                if isinstance(out, list) and out:
                    return out[0]
                return None

            if status in ("failed", "canceled"):
                return None

            if asyncio.get_event_loop().time() - t0 > timeout_sec:
                return None
