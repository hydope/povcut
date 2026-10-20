"""Post: dual-track publishing.

Track A — official APIs via the shared creator-publish package
    (YouTube first; TikTok/Instagram/X/... when configured).
    BYO keys; nothing is scraped, nothing impersonates a human.

Track B — the honest escape hatch: a handoff pack for one-tap native
    publishing. No companion app needed: clip + caption.txt + a
    POSTING.md that walks the creator through posting natively in
    under a minute. For creators who fail an API audit or fear the
    (unproven but believed) API-reach penalty.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _cp():
    try:
        import creator_publish  # noqa: F401
        from creator_publish import schedule as sched
        from creator_publish.publish import publish
        return publish, sched
    except ImportError:
        raise SystemExit(
            "Posting needs the shared publishing package:\n"
            "  pip install creator-publish\n"
            "(or: pip install git+https://github.com/hydope/creator-publish)"
        )


def post_now(clip: str, platform: str = "youtube", title: str = "",
             description: str = "", hashtags: list[str] | None = None,
             dry_run: bool = False) -> dict:
    publish, _ = _cp()
    return publish(platform, Path(clip), title=title,
                   description=description, hashtags=hashtags or [],
                   dry_run=dry_run)


def schedule_post(clip: str, when: str, platform: str = "youtube",
                  title: str = "", description: str = "",
                  hashtags: list[str] | None = None) -> int:
    """Queue a publish job via creator-publish's durable scheduler."""
    _, sched = _cp()
    from creator_publish.config import Config
    cfg = Config()
    run_at = sched.parse_when(when, cfg.get("timezone"))
    return sched.enqueue(run_at, "publish", {
        "platform": platform,
        "video": str(Path(clip).resolve()),
        "title": title,
        "description": description,
        "hashtags": hashtags or [],
    })


def handoff(clip: str, out_dir: str | None = None,
            caption: str = "") -> str:
    """Track B: build the native-posting handoff pack. Returns its dir."""
    clip_path = Path(clip)
    dest = Path(out_dir or (clip_path.parent / (clip_path.stem + "_handoff")))
    dest.mkdir(parents=True, exist_ok=True)
    final = dest / clip_path.name
    if clip_path.resolve() != final.resolve():
        shutil.copy2(clip_path, final)
    if caption:
        (dest / "caption.txt").write_text(caption)
    (dest / "POSTING.md").write_text(
        "# Post this natively (under a minute)\n\n"
        f"1. Send `{clip_path.name}` to your phone (AirDrop / cable / Drive).\n"
        "2. Open TikTok / Instagram / YouTube.\n"
        "3. Upload the clip, paste the text from `caption.txt` as the caption.\n"
        "4. Post. Done — no API, no audit, no reach risk.\n\n"
        "Why native? Some creators prefer posting from the app itself.\n"
        "Track A (official APIs) is there when you want scheduling instead.\n"
    )
    return str(dest)
