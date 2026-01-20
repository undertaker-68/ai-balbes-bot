import asyncio
import tempfile
from pathlib import Path
import edge_tts

async def tts_to_ogg_opus(text: str, voice: str = "ru-RU-DmitryNeural") -> bytes:
    # 1) генерим mp3 во временный файл
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        mp3_path = td / "tts.mp3"
        ogg_path = td / "voice.ogg"

        communicate = edge_tts.Communicate(text=text, voice=voice)
        await communicate.save(str(mp3_path))

        # 2) конвертим в ogg/opus (формат voice в телеге)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", str(mp3_path),
            "-c:a", "libopus",
            "-b:a", "32k",
            "-vbr", "on",
            "-application", "voip",
            str(ogg_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()

        return ogg_path.read_bytes()
