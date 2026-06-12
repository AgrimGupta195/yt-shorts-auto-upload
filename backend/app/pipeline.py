import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.models import SegmentAsset, ShortScript
from app.services.image_service import ImageService
from app.services.script_service import ScriptService
from app.services.subtitle_service import subtitle_service
from app.services.video_service import video_service
from app.services.voiceover_service import tts_service
from app.services.youtube_service import YouTubeService


class ShortsPipeline:
    def __init__(self, output_dir: Path | None = None):
        self.output_dir = output_dir or settings.output_dir
        self.script_service = ScriptService()
        self.image_service = ImageService()

    def _create_run_dir(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        run_dir = self.output_dir / stamp
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _build_segment_assets(self, script: ShortScript, assets_dir: Path) -> list[SegmentAsset]:
        segment_assets: list[SegmentAsset] = []

        for index, segment in enumerate(script.segments):
            print(f"   Segment {index + 1}/{len(script.segments)}")
            audio_path = assets_dir / f"segment_{index:02d}.mp3"
            image_path = assets_dir / f"segment_{index:02d}.png"

            if audio_path.exists() and audio_path.stat().st_size > 500:
                print("   - voiceover (cached)...")
            else:
                print("   - voiceover...")
                tts_service.generate_audio_file(segment.text, audio_path)

            duration = tts_service.get_audio_duration_seconds(audio_path)
            print(f"   - image ({duration:.1f}s)...")

            if image_path.exists() and image_path.stat().st_size > 1000:
                print("   - image (cached)")
            else:
                self.image_service.generate_image(segment.image_prompt, image_path)

            segment_assets.append(
                SegmentAsset(
                    index=index,
                    text=segment.text,
                    image_prompt=segment.image_prompt,
                    audio_path=str(audio_path),
                    image_path=str(image_path),
                    duration_seconds=duration,
                )
            )

        return segment_assets

    def _cleanup_output(self) -> None:
        if not self.output_dir.exists():
            return

        for item in self.output_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        print(f"   Cleaned up output folder: {self.output_dir.resolve()}")

    def run(
        self,
        topic: str | None = None,
        upload: bool | None = None,
        resume_dir: Path | None = None,
    ) -> dict:
        if resume_dir:
            run_dir = Path(resume_dir)
            if not (run_dir / "script.json").exists():
                raise FileNotFoundError(f"No script.json found in {run_dir}")
            script = ShortScript.model_validate_json((run_dir / "script.json").read_text(encoding="utf-8"))
            print(f"1/6 Resuming run: {run_dir.name}")
            print(f"   Title: {script.title}")
        else:
            run_dir = self._create_run_dir()
            print("1/6 Generating script with Groq...")
            script = self.script_service.generate_script(topic or settings.topic or None)
            (run_dir / "script.json").write_text(
                script.model_dump_json(indent=2),
                encoding="utf-8",
            )
            print(f"   Title: {script.title}")

        assets_dir = run_dir / "assets"
        work_dir = run_dir / "work"
        assets_dir.mkdir(parents=True, exist_ok=True)

        print("2/6 Generating voiceovers with Edge TTS...")
        print("3/6 Generating images with HuggingFace...")
        segments = self._build_segment_assets(script, assets_dir)

        print("4/6 Building captions...")
        srt_path = subtitle_service.generate_srt(segments, work_dir / "captions.srt")

        print("5/6 Rendering video with FFmpeg...")
        final_video = run_dir / "short.mp4"
        video_service.render_short(segments, srt_path, work_dir, final_video)

        result = {
            "title": script.title,
            "video_path": str(final_video),
            "run_dir": str(run_dir),
            "youtube_url": None,
        }

        should_upload = settings.upload_to_youtube if upload is None else upload
        if should_upload:
            print("6/6 Uploading to YouTube...")
            youtube = YouTubeService()
            result["youtube_url"] = youtube.upload_short(final_video, script)
            print(f"   Uploaded: {result['youtube_url']}")

            if settings.cleanup_output_after_upload:
                self._cleanup_output()
                result["video_path"] = None
                result["run_dir"] = None
        else:
            print("6/6 Skipping YouTube upload (upload_to_youtube=false)")
            (run_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

        return result


def run_pipeline(
    topic: str | None = None,
    upload: bool | None = None,
    resume_dir: Path | str | None = None,
) -> dict:
    resolved_resume = Path(resume_dir) if resume_dir else None
    return ShortsPipeline().run(topic=topic, upload=upload, resume_dir=resolved_resume)
