import asyncio
import random
import tempfile
from pathlib import Path

import edge_tts

# Базовые голоса (можешь расширять)
RU_MALE = [
    "ru-RU-DmitryNeural",
    "ru-RU-DmitryNeural",
]
RU_FEMALE = [
    "ru-RU-SvetlanaNeural",
    "ru-RU-DariyaNeural",
]
EN_MALE = [
    "en-US-GuyNeural",
    "en-GB-RyanNeural",
]
EN_FEMALE = [
    "en-US-JennyNeural",
    "en-GB-SoniaNeural",
]

# Пресеты “персонажей” через ffmpeg фильтры
# Важно: фильтры аккуратные, чтобы телега принимала ogg/opus
VOICE_PRESETS = [
    # normal
    ("male", RU_MALE, ""),  # без эффектов
    ("female", RU_FEMALE, ""),
    # child: выше питч + чуть быстрее
    ("child", RU_FEMALE + RU_MALE, "asetrate=48000*1.18,aresample=48000,atempo=1.08"),
    # old: ниже питч + чуть медленнее + легкая “муть”
    ("old", RU_MALE + RU_FEMALE, "asetrate=48000*0.90,aresample=48000,atempo=0.95,highpass=f=90,lowpass=f=5200"),
    # devil: низко + немного “эхо”
    ("devil", RU_MALE + EN_MALE, "asetrate=48000*0.82,aresample=48000,atempo=0.92,aecho=0.8:0.9:60:0.35"),
    # robot: чуть “телефон” + легкая компрессия
    ("robot", RU_MALE + EN_MALE + RU_FEMALE, "highpass=f=300,lowpass=f=3400,acompressor=threshold=-20dB:ratio=4:attack=10:release=200"),
]

def _pick_voice_and_filter() -> tuple[str, str, str]:
    preset_name, voices, ff_filter = random.choice(VOICE_PRESETS)
    voice = random.choice(voices)
    return preset_name, voice, ff_filter


async def tts_to_ogg_opus_random(text: str) -> tuple[bytes, str, str]:
    """
    Возвращает (ogg_bytes, preset_name, voice_name)
    """
    preset, voice, ff_filter = _pick_voice_and_filter()

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        mp3_path = td / "tts.mp3"
        ogg_path = td / "voice.ogg"

        communicate = edge_tts.Communicate(text=text, voice=voice)
        await communicate.save(str(mp3_path))

        # ffmpeg: mp3 -> ogg/opus (telegram voice)
        cmd = [
            "ffmpeg", "-y",
            "-i", str(mp3_path),
        ]

        if ff_filter:
            cmd += ["-af", ff_filter]

        cmd += [
            "-c:a", "libopus",
            "-b:a", "32k",
            "-vbr", "on",
            "-application", "voip",
            str(ogg_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()

        return ogg_path.read_bytes(), preset, voice
