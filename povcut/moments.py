"""Find the moments worth clipping: scene cuts + audio energy peaks.

Glasses record hours; nobody scrubs hours. POVCut watches the footage
for you and ranks candidate moments by a 0-100 "viral score":

- audio peaks (laughter, exclamations, gasps, applause)
- visual change (scene cuts = something new happened)
- faces on camera (optional, needs the `vision` extra)
- duration sweet spot (15-45 s is Shorts/TikTok gold)

Output is moments.json: every candidate with start/end/score/reasons.
"""

from __future__ import annotations

import json
import os
import re
import statistics

from .util import duration, need_tools, probe, run

SCENE_THRESHOLD = 0.35
MIN_SEGMENT = 5.0
MAX_SEGMENT = 60.0
BIN = 0.5  # seconds per audio-energy bin


def scene_cuts(path: str) -> list[float]:
    """Timestamps where the picture changes a lot (ffmpeg select filter)."""
    cmd = [
        "ffmpeg", "-v", "info", "-i", path,
        "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',showinfo",
        "-f", "null", "-",
    ]
    p = run(cmd)
    cuts = []
    for m in re.finditer(r"pts_time:([\d.]+)", p.stderr):
        cuts.append(float(m.group(1)))
    return sorted(set(cuts))


def audio_energy(path: str) -> list[tuple[float, float]]:
    """Per-0.5s-bin RMS loudness in dB. Returns [(t, db), ...]."""
    cmd = [
        "ffmpeg", "-v", "info", "-i", path, "-vn",
        "-af", "astats=metadata=1:reset=1,"
               "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
        "-f", "null", "-",
    ]
    p = run(cmd)
    # ametadata=print with file=- writes to stdout, not stderr
    bins: dict[int, list[float]] = {}
    cur_t = 0.0
    for line in (p.stdout + "\n" + p.stderr).splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            cur_t = float(m.group(1))
            continue
        m = re.search(r"RMS_level=(-?[\d.]+|inf)", line)
        if m:
            val = m.group(1)
            db = -70.0 if val == "inf" else float(val)
            bins.setdefault(int(cur_t / BIN), []).append(db)
    out = [(i * BIN, statistics.fmean(v)) for i, v in sorted(bins.items())]
    return out


def energy_peaks(energy: list[tuple[float, float]]) -> list[float]:
    """Local maxima above the 80th percentile = the loud bits."""
    if len(energy) < 5:
        return []
    vals = [db for _, db in energy]
    thresh = statistics.quantiles(vals, n=5)[3]  # 80th percentile
    peaks = []
    for i in range(1, len(energy) - 1):
        t, db = energy[i]
        if db > thresh and db >= energy[i - 1][1] and db >= energy[i + 1][1]:
            peaks.append(t)
    return peaks


def _trim_to_hot_zone(a: float, b: float,
                     energy: list[tuple[float, float]]) -> tuple[float, float]:
    """Shrink a peak window to the contiguous hot zone (loud bins only)."""
    inside = [(t, db) for t, db in energy if a <= t < b]
    if len(inside) < 3:
        return a, b
    vals = sorted(db for _, db in inside)
    thresh = vals[int(len(vals) * 0.6)]  # 60th percentile
    hot = [t for t, db in inside if db >= thresh]
    if not hot:
        return a, b
    # longest contiguous run of hot bins
    runs, cur = [], [hot[0]]
    for t in hot[1:]:
        if t - cur[-1] <= BIN * 1.5:
            cur.append(t)
        else:
            runs.append(cur)
            cur = [t]
    runs.append(cur)
    best = max(runs, key=len)
    return max(a, best[0] - 1.0), min(b, best[-1] + BIN + 1.0)


def build_segments(path: str) -> list[dict]:
    """Candidate segments: loud windows merged, plus scene-change stretches."""
    total = duration(probe(path))
    energy = audio_energy(path)
    peaks = energy_peaks(energy)

    # one window per peak, merged where they overlap -> the "moment"
    windows = []
    for p in peaks:
        windows.append((max(0.0, p - 10.0), min(total, p + 10.0)))
    windows.sort()
    merged: list[list[float]] = []
    for a, b in windows:
        if merged and a <= merged[-1][1] + 2.0:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    # trim each loud window to its actual hot zone so scores stay honest
    merged = [list(_trim_to_hot_zone(a, b, energy)) for a, b in merged]

    # scene-change stretches for the quiet parts (something new happened)
    cuts = sorted(set([0.0, total] + scene_cuts(path)))
    for a, b in zip(cuts, cuts[1:]):
        if any(a < m[1] - 1.0 and b > m[0] + 1.0 for m in merged):
            continue  # already covered by a loud moment
        merged.append([a, b])

    segments = []
    for a, b in merged:
        while b - a > MAX_SEGMENT:
            segments.append((a, a + MAX_SEGMENT))
            a += MAX_SEGMENT
        if b - a >= MIN_SEGMENT:
            segments.append((a, b))
    segments.sort()
    return [{"start": round(a, 2), "end": round(b, 2)} for a, b in segments]


def analyze(path: str, out_dir: str | None = None) -> str:
    """Score every candidate moment; write moments.json. Returns its path."""
    need_tools("ffmpeg", "ffprobe")
    from .score import score_segments

    segments = build_segments(path)
    energy = audio_energy(path)
    scored = score_segments(segments, energy, path)
    scored.sort(key=lambda s: s["score"], reverse=True)

    out_dir = out_dir or os.path.join(os.path.dirname(path), ".povcut")
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(out_dir, f"{name}.moments.json")
    payload = {
        "source": path,
        "duration": round(duration(probe(path)), 2),
        "moments": scored,
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    return out_path
