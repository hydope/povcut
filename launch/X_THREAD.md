# X thread draft — post Tuesday morning ET, ~1 tweet per 20 min

1/
My Ray-Ban Meta glasses record for hours.
Nobody watches hours.

So I built povcut: one command turns a folder of POV footage
into ready-to-post vertical shorts.

pip install povcut
povcut pipeline ~/footage

[demo video]

2/
How it finds the good bits — no black box:

- audio energy peaks (laughter, reactions, applause) — 45%
- 15-45s Shorts-length fit — 30%
- faces on camera — 25%

Every moment gets a 0-100 score WITH reasons printed next to it.

3/
Then it cuts: smart 9:16 crop that follows faces,
burned-in captions, 1080x1920, 30fps.

Each clip ships in a pack: clip.mp4 + thumbnail +
a ready-to-paste caption with hashtags.

Paste and post. That's the whole workflow.

4/
The spicy feature: `povcut spin`

Instagram decides a video "came from Meta glasses" by its
QuickTime structure, not its pixels.

povcut rewrites ANY clip into that structure — so even phone
footage gets Spin View on Instagram.

5/
Pure Python + ffmpeg. MIT. No accounts, no API keys.
Auto-captions run fully on-device (faster-whisper, optional).

CI runs the entire pipeline on synthetic footage.

github.com/hydope/povcut

Built for every POV creator drowning in footage 🎥
