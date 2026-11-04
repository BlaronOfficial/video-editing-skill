"""Animated pieces in a project: start one, build it, look at it (stills, storyboard, determinism tiles), render it
with its score, and place it in the edit (an insert over footage, a whole short, or doodles over footage).

Every look at a piece goes through vedit's own renderer (mg/renderer/render.mjs): the same page, the same frames
as the final render, on the GPU when Chrome can reach it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..paths import mg_dir
from ..util import VeditError, read_json, run, short_hash, write_json
from . import ANIM, FORMATS, FPS, format_for, style_dir
from .build import STUDIO_LIVE_MAX, build

PIECE_JSON_DEFAULTS = {"loop": False, "overlay": False}


def anim_root(proj) -> Path:
    return proj.sub("anim")


def piece_dir(proj, name: str) -> Path:
    d = proj.root / "anim" / name
    if not (d / "piece.json").exists():
        raise VeditError(f"No animated piece '{name}' in {proj.root / 'anim'} (start one with `vedit anim new`).")
    return d


def meta(pd: Path) -> dict:
    return {**PIECE_JSON_DEFAULTS, **(read_json(pd / "piece.json", default={}) or {})}


def has_speech(edit) -> bool:
    """Does the edit carry speech (a VO, or footage with its own sound)? Music then sits under it."""
    return any(a.role == "vo" and a.enabled for a in edit.audio) or any(
        (edit.sources[c.source].transcript or (edit.sources[c.source].has_audio and edit.sources[c.source].kind == "video")
         or edit.sources[c.source].origin == "vo") and not c.mute
        for c in edit.main if c.source in edit.sources)


def main_format(pd: Path) -> str:
    fm = meta(pd).get("formats") or ["9:16"]
    return fm[0] if fm[0] in FORMATS else "9:16"


# ------------------------------------------------------------------ start a piece

def new(proj, name: str, *, style: str = "cut-paper", start: str = "demo", formats: list[str] | None = None,
        overlay: bool = False) -> dict:
    """Copy a starting point into edit/anim/<name>/: the style's demo (speaks its kit, morphs once), the
    multi-format starter (`piece`), or the hard-cut starter (`beat-cut`). Overlay pieces start from `piece`."""
    d = anim_root(proj) / name
    if d.exists() and any(d.iterdir()):
        raise VeditError(f"Piece '{name}' already exists: {d}")
    style_dir(style)                                         # unknown style -> a clear error
    if overlay and start == "demo":
        start = "piece"
    src = (style_dir(style) / "demo") if start == "demo" else ANIM / "templates" / start
    if not (src / "piece.json").exists():
        raise VeditError(f"No starting point '{start}' for style '{style}' ({src})")
    shutil.copytree(src, d, dirs_exist_ok=True, ignore=shutil.ignore_patterns("index.html", "renders", "review", "frames*"))
    m = read_json(d / "piece.json", default={}) or {}
    fm = [f for f in (formats or m.get("formats") or ["9:16"]) if f in FORMATS] or ["9:16"]
    head = (d / "src" / "head.html").read_text(encoding="utf-8") if (d / "src" / "head.html").exists() else ""
    if len(fm) > 1 and "const FORMATS" not in head:
        fm = fm[:1]                                          # a fixed-size demo head lays out one format only
    m.update({"name": name, "style": style, "formats": fm, "overlay": bool(overlay), "loop": False})
    write_json(d / "piece.json", m)
    for f in ("brief.md", "LOG.md"):                         # placeholders to fill (the template's are generic)
        if not (d / f).exists() and (ANIM / "templates" / "piece" / f).exists():
            shutil.copy(ANIM / "templates" / "piece" / f, d / f)
    if overlay:
        _overlay_starter(d)
    proj.log(f"anim: new piece {name} ({style}, from {start}{', overlay' if overlay else ''})")
    return {"piece": name, "dir": str(d), "style": style, "start": start, "formats": fm, "overlay": overlay,
            "next": "edit src/ (head: TIMELINE, eras, cues; scenes; bridges; score), then `vedit anim still` for the look check"}


def _overlay_starter(d: Path) -> None:
    """Overlay pieces draw no backdrop and use no bridges: leave the starter's scenes, empty its bridges."""
    b = d / "src" / "bridges.js"
    if b.exists():
        b.write_text("// overlay piece: no shape-morph bridges (the footage is the background)\nconst BRIDGES = [];\n",
                     encoding="utf-8")


