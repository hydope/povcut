"""Captions: use your own .srt, or transcribe automatically.

Auto captions need the optional extra:

    pip install "povcut[auto-captions]"

which pulls in faster-whisper (runs fully on your machine, free).
"""

from __future__ import annotations

import os


def transcribe(path: str, start: float, end: float,
               language: str | None = None) -> str:
    """Transcribe a segment to an .srt next to the source. Returns path."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        raise SystemExit(
            "Auto captions need the extra: pip install \"povcut[auto-captions]\""
        )
    model = WhisperModel("small", device="auto", compute_type="int8")
    segments, _info = model.transcribe(
        path, language=language, vad_filter=True,
    )
    lines = []
    idx = 1
    for s in segments:
        if s.end < start or s.start > end:
            continue
        a = max(0.0, s.start - start)
        b = s.end - start
        lines.append(str(idx))
        lines.append(f"{_ts(a)} --> {_ts(b)}")
        lines.append(s.text.strip())
        lines.append("")
        idx += 1
    if not lines:
        raise SystemExit("Transcription produced no captions for this segment.")
    name = os.path.splitext(os.path.basename(path))[0]
    out = os.path.join(
        os.path.dirname(path), ".povcut",
        f"{name}.{int(start)}-{int(end)}.srt",
    )
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write("\n".join(lines))
    return out


def _ts(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")
