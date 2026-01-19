import aiohttp
from typing import Optional
from bot.settings import settings

BASE = "https://api.giphy.com/v1/gifs"

async def _get_json(url: str, params: dict) -> dict:
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url, params=params) as r:
            if r.status != 200:
                return {}
            return await r.json()

def _pick_best_url(gif_obj: dict) -> Optional[str]:
    # Лучше брать mp4 — Telegram обычно стабильнее показывает
    images = (gif_obj or {}).get("images") or {}
    for path in [
        ("original_mp4", "mp4"),
        ("fixed_height_mp4", "mp4"),
        ("original", "mp4"),
        ("original", "url"),  # fallback на gif
    ]:
        block = images.get(path[0]) or {}
        u = block.get(path[1])
        if u and isinstance(u, str):
            return u
    return None

async def get_gif_by_id(gif_id: str) -> Optional[str]:
    # GIPHY get GIF by id: /v1/gifs/{gif_id} :contentReference[oaicite:1]{index=1}
    url = f"{BASE}/{gif_id}"
    params = {"api_key": settings.GIPHY_API_KEY}
    data = await _get_json(url, params)
    gif_obj = (data or {}).get("data")
    return _pick_best_url(gif_obj)

async def search_gif(query: str, limit: int = 8) -> Optional[str]:
    # Search endpoint: /v1/gifs/search :contentReference[oaicite:2]{index=2}
    url = f"{BASE}/search"
    params = {
        "api_key": settings.GIPHY_API_KEY,
        "q": query,
        "limit": limit,
        "rating": getattr(settings, "GIPHY_RATING", "r"),
        "lang": getattr(settings, "GIPHY_LANG", "ru"),
    }
    data = await _get_json(url, params)
    items = (data or {}).get("data") or []
    for gif_obj in items:
        u = _pick_best_url(gif_obj)
        if u:
            return u
    return None
