"""End-to-end tests. Needs ffmpeg/ffprobe on PATH (CI installs them)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from povcut import ingest, moments, reframe, score, spin, pack  # noqa: E402
from povcut import hud as hud_mod  # noqa: E402
from povcut.util import probe  # noqa: E402


def make_test_video(path: str, dur: int = 24) -> None:
    """Synthetic footage: 4 color blocks (scene cuts every 6 s) + a sine
    that gets loud between 9-15 s (the "moment" worth clipping)."""
    args = ["ffmpeg", "-y", "-v", "error"]
    for color in ("red", "blue", "green", "yellow"):
        args += ["-f", "lavfi", "-i",
                 f"color=c={color}:size=1280x720:rate=30:duration=6"]
    args += ["-f", "lavfi", "-i",
             f"sine=frequency=440:duration={dur}:sample_rate=48000"]
    args += [
        "-filter_complex",
        "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[v];"
        "[4:a]volume='if(between(t\\,9\\,15)\\,1.0\\,0.08)':eval=frame[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
        "-c:a", "aac", "-t", str(dur), path,
    ]
    subprocess.check_call(args)


class POVCutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for tool in ("ffmpeg", "ffprobe"):
            if shutil.which(tool) is None:
                raise unittest.SkipTest(f"{tool} not installed")
        cls.tmp = tempfile.mkdtemp(prefix="povcut-test-")
        cls.video = os.path.join(cls.tmp, "footage.mp4")
        make_test_video(cls.video)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_ingest_dedupes(self):
        lib = os.path.join(self.tmp, "lib")
        src = os.path.join(self.tmp, "src")
        os.makedirs(src)
        shutil.copy2(self.video, os.path.join(src, "a.mp4"))
        first = ingest.import_folder(src, library=lib)
        second = ingest.import_folder(src, library=lib)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)

    def test_moments_found_and_ranked(self):
        out = moments.analyze(self.video,
                              out_dir=os.path.join(self.tmp, "m"))
        with open(out) as f:
            data = json.load(f)
        ms = data["moments"]
        self.assertGreater(len(ms), 0)
        scores = [m["score"] for m in ms]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for m in ms:
            self.assertLessEqual(m["start"], m["end"])
            self.assertTrue(0 <= m["score"] <= 100)
            self.assertTrue(m["reasons"])
        # the loud 9-15 s window must win, with a "loud moment" reason
        top = ms[0]
        self.assertLess(top["start"], 12)
        self.assertGreater(top["end"], 9)
        self.assertTrue(any("loud" in r for r in top["reasons"]))

    def test_score_math(self):
        segs = [{"start": 0.0, "end": 30.0}, {"start": 30.0, "end": 35.0}]
        energy = [(t * 0.5, -20.0 if 18 <= t * 0.5 < 24 else -50.0)
                  for t in range(120)]
        scored = score.score_segments(segs, energy, self.video)
        # the loud 18-24 s window sits inside the first segment
        self.assertGreater(scored[0]["score"], scored[1]["score"])

    def test_cut_is_vertical(self):
        m = {"start": 8.0, "end": 14.0, "score": 88.0, "reasons": ["loud moment"]}
        out = os.path.join(self.tmp, "clip.mp4")
        reframe.cut_clip(self.video, m, out)
        info = probe(out)
        vs = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((int(vs["width"]), int(vs["height"])), (1080, 1920))

    def test_hud_themes(self):
        self.assertEqual(hud_mod.build_filter("off", 10.0), "")
        self.assertIn("drawbox", hud_mod.build_filter("minimal", 10.0))
        tactical = hud_mod.build_filter("tactical", 10.0, title="wait for it...")
        self.assertIn("REC", tactical)
        self.assertIn("drawtext", tactical)
        self.assertRaises(ValueError, hud_mod.build_filter, "nope", 10.0)
        self.assertEqual(hud_mod.hook_title("loud moment (laughter)"),
                         "wait for it...")

    def test_hud_changes_pixels(self):
        """Done-criteria: tactical HUD must visibly alter the frame."""
        m = {"start": 8.0, "end": 14.0, "score": 88.0,
             "reasons": ["loud moment"]}
        plain = os.path.join(self.tmp, "hud_off.mp4")
        fancy = os.path.join(self.tmp, "hud_tac.mp4")
        reframe.cut_clip(self.video, m, plain, hud="off", hook=False)
        reframe.cut_clip(self.video, m, fancy, hud="tactical", hook=True)

        def frame_mean(path, t=1.0):
            out = os.path.join(self.tmp, "f.ppm")
            subprocess.check_call([
                "ffmpeg", "-y", "-v", "error", "-ss", str(t),
                "-i", path, "-frames:v", "1", out])
            with open(out, "rb") as f:
                data = f.read()
            return sum(data) / len(data)

        diff = abs(frame_mean(plain) - frame_mean(fancy))
        self.assertGreater(diff, 0.5,
                           "tactical HUD did not visibly change the frame")

    def test_post_tracks(self):
        from povcut import post as post_mod
        clip = os.path.join(self.tmp, "postclip.mp4")
        m = {"start": 8.0, "end": 14.0, "score": 88.0,
             "reasons": ["loud moment"], "_source": "footage.mp4"}
        reframe.cut_clip(self.video, m, clip, hud="off", hook=False)
        # Track A dry run: validates without posting or needing creds
        res = post_mod.post_now(clip, platform="youtube", title="t",
                                hashtags=["#pov"], dry_run=True)
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["platform"], "youtube")
        # Track B handoff: pack with instructions, no API involved
        dest = post_mod.handoff(clip, os.path.join(self.tmp, "hand"),
                                caption="hello")
        self.assertTrue(os.path.isfile(os.path.join(dest, "caption.txt")))
        self.assertTrue(os.path.isfile(os.path.join(dest, "POSTING.md")))
        self.assertTrue(os.path.isfile(
            os.path.join(dest, os.path.basename(clip))))

    def test_pack_layout(self):
        m = {"start": 8.0, "end": 14.0, "score": 88.0,
             "reasons": ["loud moment"], "_source": "footage.mp4"}
        clip = os.path.join(self.tmp, "pclip.mp4")
        reframe.cut_clip(self.video, m, clip)
        folder = pack.pack_clip(clip, m, os.path.join(self.tmp, "packs"))
        self.assertTrue(os.path.isfile(os.path.join(folder, "clip.mp4")))
        self.assertTrue(os.path.isfile(os.path.join(folder, "thumb.jpg")))
        cap = open(os.path.join(folder, "caption.txt")).read()
        self.assertIn("#raybanmeta", cap)

    def test_spin_structure(self):
        out = os.path.join(self.tmp, "footage_SPIN.MOV")
        result = spin.convert(self.video, out)
        self.assertEqual(result, out)
        problems = spin.verify(out)
        self.assertEqual(problems, [], f"spin verify failed: {problems}")
        # and it still plays: duration sane, 2 streams
        info = probe(out)
        self.assertEqual(len(info["streams"]), 2)
        self.assertGreater(float(info["format"]["duration"]), 20)


if __name__ == "__main__":
    unittest.main()
