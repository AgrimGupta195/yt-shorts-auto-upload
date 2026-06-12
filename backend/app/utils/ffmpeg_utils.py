import os
import shutil
from functools import lru_cache
from pathlib import Path


def _search_windows_ffmpeg(name: str) -> Path | None:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None

    packages_dir = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
    if not packages_dir.exists():
        return None

    for package_dir in packages_dir.glob("Gyan.FFmpeg*"):
        for candidate in package_dir.rglob(name):
            if candidate.is_file():
                return candidate
    return None


@lru_cache(maxsize=1)
def find_ffmpeg() -> str:
    override = os.environ.get("FFMPEG_PATH", "").strip()
    if override:
        path = Path(override)
        if path.is_file():
            return str(path)
        binary = path / "ffmpeg.exe" if os.name == "nt" else path / "ffmpeg"
        if binary.is_file():
            return str(binary)

    found = shutil.which("ffmpeg")
    if found:
        return found

    windows_binary = _search_windows_ffmpeg("ffmpeg.exe")
    if windows_binary:
        return str(windows_binary)

    raise FileNotFoundError(
        "ffmpeg not found. Install it with `winget install Gyan.FFmpeg` "
        "or set FFMPEG_PATH to your ffmpeg binary."
    )


@lru_cache(maxsize=1)
def find_ffprobe() -> str:
    ffmpeg_path = Path(find_ffmpeg())
    probe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    sibling = ffmpeg_path.parent / probe_name
    if sibling.is_file():
        return str(sibling)

    found = shutil.which("ffprobe")
    if found:
        return found

    windows_binary = _search_windows_ffmpeg(probe_name)
    if windows_binary:
        return str(windows_binary)

    raise FileNotFoundError(
        "ffprobe not found. Install FFmpeg with `winget install Gyan.FFmpeg` "
        "or set FFMPEG_PATH to your ffmpeg install folder."
    )
