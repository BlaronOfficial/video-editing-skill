"""CLI for the FFmpeg toolkit (ported from kajisho5/ffmpeg-skill, MIT, into vedit's own modules):

  vedit footage check <file|project> | lut <p> <source> <file.cube> | bars <p> [--apply]
  vedit delivery check <file> --platform reels [--compare m.mp4] | export <file> --preset reels [--fit] [--max-mb]
                 | compare <a> <b> | repair <file> | safe <file> --platform tiktok [--at 3] | platforms
  vedit fix <tool> <file> [options] --out x.mp4      stabilize denoise deinterlace to_sdr redact crop v360 reverse
                                                       straighten loop smooth
  vedit clip set <p> <clip> [--stabilize] [--denoise medium] [--reverse] [--smooth interpolate] [--crop x,y,w,h]
                 [--redact x,y,w,h[:mode]] [--projection yaw,pitch,h_fov,v_fov] [--straighten DEG] [--clear]
  vedit clip ramp <p> <clip> --segment 0-2:1 --segment 2-3:0.25 ... | freeze <p> --at 12.4 --hold 2
  vedit audio sync <ref> <other> [--drift] | replace <video> <recorder> [--drift] --out | clean | dynamics | widen
                 | downmix | extract <file>
  vedit grid | audiogram | waveform | kenburns | batch | report       (see extras.py)

Every writing tool refuses to overwrite its input and refuses an existing output without --overwrite;
long jobs take --dry-run and print the plan as JSON first.
"""

from __future__ import annotations

from pathlib import Path

from .util import VeditError, print_json


def _proj(path: str):
    from .project import find
    return find(path)


def _box(spec: str) -> dict:
    head, _, mode = spec.partition(":")
    x, y, w, h = (int(float(v)) for v in head.split(","))
    return {"x": x, "y": y, "w": w, "h": h, "mode": mode or "blur"}


# ------------------------------------------------------------------ handlers

def cmd_footage(a) -> None:
    from . import footage
    if a.action == "check":
        p = Path(a.target)
        if p.is_file():
            print_json(footage.summary(p))
            return
        proj = _proj(a.target)
        e = proj.edit()
        out = {}
        for sid, s in e.sources.items():
            if s.kind == "video":
                s.color = footage.analyze(s.path)
                s.notes = footage.notes(s.color)
                out[sid] = {"notes": s.notes, "hdr": s.color.get("hdr"), "timing": s.color.get("timing"),
                            "log": (s.color.get("log") or {}).get("looks_like_log"), "device": s.color.get("device")}
        proj.save_edit(e)
        print_json(out)
    elif a.action == "lut":
        proj = _proj(a.target)
        e = proj.edit()
        if a.source not in e.sources:
            raise VeditError(f"No source '{a.source}'")
        if a.file and not Path(a.file).exists():
            raise VeditError(f"LUT not found: {a.file}")
        e.sources[a.source].lut = str(Path(a.file).resolve()) if a.file else None
        proj.save_edit(e)
        proj.log(f"camera LUT for {a.source}: {a.file or 'none'}")
        print_json({"source": a.source, "lut": e.sources[a.source].lut})
    elif a.action == "bars":
        proj = _proj(a.target)
        e = proj.edit()
        done = {}
        for sid, s in e.sources.items():
            bars = (s.color or {}).get("black_bars")
            if bars:
                done[sid] = bars
                if a.apply:
                    for c in [*e.main, *e.broll]:
                        if c.source == sid and not c.src_crop:
                            c.src_crop = dict(bars)
        if a.apply:
            proj.save_edit(e)
        print_json({"black_bars": done, "applied": bool(a.apply)})


