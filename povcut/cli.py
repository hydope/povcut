"""povcut: turn Ray-Ban Meta footage into viral shorts with one command."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__


def cmd_import(args) -> int:
    from .ingest import import_folder
    new = import_folder(args.source, library=args.library, copy=not args.move)
    print(f"Imported {len(new)} new clip(s) into the library.")
    for p in new:
        print("  " + p)
    return 0


def cmd_moments(args) -> int:
    from .moments import analyze
    out = analyze(args.video, out_dir=args.out_dir)
    with open(out) as f:
        data = json.load(f)
    moments = data["moments"]
    print(f"Found {len(moments)} moment(s) in {os.path.basename(args.video)}:")
    for i, m in enumerate(moments[: args.top]):
        print(f"  [{i}] {m['start']:7.1f}s -> {m['end']:7.1f}s  "
              f"score {m['score']:5.1f}  ({'; '.join(m['reasons'])})")
    print(f"\nFull ranking: {out}")
    return 0


def _load_moments(video: str, moments_json: str | None):
    if moments_json:
        with open(moments_json) as f:
            return json.load(f)["moments"]
    from .moments import analyze
    out = analyze(video)
    with open(out) as f:
        return json.load(f)["moments"]


def cmd_cut(args) -> int:
    from .captions import transcribe
    from .pack import pack_clip
    from .reframe import cut_clip

    moments = _load_moments(args.video, args.moments_json)
    picks = moments[: args.top]
    if args.pick is not None:
        picks = [moments[args.pick]]

    srt = args.captions
    if srt == "auto":
        srt = None  # transcribed per clip below
    os.makedirs(args.out, exist_ok=True)
    for i, m in enumerate(picks):
        m = dict(m)
        m["_source"] = args.video
        stem = (os.path.splitext(os.path.basename(args.video))[0]
                + f"_moment{i}_s{int(m['score'])}")
        clip_path = os.path.join(args.out, stem + ".mp4")
        clip_srt = srt
        if args.captions == "auto":
            try:
                clip_srt = transcribe(args.video, m["start"], m["end"],
                                      language=args.language)
            except SystemExit as e:
                print(f"  [!] captions skipped for moment {i}: {e}")
                clip_srt = None
        cut_clip(args.video, m, clip_path, captions_srt=clip_srt)
        folder = pack_clip(clip_path, m, args.out)
        print(f"  moment {i}: score {m['score']} -> {folder}")
    return 0


def cmd_spin(args) -> int:
    from .spin import convert, verify
    out = convert(args.video, args.out)
    problems = verify(out)
    if problems:
        print("Converted, but structural check found issues:")
        for p in problems:
            print("  - " + p)
        return 1
    print(f"Spin View-ready: {out}")
    print("Structural check passed (ftyp/wide/mdat/moov, meta, tapt, "
          "timescales, chunk offsets).")
    return 0


def cmd_pipeline(args) -> int:
    """import -> moments -> cut -> pack, the one-command happy path."""
    from .ingest import default_library, import_folder
    from .pack import pack_clip
    from .reframe import cut_clip
    from .captions import transcribe

    new = import_folder(args.source, library=args.library)
    if not new:
        print("Nothing new to import.")
        return 0
    out = args.out or os.path.join(args.library or default_library(), "shorts")
    os.makedirs(out, exist_ok=True)
    from .moments import analyze
    for video in new:
        moments_path = analyze(video)
        with open(moments_path) as f:
            moments = json.load(f)["moments"][: args.top]
        for i, m in enumerate(moments):
            m = dict(m)
            m["_source"] = video
            stem = (os.path.splitext(os.path.basename(video))[0]
                    + f"_moment{i}_s{int(m['score'])}")
            clip_path = os.path.join(out, stem + ".mp4")
            clip_srt = None
            if args.captions == "auto":
                try:
                    clip_srt = transcribe(video, m["start"], m["end"])
                except SystemExit as e:
                    print(f"  [!] captions skipped: {e}")
            cut_clip(video, m, clip_path, captions_srt=clip_srt)
            folder = pack_clip(clip_path, m, out)
            print(f"  {os.path.basename(video)} moment {i}: "
                  f"score {m['score']} -> {folder}")
    print(f"\nDone. Ready-to-post packs in {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="povcut",
        description="Turn Ray-Ban Meta footage into viral shorts with one command.",
    )
    p.add_argument("--version", action="version", version=f"povcut {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("import", help="Import new footage into the library")
    pi.add_argument("source", help="Folder with footage (Meta AI export, phone mount, ...)")
    pi.add_argument("--library", default=None)
    pi.add_argument("--move", action="store_true", help="Move instead of copy")
    pi.set_defaults(func=cmd_import)

    pm = sub.add_parser("moments", help="Rank the moments worth clipping")
    pm.add_argument("video")
    pm.add_argument("--top", type=int, default=10)
    pm.add_argument("--out-dir", default=None)
    pm.set_defaults(func=cmd_moments)

    pc = sub.add_parser("cut", help="Cut top moments into vertical shorts")
    pc.add_argument("video")
    pc.add_argument("--moments-json", default=None)
    pc.add_argument("--top", type=int, default=3)
    pc.add_argument("--pick", type=int, default=None,
                    help="Cut a single moment by index from the ranking")
    pc.add_argument("--captions", default=None,
                    help="'auto' (needs the auto-captions extra) or path to .srt")
    pc.add_argument("--language", default=None)
    pc.add_argument("--out", default="out")
    pc.set_defaults(func=cmd_cut)

    ps = sub.add_parser("spin", help="Rewrite any clip as Meta-glasses footage (Spin View)")
    ps.add_argument("video")
    ps.add_argument("--out", default=None)
    ps.set_defaults(func=cmd_spin)

    pp = sub.add_parser("pipeline", help="import -> moments -> cut -> pack in one go")
    pp.add_argument("source")
    pp.add_argument("--library", default=None)
    pp.add_argument("--out", default=None)
    pp.add_argument("--top", type=int, default=3)
    pp.add_argument("--captions", default=None,
                    help="'auto' or path to .srt (applied to every clip)")
    pp.set_defaults(func=cmd_pipeline)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SystemExit as e:
        msg = str(e).strip()
        if msg:
            print(f"povcut: {msg}", file=sys.stderr)
        return 1 if e.code in (None, 0) else int(e.code)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
