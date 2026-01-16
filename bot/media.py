from __future__ import annotations
import os, random, glob, json
import aiohttp
from aiogram import Bot
from aiogram.types import BufferedInputFile
from .settings import settings
from .ai import tts_bytes, image_png_bytes

def _pick_asset(subdir: str, exts: tuple[str, ...]) -> str | None:
    base = os.path.join(settings.ASSETS_DIR, subdir)
    files = []
    for e in exts:
        files += glob.glob(os.path.join(base, f"*.{e}"))
    return random.choice(files) if files else None

async def send_gif(bot: Bot, chat_id: int, query: str) -> None:
    # Если TENOR_API_KEY пустой — попробуем локальные гифки assets/gifs
    if not settings.TENOR_API_KEY:
        path = _pick_asset("gifs", ("gif", "mp4"))
        if path:
            await bot.send_animation(chat_id, BufferedInputFile(open(path, "rb").read(), filename=os.path.basename(path)))
        return

    # Tenor search -> берём media_formats.gif.url (упрощенно)
    async with aiohttp.ClientSession() as s:
        params = {
            "q": query,
            "key": settings.TENOR_API_KEY,
            "limit": 8,
            "media_filter": "gif",
            "contentfilter": "medium",
        }
        async with s.get("https://tenor.googleapis.com/v2/search", params=params) as r:
            data = await r.json()
    results = data.get("results", [])
    if not results:
        return
    pick = random.choice(results)
    mf = pick.get("media_formats", {}).get("gif", {})
    url = mf.get("url")
    if url:
        await bot.send_animation(chat_id, url)

async def send_image(bot: Bot, chat_id: int, prompt: str) -> None:
    png = image_png_bytes(prompt=prompt)
    await bot.send_photo(chat_id, BufferedInputFile(png, filename="balbes.png"))

async def send_voice(bot: Bot, chat_id: int, text: str) -> None:
    mp3 = tts_bytes(text=text, voice="alloy")
    await bot.send_voice(chat_id, BufferedInputFile(mp3, filename="balbes.mp3"))

async def send_video(bot: Bot, chat_id: int) -> None:
    path = _pick_asset("videos", ("mp4", "mov"))
    if not path:
        return
    await bot.send_video(chat_id, BufferedInputFile(open(path, "rb").read(), filename=os.path.basename(path)))

async def send_video_note(bot: Bot, chat_id: int) -> None:
    # кружок: mp4 до 60 сек, квадратный желательно :contentReference[oaicite:3]{index=3}
    path = _pick_asset("circles", ("mp4",))
    if not path:
        return
    await bot.send_video_note(chat_id, BufferedInputFile(open(path, "rb").read(), filename=os.path.basename(path)))
