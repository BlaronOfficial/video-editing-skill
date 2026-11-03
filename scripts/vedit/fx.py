"""Clean-up and time FX: stabilize, denoise, deinterlace, redact (blur / pixelate / delogo), straighten,
crop away black bars, 360 -> flat, reverse, freeze, loop, speed ramps, smooth slow motion.

Two ways in, one filter builder:
  * in an edit: fields on the clip (`src_crop`, `projection`, `stabilize`, `denoise`, `reverse`, `smooth`,
    `redact`) rendered at decode by render.py, so the Studio, QA and hand-offs see one edit; speed ramps
    and freeze frames are edit operations (they split clips / insert a still), so every hand-off can
    represent them;
  * on a file: `vedit fx <tool> <file> --out ...` for one-off jobs (never overwrites the input).

Filter choices follow kajisho5/ffmpeg-skill (MIT): two-pass vidstab, hqdn3d/nlmeans, bwdif, delogo,
v360, minterpolate for smooth slow motion.
"""

from __future__ import annotations

import math
from pathlib import Path

from .footage import input_chain
from .media import ffmpeg, probe
from .timeline import Clip, Edit, Source
from .util import VeditError, run, short_hash

# measured on a real 720p frame with sigma ~7 grain: light +0.8 dB PSNR, medium +3 dB (both real-time-ish),
# strong (non-local means) +4-6 dB with the most detail kept, but ~0.4 s per 720p frame: say so before long clips
DENOISE = {"light": "hqdn3d=4:3:6:4.5", "medium": "hqdn3d=8:6:12:9", "strong": "nlmeans=s=3:p=5:r=9"}


def redact_filters(boxes: list[dict], tag: str) -> list[str]:
    """Chain pieces (with their own labels) that blur / pixelate / delogo boxes in source pixels."""
    parts = []
    for i, b in enumerate(boxes):
        x, y, w, h = (int(b[k]) for k in ("x", "y", "w", "h"))
        en = ""
        if b.get("start") is not None or b.get("end") is not None:
            en = f":enable='between(t,{float(b.get('start') or 0):.3f},{float(b.get('end') or 1e9):.3f})'"
        mode = b.get("mode", "blur")
        if mode == "delogo":
            parts.append(f"delogo=x={x}:y={y}:w={w}:h={h}{en}")
            continue
        a, c, d = f"{tag}r{i}a", f"{tag}r{i}b", f"{tag}r{i}c"
        if mode == "pixelate":
            block = max(4, int(b.get("block", max(w, h) / 12)))
            inner = f"scale={max(1, w // block)}:{max(1, h // block)}:flags=area,scale={w}:{h}:flags=neighbor"
        else:
            r = max(4, int(b.get("radius", min(w, h) / 6)))
            inner = f"boxblur={r}:2"
        parts.append(f"split[{a}][{c}];[{c}]crop={w}:{h}:{x}:{y},{inner}[{d}];[{a}][{d}]overlay={x}:{y}{en}")
    return parts


def stabilize_detect(src: Source, ss: float, t: float, pre: list[str], params: dict, work: Path) -> str:
    """Pass 1 of vidstab on exactly the frames the segment decodes; returns the .trf name (inside work)."""
    shaky = int(params.get("shakiness", 8))          # handheld footage: the reason to stabilize at all
    name = f"stab_{short_hash(src.path, round(ss, 3), round(t, 3), pre, shaky)}.trf"
    if not (work / name).exists():
        vf = ",".join([*pre, f"vidstabdetect=shakiness={shaky}:accuracy=15:result={name}"])
        run([ffmpeg(), "-y", "-v", "error", "-ss", f"{ss:.4f}", "-t", f"{t:.4f}", "-i", src.path, "-vf", vf,
             "-f", "null", "-"], cwd=work, timeout=7200)
    return name


def clip_prefilters(clip: Clip, src: Source, work: Path, *, ss: float, t: float, tag: str = "c",
                    tracks: dict | None = None, project_root: Path | None = None) -> list[str]:
    """Everything that happens to a clip's picture before speed and framing: the source chain (deinterlace,
    HDR -> SDR, camera LUT), redaction, VFX layers (tracked blur, screen inserts, cut-out background,
    depth of field), black-bar crop, 360 reframe, stabilize, denoise, reverse."""
    from .vfx.layers import clip_pieces
    pre = input_chain(src, lut_dir=work)
    pre += redact_filters([r for r in clip.redact if not r.get("track")], tag)
    pieces = clip_pieces(clip, src, work, ss=ss, t=t, tag=tag, tracks=tracks, project_root=project_root)
    pre += pieces
    if clip.src_crop:
        c = clip.src_crop
        pre.append(f"crop={int(c['w'])}:{int(c['h'])}:{int(c['x'])}:{int(c['y'])}")
    if clip.projection:
        pj = clip.projection
        ow = int(pj.get("w") or 1920)
        oh = int(pj.get("h") or round(ow * float(pj.get("v_fov", 70)) / float(pj.get("h_fov", 100)) / 2) * 2)
        pre.append(f"v360=input={pj.get('input', 'e')}:output=flat:yaw={pj.get('yaw', 0):g}:pitch={pj.get('pitch', 0):g}"
                   f":roll={pj.get('roll', 0):g}:h_fov={pj.get('h_fov', 100):g}:v_fov={pj.get('v_fov', 70):g}:w={ow}:h={oh}")
    if clip.stabilize is not None:
        st = clip.stabilize
        # motion is measured on the camera picture, not on composited VFX (a swapped background is static)
        trf = stabilize_detect(src, ss, t, [f for f in pre if f not in pieces], st, work)
        pre.append(f"vidstabtransform=input={trf}:smoothing={int(st.get('smoothing', 30))}:zoom={float(st.get('zoom', 0)):g}"
                   f":optzoom={1 if not st.get('zoom') else 0}:crop=black:interpol=bicubic")
    if clip.denoise:
        pre.append(DENOISE[clip.denoise])
    if clip.reverse:
        pre.append("reverse")
    return pre


