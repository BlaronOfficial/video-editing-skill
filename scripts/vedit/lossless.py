"""Native smart cut: frame-accurate cuts that re-encode only a few frames.

For each kept range [a, b) of an H.264/HEVC file:
  head  [a, k1)   re-encoded (k1 = first keyframe after a), matching codec, profile, pixel format and colour
                  tags, at the source bitrate x 1.2
  body  [k1, kN)  whole GOPs stream-copied, split on keyframes by FFmpeg's segment muxer (bit-exact)
  tail  [kN, b)   re-encoded (kN = last keyframe before b)
Pieces travel as MPEG-TS (parameter sets in-band) and are joined by the concat demuxer; audio is cut
sample-exact from the same ranges and encoded once (AAC 320k by default, or PCM in .mov). Ranges snap
to the source frame grid so picture and sound stay the same length.

Modes: smart (above), keyframe (pure stream copy, cuts move to keyframes, like LosslessCut's default),
accurate (everything re-encoded at high quality: any codec). Used by `vedit render --lossless` (edits
that are only cuts), selects, splits, merging split camera files and chapters.
"""

from __future__ import annotations

import json
import shutil
import time
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path

from .media import ffmpeg, ffprobe, probe
from .util import VeditError, run, short_hash, write_text

SMART_CODECS = {"h264": "libx264", "hevc": "libx265"}


@dataclass
class VideoParams:
    codec: str
    profile: str
    level: int
    pix_fmt: str
    width: int
    height: int
    fps_num: int
    fps_den: int
    bitrate: int
    rotation: int
    color: dict
    audio_codec: str
    audio_rate: int
    audio_bitrate: int

    @property
    def fps(self) -> float:
        return self.fps_num / self.fps_den

    def key(self) -> tuple:
        return (self.codec, self.profile, self.pix_fmt, self.width, self.height, self.fps_num, self.fps_den)


def params(path: str | Path) -> VideoParams:
    out = run([ffprobe(), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]).stdout
    data = json.loads(out or "{}")
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), None)
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not v:
        raise VeditError(f"{path}: no video stream")
    num, den = (v.get("r_frame_rate") or "30/1").split("/")
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    br = int(v.get("bit_rate") or 0) or int(int(data.get("format", {}).get("bit_rate") or 0) * 0.9)
    return VideoParams(codec=v.get("codec_name", ""), profile=v.get("profile", ""), level=int(v.get("level") or 0),
                       pix_fmt=v.get("pix_fmt", "yuv420p"), width=int(v.get("width", 0)), height=int(v.get("height", 0)),
                       fps_num=int(num), fps_den=int(den) or 1, bitrate=br, rotation=rot,
                       color={k: v.get(k) for k in ("color_range", "color_space", "color_transfer", "color_primaries")
                              if v.get(k) and v.get(k) != "unknown"},
                       audio_codec=(a or {}).get("codec_name", ""), audio_rate=int((a or {}).get("sample_rate") or 48000),
                       audio_bitrate=int((a or {}).get("bit_rate") or 0))


def keyframes(path: str | Path) -> list[float]:
    """Keyframe presentation times of the first video stream (packet flags; no decoding)."""
    out = run([ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,flags",
               "-of", "csv=p=0", str(path)], timeout=3600).stdout or ""
    kf = []
    for line in out.splitlines():
        parts = line.split(",")
        if len(parts) >= 2 and "K" in parts[1] and parts[0] not in ("", "N/A"):
            kf.append(float(parts[0]))
    return sorted(kf)


def _snap(t: float, p: VideoParams) -> float:
    return round(t * p.fps) / p.fps


def _encode_args(p: VideoParams) -> list[str]:
    enc = SMART_CODECS.get(p.codec, "libx264")
    br = max(p.bitrate, 2_000_000)
    args = ["-c:v", enc, "-b:v", str(int(br * 1.2)), "-maxrate", str(int(br * 1.8)), "-bufsize", str(int(br * 2.4)),
            "-pix_fmt", p.pix_fmt, "-preset", "medium"]
    prof = (p.profile or "").lower().replace(" ", "")
    if enc == "libx264" and prof in ("baseline", "constrainedbaseline", "main", "high", "high10", "high422", "high444"):
        args += ["-profile:v", {"constrainedbaseline": "baseline"}.get(prof, prof)]
    if enc == "libx264" and p.level:
        args += ["-level:v", f"{p.level / 10:.1f}"]
    if enc == "libx265":
        args += ["-x265-params", "log-level=error"]
        if prof in ("main", "main10"):
            args += ["-profile:v", prof]
    for k, flag in (("color_range", "-color_range"), ("color_space", "-colorspace"), ("color_transfer", "-color_trc"),
                    ("color_primaries", "-color_primaries")):
        if k in p.color:
            args += [flag, p.color[k]]
    return args