# ------------------------------------------------------------------ the renderer

def _renderer(args: list[str], *, timeout: int = 7200) -> dict:
    from ..mg import _node, chrome
    if chrome() is None:
        raise VeditError("Animated pieces need Chrome or Edge (headless). Install one, or set VEDIT_CHROME.")
    proc = run([_node(), str(mg_dir() / "renderer" / "render.mjs"), *[str(a) for a in args]], check=False, timeout=timeout)
    lines = [l for l in (proc.stdout or "").splitlines() if l.startswith("{")]
    errs = [l for l in (proc.stderr or "").splitlines() if l.strip()]
    if proc.returncode != 0 or not lines:
        raise VeditError("Animation render failed:\n" + "\n".join([l for l in errs if "[missing]" not in l][-25:]))
    res = json.loads(lines[-1])
    page = [l for l in errs if l.startswith(("[page", "[gpu]", "[missing]"))]
    if page:
        res["page_log"] = page[-20:]
    return res


def _data(pd: Path, fmt: str, blur: int = 1) -> Path:
    f = pd / "renders" / f".data_{fmt.replace(':', 'x')}_{blur}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    write_json(f, {"format": fmt, "fps": FPS, "blur": int(blur)})
    return f


def _page(pd: Path, fmt: str | None, blur: int = 1) -> tuple[list[str], str]:
    fmt = fmt or main_format(pd)
    if fmt not in FORMATS:
        raise VeditError(f"Unknown format {fmt}: {', '.join(FORMATS)}")
    W, H = FORMATS[fmt]
    return ["--input", str(pd / "index.html"), "--width", str(W), "--height", str(H), "--fps", str(FPS),
            "--data", str(_data(pd, fmt, blur))], fmt


def info(proj, name: str, *, fmt: str | None = None, rebuild: bool = True) -> dict:
    pd = piece_dir(proj, name)
    b = build(pd) if rebuild or not (pd / "index.html").exists() else {}
    args, fmt = _page(pd, fmt)
    res = _renderer([*args, "--info"], timeout=600)
    return {"piece": name, "format": fmt, "duration": res.get("duration"), "width": res["width"], "height": res["height"],
            "gpu": res.get("gpu"), "timeline": res.get("timeline"), "build": b, "page_log": res.get("page_log")}


# ------------------------------------------------------------------ looking at it

def _strip(pngs: list[Path], labels: list[str], out: Path, *, scale: float = 0.5, gap: int = 16) -> Path:
    from PIL import Image, ImageDraw
    ims = [Image.open(p).convert("RGB") for p in pngs]
    ims = [im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS) for im in ims]
    out.parent.mkdir(parents=True, exist_ok=True)
    if len(ims) == 1:  # one frame: the frame itself (a style's sample.jpg), no sheet around it
        sheet = ims[0]
    else:
        w = sum(im.width for im in ims) + gap * (len(ims) + 1)
        h = max(im.height for im in ims) + 2 * gap + 34
        sheet = Image.new("RGB", (w, h), (34, 30, 27))
        d = ImageDraw.Draw(sheet)
        x = gap
        for im, lab in zip(ims, labels):
            sheet.paste(im, (x, gap))
            d.text((x, gap + im.height + 8), lab, fill=(232, 222, 200))
            x += im.width + gap
    sheet.save(out, **({"quality": 88} if out.suffix.lower() in (".jpg", ".jpeg") else {}))
    return out


def stills(proj, name: str, times: list[float], out: str | Path | None = None, *, fmt: str | None = None,
           scale: float = 0.5) -> dict:
    """Full frames at `times`, side by side (the look check; any frames you want to see)."""
    pd = piece_dir(proj, name)
    build(pd)
    args, fmt = _page(pd, fmt)
    tmp = pd / "review" / "_stills"
    shutil.rmtree(tmp, ignore_errors=True)
    res = _renderer([*args, "--stills", ",".join(f"{t:.3f}" for t in times), "--still-dir", str(tmp)], timeout=900)
    out = Path(out) if out else pd / "review" / f"look_{fmt.replace(':', 'x')}.png"
    _strip([Path(p) for p in res["stills"]], [f"{t:.2f}s" for t in times], out, scale=scale)
    shutil.rmtree(tmp, ignore_errors=True)
    return {"piece": name, "image": str(out), "times": times, "format": fmt, "gpu": res.get("gpu"),
            "page_log": res.get("page_log")}


