"""Import footage into a POVCut library: dedupe + date-organized.

Point it at the folder where your Ray-Ban Meta captures land (the Meta AI
app export folder, a mounted phone, an SD card) and POVCut copies new
clips into ~/Videos/POVCut/YYYY-MM-DD/ without ever importing the same
file twice.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

from .util import find_videos, probe, quick_hash

STATE_NAME = ".povcut.json"


def default_library() -> str:
    return os.path.join(os.path.expanduser("~"), "Videos", "POVCut")


def _load_state(library: str) -> dict:
    path = os.path.join(library, STATE_NAME)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"imported": {}}


def _save_state(library: str, state: dict) -> None:
    with open(os.path.join(library, STATE_NAME), "w") as f:
        json.dump(state, f, indent=2)


def capture_date(path: str) -> str:
    """Best-effort capture date: container creation_time, else file mtime."""
    try:
        info = probe(path)
        tags = info.get("format", {}).get("tags", {})
        stamp = tags.get("creation_time")
        if stamp:
            return stamp[:10]
    except SystemExit:
        pass
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")


def import_folder(source: str, library: str | None = None,
                 copy: bool = True) -> list[str]:
    """Import new videos from *source* into the library. Returns new paths."""
    from .util import need_tools
    need_tools("ffmpeg", "ffprobe")
    library = library or default_library()
    os.makedirs(library, exist_ok=True)
    state = _load_state(library)
    imported = state.setdefault("imported", {})

    new_paths: list[str] = []
    for src in find_videos(source):
        digest = quick_hash(src)
        if digest in imported:
            continue
        day = capture_date(src)
        dest_dir = os.path.join(library, day)
        os.makedirs(dest_dir, exist_ok=True)
        base = os.path.basename(src)
        dest = os.path.join(dest_dir, base)
        i = 1
        while os.path.exists(dest):
            stem, ext = os.path.splitext(base)
            dest = os.path.join(dest_dir, f"{stem}-{i}{ext}")
            i += 1
        if copy:
            shutil.copy2(src, dest)
        else:
            os.rename(src, dest)
        imported[digest] = dest
        new_paths.append(dest)

    _save_state(library, state)
    return new_paths