def _encode_piece(src: str, a: float, n_frames: int, p: VideoParams, out: Path) -> Path:
    run([ffmpeg(), "-y", "-v", "error", "-noautorotate", "-ss", f"{a:.6f}", "-i", src, "-map", "0:v:0",
         "-frames:v", str(n_frames), "-r", f"{p.fps_num}/{p.fps_den}", *_encode_args(p), "-an", "-sn", "-dn",
         "-f", "mpegts", str(out)], timeout=3600)
    return out


def _copy_gops(src: str, k_first: float, k_last: float, work: Path, tag: str) -> Path:
    """Stream-copy whole GOPs [k_first, k_last): the segment muxer splits exactly before keyframe packets."""
    pattern = work / f"{tag}_gop%03d.ts"
    run([ffmpeg(), "-y", "-v", "error", "-noautorotate", "-ss", f"{k_first:.6f}", "-i", src,
         "-t", f"{k_last - k_first + 2.0:.6f}", "-map", "0:v:0", "-c", "copy", "-an", "-sn", "-dn",
         "-f", "segment", "-segment_times", f"{k_last - k_first:.6f}", "-reset_timestamps", "1",
         "-segment_format", "mpegts", str(pattern)], timeout=3600)
    first = work / f"{tag}_gop000.ts"
    for extra in work.glob(f"{tag}_gop*.ts"):
        if extra != first:
            extra.unlink()
    return first


def _frames(path: Path) -> int:
    out = run([ffprobe(), "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
               "stream=nb_read_packets", "-of", "csv=p=0", str(path)]).stdout.strip()
    return int(out or 0)


def plan(src: str, a: float, b: float, kf: list[float], p: VideoParams, mode: str) -> list[tuple[str, float, float]]:
    """[(kind, start, end)] pieces for one range; kind = encode | copy."""
    eps = 0.5 / p.fps
    a, b = _snap(a, p), _snap(b, p)
    if mode == "accurate" or p.codec not in SMART_CODECS:
        return [("encode", a, b)]
    if mode == "keyframe":
        i = max(0, bisect_right(kf, a + eps) - 1)
        return [("copy", kf[i], b)]
    i = bisect_left(kf, a - eps)
    j = bisect_right(kf, b + eps) - 1
    if i >= len(kf) or j < i or kf[i] >= b - eps:
        return [("encode", a, b)]
    k1, kn = kf[i], kf[j]
    if kn <= k1 + eps and k1 > a + eps:          # one keyframe inside: nothing whole to copy
        return [("encode", a, b)]
    pieces = []
    if k1 > a + eps:
        pieces.append(("encode", a, k1))
    if kn > k1 + eps:
        pieces.append(("copy", k1, kn))
    if b > kn + eps:
        pieces.append(("encode", kn, b))
    return pieces


