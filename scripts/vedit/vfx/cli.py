"""`vedit vfx ...`: tracking, tracked blur, labels that follow, screen replacement, cut-outs, depth.

Times: `--at` is a SOURCE time (what `vedit view <source>` shows); `--at-timeline` takes a timeline time
instead. Boxes and corners are SOURCE pixels. Every command that changes the edit saves edit.json, so
the Studio, renders and hand-offs see it.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..timeline import Clip, Edit
from ..util import VeditError, print_json
from . import frames


# ------------------------------------------------------------------ helpers

def _clips(edit: Edit) -> list[Clip]:
    return [*edit.main, *edit.broll]


def _clip(edit: Edit, cid: str) -> Clip:
    c = next((c for c in _clips(edit) if c.id == cid), None)
    if c is None:
        raise VeditError(f"No clip '{cid}'. Clips: {', '.join(c.id for c in _clips(edit))}")
    return c


def _floats(text: str, n: int | None = None) -> list[float]:
    vals = [float(v) for v in str(text).replace(";", ",").split(",") if v.strip()]
    if n and len(vals) != n:
        raise VeditError(f"Expected {n} comma-separated numbers, got '{text}'")
    return vals


def _source_time(edit: Edit, clip: Clip | None, at: float | None, at_timeline: float | None) -> tuple[str, float]:
    if at_timeline is not None:
        loc = None
        for c in _clips(edit):
            if c.start is not None and c.start <= at_timeline < c.end and (clip is None or c.id == clip.id):
                loc = (c.source, c.src_in + (at_timeline - c.start) * c.speed)
                break
        if loc is None:
            raise VeditError(f"No clip{' ' + clip.id if clip else ''} at timeline {at_timeline:.2f}s")
        return loc
    if clip is None:
        raise VeditError("Give --clip (or --at-timeline)")
    return clip.source, clip.src_in if at is None else at


def _range(edit: Edit, clip: Clip, margin: float = 0.5) -> tuple[float, float]:
    src = edit.sources[clip.source]
    return max(0.0, clip.src_in - margin), min(src.duration or clip.src_out + margin, clip.src_out + margin)


def _merged_ranges(edit: Edit, source: str, margin: float = 0.5) -> list[tuple[float, float]]:
    rs = sorted(_range(edit, c, margin) for c in _clips(edit) if c.source == source)
    out: list[list[float]] = []
    for a, b in rs:
        if out and a <= out[-1][1] + 0.05:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def canvas_to_source(edit: Edit, clip: Clip, u: float, X: float, Y: float) -> tuple[float, float]:
    """Inverse of track.source_to_canvas (axis-aligned affine at a given moment)."""
    from .track import source_to_canvas
    x0, y0 = source_to_canvas(edit, clip, u, 0.0, 0.0)
    x1, y1 = source_to_canvas(edit, clip, u, 1000.0, 1000.0)
    ax, ay = (x1 - x0) / 1000.0, (y1 - y0) / 1000.0
    return (X - x0) / ax, (Y - y0) / ay


# ------------------------------------------------------------------ commands

def cmd_track(a) -> dict:
    from ..project import find
    from .track import finish_box_samples, save, track_box, unique_id
    p = find(a.path)
    e = p.edit()
    clip = _clip(e, a.clip) if a.clip else None
    sid, at = _source_time(e, clip, a.at, a.at_timeline)
    src = e.sources[sid]
    t0, t1 = (_floats(a.range, 2) if a.range else (_range(e, clip) if clip else (max(0, at - 5), at + 5)))
    box = _floats(a.box, 4)
    samples = track_box(src.path, src.color, at=at, box=tuple(box), t0=t0, t1=t1, method=a.method, work=p.root / "vfx")
    lost = sum(1 for s in samples if s[5] <= 0)
    samples = finish_box_samples(samples, sigma=a.smooth, size=(src.width, src.height))
    tid = unique_id(e, a.id or f"track_{sid}")
    tr = save(p.root, e, {"id": tid, "source": sid, "kind": "object", "fps": frames.source_size(src.path)[2],
                          "size": [src.width, src.height], "method": a.method, "samples": samples}, label=a.label or "")
    p.save_edit(e)
    out = {"track": tr.id, "frames": len(samples), "lost_frames": lost, "range": [tr.t0, tr.t1], "file": tr.file}
    if lost > 0.2 * len(samples):
        out["warning"] = "the target was lost on many frames: check `vedit vfx sheet`, give a tighter box or try --method flow|vit"
    return out


def cmd_faces(a) -> dict:
    from ..project import find
    from .track import save, track_faces
    p = find(a.path)
    e = p.edit()
    targets = [_clip(e, c) for c in (a.clip or [])] or [c for c in _clips(e) if e.sources[c.source].kind == "video"]
    sources = sorted({c.source for c in targets})
    made = []
    for sid in sources:
        src = e.sources[sid]
        for n, (t0, t1) in enumerate(_merged_ranges(e, sid)):
            found = track_faces(src.path, src.color, t0=t0, t1=t1, min_size=a.min_size, work=p.root / "vfx")
            for k, f in enumerate(found):
                tid = f"face_{sid}_{n + 1}_{k + 1}"
                tr = save(p.root, e, {"id": tid, "source": sid, "kind": "face", "fps": frames.source_size(src.path)[2],
                                      "size": [src.width, src.height], "samples": f["samples"]},
                          label="largest face" if k == 0 else f"face {k + 1}")
                made.append({"track": tr.id, "source": sid, "range": [tr.t0, tr.t1], "frames_seen": f["frames"],
                             "size_px": int(f["area"] ** 0.5), "largest": k == 0})
    added = 0
    if a.blur or a.pixelate:
        mode = "pixelate" if a.pixelate else "blur"
        for c in targets:
            faces_here = [m for m in made if m["source"] == c.source and m["range"][0] < c.src_out and m["range"][1] > c.src_in]
            if a.keep_largest:
                faces_here = [m for m in faces_here if not m["largest"]]
            for m in faces_here:
                c.redact = [r for r in c.redact if r.get("track") != m["track"]]
                c.redact.append({"track": m["track"], "mode": mode, "shape": "ellipse", "pad": a.pad})
                added += 1
    p.save_edit(e)
    return {"faces": made, "redactions_added": added,
            "next": "look at `vedit vfx sheet <p> --track <id>` (and a preview render) before calling it done"}


def cmd_blur(a) -> dict:
    from ..project import find
    from .track import get
    p = find(a.path)
    e = p.edit()
    c = _clip(e, a.clip)
    get(e, a.track)
    c.redact = [r for r in c.redact if r.get("track") != a.track]
    if not a.clear:
        c.redact.append({"track": a.track, "mode": a.mode, "shape": a.shape, "pad": a.pad, "strength": a.strength})
    p.save_edit(e)
    return {"clip": c.id, "redact": c.redact}


def cmd_attach(a) -> dict:
    from ..project import find
    from .track import attach_path, get
    p = find(a.path)
    e = p.edit()
    ov = next((o for o in e.overlays if o.id == a.overlay), None)
    if ov is None:
        raise VeditError(f"No overlay '{a.overlay}'")
    if a.detach:
        ov.attach = None
    else:
        get(e, a.track)
        ov.attach = {"track": a.track, "offset": _floats(a.offset, 2) if a.offset else [0.0, 0.0], "point": a.point}
        if a.smooth:
            ov.attach["smooth"] = a.smooth
    p.save_edit(e)
    path = attach_path(e.layout(), ov, e.canvas.fps) if ov.attach else []
    return {"overlay": ov.id, "attach": ov.attach, "frames_on_screen": len(path),
            "first": path[0] if path else None, "last": path[-1] if path else None}


def cmd_screen(a) -> dict:
    from ..project import find
    from .planar import check_corners, draw_quads, suggest_quads
    p = find(a.path)
    e = p.edit()
    clip = _clip(e, a.clip)
    sid, at = _source_time(e, clip, a.at, a.at_timeline)
    src = e.sources[sid]
    if a.suggest:
        w, h, fps = frames.source_size(src.path)
        spec = frames.FrameSpec(w, h, w, h, fps)
        from ..footage import input_chain
        fr = next(frames.read(src.path, ss=at, t=0.2, spec=spec, chain=input_chain(src, lut_dir=None)), None)
        if fr is None:
            raise VeditError("Could not read that frame")
        cands = suggest_quads(fr)
        out = p.root / "qa" / f"screen_candidates_{clip.id}.png"
        draw_quads(fr, [c["corners"] for c in cands], out)
        return {"frame": str(out), "at": at, "candidates": cands,
                "next": "Read the PNG, pick one (or give your own corners), then vedit vfx screen ... --corners ... --media ..."}
    if a.clear:
        clip.screen = []
        p.save_edit(e)
        return {"clip": clip.id, "screen": []}
    if not (a.corners and a.media):
        raise VeditError("Give --corners x1,y1,...,x4,y4 (source px, at --at) and --media <image or video>")
    media = Path(a.media).resolve()
    if not media.exists():
        raise VeditError(f"No such file: {media}")
    entry = {"corners": check_corners(_floats(a.corners, 8)), "at": round(at, 4), "media": str(media), "fit": a.fit,
             "keep_light": a.keep_light}
    clip.screen.append(entry)
    res = prepare(p, e, only=[clip.id])
    p.save_edit(e)
    return {"clip": clip.id, "screen": clip.screen, **res}


def prepare(p, e: Edit, only: list[str] | None = None) -> dict:
    """Turn requests into tracks: screen entries with corners (source or canvas) but no track yet."""
    from .planar import check_corners, track_plane
    from .track import save, unique_id
    done = []
    for c in _clips(e):
        if only and c.id not in only:
            continue
        for entry in c.screen:
            if entry.get("track"):
                continue
            src = e.sources[c.source]
            if entry.get("canvas_corners") is not None:          # from the Studio: canvas 0..1 at a timeline time
                T = float(entry["timeline_at"])
                u = T - (c.start or 0.0)
                pts = [canvas_to_source(e, c, u, x * e.canvas.width, y * e.canvas.height) for x, y in entry["canvas_corners"]]
                entry["corners"] = check_corners([v for pt in pts for v in pt])
                entry["at"] = round(c.src_in + u * c.speed, 4)
            if not entry.get("corners"):
                continue
            t0, t1 = _range(e, c)
            samples = track_plane(src.path, src.color, at=float(entry["at"]), corners=entry["corners"], t0=t0, t1=t1,
                                  grow=float(entry.get("grow", 0.25)), work=p.root / "vfx")
            lost = sum(1 for s in samples if s[9] <= 0)
            tid = unique_id(e, f"screen_{c.id}")
            tr = save(p.root, e, {"id": tid, "source": c.source, "kind": "planar", "fps": frames.source_size(src.path)[2],
                                  "size": [src.width, src.height], "samples": samples}, label=f"screen in {c.id}")
            entry["track"] = tr.id
            done.append({"clip": c.id, "track": tr.id, "frames": len(samples), "lost_frames": lost})
    return {"tracked": done}


def cmd_prepare(a) -> dict:
    from ..project import find
    p = find(a.path)
    e = p.edit()
    res = prepare(p, e)
    p.save_edit(e)
    return res


def cmd_subject(a) -> dict:
    from ..project import find
    p = find(a.path)
    e = p.edit()
    c = _clip(e, a.clip)
    if a.clear:
        c.subject = None
    else:
        sub = dict(c.subject or {})
        if a.background:
            sub["background"] = a.background
        if a.outline:
            col, _, w = a.outline.partition(":")
            sub["outline"] = {"color": col, "width": float(w or 10)}
        if a.glow:
            col, _, sz = a.glow.partition(":")
            sub["glow"] = {"color": col, "size": float(sz or 30)}
        if a.above is not None:
            sub["above"] = a.above
        if not sub:
            raise VeditError("Give --background, --outline, --glow and/or --above")
        c.subject = sub
    p.save_edit(e)
    from .. import models
    return {"clip": c.id, "subject": c.subject, "model_ready": models.is_ready("modnet"),
            "note": "graphics on overlay layers below `above` sit behind the person" if (c.subject or {}).get("above") is not None else ""}


def cmd_dof(a) -> dict:
    from ..project import find
    p = find(a.path)
    e = p.edit()
    c = _clip(e, a.clip)
    if a.clear:
        c.dof = None
    else:
        d = {"focus": "auto" if a.focus in (None, "auto") else float(a.focus), "range": a.range, "blur": a.blur}
        if a.pull:
            pts = _floats(a.pull)
            d["pull"] = [[pts[i], pts[i + 1]] for i in range(0, len(pts) - 1, 2)]
        c.dof = d
    p.save_edit(e)
    return {"clip": c.id, "dof": c.dof}


def cmd_list(a) -> dict:
    from ..project import find
    e = find(a.path).edit()
    clips = []
    for c in _clips(e):
        items = {k: v for k, v in (("redact", c.redact), ("subject", c.subject), ("dof", c.dof), ("screen", c.screen)) if v}
        if items:
            clips.append({"clip": c.id, **items})
    return {"tracks": [t.model_dump() for t in e.tracks], "clips": clips,
            "attached": [{"overlay": o.id, **(o.attach or {})} for o in e.overlays if o.attach]}


def cmd_sheet(a) -> dict:
    """Frames across a track with its boxes / quads drawn: for Claude's eyes before claiming it worked."""
    import cv2
    from ..footage import input_chain
    from ..project import find
    from .track import get, load, value_at
    p = find(a.path)
    e = p.edit()
    tr = get(e, a.track)
    data = load(tr)
    src = e.sources[tr.source]
    w, h, fps = frames.source_size(src.path)
    spec = frames.spec_for(src.path, max_side=640)
    k = spec.scale
    times = np.linspace(tr.t0, tr.t1, a.frames)
    tiles = []
    for t in times:
        fr = next(frames.read(src.path, ss=float(t), t=0.2, spec=spec, chain=input_chain(src, lut_dir=None)), None)
        if fr is None:
            continue
        fr = fr.copy()
        v = value_at(data, float(t))
        if v is not None:
            if data["kind"] == "planar":
                cv2.polylines(fr, [(np.asarray(v[:8]).reshape(4, 2) * k).astype(np.int32)], True, (0, 220, 255), 2)
            else:
                x, y, bw, bh = (float(q) * k for q in v[:4])
                cv2.rectangle(fr, (int(x), int(y)), (int(x + bw), int(y + bh)), (0, 220, 255), 2)
            cv2.putText(fr, f"{t:.2f}s conf {v[-1]:.2f}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 255), 2)
        tiles.append(fr)
    if not tiles:
        raise VeditError("No frames read for this track")
    cols = min(3, len(tiles))
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    out = Path(a.out) if a.out else p.root / "qa" / f"track_{tr.id}.png"
    frames.write_image(out, np.vstack(rows))
    return {"sheet": str(out), "track": tr.id, "frames": len(times)}


def cmd_cutout(a) -> dict:
    from .matte import cutout
    out = a.out or str(Path(a.image).with_name(Path(a.image).stem + "_cutout.png"))
    if Path(out).resolve() == Path(a.image).resolve():
        raise VeditError("Refusing to overwrite the original; write somewhere else.")
    return cutout(a.image, out, model=a.model)


def cmd_depth(a) -> dict:
    from .depth import depth_image
    out = a.out or str(Path(a.image).with_name(Path(a.image).stem + "_depth.png"))
    d, path = depth_image(a.image, out)
    return {"output": str(path), "near_fraction": round(float((d > 0.66).mean()), 3), "far_fraction": round(float((d < 0.33).mean()), 3)}


def cmd_parallax(a) -> dict:
    from .depth import parallax
    if a.project:
        from ..project import add_source, find
        p = find(a.project)
        e = p.edit()
        out = p.root / "assets" / "parallax" / f"{Path(a.image).stem}_{a.move}.mp4"
        size = (e.canvas.width, e.canvas.height)
    else:
        out = Path(a.out or Path(a.image).with_name(Path(a.image).stem + f"_{a.move}.mp4"))
        size = tuple(int(v) for v in a.size.split("x")) if a.size else None
    res = parallax(a.image, out, duration=a.duration, fps=a.fps, move=a.move, amount=a.amount, size=size)
    if a.project:
        sid = add_source(p, out, origin=f"parallax:{Path(a.image).name}")
        e = p.edit()
        c = Clip(id=f"px_{sid}", source=sid, src_in=0.0, src_out=round(a.duration - 1 / a.fps, 3), fit="cover",
                 label=f"3D photo: {Path(a.image).stem}")
        if a.track == "main":
            e.main.append(c)
        else:
            c.start = a.at
            e.broll.append(c)
        p.save_edit(e)
        res.update({"clip": c.id, "source": sid, "track": a.track, "start": a.at})
    return res


def cmd_dof_image(a) -> dict:
    from .depth import dof_image
    out = a.out or str(Path(a.image).with_name(Path(a.image).stem + "_dof.png"))
    return dof_image(a.image, out, focus=a.focus if a.focus == "auto" else float(a.focus), range_=a.range, blur=a.blur)


def cmd_check(a) -> dict:
    import cv2
    from .. import models
    from ..addons import find_blender
    from .depth import MOVES  # noqa: F401  (registers the depth model)
    from . import matte, track  # noqa: F401
    return {"opencv": cv2.__version__, "vit_tracker": hasattr(cv2, "TrackerVit_create"),
            "models": {m: models.info(m) for m in ("yunet", "vittrack", "modnet", "depth_small", "birefnet_lite")},
            "blender": str(find_blender() or "")}


# ------------------------------------------------------------------ CLI

def register_cli(sp) -> None:
    s = sp.add_parser("vfx", help="tracking, tracked blur, follow labels, screen replacement, cut-outs, depth")
    sub = s.add_subparsers(dest="vfx_cmd", required=True)

    t = sub.add_parser("track", help="track a box (source px) from a moment")
    t.add_argument("path"); t.add_argument("--clip"); t.add_argument("--box", required=True, help="x,y,w,h source px")
    t.add_argument("--at", type=float); t.add_argument("--at-timeline", type=float); t.add_argument("--range", help="t0,t1 source s")
    t.add_argument("--method", default="auto", choices=["auto", "vit", "flow"]); t.add_argument("--id"); t.add_argument("--label")
    t.add_argument("--smooth", type=float, default=2.0, help="smoothing sigma in frames")
    t.set_defaults(fn=lambda a: print_json(cmd_track(a)))

    f = sub.add_parser("faces", help="find and track every face; --blur/--pixelate redacts them")
    f.add_argument("path"); f.add_argument("--clip", nargs="*"); f.add_argument("--blur", action="store_true")
    f.add_argument("--pixelate", action="store_true"); f.add_argument("--keep-largest", action="store_true")
    f.add_argument("--min-size", type=float, default=0.03); f.add_argument("--pad", type=float, default=0.18)
    f.set_defaults(fn=lambda a: print_json(cmd_faces(a)))

    b = sub.add_parser("blur", help="blur / pixelate a tracked thing on a clip")
    b.add_argument("path"); b.add_argument("--clip", required=True); b.add_argument("--track", required=True)
    b.add_argument("--mode", default="blur", choices=["blur", "pixelate"]); b.add_argument("--shape", default="box", choices=["box", "ellipse"])
    b.add_argument("--pad", type=float, default=0.1); b.add_argument("--strength", type=float, default=1.0)
    b.add_argument("--clear", action="store_true")
    b.set_defaults(fn=lambda a: print_json(cmd_blur(a)))

    at = sub.add_parser("attach", help="make an overlay follow a track")
    at.add_argument("path"); at.add_argument("overlay"); at.add_argument("--track"); at.add_argument("--offset", help="x,y half-canvas units")
    at.add_argument("--point", default="center", choices=["center", "top", "bottom"]); at.add_argument("--smooth", type=float)
    at.add_argument("--detach", action="store_true")
    at.set_defaults(fn=lambda a: print_json(cmd_attach(a)))

    sc = sub.add_parser("screen", help="replace a screen / sign / poster (four corners) with an image or video")
    sc.add_argument("path"); sc.add_argument("--clip", required=True); sc.add_argument("--corners"); sc.add_argument("--media")
    sc.add_argument("--at", type=float); sc.add_argument("--at-timeline", type=float); sc.add_argument("--fit", default="cover", choices=["cover", "stretch"])
    sc.add_argument("--keep-light", type=float, default=0.0); sc.add_argument("--suggest", action="store_true"); sc.add_argument("--clear", action="store_true")
    sc.set_defaults(fn=lambda a: print_json(cmd_screen(a)))

    pr = sub.add_parser("prepare", help="track pending requests (screen corners picked in the Studio)")
    pr.add_argument("path"); pr.set_defaults(fn=lambda a: print_json(cmd_prepare(a)))

    su = sub.add_parser("subject", help="person cut-out: background blur/swap, outline, glow, text behind the person")
    su.add_argument("path"); su.add_argument("--clip", required=True); su.add_argument("--background")
    su.add_argument("--outline", help="#hex:width"); su.add_argument("--glow", help="#hex:size")
    su.add_argument("--above", type=int, help="overlay layers below this go behind the person"); su.add_argument("--clear", action="store_true")
    su.set_defaults(fn=lambda a: print_json(cmd_subject(a)))

    d = sub.add_parser("dof", help="fake depth of field on a clip (focus 1 = nearest)")
    d.add_argument("path"); d.add_argument("--clip", required=True); d.add_argument("--focus", default="auto", help="auto | 0..1 (1 = nearest)")
    d.add_argument("--range", type=float, default=0.25); d.add_argument("--blur", type=float, default=10)
    d.add_argument("--pull", help="clip-local s,focus pairs: 0,0.9,2,0.3"); d.add_argument("--clear", action="store_true")
    d.set_defaults(fn=lambda a: print_json(cmd_dof(a)))

    ls = sub.add_parser("list", help="tracks and VFX on clips"); ls.add_argument("path")
    ls.set_defaults(fn=lambda a: print_json(cmd_list(a)))
    sh = sub.add_parser("sheet", help="frames with a track drawn (look before claiming)")
    sh.add_argument("path"); sh.add_argument("--track", required=True); sh.add_argument("--frames", type=int, default=6); sh.add_argument("--out")
    sh.set_defaults(fn=lambda a: print_json(cmd_sheet(a)))

    co = sub.add_parser("cutout", help="transparent PNG of a still's subject")
    co.add_argument("image"); co.add_argument("--out"); co.add_argument("--model", default="auto", choices=["auto", "modnet", "birefnet"])
    co.set_defaults(fn=lambda a: print_json(cmd_cutout(a)))
    de = sub.add_parser("depth", help="depth map of a still (16-bit PNG, white = near)")
    de.add_argument("image"); de.add_argument("--out"); de.set_defaults(fn=lambda a: print_json(cmd_depth(a)))
    px = sub.add_parser("parallax", help="3D photo: a camera move inside a still")
    px.add_argument("image"); px.add_argument("--project"); px.add_argument("--at", type=float, default=0.0)
    px.add_argument("--track", default="broll", choices=["broll", "main"]); px.add_argument("--out"); px.add_argument("--size", help="WxH")
    px.add_argument("--duration", type=float, default=5.0); px.add_argument("--fps", type=float, default=30.0)
    px.add_argument("--move", default="dolly_in"); px.add_argument("--amount", type=float, default=1.0)
    px.set_defaults(fn=lambda a: print_json(cmd_parallax(a)))
    di = sub.add_parser("dof-image", help="depth of field on a still")
    di.add_argument("image"); di.add_argument("--out"); di.add_argument("--focus", default="auto")
    di.add_argument("--range", type=float, default=0.25); di.add_argument("--blur", type=float, default=10)
    di.set_defaults(fn=lambda a: print_json(cmd_dof_image(a)))
    ck = sub.add_parser("check", help="what VFX can run here (OpenCV, models, Blender)")
    ck.set_defaults(fn=lambda a: print_json(cmd_check(a)))
