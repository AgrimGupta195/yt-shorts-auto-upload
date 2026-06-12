import re
from pathlib import Path

from app.config import settings
from app.models import SegmentAsset


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _wrap_line(text: str, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current: list[str] = []
    length = 0

    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and length + extra > max_chars:
            lines.append(" ".join(current))
            current = [word]
            length = len(word)
        else:
            current.append(word)
            length += extra

    if current:
        lines.append(" ".join(current))
    return lines


def _wrap_caption(text: str) -> str:
    lines = _wrap_line(text.strip(), settings.subtitle_max_chars_per_line)
    max_lines = settings.subtitle_max_lines
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    return "\n".join(lines)


def _split_into_chunks(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return []

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    chunks: list[str] = []
    max_words = settings.subtitle_max_words_per_chunk

    for sentence in sentences:
        words = sentence.split()
        for index in range(0, len(words), max_words):
            chunk = " ".join(words[index : index + max_words])
            if chunk:
                chunks.append(chunk)

    return chunks or [cleaned]


class SubtitleService:
    def generate_srt(self, segments: list[SegmentAsset], output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        cursor = 0.0
        cue_index = 1

        for segment in segments:
            chunks = _split_into_chunks(segment.text)
            if not chunks:
                continue

            segment_start = cursor
            segment_end = segment_start + segment.duration_seconds
            total_chars = sum(len(chunk) for chunk in chunks)

            for index, chunk in enumerate(chunks):
                start = cursor
                if index == len(chunks) - 1:
                    end = segment_end
                else:
                    proportion = len(chunk) / total_chars
                    end = start + (segment.duration_seconds * proportion)

                lines.extend(
                    [
                        str(cue_index),
                        f"{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}",
                        _wrap_caption(chunk),
                        "",
                    ]
                )
                cue_index += 1
                cursor = end

        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path


subtitle_service = SubtitleService()