def board(proj, name: str, out: str | Path | None = None, *, fmt: str | None = None, panels: bool = False) -> dict:
    """The storyboard: every beat in TIMELINE.board drawn by the piece itself, with its notes. `panels` also writes
    one image per panel (for the Studio's thumbs up / down cards)."""
    pd = piece_dir(proj, name)
    build(pd)
    args, fmt = _page(pd, fmt)
    out = Path(out) if out else pd / "review" / "storyboard.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    extra: list[str] = []
    inf = _renderer([*args, "--info"], timeout=600)
    beats = (inf.get("timeline") or {}).get("board") or []
    if not beats:
        raise VeditError("TIMELINE.board is empty: add one { t, title, sound, next } per beat in the head")
    pdir = pd / "review" / "panels"
    if panels:
        shutil.rmtree(pdir, ignore_errors=True)
        extra = ["--stills", ",".join(f"{b['t']:.3f}" for b in beats), "--still-dir", str(pdir)]
    res = _renderer([*args, "--board", str(out), *extra], timeout=900)
    rows = [{"n": i + 1, "t": b["t"], "title": b.get("title", ""), "sound": b.get("sound", ""), "next": b.get("next", ""),
             **({"image": res["stills"][i]} if panels and i < len(res.get("stills", [])) else {})}
            for i, b in enumerate(beats)]
    return {"piece": name, "image": str(out), "panels": rows, "format": fmt}


def board_cards(proj, name: str, rows: list[dict]) -> dict:
    """One Studio card per storyboard panel: thumbs up / down, jumping the live piece to that panel's frame (when
    the piece is in the edit). The owner's answers come back as decisions (`vedit suggest list`)."""
    from ..suggest import add_suggestions
    edit = proj.edit()
    ov = next((o for o in edit.overlays if o.id == f"anim_{name}"), None)
    base = ov.start if ov else None
    items = []
    for r in rows:
        at = {"start": round(base + r["t"], 3), "end": round(base + r["t"] + 0.5, 3)} if base is not None else None
        items.append({"id": f"board_{name}_{r['n']}", "kind": "graphic", "title": f"Panel {r['n']}: {r['title']}",
                      "reason": "; ".join(x for x in (f"sound: {r['sound']}" if r.get("sound") else "",
                                                      f"next: {r['next']}" if r.get("next") else "") if x),
                      "at": at, "options": [{"id": "up", "label": "Thumbs up", "ops": []},
                                            {"id": "down", "label": "Thumbs down: redraw", "ops": []}],
                      "default": "up"})
    return add_suggestions(proj, items)


def tile(proj, name: str, frames: list[int], out: str | Path | None = None, *, fmt: str | None = None) -> dict:
    """Test tiles: those frames side by side, plus a determinism check (each frame rendered twice must match)."""
    pd = piece_dir(proj, name)
    build(pd)
    args, fmt = _page(pd, fmt)
    tmp = pd / "review" / "_tile"
    shutil.rmtree(tmp, ignore_errors=True)
    res = _renderer([*args, "--hash-frames", ",".join(str(int(f)) for f in frames),
                     "--stills", ",".join(f"{f / FPS:.4f}" for f in frames), "--still-dir", str(tmp)], timeout=900)
    out = Path(out) if out else pd / "review" / "tile.png"
    _strip([Path(p) for p in res["stills"]], [f"f{f} ({f / FPS:.2f}s)" for f in frames], out, scale=0.25)
    shutil.rmtree(tmp, ignore_errors=True)
    return {"piece": name, "image": str(out), "deterministic": res.get("deterministic"),
            "nondeterministic_frames": res.get("nondeterministic_frames", []), "gpu": res.get("gpu"),
            "page_log": res.get("page_log")}


# ------------------------------------------------------------------ rendering