def cmd_delivery(a) -> None:
    from . import delivery
    if a.action == "platforms":
        print_json({k: {"title": v["title"], "frame": v["frame"], "max_duration": v["max_duration"], "lufs": v["lufs"],
                        "safe": v["safe"]} for k, v in delivery.PLATFORMS.items()})
    elif a.action == "check":
        print_json(delivery.check(a.target, a.platform or "youtube", compare=a.compare))
    elif a.action == "export":
        print_json(delivery.export(a.target, a.preset, out=a.out, fit=a.fit, max_mb=a.max_mb, normalize=not a.no_normalize,
                                   overwrite=a.overwrite, dry_run=a.dry_run))
    elif a.action == "compare":
        if not a.other:
            raise VeditError("compare needs two files")
        print_json(delivery.compare_files(a.target, a.other))
    elif a.action == "repair":
        print_json(delivery.repair(a.target, a.out, overwrite=a.overwrite))
    elif a.action == "safe":
        out = a.out or str(Path(a.target).with_name(Path(a.target).stem + f"_safe_{a.platform}.png"))
        print(delivery.safe_frame(a.target, a.platform or "tiktok", out, at=a.at))


def cmd_fx(a) -> None:
    from . import fx
    if a.tool == "set":
        proj = _proj(a.target)
        e = proj.edit()
        clip = next((c for c in [*e.main, *e.broll] if c.id == a.clip), None)
        if not clip:
            raise VeditError(f"No clip '{a.clip}'")
        if a.clear:
            clip.stabilize = clip.denoise = clip.smooth = clip.src_crop = clip.projection = None
            clip.reverse, clip.redact = False, []
        if a.stabilize:
            clip.stabilize = {"smoothing": a.smoothing, "shakiness": 5, "zoom": 0}
        if a.denoise:
            clip.denoise = a.denoise
        if a.reverse:
            clip.reverse = True
        if a.smooth:
            clip.smooth = a.smooth
        if a.crop:
            b = _box(a.crop)
            clip.src_crop = {k: b[k] for k in ("x", "y", "w", "h")}
        for r in a.redact or []:
            clip.redact.append(_box(r))
        if a.projection:
            yaw, pitch, hf, vf = (float(x) for x in a.projection.split(","))
            clip.projection = {"yaw": yaw, "pitch": pitch, "h_fov": hf, "v_fov": vf, "input": "e"}
        if a.straighten is not None:
            src = e.sources[clip.source]
            clip.transform.rotation = a.straighten
            clip.transform.scale = round(fx.straighten_scale(a.straighten, e.canvas.width, e.canvas.height), 4)
        proj.save_edit(e)
        print_json(clip.model_dump(include={"id", "stabilize", "denoise", "reverse", "smooth", "src_crop", "projection",
                                            "redact", "transform"}, exclude_none=True))
    elif a.tool == "ramp":
        proj = _proj(a.target)
        segs = []
        for s in a.segment or []:
            rng, _, sp = s.rpartition(":")
            x, y = rng.split("-")
            segs.append((float(x), float(y), float(sp)))
        e = fx.ramp(proj.edit(), a.clip, segs)
        proj.save_edit(e)
        print_json({"main_clips": [{"id": c.id, "speed": c.speed, "duration": round(c.duration, 3)} for c in e.main
                                   if c.id.startswith(a.clip)], "duration": round(e.duration, 3)})
    elif a.tool == "freeze":
        proj = _proj(a.target)
        e = fx.freeze(proj.edit(), proj.root, at=a.at, hold=a.hold)
        proj.save_edit(e)
        print_json({"duration": round(e.duration, 3), "main_clips": len(e.main)})
    else:
        kw = {k: getattr(a, k) for k in ("smoothing", "shakiness", "zoom", "strength", "mode", "start", "end", "yaw",
                                          "pitch", "roll", "h_fov", "v_fov", "w", "degrees", "duration", "factor", "method")
              if getattr(a, k, None) is not None}
        if a.box:
            kw.update({k: v for k, v in _box(a.box).items() if k != "mode"})
        print_json(fx.file_tool(a.tool, a.target, out=a.out, overwrite=a.overwrite, dry_run=a.dry_run, **kw))


def cmd_audio(a) -> None:
    from . import audiotools
    if a.action == "sync":
        r = audiotools.sync(a.target, a.other, drift=a.drift)
        r["note"] = audiotools.clock_note(r)
        print_json(r)
    elif a.action == "replace":
        out = a.out or str(Path(a.target).with_name(Path(a.target).stem + "_synced" + Path(a.target).suffix))
        print_json(audiotools.replace(a.target, a.other, out, drift=a.drift, overwrite=a.overwrite))
    else:
        print_json(audiotools.file_tool(a.action, a.target, out=a.out, overwrite=a.overwrite, voice=a.voice,
                                        denoise=a.denoise, gate=a.gate, compress=a.compress, limit=a.limit, amount=a.amount))


