# Reddit drafts — post Tuesday morning ET

## r/raybanmeta (primary)

**Title:** I built a tool that turns your glasses footage into Shorts/TikToks with one command

**Body:**

I love shooting POV on my Ray-Ban Metas, but I hated the editing part —
scrubbing through hours of footage to find the 30 seconds worth posting.

So I built povcut (open source, MIT). You point it at a folder of footage:

```
pip install povcut
povcut pipeline ~/footage
```

and it:

- finds the moments worth clipping, ranked 0-100 (it listens for the loud
  bits — laughter, reactions — plus scene changes and faces, and tells you
  *why* each moment scored what it did)
- cuts them into vertical 1080x1920 shorts with a face-following crop
  and burned-in captions
- packs each clip with a thumbnail + ready-to-paste caption and hashtags

Bonus feature: `povcut spin` rewrites any clip into the Ray-Ban Meta
QuickTime structure so Instagram treats it as glasses footage and enables
Spin View — yes, even for phone footage. (Structural recipe credit to the
metaspin project's public reverse-engineering; I reimplemented it with a
self-check that verifies the output.)

Pure Python + ffmpeg, no accounts or API keys needed. Would love feedback
from actual creators — what's missing from your footage-to-post workflow?

github.com/hydope/povcut

---

## r/VideoEditing (secondary, a day later)

**Title:** [Tool] povcut — auto-finds the best moments in long POV footage and cuts vertical shorts

**Body:** (shorter version of the above, focused on the moment-detection +
auto-reframe pipeline; mention it's built for Ray-Ban Meta footage but
works on any video)
