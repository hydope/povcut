"""Stats + the tuning experiment (Phase 3).

Hypothesis: per-creator scoring weights, tuned on what actually popped
for THIS creator, beat the static defaults.

Kill criteria — enforced in code, not in a doc:
  - weights stay FROZEN until >= MIN_CLIPS posted clips are recorded;
  - the phase is declared dead (and static scoring kept) if, once the
    data exists, feature/view correlation is too weak to act on
    (|r| < MIN_SIGNAL for every feature).

Instrumentation ships now; conclusions wait for data. `record_post`
is called after every Track A post; `refresh` pulls views/likes;
`tune` refuses to run until the criteria allow it.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIN_CLIPS = 50           # kill-criterion: no tuning before this many posts
MIN_SPAN_DAYS = 60       # kill-criterion: and not before this much history
MIN_SIGNAL = 0.25        # kill-criterion: |r| below this = no signal, dead

DB = Path.home() / ".povcut" / "stats.db"


def _db() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS clips(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        clip TEXT NOT NULL, platform TEXT NOT NULL, external_id TEXT,
        posted_at TEXT NOT NULL, features TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS metrics(
        clip_id INTEGER NOT NULL, checked_at TEXT NOT NULL,
        views INTEGER, likes INTEGER, comments INTEGER)""")
    con.commit()
    return con


def record_post(clip: str, platform: str, external_id: str | None,
                features: dict) -> int:
    con = _db()
    cur = con.execute(
        "INSERT INTO clips(clip, platform, external_id, posted_at, features)"
        " VALUES(?,?,?,?,?)",
        (clip, platform, external_id,
         datetime.now(timezone.utc).isoformat(),
         json.dumps(features)))
    con.commit()
    return int(cur.lastrowid)


def record_metrics(clip_id: int, views: int, likes: int, comments: int) -> None:
    con = _db()
    con.execute(
        "INSERT INTO metrics(clip_id, checked_at, views, likes, comments)"
        " VALUES(?,?,?,?,?)",
        (clip_id, datetime.now(timezone.utc).isoformat(),
         views, likes, comments))
    con.commit()


def list_clips() -> list[dict]:
    con = _db()
    rows = con.execute(
        "SELECT c.id, c.clip, c.platform, c.external_id, c.posted_at,"
        " (SELECT views FROM metrics m WHERE m.clip_id=c.id"
        "  ORDER BY checked_at DESC LIMIT 1)"
        " FROM clips c ORDER BY c.id").fetchall()
    return [{"id": r[0], "clip": r[1], "platform": r[2],
             "external_id": r[3], "posted_at": r[4], "views": r[5]}
            for r in rows]


def refresh() -> list[dict]:
    """Pull latest views/likes/comments for posted clips (best effort).

    YouTube works once the OAuth grant includes the readonly scope; other
    platforms are reported as pending (their insights APIs need separate
    approvals). Nothing here fakes data: no metrics, no tuning.
    """
    con = _db()
    out = []
    for row in con.execute(
            "SELECT id, platform, external_id FROM clips"
            " WHERE external_id IS NOT NULL"):
        cid, platform, ext = row
        if platform != "youtube":
            out.append({"id": cid, "platform": platform,
                        "status": "pending (insights API not wired yet)"})
            continue
        try:
            from creator_publish.publish.youtube import _service
            yt = _service()
            resp = yt.videos().list(
                part="statistics", id=ext).execute()
            items = resp.get("items", [])
            if not items:
                out.append({"id": cid, "status": "video not found"})
                continue
            s = items[0]["statistics"]
            record_metrics(cid, int(s.get("viewCount", 0)),
                           int(s.get("likeCount", 0)),
                           int(s.get("commentCount", 0)))
            out.append({"id": cid, "platform": platform,
                        "status": "refreshed",
                        "views": s.get("viewCount")})
        except Exception as e:  # scope missing, revoked token, quota...
            out.append({"id": cid, "platform": platform,
                        "status": f"failed: {e}"})
    return out


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


class ExperimentNotReady(Exception):
    """Raised when the kill criteria say: not enough data / no signal."""


def tune() -> dict:
    """Attempt per-creator weight tuning. Refuses until criteria are met."""
    con = _db()
    rows = con.execute(
        "SELECT c.features,"
        " (SELECT views FROM metrics m WHERE m.clip_id=c.id"
        "  ORDER BY checked_at DESC LIMIT 1) AS views,"
        " c.posted_at FROM clips c").fetchall()
    data = [(json.loads(f), v, p) for f, v, p in rows if v is not None]

    if len(data) < MIN_CLIPS:
        raise ExperimentNotReady(
            f"tuning is frozen: {len(data)}/{MIN_CLIPS} clips with metrics. "
            "Static scoring stays. This is the kill criteria working.")
    span = (datetime.now(timezone.utc)
            - min(datetime.fromisoformat(d[2]) for d in data)).days
    if span < MIN_SPAN_DAYS:
        raise ExperimentNotReady(
            f"tuning is frozen: {span}/{MIN_SPAN_DAYS} days of history.")

    feats = ["loudness", "duration_fit", "face_ratio"]
    corrs = {}
    for feat in feats:
        xs = [float(d[0].get(feat, 0.0)) for d in data]
        ys = [float(d[1]) for d in data]
        corrs[feat] = _pearson(xs, ys)

    if all(abs(r) < MIN_SIGNAL for r in corrs.values()):
        raise ExperimentNotReady(
            "no signal: no feature correlates with views "
            f"(|r| < {MIN_SIGNAL}). Phase 3 is dead by its own criteria; "
            "static scoring stays. Correlations: "
            + ", ".join(f"{k}={v:+.2f}" for k, v in corrs.items()))

    # nudge weights toward the winning features (bounded, conservative)
    base = {"loudness": 0.45, "length": 0.30, "faces": 0.25}
    keymap = {"loudness": "loudness", "duration_fit": "length",
              "face_ratio": "faces"}
    weights = dict(base)
    for feat, r in corrs.items():
        weights[keymap[feat]] = max(0.10, min(0.70, base[keymap[feat]] + r * 0.15))
    total = sum(weights.values())
    weights = {k: round(v / total, 3) for k, v in weights.items()}
    return {"weights": weights, "correlations": corrs, "n": len(data)}