def cmd_extras(a) -> None:
    from . import extras
    if a.cmd == "grid":
        print_json(extras.grid(a.files, a.out, cols=a.cols, rows=a.rows, cell=a.cell, audio=a.audio, overwrite=a.overwrite))
    elif a.cmd in ("audiogram", "waveform"):
        print_json(extras.audiogram(a.audio_file, a.out, image=a.image, title=a.title or "", size=a.size, style=a.style,
                                    overwrite=a.overwrite))
    elif a.cmd == "kenburns":
        print_json(extras.kenburns(_proj(a.path), a.image, at=a.at, duration=a.duration, zoom=a.zoom, pan=a.pan,
                                   track=a.track))
    elif a.cmd == "batch":
        print_json(extras.batch(a.folder, a.recipe, jobs=a.jobs, dry_run=a.dry_run, pattern=a.pattern))
    elif a.cmd == "report":
        print_json(extras.report(a.after, a.out, before=a.before, platform=a.platform, title=a.title or "",
                                 steps=a.step or None))


# ------------------------------------------------------------------ parser

def argparse_suppress():
    import argparse
    return argparse.SUPPRESS


def register_cli(sp) -> None:
    from .delivery import PLATFORMS, PRESETS
    s = sp.add_parser("footage", help="HDR / Log / VFR / interlacing / black bars / device: check and fix sources")
    s.add_argument("action", choices=["check", "lut", "bars"]); s.add_argument("target", help="file or project")
    s.add_argument("source", nargs="?"); s.add_argument("file", nargs="?"); s.add_argument("--apply", action="store_true")
    s.set_defaults(fn=cmd_footage)

    s = sp.add_parser("delivery", help="platform checks, export presets, size targets, compare, repair, safe zones")
    s.add_argument("action", choices=["check", "export", "compare", "repair", "safe", "platforms"])
    s.add_argument("target", nargs="?"); s.add_argument("other", nargs="?")
    s.add_argument("--platform", choices=list(PLATFORMS) + ["ig", "instagram", "youtube-shorts", "twitter", "fb"])
    s.add_argument("--preset", default="youtube", choices=list(PRESETS)); s.add_argument("--fit", default="pad",
                   choices=["pad", "crop", "blur"])
    s.add_argument("--max-mb", type=float); s.add_argument("--no-normalize", action="store_true"); s.add_argument("--compare")
    s.add_argument("--out"); s.add_argument("--at", type=float, default=1.0); s.add_argument("--overwrite", action="store_true")
    s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=cmd_delivery)

    def fx_args(s, edit_ops: bool) -> None:
        s.add_argument("--out"); s.add_argument("--overwrite", action="store_true"); s.add_argument("--dry-run", action="store_true")
        s.add_argument("--smoothing", type=int, default=30, help="stabilize: frames each side (30 = 1 s at 30 fps)"); s.add_argument("--shakiness", type=int); s.add_argument("--zoom", type=float)
        s.add_argument("--strength", choices=["light", "medium", "strong"]); s.add_argument("--box", help="x,y,w,h in source px")
        s.add_argument("--mode", choices=["blur", "pixelate", "delogo"]); s.add_argument("--start", type=float)
        s.add_argument("--end", type=float); s.add_argument("--yaw", type=float); s.add_argument("--pitch", type=float)
        s.add_argument("--roll", type=float); s.add_argument("--h-fov", type=float); s.add_argument("--v-fov", type=float)
        s.add_argument("--w", type=int); s.add_argument("--degrees", type=float); s.add_argument("--duration", type=float)
        s.add_argument("--factor", type=float, help="smooth: 2 = twice as long"); s.add_argument("--method", choices=["interpolate", "blend"])
        s.add_argument("--stabilize", action="store_true"); s.add_argument("--denoise", choices=["light", "medium", "strong"])
        s.add_argument("--reverse", action="store_true"); s.add_argument("--smooth", choices=["interpolate", "blend"])
        s.add_argument("--crop", help="x,y,w,h source px"); s.add_argument("--redact", action="append", help="x,y,w,h[:blur|pixelate|delogo]")
        s.add_argument("--projection", help="yaw,pitch,h_fov,v_fov"); s.add_argument("--straighten", type=float)
        s.add_argument("--clear", action="store_true")
        s.add_argument("--segment", action="append", help="ramp: from-to:speed in clip source seconds, e.g. 0-2:1")
        s.add_argument("--at", type=float); s.add_argument("--hold", type=float, default=2.0)
        s.set_defaults(fn=cmd_fx)

    s = sp.add_parser("fix", help="one-off clean-up / time FX on a file (never overwrites it)")
    s.add_argument("tool", choices=["stabilize", "denoise", "deinterlace", "to_sdr", "redact", "crop", "v360", "reverse",
                                    "straighten", "loop", "smooth"])
    s.add_argument("target", help="the file"); s.add_argument("clip", nargs="?", help=argparse_suppress())
    fx_args(s, False)
    s = sp.add_parser("clip", help="clean-up and time FX on a clip of an edit: set / ramp (speed sections) / freeze")
    s.add_argument("tool", choices=["set", "ramp", "freeze"]); s.add_argument("target", help="project")
    s.add_argument("clip", nargs="?", help="clip id (set / ramp)")
    fx_args(s, True)

    s = sp.add_parser("audio", help="sync with drift, replace with a recorder, clean, dynamics, widen, downmix, extract")
    s.add_argument("action", choices=["sync", "replace", "clean", "dynamics", "widen", "downmix", "extract"])
    s.add_argument("target"); s.add_argument("other", nargs="?"); s.add_argument("--drift", action="store_true")
    s.add_argument("--out"); s.add_argument("--overwrite", action="store_true")
    s.add_argument("--voice", choices=["light", "medium", "strong"]); s.add_argument("--denoise", action="store_true")
    s.add_argument("--gate", type=float); s.add_argument("--compress", help="threshold_db:ratio, e.g. -20:4")
    s.add_argument("--limit", type=float); s.add_argument("--amount", type=float)
    s.set_defaults(fn=cmd_audio)

    s = sp.add_parser("grid", help="videos side by side"); s.add_argument("files", nargs="+"); s.add_argument("--out", required=True)
    s.add_argument("--cols", type=int, default=2); s.add_argument("--rows", type=int); s.add_argument("--cell", default="960x540")
    s.add_argument("--audio", default="first", choices=["first", "mix"]); s.add_argument("--overwrite", action="store_true")
    s.set_defaults(fn=cmd_extras)
    for name in ("audiogram", "waveform"):
        s = sp.add_parser(name, help="sound as a video: waveform over a cover or colour, optional title")
        s.add_argument("audio_file"); s.add_argument("--out", required=True); s.add_argument("--image"); s.add_argument("--title")
        s.add_argument("--size", default="1080x1080" if name == "audiogram" else "1920x1080")
        s.add_argument("--style", default="line", choices=["line", "bars", "dots"]); s.add_argument("--overwrite", action="store_true")
        s.set_defaults(fn=cmd_extras)
    s = sp.add_parser("kenburns", help="a still with a slow zoom/drift into the edit"); s.add_argument("path"); s.add_argument("image")
    s.add_argument("--at", type=float, default=0.0); s.add_argument("--duration", type=float, default=5.0)
    s.add_argument("--zoom", default="in", choices=["in", "out"]); s.add_argument("--pan", default="none",
                   choices=["none", "left", "right", "up", "down"])
    s.add_argument("--track", default="broll", choices=["broll", "main"]); s.set_defaults(fn=cmd_extras)
    s = sp.add_parser("batch", help="a recipe of vedit commands over every file in a folder (parallel, cached)")
    s.add_argument("folder"); s.add_argument("--recipe", required=True); s.add_argument("--jobs", default="auto")
    s.add_argument("--pattern"); s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=cmd_extras)
    s = sp.add_parser("report", help="HTML summary: before/after facts, delivery check, frames")
    s.add_argument("--after", required=True); s.add_argument("--before"); s.add_argument("--platform")
    s.add_argument("--out", required=True); s.add_argument("--title"); s.add_argument("--step", action="append")
    s.set_defaults(fn=cmd_extras)
