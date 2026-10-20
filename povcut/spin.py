"""Spin View export: make ANY clip look like Ray-Ban Meta capture.

Instagram decides a video came from Meta glasses by its QuickTime
structure, not its pixels. This module rewrites a clip into that
structure — QuickTime container, `qt  ` brand, ftyp/wide/mdat/moov order,
`meta` atom as a direct child of `moov`, Core Media handler names, the
`tapt` atom, the glasses' device metadata — so Instagram treats it as
glasses footage and enables Spin View.

The structural recipe was reverse-engineered by the public metaspin
project (github.com/loui89/metaspin, MIT) by comparing its rebuilds
against genuine Ray-Ban Meta Gen 2 captures and testing on a real
account. Their research is credited there and in our README; this is an
independent implementation of the documented structure. No serial
numbers or device identifiers are copied — only the shared structure.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import uuid
from datetime import datetime, timezone

from .util import has_audio, need_tools, probe, run

WIDTH, HEIGHT = 1376, 1840
FPS = 30
VIDEO_TIMESCALE = 600
MOVIE_TIMESCALE = 48000
AUDIO_RATE = 48000

DEVICE_MAKE = "Meta AI"
DEVICE_MODEL = "Ray-Ban Meta Smart Glasses 2"

VIDEO_HANDLER = "Core Media Video"
AUDIO_HANDLER = "Core Media Audio"
DATA_HANDLER = "Core Media Data Handler"


# ---------------------------------------------------------------- atoms

def atom(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def parse(data: bytes, start: int = 0, end: int | None = None):
    if end is None:
        end = len(data)
    out = []
    p = start
    while p + 8 <= end:
        size = struct.unpack(">I", data[p:p + 4])[0]
        kind = data[p + 4:p + 8]
        header = 8
        if size == 1:
            size = struct.unpack(">Q", data[p + 8:p + 16])[0]
            header = 16
        elif size == 0:
            size = end - p
        if size < header or p + size > end:
            break
        out.append((kind, p, size, p + header))
        p += size
    return out


def find(children, kind):
    for c in children:
        if c[0] == kind:
            return c
    return None


def _pascal(text: str) -> bytes:
    raw = text.encode("utf-8")
    return bytes([len(raw)]) + raw


def make_tapt(width: int, height: int) -> bytes:
    def dims(kind: bytes) -> bytes:
        return atom(kind, struct.pack(">III", 0, width << 16, height << 16))
    return atom(b"tapt", dims(b"clef") + dims(b"prof") + dims(b"enof"))


def make_hdlr(component_type: bytes, subtype: bytes, name: str) -> bytes:
    payload = struct.pack(">I", 0)
    payload += component_type + subtype + b"appl"
    payload += struct.pack(">II", 0, 0)
    payload += _pascal(name)
    return atom(b"hdlr", payload)


def make_meta(created: datetime) -> bytes:
    # In QuickTime, `meta` carries no version/flags; children start right
    # after the 8-byte header (the opposite of MP4).
    hdlr = atom(b"hdlr", struct.pack(">I", 0) + struct.pack(">I", 0)
                + b"mdta" + b"\x00" * 12 + b"\x00\x00")
    stamp = created.strftime("%Y-%m-%dT%H:%M:%SZ")
    fields = [
        ("com.apple.quicktime.copyright", DEVICE_MAKE),
        ("com.apple.quicktime.comment",
         "app=%s&device=%s&id=%s" % (DEVICE_MAKE, DEVICE_MODEL,
                                     str(uuid.uuid4()).upper())),
        ("com.apple.quicktime.model", DEVICE_MODEL),
        ("com.apple.quicktime.creationdate", stamp),
    ]
    entries = b""
    for key, _ in fields:
        raw = key.encode("utf-8")
        entries += struct.pack(">I", 8 + len(raw)) + b"mdta" + raw
    keys = atom(b"keys", struct.pack(">II", 0, len(fields)) + entries)

    items = b""
    for index, (_, value) in enumerate(fields, start=1):
        raw = value.encode("utf-8")
        data_box = atom(b"data", struct.pack(">II", 1, 0) + raw)
        items += struct.pack(">I", 8 + len(data_box)) + struct.pack(">I", index) + data_box
    ilst = atom(b"ilst", items)
    return atom(b"meta", hdlr + keys + ilst)


def _rescale(value: int, old_ts: int, new_ts: int) -> int:
    return int(round(value * new_ts / float(old_ts)))


def patch_mvhd(blob: bytes, new_timescale: int):
    version = blob[8]
    body = bytearray(blob)
    if version == 1:
        ts_off, dur_off, dur_fmt = 12 + 16, 12 + 20, ">Q"
        old_ts = struct.unpack(">I", bytes(body[ts_off:ts_off + 4]))[0]
        old_dur = struct.unpack(">Q", bytes(body[dur_off:dur_off + 8]))[0]
        struct.pack_into(">I", body, ts_off, new_timescale)
        struct.pack_into(">Q", body, dur_off, _rescale(old_dur, old_ts, new_timescale))
    else:
        ts_off, dur_off = 12 + 8, 12 + 12
        old_ts = struct.unpack(">I", bytes(body[ts_off:ts_off + 4]))[0]
        old_dur = struct.unpack(">I", bytes(body[dur_off:dur_off + 4]))[0]
        struct.pack_into(">I", body, ts_off, new_timescale)
        struct.pack_into(">I", body, dur_off, _rescale(old_dur, old_ts, new_timescale))
    return bytes(body), old_ts


def patch_tkhd(blob: bytes, old_ts: int, new_ts: int) -> bytes:
    version = blob[8]
    body = bytearray(blob)
    if version == 1:
        off = 12 + 16 + 4 + 4
        old = struct.unpack(">Q", bytes(body[off:off + 8]))[0]
        struct.pack_into(">Q", body, off, _rescale(old, old_ts, new_ts))
    else:
        off = 12 + 8 + 4 + 4
        old = struct.unpack(">I", bytes(body[off:off + 4]))[0]
        struct.pack_into(">I", body, off, _rescale(old, old_ts, new_ts))
    return bytes(body)


def patch_elst(blob: bytes, old_ts: int, new_ts: int) -> bytes:
    version = blob[8]
    body = bytearray(blob)
    count = struct.unpack(">I", bytes(body[12:16]))[0]
    p = 16
    for _ in range(count):
        if version == 1:
            dur = struct.unpack(">Q", bytes(body[p:p + 8]))[0]
            struct.pack_into(">Q", body, p, _rescale(dur, old_ts, new_ts))
            p += 20
        else:
            dur = struct.unpack(">I", bytes(body[p:p + 4]))[0]
            struct.pack_into(">I", body, p, _rescale(dur, old_ts, new_ts))
            p += 12
    return bytes(body)


def patch_stsd(blob: bytes) -> bytes:
    # ffmpeg writes the encoder name here; the glasses write 'hvc1'.
    body = bytearray(blob)
    for kind, start, size, _payload in parse(bytes(body), 16, len(body)):
        if kind != b"hvc1":
            continue
        field = start + 50
        name = _pascal("'hvc1'")
        body[field:field + 32] = name + b"\x00" * (32 - len(name))
    return bytes(body)


def shift_chunk_offsets(blob: bytes, delta: int) -> bytes:
    """Shift every stco/co64 chunk offset by *delta* (mdat moved)."""
    body = bytearray(blob)

    def visit(buf: bytearray, start: int, end: int):
        for kind, s, size, payload in parse(bytes(buf), start, end):
            if kind == b"stco":
                count = struct.unpack(">I", buf[payload + 4:payload + 8])[0]
                for i in range(count):
                    o = payload + 8 + i * 4
                    v = struct.unpack(">I", buf[o:o + 4])[0]
                    struct.pack_into(">I", buf, o, (v + delta) & 0xFFFFFFFF)
            elif kind == b"co64":
                count = struct.unpack(">I", buf[payload + 4:payload + 8])[0]
                for i in range(count):
                    o = payload + 8 + i * 8
                    v = struct.unpack(">Q", buf[o:o + 8])[0]
                    struct.pack_into(">Q", buf, o, v + delta)
            elif kind in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
                visit(buf, payload, s + size)

    visit(body, 0, len(body))
    return bytes(body)


# ------------------------------------------------------- moov rebuild

def rebuild_stbl(data: bytes, node) -> bytes:
    kids = parse(data, node[3], node[1] + node[2])
    out = b""
    for kind, start, size, _ in kids:
        blob = data[start:start + size]
        out += patch_stsd(blob) if kind == b"stsd" else blob
    return atom(b"stbl", out)


def rebuild_minf(data: bytes, node, is_video: bool) -> bytes:
    kids = parse(data, node[3], node[1] + node[2])
    out = b""
    for kind, start, size, _ in kids:
        if kind == b"hdlr":
            out += make_hdlr(b"dhlr", b"alis", DATA_HANDLER)
        elif kind == b"stbl" and is_video:
            out += rebuild_stbl(data, (kind, start, size, start + 8))
        else:
            out += data[start:start + size]
    return atom(b"minf", out)


def rebuild_mdia(data: bytes, node, is_video: bool) -> bytes:
    kids = parse(data, node[3], node[1] + node[2])
    out = b""
    for kind, start, size, _ in kids:
        if kind == b"minf":
            out += rebuild_minf(data, (kind, start, size, start + 8), is_video)
        elif kind == b"hdlr":
            name = VIDEO_HANDLER if is_video else AUDIO_HANDLER
            out += make_hdlr(b"mhlr", b"vide" if is_video else b"soun", name)
        else:
            out += data[start:start + size]
    return atom(b"mdia", out)


def rebuild_trak(data: bytes, node, old_ts: int, new_ts: int) -> bytes:
    kids = parse(data, node[3], node[1] + node[2])
    mdia = find(kids, b"mdia")
    is_video = False
    if mdia:
        for kind, start, size, body in parse(data, mdia[3], mdia[1] + mdia[2]):
            if kind == b"hdlr":
                is_video = data[body + 8:body + 12] == b"vide"

    out = b""
    for kind, start, size, _ in kids:
        blob = data[start:start + size]
        if kind == b"tkhd":
            out += patch_tkhd(blob, old_ts, new_ts)
            if is_video:
                out += make_tapt(WIDTH, HEIGHT)
        elif kind == b"tapt":
            continue
        elif kind == b"edts":
            inner = b""
            for k2, s2, sz2, _ in parse(data, start + 8, start + size):
                inner += patch_elst(data[s2:s2 + sz2], old_ts, new_ts) if k2 == b"elst" \
                    else data[s2:s2 + sz2]
            out += atom(b"edts", inner)
        elif kind == b"mdia":
            out += rebuild_mdia(data, (kind, start, size, start + 8), is_video)
        else:
            out += blob
    return atom(b"trak", out)


def rebuild_moov(data: bytes, node, created: datetime) -> bytes:
    kids = parse(data, node[3], node[1] + node[2])
    mvhd = find(kids, b"mvhd")
    new_mvhd, old_ts = patch_mvhd(data[mvhd[1]:mvhd[1] + mvhd[2]], MOVIE_TIMESCALE)

    out = new_mvhd
    for kind, start, size, _ in kids:
        if kind in (b"mvhd", b"udta", b"meta"):
            continue
        if kind == b"trak":
            out += rebuild_trak(data, (kind, start, size, start + 8),
                                old_ts, MOVIE_TIMESCALE)
        else:
            out += data[start:start + size]
    out += make_meta(created)
    return atom(b"moov", out)


# ------------------------------------------------------- pipeline

def transcode(path_in: str, path_raw: str) -> bool:
    """Encode to the glasses' codec profile. Returns True if colors were kept."""
    info = probe(path_in)
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = has_audio(info)

    # Converting twice flattens contrast; check before touching color.
    already = (stream.get("color_primaries") == "bt2020"
               and stream.get("color_transfer") in ("arib-std-b67", "smpte2084"))
    chain = ("scale=%d:%d:force_original_aspect_ratio=increase,"
             "crop=%d:%d,fps=%d,format=yuv420p"
             % (WIDTH, HEIGHT, WIDTH, HEIGHT, FPS))
    if not already:
        chain += (",zscale=primariesin=bt709:transferin=bt709:matrixin=bt709:"
                  "primaries=bt2020:transfer=arib-std-b67:matrix=bt2020nc")

    cmd = ["ffmpeg", "-y", "-v", "error", "-i", path_in, "-map", "0:v:0"]
    if audio:
        cmd += ["-map", "0:a:0"]
    cmd += [
        "-vf", chain,
        "-c:v", "libx265", "-profile:v", "main", "-pix_fmt", "yuv420p",
        "-x265-params", "info=0:log-level=none",
        "-tag:v", "hvc1", "-r", str(FPS),
        "-color_primaries", "bt2020", "-color_trc", "arib-std-b67",
        "-colorspace", "bt2020nc",
        "-video_track_timescale", str(VIDEO_TIMESCALE),
    ]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "192k",
                "-ar", str(AUDIO_RATE), "-ac", "2"]
    cmd += ["-map_metadata", "-1", "-map_metadata:s:v", "-1",
            "-f", "mov", path_raw]
    p = run(cmd)
    if p.returncode != 0:
        raise SystemExit(f"spin transcode failed:\n{p.stderr.strip()}")
    return already


