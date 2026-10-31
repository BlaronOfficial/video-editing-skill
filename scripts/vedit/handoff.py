"""CLI for phase 3: hand-offs to other editors, Resolve, LosslessCut, smart cuts, cut lists and markers.

  vedit handoff make <p> --to resolve|fcp|premiere|kdenlive|shotcut|otio|edl|nle|losslesscut [--collect]
  vedit handoff diff <p> <exported file> [--learn STYLE] [--apply-cuts]
  vedit handoff read <file> | validate <file.fcpxml> [--dtd]
  vedit resolve status | import <p> [--project NAME] [--into-current] | screen-import <p>
  vedit llc write <p> | import <p> <file.llc> | open <p> | export
  vedit lossless cut <file> --keep 0-5,7.5-9 --out x.mp4 | merge a b --out | split <file> --at 60,120
                 | chapters <file> --from chapters.txt --out | selects <p> [--handles 0.5]
  vedit cutlist export <p> --format csv|chapters|llc|srt|edl|otio|xml|fcpxml | import <p> <file> [--as main|markers]
  vedit marker add <p> --t 12.4 --name "..." [--note] [--kind note|chapter|todo] | list <p> | rm <p> <id>
"""

from __future__ import annotations

from pathlib import Path

from .util import VeditError, print_json


def _proj(path: str):
    from .project import find
    return find(path)


def _ranges(spec: str) -> list[tuple[float, float]]:
    from .cutlist import parse_time
    out = []
    for part in spec.split(","):
        if not part.strip():
            continue
        a, b = part.split("-", 1) if part.count("-") == 1 else part.rsplit("-", 1)
        out.append((parse_time(a), parse_time(b)))
    return out


# ------------------------------------------------------------------ handlers

def cmd_handoff(a) -> None:
    if a.action == "make":
        p = _proj(a.path)
        if a.to == "losslesscut":
            from .llc import from_edit
            print_json({"projects": from_edit(p.edit(), p.sub("handoff") / "losslesscut", footage_dir=p.footage_dir),
                        "next": "Open the video in LosslessCut (or `vedit llc open <project>`): it loads <name>-proj.llc."})
            return
        if a.to == "capcut":
            raise VeditError("CapCut has its own builder: `vedit capcut build <project>`.")
        from .exports.package import build
        print_json(build(p, a.to, out_dir=a.out, collect=a.collect, stems=not a.no_stems, graphics=not a.no_graphics,
                         styled_captions=not a.no_styled_captions))
    elif a.action == "diff":
        from .exports.diff import run_diff
        print_json(run_diff(_proj(a.path), a.file, target=a.target, learn_style=a.learn, apply_cuts=a.apply_cuts))
    elif a.action == "read":
        from .exports.diff import read_any
        print_json(read_any(a.path))
    elif a.action == "validate":
        from .exports.otio import validate_fcpxml
        print_json(validate_fcpxml(a.path, a.dtd))


def cmd_resolve(a) -> None:
    from .resolve import live
    if a.action == "status":
        print_json(live.status())
        return
    p = _proj(a.path)
    pkg = Path(a.package) if a.package else p.root / "handoff" / "resolve"
    if not (pkg / "handoff.json").exists():
        raise VeditError(f"No Resolve package at {pkg}: run `vedit handoff make {a.path} --to resolve` first.")
    if a.action == "import":
        res = live.import_package(pkg, project=a.project, into_current=a.into_current, apply_lut=not a.no_lut)
        p.log(f"imported into Resolve Studio: {res.get('project')} / {res.get('timeline', {}).get('name')}")
        print_json(res)
    elif a.action == "screen-import":
        from .resolve.screen import import_timeline
        print_json(import_timeline(pkg, p.sub("qa") / "resolve_screen"))


