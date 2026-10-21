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


def _face_track(path: str, start: float, end: float,
                crop_w: int, frame_w: int) -> list[tuple[float, int]] | None:
    """Per-frame face tracking: [(t_rel, crop_x), ...] at 4 samples/sec.

    The crop window follows the largest face, smoothed (moving average +
    velocity cap) so it glides instead of jittering. Returns None when
    OpenCV is missing or no face is ever seen — caller falls back to the
    static median-face crop.
    """
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    cap = cv2.VideoCapture(path)
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    step = 0.25
    raw: list[tuple[float, float | None]] = []
    t = start
    while t < end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.2, 4)
        cx = None
        if len(faces):
            x, _y, w, _h = max(faces, key=lambda f: f[2] * f[3])
            cx = x + w / 2
        raw.append((t - start, cx))
        t += step
    cap.release()

    seen = [c for _, c in raw if c is not None]
    if len(seen) < 4:
        return None
    # fill gaps by holding the last seen position (start: first seen)
    filled: list[float] = []
    last = seen[0]
    for _, cx in raw:
        if cx is not None:
            last = cx
        filled.append(last)
    # desired crop x per sample, clamped to the frame
    want = [min(max(c - crop_w / 2, 0), max(frame_w - crop_w, 0))
            for c in filled]
    # smooth: centered moving average, then cap velocity (no jumps)
    smooth: list[float] = []
    for i in range(len(want)):
        lo = max(0, i - 2)
        hi = min(len(want), i + 3)
        smooth.append(sum(want[lo:hi]) / (hi - lo))
    max_step = crop_w * 0.06  # per 0.25 s sample
    out: list[tuple[float, int]] = []
    prev = smooth[0]
    for i, v in enumerate(smooth):
        v = min(max(v, prev - max_step), prev + max_step)
        out.append((round(i * step, 2), int(v)))
        prev = v
    return out


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
    track = _face_track(path, start, end, crop_w, w)
    cmd_file = None
    if track and max(x for _, x in track) - min(x for _, x in track) > 20:
        # per-frame tracking: the crop window follows the face
        import tempfile
        fd, cmd_file = tempfile.mkstemp(prefix="povcut-track-",
                                        suffix=".cmd")
        with os.fdopen(fd, "w") as f:
            for t_rel, cx in track:
                f.write(f"{t_rel:.2f} [enter] crop@trk x {cx};\n")
        x0 = track[0][1]
        crop = (f"sendcmd=f={cmd_file},"
                f"crop@trk=w={crop_w}:h={h}:x={x0}:y=0")
    else:
        center = _face_center_x(path, start, end, w)
        if center is None:
            center = w / 2
        x = int(min(max(center - crop_w / 2, 0), max(w - crop_w, 0)))
        crop = f"crop=w={crop_w}:h={h}:x={x}:y=0"

    vf = crop + f",scale={OUT_W}:{OUT_H}:flags=lanczos"
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
    if cmd_file:
        try:
            os.remove(cmd_file)
        except OSError:
            pass
    if p.returncode != 0:
        raise SystemExit(f"ffmpeg cut failed:\n{p.stderr.strip()}")
    return out_path