def restructure(path_in: str, path_out: str, created: datetime) -> None:
    data = open(path_in, "rb").read()
    top = parse(data)
    mdat = find(top, b"mdat")
    if mdat is None:
        raise SystemExit("No mdat atom found in transcoded file.")

    new_ftyp = atom(b"ftyp", b"qt  " + struct.pack(">I", 0) + b"qt  ")
    new_wide = atom(b"wide", b"")
    prefix = new_ftyp + new_wide
    delta = len(prefix) - mdat[1]  # where mdat moves to

    moov_node = find(top, b"moov")
    new_moov = shift_chunk_offsets(
        rebuild_moov(data, (moov_node[0], moov_node[1], moov_node[2],
                            moov_node[1] + 8), created),
        delta,
    )
    out = prefix + data[mdat[1]:mdat[1] + mdat[2]] + new_moov
    open(path_out, "wb").write(out)


def convert(path_in: str, out_path: str | None = None) -> str:
    """Full Spin View conversion. Returns the output path."""
    need_tools("ffmpeg", "ffprobe")
    if out_path is None:
        stem = os.path.splitext(os.path.basename(path_in))[0]
        out_path = os.path.join(os.path.dirname(path_in) or ".",
                                f"{stem}_SPIN.MOV")
    tmp = out_path + ".raw.tmp.mov"
    try:
        transcode(path_in, tmp)
        restructure(tmp, out_path, datetime.now(timezone.utc))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out_path


