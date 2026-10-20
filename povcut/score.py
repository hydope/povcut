"""Viral score: 0-100 per segment, with human-readable reasons."""

from __future__ import annotations

import statistics

from .util import clamp


def _face_ratio(path: str, start: float, end: float) -> float | None:
    """Fraction of sampled frames containing a face (needs `vision` extra)."""
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    hits, total = 0, 0
    t = start
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        total += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if len(cascade.detectMultiScale(gray, 1.2, 4)) > 0:
            hits += 1
        t += max(2.0, (end - start) / 8)
    cap.release()
    return (hits / total) if total else 0.0


def score_segments(segments: list[dict],
                   energy: list[tuple[float, float]],
                   path: str) -> list[dict]:
    """Attach score (0-100) + reasons to each segment."""
    if energy:
        vals = [db for _, db in energy]
        lo = min(vals)
        span = max(vals) - lo or 1.0
    else:
        lo, span = -70.0, 1.0

    def loudness(a: float, b: float) -> float:
        pts = [db for t, db in energy if a <= t < b]
        if not pts:
            return 0.0
        return clamp((statistics.fmean(pts) - lo) / span, 0.0, 1.0)

    scored = []
    for seg in segments:
        a, b, length = seg["start"], seg["end"], seg["end"] - seg["start"]
        loud = loudness(a, b)
        # 15-45 s is the Shorts/TikTok sweet spot
        if 15 <= length <= 45:
            dur_score = 1.0
        elif length < 15:
            dur_score = 0.4 + 0.6 * (length / 15)
        else:
            dur_score = max(0.3, 1.0 - (length - 45) / 60)

        face = _face_ratio(path, a, b)
        face_score = clamp(face, 0.0, 1.0) if face is not None else 0.5

        score = round(
            100 * (0.45 * loud + 0.30 * dur_score + 0.25 * face_score), 1
        )
        reasons = []
        if loud > 0.7:
            reasons.append("loud moment (laughter / reaction / applause)")
        elif loud > 0.45:
            reasons.append("lively audio")
        if 15 <= length <= 45:
            reasons.append("ideal Shorts length")
        if face is not None and face > 0.5:
            reasons.append("faces on camera")
        if not reasons:
            reasons.append("scene change")
        scored.append({**seg, "score": score, "reasons": reasons})
    return scored