def smart_cut(segments: list[dict], out: str | Path, *, mode: str = "smart", audio: str = "aac",
              work_dir: str | Path | None = None, chapters: list[dict] | None = None) -> dict:
    """segments: [{"path", "start", "end"}] in playback order (several files allowed if they share codec settings).
    audio: aac | pcm | none. Returns the plan, frame counts and timing."""
    t0 = time.time()
    out = Path(out).resolve()
    if not segments:
        raise VeditError("Nothing to cut: no segments.")
    srcs = sorted({str(Path(s["path"]).resolve()) for s in segments})
    ps = {s: params(s) for s in srcs}
    keys = {ps[s].key() for s in srcs}
    if len(keys) > 1 and mode != "accurate":
        raise VeditError("The files differ in codec, size or frame rate; smart cut needs matching files. "
                         "Use --mode accurate (re-encodes) or the normal render.")
    p0 = ps[srcs[0]]
    kfs = {s: keyframes(s) if mode != "accurate" else [] for s in srcs}
    work = Path(work_dir) if work_dir else out.parent / f".lossless_{short_hash(segments, mode)}"
    work.mkdir(parents=True, exist_ok=True)
    pieces: list[Path] = []
    report = []
    expected_frames = 0
    for n, seg in enumerate(segments):
        src = str(Path(seg["path"]).resolve())
        p = ps[src]
        a, b = float(seg["start"]), float(seg["end"])
        info = probe(src)
        b = min(b, info.duration)
        if b - a < 1 / p.fps:
            continue
        expected_frames += round(_snap(b, p) * p.fps) - round(_snap(a, p) * p.fps)
        for m, (kind, s, e) in enumerate(plan(src, a, b, kfs[src], p, mode)):
            tag = f"s{n:03d}_{m}"
            if kind == "copy":
                f = _copy_gops(src, s, e, work, tag) if mode != "keyframe" else _copy_range(src, s, e, work, tag)
            else:
                f = _encode_piece(src, s, max(1, round((e - s) * p.fps)), p, work / f"{tag}.ts")
            pieces.append((f, max(1, round((e - s) * p.fps)) * p.fps_den / p.fps_num))
            report.append({"segment": n, "kind": kind, "start": round(s, 4), "end": round(e, 4), "file": f.name})
    if not pieces:
        raise VeditError("All segments are shorter than one frame.")
    lst = work / "pieces.txt"
    # exact durations: the concat demuxer otherwise guesses a short piece's length from its packets
    write_text(lst, "".join(f"file '{x.name}'\nduration {d:.6f}\n" for x, d in pieces))

    # audio: the same ranges, snapped to the frame grid, sample-exact, one encode
    has_audio = audio != "none" and any(probe(s).has_audio for s in srcs)
    audio_file = None
    if has_audio:
        inputs, parts = [], []
        idx = {s: i for i, s in enumerate(srcs)}
        for s in srcs:
            inputs += ["-i", s]
        k = 0
        for seg in segments:
            src = str(Path(seg["path"]).resolve())
            p = ps[src]
            a, b = _snap(float(seg["start"]), p), _snap(min(float(seg["end"]), probe(src).duration), p)
            if b - a < 1 / p.fps:
                continue
            parts.append(f"[{idx[src]}:a:0]atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-STARTPTS,"
                         f"aresample={p0.audio_rate or 48000}[a{k}]")
            k += 1
        graph = ";".join(parts) + ";" + "".join(f"[a{i}]" for i in range(k)) + f"concat=n={k}:v=0:a=1[aout]"
        write_text(work / "audio.fg", graph)
        audio_file = work / ("audio.wav" if audio == "pcm" else "audio.m4a")
        codec = ["-c:a", "pcm_s24le"] if audio == "pcm" else ["-c:a", "aac", "-b:a", str(max(320_000, p0.audio_bitrate))]
        run([ffmpeg(), "-y", "-v", "error", *inputs, "-/filter_complex", str(work / "audio.fg"), "-map", "[aout]", *codec,
             str(audio_file)], timeout=7200)

    meta_args: list[str] = []
    if chapters:
        meta = work / "chapters.txt"
        lines = [";FFMETADATA1"]
        for i, c in enumerate(chapters):
            end = chapters[i + 1]["t"] if i + 1 < len(chapters) else c.get("end", c["t"] + 1)
            lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(c['t'] * 1000)}", f"END={int(end * 1000)}",
                      f"title={c['title']}"]
        write_text(meta, "\n".join(lines) + "\n")
    args = [ffmpeg(), "-y", "-v", "error"]
    if p0.rotation:
        args += ["-display_rotation:v:0", str(p0.rotation)]
    args += ["-f", "concat", "-safe", "0", "-i", str(lst)]
    if audio_file:
        args += ["-i", str(audio_file)]
    if chapters:
        args += ["-i", str(work / "chapters.txt")]
    args += ["-map", "0:v:0"] + (["-map", "1:a:0"] if audio_file else [])
    if chapters:
        args += ["-map_chapters", str(2 if audio_file else 1)]
    args += ["-c", "copy"]
    if p0.codec == "hevc":
        args += ["-tag:v", "hvc1"]
    if out.suffix.lower() in (".mp4", ".mov", ".m4v"):
        args += ["-movflags", "+faststart"]
    args += [str(out)]
    run(args, timeout=7200)
    got = _frames(out)
    shutil.rmtree(work, ignore_errors=True)
    copied = sum(r["end"] - r["start"] for r in report if r["kind"] == "copy")
    total = sum(r["end"] - r["start"] for r in report)
    return {"output": str(out), "mode": mode, "pieces": report, "frames": got, "expected_frames": expected_frames,
            "copied_share": round(copied / total, 3) if total else 0.0, "seconds": round(time.time() - t0, 1)}


def _copy_range(src: str, a: float, b: float, work: Path, tag: str) -> Path:
    """keyframe mode: plain stream copy from the keyframe at/before a up to b (LosslessCut's default cut)."""
    out = work / f"{tag}.ts"
    run([ffmpeg(), "-y", "-v", "error", "-noautorotate", "-ss", f"{a:.6f}", "-i", src, "-t", f"{b - a:.6f}",
         "-map", "0:v:0", "-c", "copy", "-an", "-f", "mpegts", str(out)], timeout=3600)
    return out


# ------------------------------------------------------------------ helpers on top