GEOMETRY = ("crop", "v360", "vidstabtransform", "reverse")


def geometry_only(pre: list[str]) -> list[str]:
    """The filters of a clip's prefilters that move pixels (for a matte that must follow the picture)."""
    return [f for f in pre if f.split("=", 1)[0] in GEOMETRY]


def fps_filter(clip: Clip, fps: float) -> str:
    """Frame-rate conform; smooth slow motion builds the missing frames instead of repeating them."""
    if clip.smooth == "interpolate" and clip.speed < 0.999:
        return f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
    if clip.smooth == "blend" and clip.speed < 0.999:
        return f"minterpolate=fps={fps}:mi_mode=blend"
    return f"fps={fps}"


def straighten_scale(degrees: float, w: int, h: int) -> float:
    """Zoom that hides the corners a rotation would reveal."""
    th = math.radians(abs(degrees))
    return math.cos(th) + max(w / h, h / w) * math.sin(th)


# ------------------------------------------------------------------ edit operations

def ramp(edit: Edit, clip_id: str, segments: list[tuple[float, float, float]]) -> Edit:
    """Split a main clip into speed sections: [(from, to, speed)] in clip-local SOURCE seconds (0 = clip in).
    Each section is an ordinary clip, so CapCut, NLEs, the Studio and anchors all understand it."""
    idx = next((i for i, c in enumerate(edit.main) if c.id == clip_id), None)
    if idx is None:
        raise VeditError(f"No main clip '{clip_id}'")
    base = edit.main[idx]
    span = base.src_out - base.src_in
    pieces = []
    for n, (a, b, sp) in enumerate(sorted(segments)):
        a, b = max(0.0, a), min(span, b)
        if b - a <= 1e-3 or sp <= 0:
            continue
        c = base.model_copy(deep=True)
        c.id, c.src_in, c.src_out, c.speed = f"{base.id}_r{n + 1}", base.src_in + a, base.src_in + b, sp
        c.transition_in = base.transition_in if n == 0 else None
        if sp < 1 and not c.smooth:
            c.smooth = "interpolate" if sp >= 0.2 else "blend"
        if n:
            c.fade_in = 0.0
        pieces.append(c)
    if not pieces:
        raise VeditError("No valid ramp sections")
    for c in pieces[:-1]:
        c.fade_out = 0.0
    edit.main[idx:idx + 1] = pieces
    return edit.layout()


def freeze(edit: Edit, proj_root: Path, *, at: float, hold: float) -> Edit:
    """Hold the frame at timeline time `at` for `hold` seconds (a still inserted into the main track)."""
    from .timeline import Source as Src
    loc = edit.timeline_to_source(at)
    if not loc:
        raise VeditError(f"Nothing on the main track at {at:.2f}s")
    sid, t = loc
    src = edit.sources[sid]
    out_dir = proj_root / "assets" / "freeze"
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{sid}_{t:.3f}.png"
    chain = input_chain(src, lut_dir=out_dir)
    run([ffmpeg(), "-y", "-v", "error", "-ss", f"{t:.4f}", "-i", src.path, "-frames:v", "1",
         *(["-vf", ",".join(chain)] if chain else []), str(png)], cwd=out_dir)
    still = f"{sid}_freeze_{int(t * 1000)}"
    edit.sources[still] = Src(id=still, path=str(png), kind="image", width=src.width, height=src.height,
                              origin=f"freeze:{sid}@{t:.3f}")
    i = next(i for i, c in enumerate(edit.main) if c.start is not None and c.start <= at < c.end)
    c = edit.main[i]
    split_src = c.src_in + (at - c.start) * c.speed
    head = c.model_copy(deep=True)
    head.src_out = split_src
    tail = c.model_copy(deep=True)
    tail.id, tail.src_in, tail.transition_in = f"{c.id}_b", split_src, None
    hold_clip = Clip(id=f"{c.id}_hold", source=still, src_in=0.0, src_out=hold, fit=c.fit, transform=c.transform,
                     zoom=None, crop=[], label="freeze frame")
    parts = [p for p in (head, hold_clip, tail) if p.src_out - p.src_in > 1e-3]
    edit.main[i:i + 1] = parts
    return edit.layout()


# ------------------------------------------------------------------ one-off file tools

