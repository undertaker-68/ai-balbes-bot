import aiohttp
from settings import settings

GIPHY_URL = "https://api.giphy.com/v1/gifs/{}"

async def get_gif_by_id(gif_id: str) -> str | None:
    params = {
        "api_key": settings.GIPHY_API_KEY,
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(GIPHY_URL.format(gif_id), params=params) as r:
            if r.status != 200:
                return None

            data = await r.json()
            return data["data"]["images"]["original"]["url"]