def merge(files: list[str | Path], out: str | Path) -> dict:
    """Join split camera files (same settings) without re-encoding."""
    ps = [params(f) for f in files]
    if len({p.key() for p in ps}) > 1:
        raise VeditError("These files differ in codec, size or frame rate; they cannot be joined losslessly.")
    out = Path(out).resolve()
    lst = out.with_suffix(".txt")
    write_text(lst, "".join(f"file '{Path(f).resolve().as_posix()}'\n" for f in files))
    run([ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-map", "0", "-c", "copy",
         *(["-movflags", "+faststart"] if out.suffix.lower() in (".mp4", ".mov") else []), str(out)], timeout=7200)
    lst.unlink(missing_ok=True)
    return {"output": str(out), "files": len(files), "duration": round(probe(out).duration, 3)}


def split(src: str | Path, at: list[float], out_dir: str | Path, *, mode: str = "smart") -> list[dict]:
    """Cut one file into pieces at the given times (each piece frame-accurate)."""
    info = probe(src)
    points = [0.0, *sorted(t for t in at if 0 < t < info.duration), info.duration]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = []
    for i, (a, b) in enumerate(zip(points, points[1:]), 1):
        f = out_dir / f"{Path(src).stem}_{i:02d}{Path(src).suffix if Path(src).suffix in ('.mp4', '.mov') else '.mp4'}"
        res.append(smart_cut([{"path": str(src), "start": a, "end": b}], f, mode=mode))
    return res


def add_chapters(src: str | Path, chapters: list[dict], out: str | Path) -> dict:
    """Write chapter markers into a file (stream copy). chapters: [{"t", "title"}]."""
    out = Path(out).resolve()
    meta = out.with_suffix(".chapters.txt")
    dur = probe(src).duration
    lines = [";FFMETADATA1"]
    for i, c in enumerate(chapters):
        end = chapters[i + 1]["t"] if i + 1 < len(chapters) else dur
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(c['t'] * 1000)}", f"END={int(end * 1000)}", f"title={c['title']}"]
    write_text(meta, "\n".join(lines) + "\n")
    run([ffmpeg(), "-y", "-v", "error", "-i", str(src), "-i", str(meta), "-map", "0", "-map_chapters", "1", "-c", "copy",
         str(out)], timeout=7200)
    meta.unlink(missing_ok=True)
    return {"output": str(out), "chapters": len(chapters)}


def cuts_only(edit) -> list[str]:
    """Why an edit cannot be rendered losslessly ([] = it can: plain cuts of the sources, nothing on top)."""
    why = []
    if edit.broll:
        why.append("b-roll")
    if [o for o in edit.overlays if o.enabled]:
        why.append("graphics overlays")
    if [t for t in edit.texts if t.enabled]:
        why.append("text items")
    if [a for a in edit.audio if a.enabled]:
        why.append("music / sound effects")
    if [x for x in edit.effects if x.enabled] or [f for f in edit.custom_fx if f.enabled]:
        why.append("effects")
    if edit.color.preset or edit.color.lut:
        why.append("a colour grade")
    for c in edit.main:
        src = edit.sources[c.source]
        if src.kind != "video":
            why.append(f"{c.id}: not a video source")
        if abs(c.speed - 1) > 1e-4 or c.zoom or c.crop or c.transition_in or c.fade_in or c.fade_out or c.color:
            why.append(f"{c.id}: speed, zoom, reframe, transition, fade or grade")
        t = c.transform
        if abs(t.scale - 1) > 1e-4 or abs(t.x) > 1e-4 or abs(t.y) > 1e-4 or t.rotation or t.opacity < 0.999:
            why.append(f"{c.id}: transform")
    return sorted(set(why))


def render_edit(edit, out: str | Path, *, mode: str = "smart", captions: bool = True) -> dict:
    """`vedit render --lossless`: the main track as a smart cut; captions ride along as a soft subtitle track
    (sidecar SRT) because burning them in would mean re-encoding everything."""
    from .knobs import bake
    e = bake(edit.layout()).active()
    blockers = cuts_only(e)            # the output keeps the source size; the canvas does not apply
    if blockers:
        raise VeditError("This edit is more than cuts, so it cannot be rendered losslessly: " + "; ".join(blockers)
                         + ". Use the normal render, or `vedit lossless selects` for the raw kept ranges.")
    segs = [{"path": e.sources[c.source].path, "start": c.src_in, "end": c.src_out} for c in e.main]
    chapters = [{"t": m.t, "title": m.name} for m in e.markers if m.kind == "chapter"]
    res = smart_cut(segs, out, mode=mode, chapters=chapters or None)
    if captions and e.captions.enabled:
        from . import captions as caps
        chunks = e.captions.chunks or caps.build_chunks(e)
        if chunks:
            res["srt"] = str(caps.to_srt(chunks, Path(out).with_suffix(".srt")))
    return res