def _out_path(src: Path, out: str | None, suffix: str, overwrite: bool) -> Path:
    o = Path(out) if out else src.with_name(f"{src.stem}_{suffix}{src.suffix if src.suffix.lower() in ('.mp4', '.mov', '.mkv') else '.mp4'}")
    if o.resolve() == src.resolve():
        raise VeditError("Refusing to overwrite the original; write somewhere else.")
    if o.exists() and not overwrite:
        raise VeditError(f"{o} exists; pass --overwrite if this job made it or the owner asked to replace it.")
    o.parent.mkdir(parents=True, exist_ok=True)
    return o


def file_tool(tool: str, path: str, *, out: str | None = None, overwrite: bool = False, dry_run: bool = False,
              **kw) -> dict:
    """One clean-up / time FX on a whole file. Video re-encodes at CRF 16 (an intermediate, not a delivery)."""
    from .footage import analyze
    src = Path(path).resolve()
    info = probe(src)
    if info.kind != "video":
        raise VeditError("input has no video stream")
    o = _out_path(src, out, tool, overwrite)
    work = o.parent / f".fx_{short_hash(str(src), tool, kw)}"
    s = Source(id="s", path=str(src), kind="video", width=info.width, height=info.height, fps=info.fps,
               color=analyze(src, deep=False) if tool in ("deinterlace", "to_sdr") else None)
    c = Clip(id="c", source="s", src_in=0, src_out=max(info.duration, 0.04))
    vf: list[str] = []
    af: list[str] = []
    if tool == "stabilize":
        c.stabilize = {"smoothing": kw.get("smoothing", 30), "shakiness": kw.get("shakiness", 8), "zoom": kw.get("zoom", 0)}
    elif tool == "denoise":
        c.denoise = kw.get("strength", "medium")
    elif tool == "deinterlace":
        s.color = {**(s.color or {}), "interlaced": True}
    elif tool == "to_sdr":
        if not (s.color or {}).get("hdr") and not (s.color or {}).get("bt2020_sdr"):
            raise VeditError("This file is not HDR or BT.2020 (nothing to convert).")
    elif tool == "redact":
        c.redact = [{k: kw[k] for k in ("x", "y", "w", "h") if k in kw} | {"mode": kw.get("mode", "blur"),
                                                                          "start": kw.get("start"), "end": kw.get("end")}]
    elif tool == "crop":
        c.src_crop = {k: kw[k] for k in ("x", "y", "w", "h")}
    elif tool == "v360":
        c.projection = {k: kw[k] for k in ("yaw", "pitch", "roll", "h_fov", "v_fov", "w") if kw.get(k) is not None}
    elif tool == "reverse":
        if info.duration > 120:
            raise VeditError("reverse holds the whole clip in memory; cut it to under 2 minutes first.")
        c.reverse = True
        af.append("areverse")
    elif tool == "straighten":
        deg = float(kw["degrees"])
        sc = straighten_scale(deg, info.width, info.height)
        vf.append(f"rotate={deg}*PI/180:c=black,scale=iw*{sc:.5f}:-2,crop={info.width}:{info.height}")
    elif tool == "loop":
        target = float(kw["duration"])
        n = max(0, math.ceil(target / max(info.duration, 0.04)) - 1)
        if dry_run:
            return {"dry_run": True, "output": str(o), "loops": n + 1}
        run([ffmpeg(), "-y", "-v", "error", "-stream_loop", str(n), "-i", str(src), "-t", f"{target:.3f}", "-c", "copy",
             str(o)], timeout=3600)
        return {"output": str(o), "duration": round(probe(o).duration, 3)}
    elif tool == "smooth":
        factor = float(kw.get("factor", 2.0))           # 2 = twice as long
        c.speed, c.smooth = 1 / factor, kw.get("method", "interpolate")
        vf.append(f"setpts={factor:g}*PTS")
        af.append(f"atempo={1 / factor:g}" if factor <= 2 else f"atempo=0.5,atempo={2 / factor:g}")
    else:
        raise VeditError(f"Unknown fx tool '{tool}'")
    work.mkdir(parents=True, exist_ok=True)
    pre = clip_prefilters(c, s, work, ss=0.0, t=info.duration)
    chain = pre + vf
    if tool == "smooth":
        chain.append(fps_filter(c, info.fps or 30))
    plan = {"tool": tool, "input": str(src), "output": str(o), "video_filters": chain, "audio_filters": af}
    if dry_run:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
        return {"dry_run": True, **plan}
    args = [ffmpeg(), "-y", "-v", "error", "-i", str(src), "-filter_complex", f"[0:v]{','.join(chain) or 'null'}[v]",
            "-map", "[v]"]
    if info.has_audio:
        args += ["-map", "0:a:0"] + (["-af", ",".join(af), "-c:a", "aac", "-b:a", "256k"] if af else ["-c:a", "copy"])
    args += ["-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(o)]
    run(args, cwd=work, timeout=14400)
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    p2 = probe(o)
    return {**plan, "duration": round(p2.duration, 3), "size": f"{p2.width}x{p2.height}", "fps": round(p2.fps, 3)}
