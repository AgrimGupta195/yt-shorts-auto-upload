import subprocess
from pathlib import Path

from app.config import settings
from app.models import SegmentAsset
from app.utils.ffmpeg_utils import find_ffmpeg


class VideoService:
    def __init__(self):
        self.width = settings.video_width
        self.height = settings.video_height
        self.fps = settings.video_fps
        self.ffmpeg = find_ffmpeg()

    def _run(self, cmd: list[str]) -> None:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg failed:\nCMD: {' '.join(cmd)}\nSTDERR: {result.stderr}"
            )

    def _create_segment_clip(self, image_path: Path, duration: float, output_path: Path) -> None:
        vf = (
            f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,"
            f"crop={self.width}:{self.height},"
            f"zoompan=z='min(zoom+0.0015,1.15)':d={int(duration * self.fps)}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={self.width}x{self.height},"
            f"fps={self.fps}"
        )
        self._run(
            [
                self.ffmpeg,
                "-y",
                "-loop",
                "1",
                "-i",
                str(image_path),
                "-t",
                str(duration),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(output_path),
            ]
        )

    def _concat_audio(self, audio_files: list[Path], output_path: Path) -> None:
        list_file = output_path.with_suffix(".txt")
        list_file.write_text(
            "\n".join(f"file '{path.resolve().as_posix()}'" for path in audio_files),
            encoding="utf-8",
        )
        self._run(
            [
                self.ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(output_path),
            ]
        )

    def _concat_video(self, clip_files: list[Path], output_path: Path) -> None:
        list_file = output_path.with_suffix(".txt")
        list_file.write_text(
            "\n".join(f"file '{path.resolve().as_posix()}'" for path in clip_files),
            encoding="utf-8",
        )
        self._run(
            [
                self.ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(output_path),
            ]
        )

    def render_short(
        self,
        segments: list[SegmentAsset],
        srt_path: Path,
        work_dir: Path,
        output_path: Path,
    ) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        clip_paths: list[Path] = []
        audio_paths = [Path(segment.audio_path) for segment in segments]

        for segment in segments:
            clip_path = work_dir / f"clip_{segment.index:02d}.mp4"
            self._create_segment_clip(
                Path(segment.image_path),
                segment.duration_seconds,
                clip_path,
            )
            clip_paths.append(clip_path)

        video_only = work_dir / "video_only.mp4"
        audio_path = work_dir / "narration.mp3"
        merged_path = work_dir / "merged.mp4"

        self._concat_video(clip_paths, video_only)
        self._concat_audio(audio_paths, audio_path)

        self._run(
            [
                self.ffmpeg,
                "-y",
                "-i",
                str(video_only),
                "-i",
                str(audio_path),
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                str(merged_path),
            ]
        )

        srt_escaped = str(srt_path.resolve()).replace("\\", "/").replace(":", r"\:")
        margin_lr = settings.subtitle_margin_lr
        subtitle_style = (
            f"FontName=Arial,FontSize={settings.subtitle_font_size},"
            "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            f"Outline=3,Shadow=1,Alignment=2,MarginV={settings.subtitle_margin_v},"
            f"MarginL={margin_lr},MarginR={margin_lr},Bold=1,WrapStyle=0"
        )
        subtitle_filter = f"subtitles='{srt_escaped}':force_style='{subtitle_style}'"

        self._run(
            [
                self.ffmpeg,
                "-y",
                "-i",
                str(merged_path),
                "-vf",
                subtitle_filter,
                "-c:a",
                "copy",
                str(output_path),
            ]
        )
        return output_path


video_service = VideoService()
