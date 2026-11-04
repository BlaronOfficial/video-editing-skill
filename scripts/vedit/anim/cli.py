"""`vedit anim ...`: animated pieces (see references/animation.md)."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..util import VeditError, print_json

ACTIONS = ["styles", "gallery", "new", "build", "info", "still", "board", "tile", "render", "review", "voice", "beats",
           "capture", "add", "measure", "shotlog", "compare", "save-style"]


def _floats(s: str | None) -> list[float]:
    return [float(x) for x in (s or "").split(",") if x.strip()]


def _proj(path: str | None):
    from ..project import find
    if not path:
        raise VeditError("give the project path")
    return find(path)


def cmd(a) -> None:
    from . import pieces
    act = a.action
    if act == "styles":
        from . import styles
        print_json(styles())
        return
    if act == "gallery":
        from .refs import gallery
        out = a.out or str(Path.cwd() / "anim_styles.png")
        print_json(gallery(out, extra=[a.styles] if a.styles else []))
        return
    if act == "measure":
        from .refs import measure
        pts = [tuple(int(v) for v in p.split(",")) for p in (a.points or "").split(";") if p.strip()]
        print_json(measure([a.path, *(a.files or [])], top=a.top, points=pts, accent=a.accent))
        return
    if act == "shotlog":
        from .refs import shotlog
        print_json(shotlog(a.path, fps=a.fps))
        return
    p = _proj(a.path)
    if act == "new":
        print_json(pieces.new(p, a.name, style=a.style, start=a.from_,
                              formats=[f.strip() for f in a.formats.split(",")] if a.formats else None, overlay=a.overlay))
        return
    if not a.name:
        raise VeditError(f"vedit anim {act} <project> <piece>")
    if act == "build":
        from .build import build
        print_json(build(pieces.piece_dir(p, a.name)))
    elif act == "info":
        print_json(pieces.info(p, a.name, fmt=a.format))
    elif act == "still":
        print_json(pieces.stills(p, a.name, _floats(a.at) or [1.0], a.out, fmt=a.format, scale=a.scale))
    elif act == "board":
        res = pieces.board(p, a.name, a.out, fmt=a.format, panels=a.panels)
        if a.cards:
            pieces.board_cards(p, a.name, res["panels"])
            res["cards"] = len(res["panels"])
            res["next"] = "sync the Studio (vedit studio docs): one thumbs up / down card per panel"
        print_json(res)
    elif act == "tile":
        print_json(pieces.tile(p, a.name, [int(f) for f in _floats(a.frames)] or [0, 24, 48, 96], a.out, fmt=a.format))
    elif act == "render":
        print_json(pieces.render(p, a.name, fmt=a.format, blur=a.blur, force=a.force, workers=a.workers))
    elif act == "review":
        from .review import review
        print_json(review(p, a.name, fmt=a.format))
    elif act == "voice":
        from .voice import speak
        print_json(speak(p, a.name, voice=a.voice, speed=a.speed, language=a.language, scratch=a.scratch))
    elif act == "beats":
        from ..audio import beats
        from ..util import write_json
        pd = pieces.piece_dir(p, a.name)
        if not a.track:
            raise VeditError("--track <music file the owner owns or licensed>")
        src = Path(a.track)
        dst = pd / "audio" / ("track" + src.suffix.lower())
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dst.resolve():
            shutil.copy(src, dst)
        res = beats(dst, start=a.start, dur=a.dur, bpm=a.bpm)
        write_json(pd / "beats.json", res)
        m = pieces.meta(pd)
        m["music"] = {"file": f"audio/{dst.name}", "start": a.start, "gain": 0, "fade": 0.5}
        write_json(pd / "piece.json", {k: v for k, v in m.items()})
        print_json({"piece": a.name, "track": str(dst), "bpm": res.get("bpm"), "offset": res.get("offset"),
                    "beats": len(res.get("beats", [])), "bars": len(res.get("downbeats", [])), "hits": res.get("hits", [])[:12],
                    "loudest": res.get("loudest"), "quiet": res.get("quiet"), "other_tempos": res.get("other_tempos"),
                    "confidence": res.get("confidence"),
                    "next": "cut on onBeat(t); the turn on a drop (BEATS.quiet), the payoff on BEATS.loudest / hits"})
    elif act == "capture":
        from .capture import capture
        print_json(capture(p, a.name, a.url, a.out or "home.png", selector=a.selector, full=a.full, dark=a.dark,
                           hide=a.hide, width=a.width, height=a.height, scale=a.dpr, wait=a.wait))
    elif act == "add":
        print_json(pieces.add(p, a.name, as_=a.as_, at=a.at, fmt=a.format, music_db=a.music_db, sfx_db=a.sfx_db,
                              score=not a.no_score, blur=a.blur))
    elif act == "compare":
        from .refs import compare
        if not a.ref:
            raise VeditError("--ref <reference image>")
        st = pieces.stills(p, a.name, [(_floats(a.at) or [1.0])[0]], fmt=a.format, scale=1.0)
        crop = tuple(int(v) for v in a.crop.split(",")) if a.crop else None
        crop_ours = tuple(int(v) for v in a.crop_ours.split(",")) if a.crop_ours else None
        out = a.out or str(pieces.piece_dir(p, a.name) / "review" / "compare.png")
        print_json(compare(a.ref, st["image"], out, crop=crop, crop_ours=crop_ours, auto_trim=a.auto_trim))
    elif act == "save-style":
        from . import personal_styles_dir
        src = p.root / "anim" / "styles" / a.name
        if not (src / "kit.js").exists():
            raise VeditError(f"No style folder at {src} (a new look lives in edit/anim/styles/<name>/ while it is made)")
        dst = personal_styles_dir() / (a.as_name or a.name)
        if dst.exists() and not a.force:
            raise VeditError(f"{dst} exists (--force replaces it)")
        shutil.copytree(src, dst, dirs_exist_ok=True)
        print_json({"style": dst.name, "path": str(dst), "next": "every project can now use it: --style " + dst.name})


def register_cli(sp) -> None:
    s = sp.add_parser("anim", help="animated pieces: illustrated procedural animation in 7 styles (+ your own), "
                                   "timed to voices and music, placed as inserts, shorts or doodles")
    s.add_argument("action", choices=ACTIONS)
    s.add_argument("path", nargs="?", help="project (most actions); image/folder (measure); video (shotlog)")
    s.add_argument("name", nargs="?", help="piece name (style name for save-style)")
    s.add_argument("files", nargs="*", help="measure: more images")
    s.add_argument("--style", default="cut-paper")
    s.add_argument("--from", dest="from_", default="demo", choices=["demo", "piece", "beat-cut"], help="new: the starting point")
    s.add_argument("--start", type=float, default=0.0, help="beats: where in the track the piece begins (s)")
    s.add_argument("--dpr", type=float, default=2.0, help="capture: device pixel ratio")
    s.add_argument("--formats", help="new: e.g. 9:16,16:9 (the first is the main one)")
    s.add_argument("--overlay", action="store_true", help="new: transparent paper, drawn over footage")
    s.add_argument("--format", help="9:16 | 4:5 | 1:1 | 16:9"); s.add_argument("--out")
    s.add_argument("--at", help="seconds (still: comma list; add: where the insert starts)")
    s.add_argument("--scale", type=float, default=0.5); s.add_argument("--panels", action="store_true")
    s.add_argument("--cards", action="store_true", help="board: one Studio card per panel (thumbs up / down)")
    s.add_argument("--frames", help="tile: frame numbers, e.g. 0,24,48")
    s.add_argument("--blur", type=int, default=1, help="motion blur sub-frames (styles on 1s only)")
    s.add_argument("--force", action="store_true"); s.add_argument("--workers", type=int)
    s.add_argument("--voice"); s.add_argument("--speed", type=float, default=1.0); s.add_argument("--language")
    s.add_argument("--scratch", action="store_true", help="voice: an offline timing voice (never ship it)")
    s.add_argument("--track", help="beats: the music file"); s.add_argument("--dur", type=float)
    s.add_argument("--bpm"); s.add_argument("--url"); s.add_argument("--selector"); s.add_argument("--full", action="store_true")
    s.add_argument("--dark", action="store_true"); s.add_argument("--hide"); s.add_argument("--width", type=int, default=1280)
    s.add_argument("--height", type=int, default=800); s.add_argument("--wait", type=int, default=1500)
    s.add_argument("--as", dest="as_", default="insert", choices=["insert", "short", "overlay"])
    s.add_argument("--as-name", dest="as_name", help="save-style: the name in personal/anim/styles")
    s.add_argument("--music-db", type=float, help="add: score level (default -12 under speech, 0 without)")
    s.add_argument("--sfx-db", type=float, default=-6.0)
    s.add_argument("--no-score", action="store_true")
    s.add_argument("--top", type=int, default=10); s.add_argument("--points", help="measure: x,y;x,y")
    s.add_argument("--accent", action="store_true"); s.add_argument("--fps", type=float)
    s.add_argument("--ref"); s.add_argument("--crop"); s.add_argument("--crop-ours", dest="crop_ours")
    s.add_argument("--auto-trim", action="store_true")
    s.set_defaults(fn=cmd)
