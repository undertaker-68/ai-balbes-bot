from __future__ import annotations

import asyncio
import base64
import os
import tempfile
from pathlib import Path
from typing import Optional, List

from aiogram import Bot
from aiogram.types import BufferedInputFile

from openai import OpenAI

from .settings import settings

_client = OpenAI(api_key=settings.OPENAI_API_KEY)


async def _run(cmd: list[str]) -> None:
    """Run a subprocess command asynchronously and raise on error."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{out.decode(errors='ignore')}\n"
            f"STDERR:\n{err.decode(errors='ignore')}\n"
        )


def _image_png_bytes(prompt: str, size: str = "1024x1024") -> bytes:
    # OpenAI Images: generate -> b64_json
    rsp = _client.images.generate(
        model=settings.OPENAI_IMAGE_MODEL,
        prompt=prompt,
        size=size,
    )
    b64 = rsp.data[0].b64_json
    return base64.b64decode(b64)


def _tts_mp3_bytes(text: str, voice: str = "alloy") -> bytes:
    # OpenAI TTS
    rsp = _client.audio.speech.create(
        model=settings.OPENAI_TTS_MODEL,
        voice=voice,
        input=text[:2000],
        format="mp3",
    )
    return rsp.read()


async def send_generated_image(bot: Bot, chat_id: int, prompt: str) -> None:
    png = _image_png_bytes(prompt=prompt)
    await bot.send_photo(chat_id, BufferedInputFile(png, filename="balbes.png"))


async def send_generated_voice(bot: Bot, chat_id: int, text: str) -> None:
    mp3 = _tts_mp3_bytes(text=text, voice="alloy")
    await bot.send_voice(chat_id, BufferedInputFile(mp3, filename="balbes.mp3"))


async def _make_mp4_from_frames(frames: List[Path], out_mp4: Path, fps: int = 2, square: bool = False) -> None:
    """
    Creates MP4 from image frames.
    - fps=2 and 6 frames => ~3 seconds
    - square=True crops/pads to square for video_note
    """
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # ffmpeg expects sequential names
        for i, f in enumerate(frames, start=1):
            (td_path / f"frame_{i:03d}.png").write_bytes(f.read_bytes())

        input_pattern = str(td_path / "frame_%03d.png")

        vf = []
        # Scale to 640 width keeping aspect; then optionally make square 640x640
        vf.append("scale=640:-2:flags=lanczos")
        if square:
            # pad to square
            vf.append("pad=640:640:(ow-iw)/2:(oh-ih)/2:black")
        vf_str = ",".join(vf)

        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", input_pattern,
            "-vf", vf_str,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out_mp4),
        ]
        await _run(cmd)


async def send_generated_animation(bot: Bot, chat_id: int, prompt: str) -> None:
    """
    “Гифка” в Telegram лучше как MP4 animation.
    """
    # генерим 6 кадров (немного меняем промпт)
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        frames = []
        for i in range(6):
            p = f"{prompt}\nКадр {i+1}/6, небольшое изменение позы/выражения, тот же стиль."
            png = _image_png_bytes(prompt=p)
            fp = td_path / f"f{i+1}.png"
            fp.write_bytes(png)
            frames.append(fp)

        out_mp4 = td_path / "anim.mp4"
        await _make_mp4_from_frames(frames, out_mp4, fps=2, square=False)

        await bot.send_animation(
            chat_id,
            BufferedInputFile(out_mp4.read_bytes(), filename="balbes_anim.mp4"),
        )


async def send_generated_video(bot: Bot, chat_id: int, prompt: str, narration_text: Optional[str] = None) -> None:
    """
    Генерит короткое видео MP4:
    - либо просто “слайд-шоу” из кадров
    - либо + TTS звук (если narration_text задан)
    """
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        frames = []
        for i in range(8):
            p = f"{prompt}\nКадр {i+1}/8, кинематографичный переход, тот же стиль."
            png = _image_png_bytes(prompt=p)
            fp = td_path / f"f{i+1}.png"
            fp.write_bytes(png)
            frames.append(fp)

        silent_mp4 = td_path / "video_silent.mp4"
        await _make_mp4_from_frames(frames, silent_mp4, fps=2, square=False)

        if narration_text:
            mp3 = _tts_mp3_bytes(text=narration_text, voice="alloy")
            audio_path = td_path / "voice.mp3"
            audio_path.write_bytes(mp3)

            final_mp4 = td_path / "video.mp4"
            cmd = [
                "ffmpeg", "-y",
                "-i", str(silent_mp4),
                "-i", str(audio_path),
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                str(final_mp4),
            ]
            await _run(cmd)
            data = final_mp4.read_bytes()
        else:
            data = silent_mp4.read_bytes()

        await bot.send_video(chat_id, BufferedInputFile(data, filename="balbes_video.mp4"))


async def send_generated_video_note(bot: Bot, chat_id: int, prompt: str, narration_text: Optional[str] = None) -> None:
    """
    Кружок (video note): делаем квадратное видео.
    """
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        frames = []
        for i in range(8):
            p = f"{prompt}\nКадр {i+1}/8, тот же стиль, крупнее лицо/центральный объект."
            png = _image_png_bytes(prompt=p)
            fp = td_path / f"f{i+1}.png"
            fp.write_bytes(png)
            frames.append(fp)

        silent_mp4 = td_path / "circle_silent.mp4"
        await _make_mp4_from_frames(frames, silent_mp4, fps=2, square=True)

        if narration_text:
            mp3 = _tts_mp3_bytes(text=narration_text, voice="alloy")
            audio_path = td_path / "voice.mp3"
            audio_path.write_bytes(mp3)

            final_mp4 = td_path / "circle.mp4"
            cmd = [
                "ffmpeg", "-y",
                "-i", str(silent_mp4),
                "-i", str(audio_path),
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                str(final_mp4),
            ]
            await _run(cmd)
            data = final_mp4.read_bytes()
        else:
            data = silent_mp4.read_bytes()

        await bot.send_video_note(chat_id, BufferedInputFile(data, filename="balbes_circle.mp4"))
