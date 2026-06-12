import asyncio
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

import edge_tts
from edge_tts.exceptions import NoAudioReceived
from mutagen.mp3 import MP3

from app.config import settings
from app.utils.ffmpeg_utils import find_ffprobe


def _sanitize_tts_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip())
    cleaned = cleaned.replace("—", "-").replace("–", "-").replace("…", "...")
    return cleaned


class EdgeTTSService:
    def __init__(self, voice: Optional[str] = None):
        self.voice = voice or settings.edge_tts_voice

    async def _generate_audio_file(self, text: str, output_path: Path, voice: str) -> Path:
        safe_text = _sanitize_tts_text(text)
        if not safe_text:
            raise ValueError("Cannot generate voiceover from empty text.")

        last_error: Exception | None = None
        for attempt in range(settings.tts_max_retries):
            if output_path.exists():
                output_path.unlink()

            try:
                communicate = edge_tts.Communicate(text=safe_text, voice=voice)
                await communicate.save(str(output_path))
                if not output_path.exists() or output_path.stat().st_size < 500:
                    raise NoAudioReceived("Generated audio file was empty.")
                return output_path
            except (NoAudioReceived, OSError, ConnectionError) as exc:
                last_error = exc
                if attempt + 1 < settings.tts_max_retries:
                    wait = settings.tts_retry_delay_seconds * (attempt + 1)
                    print(f"   [tts] Retry {attempt + 2}/{settings.tts_max_retries} in {wait:.0f}s...")
                    await asyncio.sleep(wait)

        raise RuntimeError(
            f"Edge TTS failed after {settings.tts_max_retries} attempts: {last_error}"
        ) from last_error

    def generate_audio_file(self, text: str, output_path: Path, voice: Optional[str] = None) -> Path:
        target_voice = voice or self.voice
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._generate_audio_file(text, output_path, target_voice))
            time.sleep(settings.tts_request_delay_seconds)
            return output_path

        raise RuntimeError(
            "generate_audio_file() cannot be called from an active event loop. "
            "Use await generate_audio_file_async(...) instead."
        )

    async def generate_audio_file_async(
        self, text: str, output_path: Path, voice: Optional[str] = None
    ) -> Path:
        target_voice = voice or self.voice
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = await self._generate_audio_file(text, output_path, target_voice)
        await asyncio.sleep(settings.tts_request_delay_seconds)
        return result

    @staticmethod
    def get_audio_duration_seconds(audio_path: Path) -> float:
        if audio_path.suffix.lower() == ".mp3":
            return MP3(str(audio_path)).info.length

        result = subprocess.run(
            [
                find_ffprobe(),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())


tts_service = EdgeTTSService()
