"""Pack: every clip ships ready to post — file, thumbnail, caption text.

Output layout:

    out/<clip-name>/
        clip.mp4        the vertical short
        thumb.jpg       frame at 1 s, vertical
        caption.txt     post caption + hashtags, ready to paste
"""

from __future__ import annotations

import os
import shutil

from .util import run

BASE_HASHTAGS = ["#raybanmeta", "#smartglasses", "#pov"]
REASON_HASHTAGS = {
    "loud": "#caughtoncamera",
    "ideal": "#shorts",
    "faces": "#irl",
}


def _thumbnail(clip: str, out: str) -> bool:
    p = run([
        "ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", clip,
        "-frames:v", "1", "-q:v", "3", out,
    ])
    return p.returncode == 0 and os.path.exists(out)


def _caption(moment: dict, source_name: str) -> str:
    reasons = ", ".join(moment.get("reasons", []))
    tags = list(BASE_HASHTAGS)
    for reason in moment.get("reasons", []):
        for key, tag in REASON_HASHTAGS.items():
            if key in reason and tag not in tags:
                tags.append(tag)
    return (
        f"POV: you won't believe what my glasses caught ({reasons})\n"
        f"Source: {source_name} · viral score {moment.get('score', '?')}/100\n"
        f"Shot on Ray-Ban Meta · cut with POVCut\n\n"
        + " ".join(tags)
    )


def pack_clip(clip: str, moment: dict, out_dir: str) -> str:
    """Create the ready-to-post pack folder for *clip*. Returns its path."""
    stem = os.path.splitext(os.path.basename(clip))[0]
    dest = os.path.join(out_dir, stem)
    os.makedirs(dest, exist_ok=True)
    final_clip = os.path.join(dest, "clip.mp4")
    if os.path.abspath(clip) != os.path.abspath(final_clip):
        shutil.copy2(clip, final_clip)
    _thumbnail(final_clip, os.path.join(dest, "thumb.jpg"))
    with open(os.path.join(dest, "caption.txt"), "w") as f:
        f.write(_caption(moment, os.path.basename(moment.get("_source", "footage"))))
    return dest
