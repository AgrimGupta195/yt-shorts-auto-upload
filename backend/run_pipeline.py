import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.pipeline import run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the YouTube Shorts automation pipeline.")
    parser.add_argument("--topic", help="Optional topic for the short")
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Render locally without uploading to YouTube",
    )
    parser.add_argument(
        "--resume",
        help="Resume a previous run folder (reuses cached audio/images)",
    )
    args = parser.parse_args()

    result = run_pipeline(
        topic=args.topic,
        upload=not args.no_upload,
        resume_dir=args.resume,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