def cmd_llc(a) -> None:
    from . import llc
    if a.action == "export":
        print_json(llc.export(port=a.port))
        return
    p = _proj(a.path)
    if a.action == "write":
        print_json({"projects": llc.from_edit(p.edit(), p.sub("handoff") / "losslesscut", footage_dir=p.footage_dir)})
    elif a.action == "import":
        from .cutlist import import_file
        print_json(import_file(p, a.file, source=a.source))
    elif a.action == "open":
        written = llc.from_edit(p.edit(), p.sub("handoff") / "losslesscut", footage_dir=p.footage_dir)
        files = [w["llc"] if not w["beside_media"] else w["media"] for w in written[:1]]
        print_json({"projects": written, "app": llc.open_app(files, port=a.port)})


def cmd_lossless(a) -> None:
    from . import lossless
    if a.action == "cut":
        segs = [{"path": a.target, "start": s, "end": e} for s, e in _ranges(a.keep)]
        out = a.out or str(Path(a.target).with_name(Path(a.target).stem + "_cut" + Path(a.target).suffix))
        print_json(lossless.smart_cut(segs, out, mode=a.mode, audio=a.audio))
    elif a.action == "merge":
        if not a.out:
            raise VeditError("--out is required")
        print_json(lossless.merge([a.target, *a.more], a.out))
    elif a.action == "split":
        from .cutlist import parse_time
        out_dir = a.out or str(Path(a.target).with_name(Path(a.target).stem + "_parts"))
        print_json(lossless.split(a.target, [parse_time(x) for x in a.at.split(",")], out_dir, mode=a.mode))
    elif a.action == "chapters":
        from .cutlist import parse_time
        import re
        ch = []
        for line in Path(a.chapters).read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([\d:.]+)\s+[-–]?\s*(.+)", line)
            if m:
                ch.append({"t": parse_time(m.group(1)), "title": m.group(2).strip()})
        out = a.out or str(Path(a.target).with_name(Path(a.target).stem + "_chapters" + Path(a.target).suffix))
        print_json(lossless.add_chapters(a.target, ch, out))
    elif a.action == "selects":
        p = _proj(a.target)
        e = p.edit()
        out_dir = p.sub("handoff") / "selects"
        res = []
        for i, c in enumerate(e.main, 1):
            src = e.sources[c.source]
            if src.kind != "video":
                continue
            a0, b0 = max(0.0, c.src_in - a.handles), min(src.duration, c.src_out + a.handles)
            name = f"{i:03d}_{(c.label or c.id)[:40]}".replace(" ", "_").replace("/", "_").replace(":", "")
            ext = Path(src.path).suffix if Path(src.path).suffix.lower() in (".mp4", ".mov") else ".mp4"
            r = lossless.smart_cut([{"path": src.path, "start": a0, "end": b0}], out_dir / f"{name}{ext}",
                                   mode=a.mode if lossless.params(src.path).codec in lossless.SMART_CODECS else "accurate")
            res.append({"clip": c.id, "file": r["output"], "mode": r["mode"], "copied_share": r["copied_share"]})
        print_json({"selects": res, "dir": str(out_dir)})


def cmd_cutlist(a) -> None:
    from . import cutlist
    p = _proj(a.path)
    if a.action == "export":
        print_json(cutlist.export(p, a.format, a.out))
    else:
        print_json(cutlist.import_file(p, a.file, source=a.source, as_=a.as_))


def cmd_marker(a) -> None:
    from .timeline import Anchor, Marker
    p = _proj(a.path)
    e = p.edit()
    if a.action == "list":
        print_json([m.model_dump(exclude_none=True) for m in e.markers])
        return
    if a.action == "rm":
        before = len(e.markers)
        e.markers = [m for m in e.markers if m.id != a.id]
        p.save_edit(e)
        print_json({"removed": before - len(e.markers)})
        return
    mid = a.id or f"mk{len(e.markers) + 1:03d}"
    m = Marker(id=mid, t=a.t, duration=a.duration, name=a.name or "", note=a.note or "", kind=a.kind, color=a.color)
    src = e.timeline_to_source(a.t)
    if src and not a.no_anchor:                 # follow the words through re-cuts
        m.anchor = Anchor(source=src[0], t=round(src[1], 3))
    e.markers.append(m)
    p.save_edit(e)
    print_json(m.model_dump(exclude_none=True))