def render(proj, name: str, *, fmt: str | None = None, blur: int = 1, force: bool = False, workers: int | None = None) -> dict:
    """Render the piece's picture (MP4, or alpha WebM for an overlay piece) and its score (mix, music, sfx stems),
    plus renders/share.mp4: picture + score (+ the voice-over, ducked) at -14 LUFS, for listening."""
    pd = piece_dir(proj, name)
    m = meta(pd)
    b = build(pd)
    args, fmt = _page(pd, fmt, blur)
    W, H = FORMATS[fmt]
    rd = pd / "renders"
    stem = rd / ("final" if fmt == main_format(pd) else f"final-{W}x{H}")
    key = short_hash((pd / "index.html").read_text(encoding="utf-8"), fmt, blur)
    cache = Path(str(stem) + ".json")
    kind = "webm" if m.get("overlay") else "mp4"
    video = Path(f"{stem}.{kind}")
    old = read_json(cache, default={}) or {}
    if not force and old.get("key") == key and video.exists():
        return {**old["result"], "cached": True}
    extra = ["--workers", str(workers)] if workers else []
    res = _renderer([*args, "--out", f"{stem}.mov", "--formats", kind, "--audio", str(rd / "score"), *extra])
    out = {"piece": name, "format": fmt, "video": str(video), "audio": res.get("audio", {}),
           "duration": res.get("duration"), "frames": res.get("frames"), "fps": FPS, "width": W, "height": H,
           "seconds": res.get("seconds"), "gpu": res.get("gpu"), "build": b, "page_log": res.get("page_log"),
           "timeline": res.get("timeline")}
    share = _share(pd, out)
    if share:
        out["share"] = str(share)
    write_json(cache, {"key": key, "result": out})
    return out


def music_track(pd: Path) -> tuple[Path, float, float] | None:
    """The owner's own track for this piece (`vedit anim beats`): (file, start in the song, gain dB)."""
    mu = meta(pd).get("music") or {}
    f = pd / mu["file"] if mu.get("file") else None
    return (f, float(mu.get("start", 0)), float(mu.get("gain", 0))) if f and f.exists() else None


def _share(pd: Path, r: dict) -> Path | None:
    """Picture + sound for the owner to watch and listen, at -14 LUFS: the score (or the owner's track with the
    score's sound effects on top), ducked under the voice-over when there is one."""
    from ..media import ffmpeg
    audio = r.get("audio") or {}
    if not audio.get("mix") or r["video"].endswith(".webm"):
        return None
    m = meta(pd)
    voice = pd / ((m.get("voice") or {}).get("file") or "voice/voice.wav")
    track = music_track(pd)
    dur = float(r.get("duration") or 0)
    out = Path(r["video"]).with_name(Path(r["video"]).stem + "_share.mp4")
    cmd = [ffmpeg(), "-y", "-v", "error", "-i", r["video"]]
    if track and audio.get("sfx"):
        f, start, gain = track
        cmd += ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(f), "-i", audio["sfx"]]
        bed = (f"[1:a]aresample=48000,volume={gain}dB,afade=t=out:st={max(0, dur - 0.5):.3f}:d=0.5[tr];"
               "[tr][2:a]amix=inputs=2:normalize=0:duration=first[bed]")
        nxt = 3
    else:
        cmd += ["-i", audio["mix"]]
        bed = "[1:a]anull[bed]"
        nxt = 2
    if voice.exists():
        db = float((m.get("voice") or {}).get("music", -12))
        cmd += ["-i", str(voice), "-filter_complex",
                f"{bed};[bed]volume={db}dB[s];[{nxt}:a]aresample=48000,asplit[v1][v2];"
                "[s][v1]sidechaincompress=threshold=0.04:ratio=6:attack=20:release=350[d];"
                "[d][v2]amix=inputs=2:normalize=0:duration=longest,loudnorm=I=-14:TP=-1.5:LRA=11[a]"]
    else:
        cmd += ["-filter_complex", f"{bed};[bed]loudnorm=I=-14:TP=-1.5:LRA=11[a]"]
    cmd += ["-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", str(out)]
    run(cmd, timeout=1800)
    return out


# ------------------------------------------------------------------ into the edit

