"""Shared helpers: ffmpeg probing, file discovery, hashing."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess

VIDEO_EXTS = (".mov", ".mp4", ".m4v", ".mkv", ".avi", ".webm")


def need_tools(*names: str) -> None:
    missing = [n for n in names if shutil.which(n) is None]
    if missing:
        raise SystemExit(
            "Missing required tools: %s. Install ffmpeg (which provides "
            "ffmpeg and ffprobe) and make sure it is on your PATH."
            % ", ".join(missing)
        )


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def probe(path: str) -> dict:
    """ffprobe -> dict with streams/format (raises SystemExit on failure)."""
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", path,
    ]
    p = run(cmd)
    if p.returncode != 0:
        raise SystemExit(f"ffprobe failed on {path}:\n{p.stderr.strip()}")
    return json.loads(p.stdout or "{}")


def video_stream(info: dict) -> dict:
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            return s
    raise SystemExit("No video stream found.")


def has_audio(info: dict) -> bool:
    return any(s.get("codec_type") == "audio" for s in info.get("streams", []))


def duration(info: dict) -> float:
    fmt = info.get("format", {})
    try:
        return float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


def find_videos(folder: str) -> list[str]:
    out = []
    for root, _dirs, files in os.walk(folder):
        for f in sorted(files):
            if f.startswith("."):
                continue
            if f.lower().endswith(VIDEO_EXTS):
                out.append(os.path.join(root, f))
    return out


def quick_hash(path: str) -> str:
    """Cheap dedupe hash: size + head/tail sample."""
    h = hashlib.sha1()
    size = os.path.getsize(path)
    h.update(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
        if size > (1 << 21):
            f.seek(-(1 << 20), os.SEEK_END)
            h.update(f.read(1 << 20))
    return h.hexdigest()[:16]


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))
