"""HUD overlays: the "how did you film that?" layer.

Burns creator-style overlays onto vertical clips with plain FFmpeg filters
(drawtext/drawbox) — no GPU, no cloud, no dependencies beyond a font.

Themes:
  tactical — REC bug + running timecode + progress bar + kinetic
             lower-third (the comment-bait look)
  minimal  — slim progress bar + tiny timecode
  off      — nothing

If no system font is found, text layers degrade gracefully (the progress
bar is pure drawbox and always works).
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess

THEMES = ("tactical", "minimal", "off")


def find_font() -> str | None:
    """Best-effort system font for drawtext."""
    for pat in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ):
        if os.path.exists(pat):
            return pat
    if shutil.which("fc-list"):
        try:
            out = subprocess.run(
                ["fc-list", ":", "file"], capture_output=True, text=True,
                timeout=10,
            )
            for line in out.stdout.splitlines():
                path = line.split(":")[0].strip()
                if path.lower().endswith((".ttf", ".ttc", ".otf")):
                    return path
        except Exception:
            pass
    matches = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    return matches[0] if matches else None


def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:"))


def hook_title(reason: str) -> str:
    """Turn a moment reason into a 1.5-second hook title."""
    r = reason.lower()
    if "loud" in r or "laughter" in r or "reaction" in r:
        return "wait for it..."
    if "applause" in r:
        return "the crowd lost it"
    if "faces" in r:
        return "POV: you had to be there"
    if "scene" in r:
        return "POV"
    return "watch this"


def build_filter(theme: str, duration: float, title: str | None = None,
                 font: str | None = None) -> str:
    """Return an ffmpeg -vf fragment (empty string for theme 'off')."""
    if theme not in THEMES:
        raise ValueError(f"unknown HUD theme: {theme!r} (pick {THEMES})")
    if theme == "off":
        return ""
    font = font or find_font()
    parts: list[str] = []

    # progress bar — always works (no font needed)
    bar_h = 10 if theme == "tactical" else 6
    parts.append(
        f"drawbox=y=ih-{bar_h}:w='iw*t/{duration:.2f}':h={bar_h}:"
        f"c=white@0.85:t=fill"
    )

    if font:
        f = _esc(font)
        # running timecode, top-left
        parts.append(
            f"drawtext=fontfile='{f}':text='%{{pts\\:hms}}':"
            f"x=28:y=28:fontsize=30:fontcolor=white:"
            f"borderw=2:bordercolor=black@0.6"
        )
        if theme == "tactical":
            # REC bug, top-right
            parts.append(
                f"drawtext=fontfile='{f}':text='REC':"
                f"x=w-text_w-28:y=28:fontsize=30:fontcolor=red:"
                f"borderw=2:bordercolor=black@0.6"
            )
            parts.append("drawbox=x=w-96:y=30:w=18:h=18:c=red:t=fill")
            # POV bug, bottom-left above the bar
            parts.append(
                f"drawtext=fontfile='{f}':text='POV':"
                f"x=28:y=h-90:fontsize=34:fontcolor=white@0.9:"
                f"borderw=2:bordercolor=black@0.6"
            )
            # kinetic lower-third for the first 4 s
            if title:
                t = _esc(title.upper())
                parts.append(
                    f"drawbox=x=28:y=h-260:w=560:h=64:"
                    f"c=black@0.55:t=fill:enable='between(t,0,4)'"
                )
                parts.append(
                    f"drawtext=fontfile='{f}':text='{t}':"
                    f"x=48:y=h-248:fontsize=34:fontcolor=white:"
                    f"enable='between(t,0,4)'"
                )
        # hook title card — big, centered, first 1.5 s (both themes)
        if title:
            t = _esc(title)
            fs = 64 if theme == "tactical" else 54
            parts.append(
                f"drawtext=fontfile='{f}':text='{t}':"
                f"x=(w-text_w)/2:y=(h-text_h)/2-120:fontsize={fs}:"
                f"fontcolor=white:borderw=3:bordercolor=black@0.7:"
                f"enable='between(t,0,1.5)'"
            )
    return ",".join(parts)