def add(proj, name: str, *, as_: str = "insert", at: float = 0.0, fmt: str | None = None, music_db: float | None = None,
        sfx_db: float = -6.0, score: bool = True, blur: int = 1, layer: int = 5) -> dict:
    """Place a piece in the edit.

    insert   the piece full-frame over the footage from `at` (the speaker keeps talking; the score ducks)
    short    the whole video: over the main track (e.g. a VO from `vedit voice vo --place main`), or as the main
             track itself when the edit is empty
    overlay  a transparent piece (piece.json "overlay": true): doodles, arrows, notes over the footage
    The piece stays live in the Studio (its page) and its render is cached where the engine looks for it.
    """
    from ..assets import add_provenance
    from ..media import probe
    from ..mg import overlay_target
    from ..timeline import AudioClip, Clip, MGSpec, Overlay, Source
    if as_ not in ("insert", "short", "overlay"):
        raise VeditError("--as must be insert, short or overlay")
    pd = piece_dir(proj, name)
    m = meta(pd)
    if as_ == "overlay" and not m.get("overlay"):
        raise VeditError(f"'{name}' is not an overlay piece (start one with `vedit anim new ... --overlay`)")
    if as_ != "overlay" and m.get("overlay"):
        as_ = "overlay"
    edit = proj.edit()
    fmt = fmt or format_for(edit.canvas.width, edit.canvas.height)
    if fmt not in (m.get("formats") or ["9:16"]) and fmt != main_format(pd):
        head = (pd / "src" / "head.html").read_text(encoding="utf-8")
        if "const FORMATS" not in head:
            raise VeditError(f"'{name}' is laid out for {main_format(pd)} only; the edit is {fmt}. Start the piece "
                             "from the multi-format `piece` template, or render it as is with --format.")
    build(pd)
    inf = info(proj, name, fmt=fmt, rebuild=False)
    dur = float(inf["duration"] or 0)
    if dur <= 0:
        raise VeditError("The piece has no duration (TIMELINE.duration)")
    oid, style = f"anim_{name}", m.get("style", "")
    edit.overlays = [o for o in edit.overlays if o.id != oid]
    edit.audio = [a for a in edit.audio if not a.id.startswith(f"{oid}_")]
    rel = (pd / "index.html").relative_to(proj.root).as_posix()
    spec = MGSpec(engine="html", file=rel, data={"format": fmt, "fps": FPS, "blur": int(blur)}, alpha=bool(m.get("overlay")))
    start = 0.0 if as_ == "short" else float(at)
    ov = Overlay(id=oid, start=start, duration=round(dur, 3), mg=spec, fit="none" if as_ == "overlay" else "cover",
                 layer=layer, label=f"anim: {name} ({style})")
    notes = f"animated piece '{name}' ({style}); drawn in code by vedit (animate kit, MIT)"

    # render where the engine's overlay pass looks for it (so the final render reuses it), with the score
    from .. import config
    mg_out = proj.sub("mg")
    stem, formats, W, H, fps = overlay_target(edit, ov, mg_out, capcut_alpha=config.load()["capcut"]["alpha_overlays"])
    data_file = Path(f"{stem}.data.json")
    write_json(data_file, {**spec.data, "duration": ov.duration})
    outs = [Path(str(stem) + suf) for suf in {"prores": ".mov", "webm": ".webm", "key": "_key.mp4", "mp4": ".mp4"}.values()]
    have = [p for p in outs if p.exists()]
    audio_dir = pd / "renders"
    res = {}
    if not have or not (audio_dir / "score_mix.wav").exists():
        res = _renderer(["--input", str(pd / "index.html"), "--out", f"{stem}.mov", "--formats", ",".join(formats),
                         "--width", str(W), "--height", str(H), "--fps", str(fps), "--duration", f"{ov.duration:.3f}",
                         "--data", str(data_file), "--audio", str(audio_dir / "score")])
        have = [Path(p) for p in res.get("outputs", [])]
    by_ext = {p.name[len(stem.name):]: p for p in have}
    ov.path = str(by_ext.get(".webm") or by_ext.get(".mp4") or by_ext.get(".mov") or have[0])
    ov.renders = {k: str(v) for k, v in by_ext.items()}
    for p in have:
        add_provenance(proj.root, p, source=f"anim:{style}", license="own (generated by vedit)", notes=notes)

    if as_ == "short" and not edit.main:
        # an empty edit: the piece is the picture (its rendered frames are the main track)
        sid = f"{oid}_video"
        mp4 = by_ext.get(".mp4") or Path(ov.path)
        pi = probe(mp4)
        edit.sources[sid] = Source(id=sid, path=str(mp4.resolve()), kind="video", duration=round(pi.duration, 3),
                                   width=pi.display_size[0], height=pi.display_size[1], fps=round(pi.fps, 3),
                                   has_audio=False, origin=f"anim:{style}", notes=[notes])
        edit.main = [Clip(id=f"{oid}_clip", source=sid, src_in=0.0, src_out=round(pi.duration, 3), mute=True,
                          label=f"anim: {name}")]
    else:
        edit.overlays.append(ov)

    added_audio = []
    # music sits under speech (-12 dB, ducked further) and is the soundtrack when nothing is said (0 dB)
    voice_file = pd / ((m.get("voice") or {}).get("file") or "voice/voice.wav")
    speech = voice_file.exists() or has_speech(edit)
    music_db = music_db if music_db is not None else (-12.0 if speech else 0.0)
    track = music_track(pd)
    if track:   # the owner's own track is the music (the score keeps only its sound effects)
        f, tstart, gain = track
        sid = f"{oid}_track"
        pa = probe(f)
        edit.sources[sid] = Source(id=sid, path=str(f.resolve()), kind="audio", duration=round(pa.duration, 3),
                                   has_audio=True, origin="library", notes=[f"music track of animated piece '{name}'"])
        edit.audio.append(AudioClip(id=sid, source=sid, start=start, src_in=round(tstart, 3),
                                    src_out=round(min(pa.duration, tstart + dur), 3),
                                    volume=round(10 ** ((music_db + gain) / 20), 4), role="music", duck=True,
                                    fade_out=0.5, sync="beats", label=f"anim music: {name}"))
        added_audio.append(sid)
    if score:
        for stem_name, role, db in (("music", "music", music_db), ("sfx", "sfx", sfx_db)):
            if track and stem_name == "music":
                continue
            f = audio_dir / f"score_{stem_name}.wav"
            if not f.exists():
                continue
            pa = probe(f)
            if pa.duration <= 0.05:
                continue
            sid = f"{oid}_{stem_name}"
            edit.sources[sid] = Source(id=sid, path=str(f.resolve()), kind="audio", duration=round(pa.duration, 3),
                                       has_audio=True, origin=f"anim:{style}", notes=[notes + f" (score {stem_name})"])
            edit.audio.append(AudioClip(id=sid, source=sid, start=start, volume=round(10 ** (db / 20), 4), role=role,
                                        duck=True if role == "music" else None, fade_out=0.3,
                                        label=f"anim score: {name} ({stem_name})"))
            add_provenance(proj.root, f, source=f"anim:{style}", license="own (generated by vedit)", notes=notes)
            added_audio.append(sid)
    # the piece's voice-over goes in as a VO clip unless the edit already speaks it (a short built on its VO)
    voice = pd / ((m.get("voice") or {}).get("file") or "voice/voice.wav")
    vo_id = None
    if voice.exists() and not any(a.role == "vo" for a in edit.audio) and not (
            edit.main and any(edit.sources[c.source].origin == "vo" for c in edit.main if c.source in edit.sources)):
        tr = voice.with_suffix(".transcript.json")
        vo_id = f"{oid}_vo"
        pv = probe(voice)
        edit.sources[vo_id] = Source(id=vo_id, path=str(voice.resolve()), kind="audio", duration=round(pv.duration, 3),
                                     has_audio=True, origin="vo", transcript=str(tr.resolve()) if tr.exists() else None,
                                     notes=[f"voice-over of animated piece '{name}'"])
        edit.audio.append(AudioClip(id=vo_id, source=vo_id, start=start, role="vo", label=f"anim VO: {name}"))
    proj.save_edit(edit.layout())
    proj.log(f"anim: added {name} as {as_} at {start:.2f}s ({dur:.2f}s, {fmt})")
    return {"piece": name, "as": as_, "overlay": oid, "start": start, "duration": round(dur, 3), "format": fmt,
            "video": ov.path, "audio": added_audio, "vo": vo_id, "rendered": bool(res),
            "studio": "live" if (pd / "index.html").stat().st_size <= STUDIO_LIVE_MAX else "rendered proxy"}