# ------------------------------------------------------------------ parser

def register_cli(sp) -> None:
    from .exports.package import TARGETS
    s = sp.add_parser("handoff", help="hand-offs to other editors (Resolve, Premiere, Final Cut, Kdenlive, Shotcut, ...)")
    s.add_argument("action", choices=["make", "diff", "read", "validate"]); s.add_argument("path")
    s.add_argument("file", nargs="?", help="diff: the timeline exported from the editor")
    s.add_argument("--to", default="resolve", choices=[*TARGETS, "losslesscut", "capcut"])
    s.add_argument("--out"); s.add_argument("--collect", action="store_true", help="copy all media into the package")
    s.add_argument("--no-stems", action="store_true"); s.add_argument("--no-graphics", action="store_true")
    s.add_argument("--no-styled-captions", action="store_true", help="skip the styled caption/title alpha layers")
    s.add_argument("--target"); s.add_argument("--learn", help="fold the diff into this style"); s.add_argument("--dtd")
    s.add_argument("--apply-cuts", action="store_true", help="diff: make the editor's cut the new main track")
    s.set_defaults(fn=cmd_handoff)

    s = sp.add_parser("resolve", help="DaVinci Resolve: Studio live import, or screen import with the owner's OK")
    s.add_argument("action", choices=["status", "import", "screen-import"]); s.add_argument("path", nargs="?")
    s.add_argument("--package"); s.add_argument("--project"); s.add_argument("--into-current", action="store_true")
    s.add_argument("--no-lut", action="store_true"); s.set_defaults(fn=cmd_resolve)

    s = sp.add_parser("llc", help="LosslessCut: .llc projects and the app's HTTP API")
    s.add_argument("action", choices=["write", "import", "open", "export"]); s.add_argument("path", nargs="?")
    s.add_argument("file", nargs="?"); s.add_argument("--source"); s.add_argument("--port", type=int, default=18080)
    s.set_defaults(fn=cmd_llc)

    s = sp.add_parser("lossless", help="smart cut (re-encodes only around cuts), merge, split, chapters, selects")
    s.add_argument("action", choices=["cut", "merge", "split", "chapters", "selects"])
    s.add_argument("target", help="file (cut/merge/split/chapters) or project (selects)"); s.add_argument("more", nargs="*")
    s.add_argument("--keep", help="ranges to keep, e.g. 0-5.2,7:30-8:10"); s.add_argument("--at"); s.add_argument("--chapters")
    s.add_argument("--out"); s.add_argument("--mode", default="smart", choices=["smart", "keyframe", "accurate"])
    s.add_argument("--audio", default="aac", choices=["aac", "pcm", "none"]); s.add_argument("--handles", type=float, default=0.0)
    s.set_defaults(fn=cmd_lossless)

    s = sp.add_parser("cutlist", help="cut lists and chapters in/out (csv, chapters, llc, srt, edl, otio, xml, fcpxml)")
    s.add_argument("action", choices=["export", "import"]); s.add_argument("path"); s.add_argument("file", nargs="?")
    s.add_argument("--format", default="csv", choices=["csv", "chapters", "llc", "srt", "edl", "otio", "xml", "fcpxml",
                                                       "kdenlive", "mlt"])
    s.add_argument("--out"); s.add_argument("--source"); s.add_argument("--as", dest="as_", default="main", choices=["main", "markers"])
    s.set_defaults(fn=cmd_cutlist)

    s = sp.add_parser("marker", help="timeline notes, chapters and to-dos (travel into every hand-off)")
    s.add_argument("action", choices=["add", "list", "rm"]); s.add_argument("path"); s.add_argument("id", nargs="?")
    s.add_argument("--t", type=float, default=0.0); s.add_argument("--duration", type=float, default=0.0)
    s.add_argument("--name"); s.add_argument("--note"); s.add_argument("--kind", default="note", choices=["note", "chapter", "todo"])
    s.add_argument("--color", default="blue"); s.add_argument("--no-anchor", action="store_true")
    s.set_defaults(fn=cmd_marker)
