"""Clip filter pieces for the VFX fields, plus the cached layer files they read.

Each piece is a chain fragment in the same style as fx.redact_filters: it may branch with labels, but it
starts from the previous filter's output and ends on one unlabeled output, so pieces join with commas.
Layer files are written into the render work dir (the graph runs with cwd=work) and named by a hash of
everything that shapes them, so re-renders and previews reuse them.

Order inside a clip: tracked redaction -> screen inserts -> subject (cut-out background, outline, glow)
-> depth of field. The subject's own pixels therefore carry any redaction.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from ..timeline import Clip, Source, Track
from ..util import VeditError, short_hash
from . import frames

BG_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
# RGB(A) layer -> YUVA with the BT.709 matrix (the default conversion would use BT.601 and shift hues)
TO_YUVA = "scale=out_color_matrix=bt709:out_range=tv,format=yuva420p"


def _stamp(path: str) -> list:
    try:
        st = os.stat(path)
        return [path, st.st_size, int(st.st_mtime)]
    except OSError:
        return [path]


def _movie(name: str, w: int, h: int, fmt: str) -> str:
    return f"movie=filename={name},setpts=PTS-STARTPTS,scale={w}:{h}:flags=bicubic,format={fmt}"


def needs_layers(clip: Clip) -> bool:
    return bool(clip.subject or clip.dof or clip.screen or any(r.get("track") for r in clip.redact))


# ------------------------------------------------------------------ tracked redaction

def redact_mask(src: Source, entries: list[dict], tracks: dict[str, Track], work: Path, *, ss: float, t: float,
                mode: str) -> str:
    import cv2
    from .matte import MATTE_SIDE
    from .track import load, value_at
    datas = []
    for e in entries:
        tr = tracks.get(e["track"])
        if tr is None:
            raise VeditError(f"Redaction uses track '{e['track']}', which is not in this edit (vedit vfx list).")
        datas.append((e, load(tr)))
    spec = frames.spec_for(src.path, max_side=MATTE_SIDE)
    name = f"rdm_{short_hash(_stamp(src.path), round(ss, 4), round(t, 4), mode, entries, [_stamp(tracks[e['track']].file) for e in entries])}.mkv"
    out = work / name
    if out.exists():
        return name
    k = spec.scale
    n = max(1, int(round(t * spec.fps)))
    with frames.Writer(out, spec.width, spec.height, spec.fps, "gray") as wr:
        for i in range(n):
            st = ss + i / spec.fps
            m = np.zeros((spec.height, spec.width), np.uint8)
            for e, data in datas:
                if (e.get("start") is not None and st < float(e["start"])) or (e.get("end") is not None and st > float(e["end"])):
                    continue
                v = value_at(data, st, hold=float(e.get("hold", 0.3)))
                if v is None:
                    continue
                if data["kind"] == "planar":
                    q = (np.asarray(v[:8]).reshape(4, 2) * k).astype(np.int32)
                    cv2.fillConvexPoly(m, q, 255)
                    continue
                x, y, w, h = (float(a) * k for a in v[:4])
                pad = float(e.get("pad", 0.15))
                cx, cy, w, h = x + w / 2, y + h / 2, w * (1 + 2 * pad), h * (1 + 2 * pad)
                if e.get("shape", "ellipse" if data["kind"] == "face" else "box") == "ellipse":
                    cv2.ellipse(m, (int(cx), int(cy)), (int(w / 2), int(h / 2 * 1.1)), 0, 0, 360, 255, -1)
                else:
                    cv2.rectangle(m, (int(cx - w / 2), int(cy - h / 2)), (int(cx + w / 2), int(cy + h / 2)), 255, -1)
            if m.any():
                m = cv2.GaussianBlur(m, (0, 0), max(1.0, 0.004 * spec.width))
            wr.write(m)
    return name


def _redact_pieces(clip: Clip, src: Source, tracks: dict[str, Track], work: Path, *, ss: float, t: float, tag: str) -> list[str]:
    tracked = [r for r in clip.redact if r.get("track")]
    if not tracked:
        return []
    W, H, _ = frames.source_size(src.path)
    out = []
    for mode in sorted({("pixelate" if r.get("mode") == "pixelate" else "blur") for r in tracked}):
        group = [r for r in tracked if ("pixelate" if r.get("mode") == "pixelate" else "blur") == mode]
        name = redact_mask(src, group, tracks, work, ss=ss, t=t, mode=mode)
        a, b, c, m, d = (f"{tag}t{mode[0]}{x}" for x in "abcmd")
        strength = max(float(r.get("strength", 1.0)) for r in group)
        if mode == "pixelate":
            block = max(6, int(max(W, H) / 60 * strength))
            effect = f"scale={max(1, W // block)}:{max(1, H // block)}:flags=area,scale={W}:{H}:flags=neighbor"
        else:
            effect = f"gblur=sigma={max(8.0, max(W, H) / 70 * strength):.1f}:steps=3"
        out.append(f"split[{a}][{b}];[{b}]{effect}[{c}];{_movie(name, W, H, 'gray')}[{m}];[{c}][{m}]alphamerge[{d}];"
                   f"[{a}][{d}]overlay=format=yuv420:eof_action=pass")
    return out


# ------------------------------------------------------------------ screen inserts

def _screen_pieces(clip: Clip, src: Source, tracks: dict[str, Track], work: Path, *, ss: float, t: float, tag: str,
                   project_root: Path | None) -> list[str]:
    from .planar import insert_layer
    from .track import load
    out = []
    for i, e in enumerate(clip.screen):
        if not e.get("track"):
            print(f"warning: clip {clip.id}: screen insert {i + 1} has no track yet (run `vedit vfx prepare`)")
            continue
        tr = tracks.get(e["track"])
        if tr is None:
            raise VeditError(f"Screen insert uses track '{e['track']}', which is not in this edit.")
        media = str(e.get("media") or "")
        if media and not Path(media).is_absolute() and project_root:
            media = str(Path(project_root) / media)
        if not media or not Path(media).exists():
            raise VeditError(f"Screen insert media not found: {e.get('media')}")
        name = f"scr_{short_hash(_stamp(src.path), round(ss, 4), round(t, 4), e, _stamp(tr.file), _stamp(media))}.mkv"
        if not (work / name).exists():
            insert_layer(src.path, load(tr)["samples"], media, work / name, ss=ss, t=t, fit=e.get("fit", "cover"),
                         keep_light=float(e.get("keep_light", 0.0)), start=e.get("start"), end=e.get("end"),
                         src_color=src.color, work=work)
        a, b = f"{tag}s{i}a", f"{tag}s{i}b"
        out.append(f"null[{a}];movie=filename={name},setpts=PTS-STARTPTS,{TO_YUVA}[{b}];"
                   f"[{a}][{b}]overlay=format=yuv420:eof_action=pass")
    return out


# ------------------------------------------------------------------ subject (person matte)

def matte_file(src: Source, work: Path, *, ss: float, t: float) -> str:
    from .matte import mask_layer
    name = f"mat_{short_hash(_stamp(src.path), round(ss, 4), round(t, 4), src.color, 'modnet1')}.mkv"
    if not (work / name).exists():
        mask_layer(src.path, src.color, work / name, ss=ss, t=t, work=work)
    return name


def _hex(c: str) -> str:
    c = str(c).strip()
    return "0x" + c[1:] if c.startswith("#") else c


def _local_copy(path: str, work: Path, project_root: Path | None) -> str:
    import shutil
    p = Path(path)
    if not p.is_absolute() and project_root:
        p = Path(project_root) / p
    if not p.exists():
        raise VeditError(f"Background file not found: {path}")
    name = f"bg_{short_hash(_stamp(str(p)))}{p.suffix.lower()}"
    if not (work / name).exists():
        shutil.copy(p, work / name)
    return name


def background_chain(spec: str, W: int, H: int, work: Path, project_root: Path | None, tag: str) -> tuple[str, str]:
    """(prefix, chain) turning the frame on [{tag}xb] into the new background on [{tag}xbg]."""
    s = str(spec)
    kind, _, val = s.partition(":")
    src, dst = f"[{tag}xb]", f"[{tag}xbg]"
    if s.startswith("#") or kind == "color":
        col = _hex(val if kind == "color" else s)
        return "", f"{src}drawbox=x=0:y=0:w=iw:h=ih:color={col}@1:t=fill{dst}"
    if kind == "blur":
        sigma = float(val or 14) * max(W, H) / 1080
        return "", f"{src}gblur=sigma={sigma:.1f}:steps=3{dst}"
    if kind == "darken":
        k = 1 - float(val or 0.5)
        return "", f"{src}lutyuv=y=val*{k:.3f}{dst}"
    if kind in ("desaturate", "bw"):
        return "", f"{src}hue=s=0{dst}"
    if kind in ("image", "video"):
        name = _local_copy(val, work, project_root)
        loop = ":loop=0" if kind == "video" else ""
        bg = f"[{tag}xbi]"
        return (f"movie=filename={name}{loop},setpts=PTS-STARTPTS,scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},scale=out_color_matrix=bt709:out_range=tv,format=yuv420p{bg}", f"{src}{bg}overlay=0:0:format=yuv420{dst}")
    if kind in ("none", "keep", ""):
        return "", f"{src}null{dst}"
    raise VeditError(f"Unknown subject background '{spec}'. Use blur:N, #hex, darken:0.5, desaturate, image:<path>, video:<path>")


def _rgb(c: str) -> tuple[int, int, int]:
    c = str(c).strip().lstrip("#")
    if c.lower().startswith("0x"):
        c = c[2:]
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except ValueError as exc:
        raise VeditError(f"Not a colour: #{c}") from exc


def _tinted(mask: str, color: str, out: str, tag: str) -> str:
    """A solid colour layer whose alpha is the mask (no infinite colour source: it ends with the mask)."""
    r, g, b = _rgb(color)
    return (f"{mask}split[{tag}1][{tag}2];[{tag}1]format=rgb24,lutrgb=r={r}:g={g}:b={b},{TO_YUVA}[{tag}3];"
            f"[{tag}3][{tag}2]alphamerge{out}")


def _subject_pieces(clip: Clip, src: Source, work: Path, *, ss: float, t: float, tag: str,
                    project_root: Path | None) -> list[str]:
    sub = clip.subject or {}
    if not (sub.get("background") or sub.get("outline") or sub.get("glow")):
        return []
    W, H, _ = frames.source_size(src.path)
    name = matte_file(src, work, ss=ss, t=t)
    pre, bg = background_chain(sub.get("background") or "none", W, H, work, project_root, tag)
    a, b, m1, m2, m3, fg = f"[{tag}xa]", f"[{tag}xb]", f"[{tag}xm1]", f"[{tag}xm2]", f"[{tag}xm3]", f"[{tag}xfg]"
    parts = [f"split{a}{b}", *([pre] if pre else []), bg, f"{_movie(name, W, H, 'gray')},split=3{m1}{m2}{m3}"]
    cur = f"[{tag}xbg]"
    scale = max(W, H) / 1080
    glow = sub.get("glow")
    if glow:
        g = glow if isinstance(glow, dict) else {"color": str(glow)}
        size = float(g.get("size", 30)) * scale
        strength = float(g.get("strength", 0.85))
        parts.append(f"{m3}gblur=sigma={size / 2:.1f},lutyuv=y=min(255\\,val*{2 * strength:.2f})[{tag}xgm]")
        parts.append(_tinted(f"[{tag}xgm]", g.get("color", "#ffffff"), f"[{tag}xgl]", f"{tag}xgt"))
        parts.append(f"{cur}[{tag}xgl]overlay=format=yuv420:eof_action=pass[{tag}xg2]")
        cur = f"[{tag}xg2]"
    else:
        parts.append(f"{m3}nullsink")
    outline = sub.get("outline")
    if outline:
        o = outline if isinstance(outline, dict) else {"color": str(outline)}
        width = float(o.get("width", 10)) * scale
        parts.append(f"{m2}gblur=sigma={width / 1.6:.1f},lutyuv=y=if(gt(val\\,24)\\,255\\,0),gblur=sigma=1[{tag}xom]")
        parts.append(_tinted(f"[{tag}xom]", o.get("color", "#ffffff"), f"[{tag}xol]", f"{tag}xot"))
        parts.append(f"{cur}[{tag}xol]overlay=format=yuv420:eof_action=pass[{tag}xo2]")
        cur = f"[{tag}xo2]"
    else:
        parts.append(f"{m2}nullsink")
    parts.append(f"{a}{m1}alphamerge{fg}")
    parts.append(f"{cur}{fg}overlay=format=yuv420:eof_action=pass")
    return [";".join(parts)]


# ------------------------------------------------------------------ depth of field

def _dof_pieces(clip: Clip, src: Source, work: Path, *, ss: float, t: float, tag: str) -> list[str]:
    from .depth import dof_layer
    dof = clip.dof
    if not dof:
        return []
    W, H, _ = frames.source_size(src.path)
    name = f"dof_{short_hash(_stamp(src.path), round(ss, 4), round(t, 4), dof, clip.src_in, clip.speed, src.color)}.mkv"
    if not (work / name).exists():
        dof_layer(src.path, src.color, work / name, dof, ss=ss, t=t, clip_in=clip.src_in, speed=clip.speed, work=work)
    sigma = float(dof.get("blur", 10)) * max(W, H) / 1080
    a, b, c, m, d = (f"{tag}d{x}" for x in "abcmd")
    return [f"split[{a}][{b}];[{b}]gblur=sigma={sigma:.1f}:steps=2[{c}];{_movie(name, W, H, 'gray')}[{m}];"
            f"[{c}][{m}]alphamerge[{d}];[{a}][{d}]overlay=format=yuv420:eof_action=pass"]


# ------------------------------------------------------------------ entry point

def clip_pieces(clip: Clip, src: Source, work: Path, *, ss: float, t: float, tag: str,
                tracks: dict[str, Track] | None = None, project_root: Path | None = None) -> list[str]:
    if not needs_layers(clip) or src.kind != "video":
        return []
    tracks = tracks or {}
    return [*_redact_pieces(clip, src, tracks, work, ss=ss, t=t, tag=tag),
            *_screen_pieces(clip, src, tracks, work, ss=ss, t=t, tag=tag, project_root=project_root),
            *_subject_pieces(clip, src, work, ss=ss, t=t, tag=tag, project_root=project_root),
            *_dof_pieces(clip, src, work, ss=ss, t=t, tag=tag)]


def layer_key(clip: Clip, tracks: dict[str, Track] | None) -> list:
    """What a cached clip render must also depend on: the track files its VFX read."""
    ids = [r.get("track") for r in clip.redact if r.get("track")] + [s.get("track") for s in clip.screen if s.get("track")]
    tracks = tracks or {}
    return [_stamp(tracks[i].file) for i in ids if i in tracks]