def verify(path: str) -> list[str]:
    """Structural checklist; returns a list of problems (empty = all good)."""
    problems = []
    data = open(path, "rb").read()
    top = parse(data)
    kinds = [k for k, _, _, _ in top]
    if kinds[:4] != [b"ftyp", b"wide", b"mdat", b"moov"]:
        problems.append(f"top-level order is {[k.decode() for k in kinds[:4]]}, "
                        "want ftyp/wide/mdat/moov")
    ftyp = find(top, b"ftyp")
    if ftyp and data[ftyp[3]:ftyp[3] + 8] != b"qt  " + struct.pack(">I", 0):
        problems.append("ftyp brand/minor is not 'qt  '/0")

    moov = find(top, b"moov")
    if moov is None:
        return problems + ["no moov atom"]
    kids = parse(data, moov[3], moov[1] + moov[2])
    if not find(kids, b"meta"):
        problems.append("no meta atom as direct child of moov")
    else:
        meta = find(kids, b"meta")
        sub = parse(data, meta[3], meta[1] + meta[2])
        keys = find(sub, b"keys")
        if keys is None:
            problems.append("meta atom has no keys")
        else:
            blob = data[keys[1]:keys[1] + keys[2]]
            for want in (b"com.apple.quicktime.copyright",
                         b"com.apple.quicktime.model",
                         b"com.apple.quicktime.creationdate"):
                if want not in blob:
                    problems.append(f"meta keys missing {want.decode()}")

    mvhd = find(kids, b"mvhd")
    if mvhd:
        ts = struct.unpack(">I", data[mvhd[3] + 12:mvhd[3] + 16])[0]
        if ts != MOVIE_TIMESCALE:
            problems.append(f"mvhd timescale is {ts}, want {MOVIE_TIMESCALE}")

    traks = [c for c in kids if c[0] == b"trak"]
    if len(traks) != 2:
        problems.append(f"found {len(traks)} tracks, want exactly 2")
    for kind, start, size, body in traks:
        tkids = parse(data, body, start + size)
        if not find(tkids, b"tapt"):
            mdia = find(tkids, b"mdia")
            is_v = False
            if mdia:
                for k2, s2, sz2, b2 in parse(data, mdia[3], mdia[1] + mdia[2]):
                    if k2 == b"hdlr":
                        is_v = data[b2 + 8:b2 + 12] == b"vide"
            if is_v:
                problems.append("video trak has no tapt atom")

    # chunk offsets must land inside mdat
    mdat = find(top, b"mdat")
    m0, m1 = mdat[1], mdat[1] + mdat[2]
    for kind, start, size, body in traks:
        for k2, s2, sz2, b2 in parse(data, body, start + size):
            if k2 != b"mdia":
                continue
            for k3, s3, sz3, b3 in parse(data, b2, s2 + sz2):
                if k3 != b"minf":
                    continue
                for k4, s4, sz4, b4 in parse(data, b3, s3 + sz3):
                    if k4 != b"stbl":
                        continue
                    for k5, s5, sz5, b5 in parse(data, b4, s4 + sz4):
                        if k5 == b"stco":
                            n = struct.unpack(">I", data[b5 + 4:b5 + 8])[0]
                            for i in range(n):
                                off = struct.unpack(">I", data[b5 + 8 + i * 4:b5 + 12 + i * 4])[0]
                                if not (m0 <= off < m1):
                                    problems.append(
                                        f"stco entry {i} points outside mdat")
                        elif k5 == b"co64":
                            n = struct.unpack(">I", data[b5 + 4:b5 + 8])[0]
                            for i in range(n):
                                off = struct.unpack(">Q", data[b5 + 8 + i * 8:b5 + 16 + i * 8])[0]
                                if not (m0 <= off < m1):
                                    problems.append(
                                        f"co64 entry {i} points outside mdat")
    return problems
