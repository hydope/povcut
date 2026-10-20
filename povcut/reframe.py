"""Cut moments into vertical 1080x1920 shorts with a smart 9:16 crop.

If OpenCV is installed (the `vision` extra), the crop window follows the
faces on camera. Otherwise it falls back to a center crop biased slightly
toward the action (motion centroid via ffmpeg signalstats is future work).
"""

from __future__ import annotations

import os

from .util import probe, run, video_stream
from .hud import build_filter, hook_title

OUT_W, OUT_H = 1080, 1920


def _face_center_x(path: str, start: float, end: float,
                   frame_w: int) -> float | None:
    """Median x of the largest face across sampled frames, in pixels."""
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    cap = cv2.VideoCapture(path)
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    xs = []
    steps = 6
    for i in range(steps):
        t = start + (end - start) * (i + 0.5) / steps
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.2, 4)
        if len(faces):
            x, _y, w, _h = max(faces, key=lambda f: f[2] * f[3])
            xs.append(x + w / 2)
    cap.release()
    if not xs:
        return None
    xs.sort()
    return xs[len(xs) // 2]


def cut_clip(path: str, moment: dict, out_path: str,
             captions_srt: str | None = None,
             hud: str = "minimal", hook: bool = True) -> str:
    """Render one vertical clip for *moment*. Returns out_path."""
    info = probe(path)
    vs = video_stream(info)
    w, h = int(vs["width"]), int(vs["height"])
    start, end = moment["start"], moment["end"]
    duration = max(0.5, end - start)

    crop_w = max(2, int(h * OUT_W / OUT_H))
    center = _face_center_x(path, start, end, w)
    if center is None:
        center = w / 2
    x = int(min(max(center - crop_w / 2, 0), max(w - crop_w, 0)))

    vf = (f"crop=w={crop_w}:h={h}:x={x}:y=0,"
          f"scale={OUT_W}:{OUT_H}:flags=lanczos")
    if captions_srt:
        srt = captions_srt.replace("\\", "/").replace("'", "\\'")
        vf += (f",subtitles='{srt}':force_style="
               "'FontSize=13,Bold=1,PrimaryColour=&HFFFFFF,"
               "OutlineColour=&H80000000,BorderStyle=1,Outline=2,"
               "Alignment=2,MarginV=90'")
    title = None
    if hook:
        reasons = moment.get("reasons", [])
        title = hook_title(reasons[0]) if reasons else "watch this"
    hud_vf = build_filter(hud, duration, title=title)
    if hud_vf:
        vf += "," + hud_vf

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", str(start), "-to", str(end), "-i", path,
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium",
        "-crf", "20", "-r", "30",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        out_path,
    ]
    p = run(cmd)
    if p.returncode != 0:
        raise SystemExit(f"ffmpeg cut failed:\n{p.stderr.strip()}")
    return out_path
