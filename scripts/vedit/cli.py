"""vedit command line. Every command prints JSON (or a short message) so Claude can chain steps reliably."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .util import VeditError, print_json, read_json


def _proj(path: str):
    from .project import find
    return find(path)


def _floats(s: str) -> list[float]:
    return [float(x) for x in s.split(",") if x.strip()]


# ------------------------------------------------------------------ handlers

def cmd_doctor(a):
    from .doctor import check
    res = check()
    if a.json:
        print_json(res)
        return
    for i in res["items"]:
        mark = "OK " if i["ok"] else ("!! " if i["required"] else "-- ")
        print(f"{mark}{i['item']}: {i['detail']}" + (f"\n     fix: {i['fix']}" if i["fix"] else ""))
    print("\nREADY" if res["ready"] else "\nNOT READY: fix the !! items above")


def cmd_setup(a):
    from . import setup
    out = {}
    what = a.what
    if what in ("all", "fonts"):
        out["fonts"] = setup.download_fonts(force=a.force)
    if what in ("all", "renderer"):
        out["renderer"] = setup.install_renderer()
    if what in ("whisper",) or (what == "all" and a.whisper):
        from . import config
        out["whisper"] = setup.prefetch_whisper(a.model or config.load()["transcription"]["whisper_model"])
    if what == "install-fonts":
        out["installed"] = setup.install_fonts_for_user()
    print_json(out)


def cmd_update(a):
    from .update import update
    print_json(update(check_only=a.check))


def cmd_config(a):
    from . import config
    if a.action == "path":
        print(config.config_path())
    elif a.action == "get":
        cfg = config.load()
        if a.key:
            for part in a.key.split("."):
                cfg = cfg[part]
        print_json(cfg)
    elif a.action == "set":
        try:
            value = json.loads(a.value)
        except json.JSONDecodeError:
            value = a.value
        print_json(config.set_value(a.key, value))


def cmd_secret(a):
    from . import config
    config.set_secret(a.name, a.value)
    print(f"saved {a.name} to personal/secrets.json (git-ignored)")


def cmd_project(a):
    from . import project
    if a.action == "init":
        p = project.init(a.path, name=a.name, ratio=a.ratio, recursive=a.recursive, force=a.force)
        e = p.edit()
        print_json({"project": str(p.root), "canvas": e.canvas.model_dump(), "sources": {k: {"kind": s.kind, "duration": s.duration,
                    "size": f"{s.width}x{s.height}"} for k, s in e.sources.items()}})
    elif a.action == "info":
        p = _proj(a.path)
        e = p.edit()
        print_json({"project": str(p.root), "meta": p.meta(), "duration": round(e.duration, 2), "main_clips": len(e.main),
                    "overlays": len(e.overlays), "sources": list(e.sources)})
    elif a.action == "log":
        p = _proj(a.path)
        p.log(a.note)
        print("logged")
    elif a.action == "add-source":
        p = _proj(a.path)
        print_json({"source_id": project.add_source(p, a.file, origin=a.origin)})


def cmd_probe(a):
    from .media import probe
    print_json([probe(f).to_dict() for f in a.files])


def cmd_transcribe(a):
    from .transcribe import transcribe_file
    p = _proj(a.path)
    e = p.edit()
    done = {}
    for sid, src in e.sources.items():
        if a.source and sid not in a.source:
            continue
        if src.kind not in ("video", "audio") or not src.has_audio:
            continue
        if not a.source and src.origin not in (None, "camera", "vo"):
            continue
        out = p.sub("transcripts") / f"{sid}.json"
        t0 = time.time()
        res = transcribe_file(src.path, out, engine=a.engine, language=a.language, model=a.model, force=a.force)
        src.transcript = str(out)
        done[sid] = {"words": len(res.get("words", [])), "language": res.get("language"), "engine": res.get("engine"),
                     "seconds": round(time.time() - t0, 1)}
    p.save_edit(e)
    p.log(f"transcribed with {a.engine}" + (f" ({a.language})" if a.language else ""))
    print_json(done)


def cmd_pack(a):
    from .pack import pack_project
    p = _proj(a.path)
    e = p.edit()
    ts = {sid: Path(s.transcript) for sid, s in e.sources.items() if s.transcript}
    if not ts:
        raise VeditError("No transcripts yet. Run `vedit transcribe` first.")
    out = pack_project(ts, p.root / "takes_packed.md", p.root / "takes_index.json", title=e.name)
    print_json({"packed": str(out), "index": str(p.root / "takes_index.json"), "chars": len(out.read_text(encoding="utf-8"))})


def cmd_words(a):
    """Kept words with their TIMELINE times (after cuts) - use these to place graphics, SFX and b-roll."""
    from .captions import transcript_words
    e = _proj(a.path).edit()
    rows = []
    for clip in e.main:
        src = e.sources[clip.source]
        if not src.transcript:
            continue
        for w in transcript_words(src.transcript):
            mid = (w["s"] + w["e"]) / 2
            if clip.src_in <= mid <= clip.src_out:
                t = (clip.start or 0) + (w["s"] - clip.src_in) / clip.speed
                rows.append({"t": round(max(t, clip.start or 0), 2), "w": w["w"], "clip": clip.id})
    if a.find:
        needle = a.find.lower().split()
        hits = []
        for i in range(len(rows)):
            window = [r["w"].lower().strip(".,!?") for r in rows[i:i + len(needle)]]
            if window == needle:
                hits.append(rows[i])
        rows = hits
    if a.start is not None or a.end is not None:
        rows = [r for r in rows if (a.start is None or r["t"] >= a.start) and (a.end is None or r["t"] <= a.end)]
    print_json(rows)


def cmd_view(a):
    from .view import timeline_view
    out = timeline_view(a.file, a.start, a.end, a.out or Path(a.file).with_suffix(f".view_{a.start:.0f}.png"),
                        transcript=a.transcript, frames=a.frames)
    print(out)


def cmd_frames(a):
    from .view import frames_at
    print(frames_at(a.file, _floats(a.at), a.out, width=a.width))


def cmd_silences(a):
    from .media import detect_silences
    print_json([{"start": round(s, 2), "end": round(e, 2)} for s, e in detect_silences(a.file, noise_db=a.noise, min_dur=a.min)])


def cmd_plan(a):
    from . import cuts
    from .timeline import json_schema
    if a.action == "schema":
        print_json(json_schema())
        return
    p = _proj(a.path)
    e = p.edit()
    if a.action == "auto":
        keeps = []
        for sid, src in e.sources.items():
            if src.transcript and (not a.source or sid in a.source):
                keeps += cuts.auto_keeps(sid, src.transcript, max_pause=a.max_pause)
        out = p.root / "keeps_auto.json"
        out.write_text(json.dumps(keeps, indent=2, ensure_ascii=False), encoding="utf-8")
        print_json({"keeps": str(out), "segments": len(keeps)})
    elif a.action == "apply":
        keeps = read_json(a.keeps)
        e = cuts.apply_keeps(e, keeps, index_path=str(p.root / "takes_index.json"), replace=not a.append)
        p.save_edit(e)
        print_json({"main_clips": len(e.main), "duration": round(e.duration, 2), "cut": cuts.removed_summary(e)})
    elif a.action == "validate":
        print_json({"ok": True, "duration": round(e.duration, 2), "main": len(e.main), "broll": len(e.broll),
                    "overlays": len(e.overlays), "audio": len(e.audio)})


def cmd_captions(a):
    from . import captions as caps
    if a.action == "styles":
        print_json({k: v.get("description", "") for k, v in caps.list_presets().items()})
        return
    p = _proj(a.path)
    e = p.edit()
    if a.action == "build":
        if a.style:
            e.captions.style = a.style
        if a.max_words:
            e.captions.max_words = a.max_words
        e.captions.chunks = []
        e.captions.chunks = caps.build_chunks(e)
        p.save_edit(e)
        print_json({"chunks": len(e.captions.chunks), "style": e.captions.style,
                    "sample": [c.text for c in e.captions.chunks[:8]]})
    elif a.action == "export":
        chunks = e.captions.chunks or caps.build_chunks(e)
        out = p.sub("render") / f"captions.{a.format}"
        {"srt": caps.to_srt, "vtt": caps.to_vtt}.get(a.format, lambda c, o: caps.to_ass(e, c, o))(chunks, out)
        print(out)


def cmd_storyboard(a):
    from .storyboard import build
    p = _proj(a.path)
    out = build(p.edit(), p.sub("storyboard"), title=a.title)
    if a.open:
        import webbrowser
        webbrowser.open(out.as_uri())
    print(out)


def cmd_mg(a):
    from . import config, mg
    if a.action == "templates":
        print_json(mg.templates())
        return
    if a.action == "file":
        outs = mg.render_html(Path(a.comp), Path(a.out).with_suffix(""), width=a.width, height=a.height, fps=a.fps,
                              duration=a.duration, data=read_json(a.data, default={}) if a.data else {},
                              formats=a.formats.split(","))
        print_json([str(o) for o in outs])
        return
    if a.action == "still":
        print(mg.still(Path(a.comp), Path(a.out), width=a.width, height=a.height, t=a.t,
                       data=read_json(a.data, default={}) if a.data else {}))
        return
    if a.action == "sheet":
        print(mg.contact_sheet(a.comp, a.out))
        return
    p = _proj(a.path)
    e = p.edit()
    alpha = config.load()["capcut"]["alpha_overlays"]
    done = mg.render_all(e, p.sub("mg"), capcut_alpha=alpha, only=a.id, force=a.force)
    p.save_edit(e)
    print_json({"rendered": done, "overlays": {o.id: o.path for o in e.overlays}})


def cmd_render(a):
    from .render import render
    p = _proj(a.path)
    e = p.edit()
    missing = [o.id for o in e.overlays if o.mg and (not o.path or not Path(o.path).exists())]
    if missing:
        raise VeditError(f"Overlays not rendered yet: {missing}. Run `vedit mg render {a.path}` first.")
    out = Path(a.out) if a.out else p.sub("render") / ("preview.mp4" if a.preview else f"{e.name}.mp4")
    t0 = time.time()
    res = render(e, out, preview=a.preview, work_dir=p.sub("render") / "work", burn_captions=not a.no_captions)
    res["seconds"] = round(time.time() - t0, 1)
    p.log(f"rendered {'preview' if a.preview else 'final'} -> {out.name}")
    print_json(res)


def cmd_qa(a):
    from . import config
    from .qa import check
    p = _proj(a.path)
    e = p.edit()
    render_path = a.render or str(p.root / "render" / f"{e.name}.mp4")
    target = e.output.audio.target_lufs or config.load()["render"]["target_lufs"]
    print_json(check(e, render_path, p.sub("qa"), target_lufs=target))


def _pro_allowed(a, e) -> bool:
    from . import config
    if a.pro in ("yes", "no"):
        return a.pro == "yes"
    if e.capcut.pro_allowed is not None:
        return e.capcut.pro_allowed
    setting = config.load()["capcut"]["pro"]
    if setting in ("yes", "no"):
        return setting == "yes"
    raise VeditError("Ask the user whether this project may use CapCut Pro resources, then pass --pro yes|no "
                     "(or set capcut.pro_allowed in edit.json).")


def cmd_capcut(a):
    from . import config
    from .capcut import store
    if a.action == "calibrate":
        print_json(store.calibrate(a.project))
    elif a.action == "list":
        print_json([p.to_dict() for p in store.list_projects()])
    elif a.action == "close":
        print_json({"closed": store.close_app(force=a.force)})
    elif a.action == "launch":
        store.launch_app()
        print("CapCut launching")
    elif a.action == "resources":
        from .capcut import resources
        pro = config.load()["capcut"]["pro"] != "no" if a.pro is None else a.pro == "yes"
        print_json(resources.catalogue(a.category, pro_allowed=pro, query=a.query, limit=a.limit))
    elif a.action == "aliases":
        from .capcut import resources
        print_json(resources.aliases(a.category))
    elif a.action == "set-alpha":
        config.set_value("capcut.alpha_overlays", a.mode)
        print(f"capcut.alpha_overlays = {a.mode}")
    elif a.action == "probe-alpha":
        print_json(_probe_alpha(store))
    elif a.action == "build":
        from .capcut import builder
        p = _proj(a.path)
        e = p.edit()
        pro = _pro_allowed(a, e)
        mode = a.overlay_mode or e.capcut.overlay_mode
        if mode == "auto":
            alpha = config.load()["capcut"]["alpha_overlays"]
            mode = {"prores": "prores", "webm": "webm"}.get(alpha, "chroma")   # unknown -> green key (always works)
        built, report = builder.build(e, pro_allowed=pro, overlay_mode=mode)
        if store.is_running():
            if not a.close:
                raise VeditError("CapCut is open. Ask the user to save their work, then rerun with --close "
                                 "(CapCut autosaves, closing is normally safe).")
            store.close_app()
        name = a.name or e.capcut.project_name or f"{e.name}_{time.strftime('%m%d_%H%M')}"
        dest = store.create_project(name, built, overwrite=a.overwrite)
        snap = p.sub("capcut") / "snapshot.json"
        store.snapshot(dest, snap)
        meta = p.meta()
        meta["capcut_project"] = name
        p.save_meta(meta)
        p.log(f"CapCut project written: {name} (pro={'yes' if pro else 'no'}, overlays={mode})")
        print_json({"capcut_project": name, "path": str(dest), "warnings": report.warnings, "counts": report.counts,
                    "next": "Open CapCut (vedit capcut launch) - the project is first in the list."})
    elif a.action == "diff":
        from .capcut import diff as dmod
        from . import styles
        p = _proj(a.path)
        name = a.name or p.meta().get("capcut_project")
        snap = read_json(p.root / "capcut" / "snapshot.json")
        if not name or snap is None:
            raise VeditError("No generated CapCut project recorded for this edit (run `vedit capcut build` first).")
        insights = dmod.diff(snap, store.read_content(name))
        if a.learn:
            styles.learn(a.learn, insights)
            insights["learned_into"] = a.learn
        print_json(insights)
    elif a.action == "vectcut":
        from .capcut.vectcut import VectCut
        p = _proj(a.path)
        e = p.edit()
        print_json(VectCut(a.url).build(e, project_name=a.name or f"{e.name}_vectcut"))


def _probe_alpha(store) -> dict:
    """Build a tiny project with a ProRes-4444 and a WebM alpha overlay over magenta, for a one-time visual check."""
    from .capcut import builder
    from .media import ffmpeg
    from .paths import personal_dir
    from .timeline import Canvas, Clip, Edit, Overlay, Source
    from .util import run
    d = personal_dir() / "capcut" / "alpha_probe"
    d.mkdir(parents=True, exist_ok=True)
    bg = d / "magenta.png"
    run([ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0xFF00FF:s=1080x1920", "-frames:v", "1", str(bg)])
    circle = "color=c=black@0.0:s=1080x1920:d=3,format=rgba,geq=r='255':g='255':b='255':a='if(lt(hypot(X-540,Y-{y}),220),255,0)'"
    run([ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", circle.format(y=700), "-c:v", "prores_ks", "-profile:v", "4",
         "-pix_fmt", "yuva444p10le", str(d / "probe_prores.mov")])
    run([ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", circle.format(y=1300), "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
         "-b:v", "1M", str(d / "probe_webm.webm")])
    e = Edit(name="vedit_alpha_probe", canvas=Canvas(width=1080, height=1920, fps=30),
             sources={"bg": Source(id="bg", path=str(bg), kind="image", width=1080, height=1920)},
             main=[Clip(id="bg", source="bg", src_in=0, src_out=3)],
             overlays=[Overlay(id="prores", start=0, duration=3, path=str(d / "probe_prores.mov"), layer=0),
                       Overlay(id="webm", start=0, duration=3, path=str(d / "probe_webm.webm"), layer=1)])
    e.captions.enabled = False
    built, _ = builder.build(e, pro_allowed=False, overlay_mode="alpha")
    if store.is_running():
        store.close_app()
    store.create_project("vedit_alpha_probe", built, overwrite=True)
    return {"project": "vedit_alpha_probe",
            "check": "Open it in CapCut. Top circle = ProRes 4444, bottom circle = WebM. Each circle should be WHITE on "
                     "MAGENTA. A black/opaque box around a circle means that format has no alpha in this CapCut build.",
            "then": "vedit capcut set-alpha prores|webm|chroma  (chroma if both show boxes)"}


def cmd_style(a):
    from . import styles
    if a.action == "list":
        print_json(styles.list_styles())
    elif a.action == "show":
        print_json(styles.load_style(a.name))
    elif a.action == "analyze":
        out_dir = Path(a.out) if a.out else Path.cwd() / f"style_{a.name}"
        print_json(styles.analyze_reference(a.videos, a.name, out_dir))
    elif a.action == "save":
        print(styles.save_style(read_json(a.file)))


def cmd_brand(a):
    from . import styles
    if a.action == "list":
        print_json(styles.list_brands())
    elif a.action == "show":
        print_json(styles.load_brand(a.name))
    elif a.action == "create":
        fields = json.loads(a.fields) if a.fields else {}
        print(styles.create_brand(a.name, **fields))


def cmd_assets(a):
    from . import assets
    if a.action == "index":
        print_json(assets.index(a.target))
    elif a.action == "search":
        print_json(assets.search(a.target or "", kind=a.kind, min_duration=a.min_duration, limit=a.limit))
    elif a.action == "tag":
        print_json(assets.tag(a.target, a.tags.split(","), a.description))


def cmd_provenance(a):
    from . import assets
    p = _proj(a.path)
    if a.action == "list":
        print_json(read_json(p.root / "assets" / "provenance.json", default=[]))
    elif a.action == "add":
        print_json(assets.add_provenance(p.root, a.file, source=a.source, url=a.url, license=a.license, notes=a.notes or ""))


def cmd_download(a):
    from . import assets, project
    p = _proj(a.path)
    out = assets.download(a.url, p.sub("assets") / a.source, name=a.name)
    rec = assets.add_provenance(p.root, out, source=a.source, url=a.page or a.url, license=a.license, notes=a.notes or "")
    sid = project.add_source(p, out, origin=f"{a.source}:{a.page or a.url}") if a.register else None
    print_json({"file": str(out), "source_id": sid, "provenance": rec})


def cmd_sfx(a):
    from .audio import synth, write_wav
    print(write_wav(synth(a.kind, duration=a.duration, seed=a.seed, pitch=a.pitch), a.out))


def cmd_beats(a):
    from .audio import beats
    print_json(beats(a.file))


def cmd_reframe(a):
    from .reframe import ratio_variant_path, reframe_edit
    from .timeline import save_edit
    p = _proj(a.path)
    e = reframe_edit(p.edit(), ratio=a.ratio)
    if a.ratio:
        e.name = f"{e.name}_{a.ratio.replace(':', 'x')}"   # its render must not overwrite the main one
    out = ratio_variant_path(p.edit_path, a.ratio) if a.ratio else p.edit_path
    save_edit(e, out)
    print_json({"edit": str(out), "canvas": e.canvas.model_dump(),
                "reframed_clips": sum(1 for c in [*e.main, *e.broll] if c.crop)})


def cmd_shorts(a):
    from . import shorts
    p = _proj(a.path)
    e = p.edit()
    if a.action == "candidates":
        out = []
        for sid, src in e.sources.items():
            if src.transcript and (not a.source or sid in a.source):
                out += shorts.candidates(sid, src.transcript, src.path, min_len=a.min, max_len=a.max, top=a.top)
        out.sort(key=lambda c: -c["score"])
        print_json(out[: a.top])
    elif a.action == "make":
        proj = shorts.make_short(p, a.name, read_json(a.keeps), ratio=a.ratio)
        print_json({"project": str(proj.root), "duration": round(proj.edit().duration, 2)})


def cmd_thumbnail(a):
    from . import thumbnail
    if a.action == "frames":
        print_json(thumbnail.best_frames(a.target, Path(a.out), count=a.count))
    elif a.action == "make":
        print(thumbnail.compose(a.target, a.title, Path(a.out), size=a.size,
                                highlight=a.highlight.split(",") if a.highlight else None, accent=a.accent, emoji=a.emoji,
                                layout=a.layout))


def cmd_tts(a):
    from . import tts
    if a.action == "voices":
        print_json(tts.voices())
    elif a.action == "models":
        print_json(tts.models())
    elif a.action == "speak":
        text = Path(a.file).read_text(encoding="utf-8") if a.file else a.text
        print_json(tts.speak(text, a.out, voice=a.voice, model=a.model, language=a.language, speed=a.speed))
    elif a.action == "clone":
        print_json(tts.clone(a.name, a.files, description=a.description or ""))


def cmd_higgsfield(a):
    from . import higgsfield as hf
    if a.action == "status":
        print_json(hf.status())
        return
    p = _proj(a.path)
    if a.action == "propose":
        print_json(hf.propose(p, read_json(a.file)))
    elif a.action == "approve":
        print_json(hf.approve(p, a.plan))
    elif a.action == "import":
        print_json(hf.import_output(p, a.src, shot_id=a.shot, prompt=a.prompt or "", model=a.model or "",
                                    credits=a.credits, kind=a.kind))
    elif a.action == "spent":
        print_json({"credits_spent": hf.spent(p)})


def cmd_screen(a):
    from . import screen
    if a.action == "shot":
        print(screen.screenshot(a.out, max_width=a.max_width))
    elif a.action == "click":
        screen.click(a.x, a.y, clicks=a.clicks, expect=a.expect or None)
        print("clicked")
    elif a.action == "keys":
        screen.send_keys(a.keys, expect=a.expect or None)
        print("sent")
    elif a.action == "foreground":
        print(screen.foreground_process())
    elif a.action == "focus":
        print_json({"focused": screen.focus(a.name)})


def cmd_mcp(a):
    from .mcp_server import main as mcp_main
    mcp_main()


# ------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vedit", description="Engine for the video-editing-skill Claude skill.")
    sp = ap.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("doctor", help="check the environment"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_doctor)
    s = sp.add_parser("setup", help="install fonts, renderer deps, whisper model")
    s.add_argument("what", nargs="?", default="all", choices=["all", "fonts", "renderer", "whisper", "install-fonts"])
    s.add_argument("--force", action="store_true"); s.add_argument("--whisper", action="store_true"); s.add_argument("--model")
    s.set_defaults(fn=cmd_setup)
    s = sp.add_parser("update", help="git pull the latest skill (keeps personal/)"); s.add_argument("--check", action="store_true")
    s.set_defaults(fn=cmd_update)
    s = sp.add_parser("config"); s.add_argument("action", choices=["get", "set", "path"]); s.add_argument("key", nargs="?")
    s.add_argument("value", nargs="?"); s.set_defaults(fn=cmd_config)
    s = sp.add_parser("secret"); s.add_argument("action", choices=["set"]); s.add_argument("name"); s.add_argument("value")
    s.set_defaults(fn=cmd_secret)

    s = sp.add_parser("project"); s.add_argument("action", choices=["init", "info", "log", "add-source"]); s.add_argument("path")
    s.add_argument("note", nargs="?"); s.add_argument("--name"); s.add_argument("--ratio", default="9:16")
    s.add_argument("--recursive", action="store_true"); s.add_argument("--force", action="store_true")
    s.add_argument("--file"); s.add_argument("--origin", default="library"); s.set_defaults(fn=cmd_project)
    s = sp.add_parser("probe"); s.add_argument("files", nargs="+"); s.set_defaults(fn=cmd_probe)
    s = sp.add_parser("transcribe"); s.add_argument("path"); s.add_argument("--engine", choices=["whisper", "scribe"], required=True)
    s.add_argument("--language"); s.add_argument("--model"); s.add_argument("--source", nargs="*"); s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_transcribe)
    s = sp.add_parser("pack"); s.add_argument("path"); s.set_defaults(fn=cmd_pack)
    s = sp.add_parser("words", help="kept words with timeline times (place graphics/SFX on words)"); s.add_argument("path")
    s.add_argument("--find", help="phrase to locate, e.g. 'try it'"); s.add_argument("--start", type=float)
    s.add_argument("--end", type=float); s.set_defaults(fn=cmd_words)
    s = sp.add_parser("view"); s.add_argument("file"); s.add_argument("--start", type=float, required=True)
    s.add_argument("--end", type=float, required=True); s.add_argument("--transcript"); s.add_argument("--frames", type=int, default=8)
    s.add_argument("--out"); s.set_defaults(fn=cmd_view)
    s = sp.add_parser("frames"); s.add_argument("file"); s.add_argument("--at", required=True); s.add_argument("--out", required=True)
    s.add_argument("--width", type=int, default=320); s.set_defaults(fn=cmd_frames)
    s = sp.add_parser("silences"); s.add_argument("file"); s.add_argument("--noise", type=float, default=-35)
    s.add_argument("--min", type=float, default=0.35); s.set_defaults(fn=cmd_silences)
    s = sp.add_parser("plan"); s.add_argument("action", choices=["auto", "apply", "validate", "schema"]); s.add_argument("path", nargs="?")
    s.add_argument("keeps", nargs="?"); s.add_argument("--source", nargs="*"); s.add_argument("--max-pause", type=float, default=0.3)
    s.add_argument("--append", action="store_true"); s.set_defaults(fn=cmd_plan)
    s = sp.add_parser("captions"); s.add_argument("action", choices=["build", "export", "styles"]); s.add_argument("path", nargs="?")
    s.add_argument("--style"); s.add_argument("--max-words", type=int); s.add_argument("--format", default="srt", choices=["srt", "vtt", "ass"])
    s.set_defaults(fn=cmd_captions)
    s = sp.add_parser("storyboard"); s.add_argument("path"); s.add_argument("--title"); s.add_argument("--open", action="store_true")
    s.set_defaults(fn=cmd_storyboard)
    s = sp.add_parser("mg", help="motion graphics"); s.add_argument("action", choices=["templates", "render", "file", "still", "sheet"])
    s.add_argument("path", nargs="?", help="project (render)"); s.add_argument("--id", nargs="*"); s.add_argument("--force", action="store_true")
    s.add_argument("--comp"); s.add_argument("--out"); s.add_argument("--data"); s.add_argument("--duration", type=float, default=3)
    s.add_argument("--width", type=int, default=1080); s.add_argument("--height", type=int, default=1920)
    s.add_argument("--fps", type=float, default=30); s.add_argument("--t", type=float, default=1.0)
    s.add_argument("--formats", default="webm,prores"); s.set_defaults(fn=cmd_mg)
    s = sp.add_parser("render"); s.add_argument("path"); s.add_argument("--preview", action="store_true"); s.add_argument("--out")
    s.add_argument("--no-captions", action="store_true"); s.set_defaults(fn=cmd_render)
    s = sp.add_parser("qa"); s.add_argument("path"); s.add_argument("--render"); s.set_defaults(fn=cmd_qa)

    s = sp.add_parser("capcut")
    s.add_argument("action", choices=["calibrate", "list", "build", "close", "launch", "resources", "aliases", "diff",
                                      "probe-alpha", "set-alpha", "vectcut"])
    s.add_argument("path", nargs="?", help="project (build/diff/vectcut) or category (resources/aliases)")
    s.add_argument("--project"); s.add_argument("--name"); s.add_argument("--pro", choices=["yes", "no"])
    s.add_argument("--overwrite", action="store_true"); s.add_argument("--close", action="store_true")
    s.add_argument("--force", action="store_true"); s.add_argument("--overlay-mode", choices=["prores", "webm", "chroma", "alpha"])
    s.add_argument("--query"); s.add_argument("--limit", type=int, default=150); s.add_argument("--learn")
    s.add_argument("--mode", choices=["prores", "webm", "chroma"]); s.add_argument("--url", default="http://localhost:9001")
    s.set_defaults(fn=cmd_capcut)

    s = sp.add_parser("style"); s.add_argument("action", choices=["list", "show", "analyze", "save"]); s.add_argument("name", nargs="?")
    s.add_argument("videos", nargs="*"); s.add_argument("--out"); s.add_argument("--file"); s.set_defaults(fn=cmd_style)
    s = sp.add_parser("brand"); s.add_argument("action", choices=["list", "show", "create"]); s.add_argument("name", nargs="?")
    s.add_argument("--fields", help='JSON, e.g. \'{"colors": {"accent": "#00E0FF"}}\''); s.set_defaults(fn=cmd_brand)
    s = sp.add_parser("assets"); s.add_argument("action", choices=["index", "search", "tag"]); s.add_argument("target", nargs="?")
    s.add_argument("--kind"); s.add_argument("--min-duration", type=float, default=0); s.add_argument("--limit", type=int, default=20)
    s.add_argument("--tags", default=""); s.add_argument("--description"); s.set_defaults(fn=cmd_assets)
    s = sp.add_parser("provenance"); s.add_argument("action", choices=["list", "add"]); s.add_argument("path")
    s.add_argument("--file"); s.add_argument("--source"); s.add_argument("--url"); s.add_argument("--license"); s.add_argument("--notes")
    s.set_defaults(fn=cmd_provenance)
    s = sp.add_parser("download", help="download an asset into a project with provenance"); s.add_argument("path"); s.add_argument("url")
    s.add_argument("--source", required=True, help="pinterest | web | higgsfield | library"); s.add_argument("--page")
    s.add_argument("--license"); s.add_argument("--notes"); s.add_argument("--name"); s.add_argument("--register", action="store_true")
    s.set_defaults(fn=cmd_download)
    s = sp.add_parser("sfx"); s.add_argument("kind"); s.add_argument("--out", required=True); s.add_argument("--duration", type=float)
    s.add_argument("--seed", type=int, default=3); s.add_argument("--pitch", type=float, default=1.0); s.set_defaults(fn=cmd_sfx)
    s = sp.add_parser("beats"); s.add_argument("file"); s.set_defaults(fn=cmd_beats)
    s = sp.add_parser("reframe"); s.add_argument("path"); s.add_argument("--ratio"); s.set_defaults(fn=cmd_reframe)
    s = sp.add_parser("shorts"); s.add_argument("action", choices=["candidates", "make"]); s.add_argument("path")
    s.add_argument("name", nargs="?"); s.add_argument("keeps", nargs="?"); s.add_argument("--source", nargs="*")
    s.add_argument("--min", type=float, default=20); s.add_argument("--max", type=float, default=60); s.add_argument("--top", type=int, default=10)
    s.add_argument("--ratio", default="9:16"); s.set_defaults(fn=cmd_shorts)
    s = sp.add_parser("thumbnail"); s.add_argument("action", choices=["frames", "make"]); s.add_argument("target")
    s.add_argument("--out", required=True); s.add_argument("--count", type=int, default=6); s.add_argument("--title", default="")
    s.add_argument("--size", default="youtube", choices=["youtube", "cover"]); s.add_argument("--highlight")
    s.add_argument("--accent", default="#FFE14D"); s.add_argument("--emoji", default=""); s.add_argument("--layout", default="left")
    s.set_defaults(fn=cmd_thumbnail)
    s = sp.add_parser("tts"); s.add_argument("action", choices=["voices", "models", "speak", "clone"]); s.add_argument("text", nargs="?")
    s.add_argument("--file"); s.add_argument("--voice"); s.add_argument("--out"); s.add_argument("--model"); s.add_argument("--language")
    s.add_argument("--speed", type=float, default=1.0); s.add_argument("--name"); s.add_argument("--files", nargs="*")
    s.add_argument("--description"); s.set_defaults(fn=cmd_tts)
    s = sp.add_parser("higgsfield"); s.add_argument("action", choices=["status", "propose", "approve", "import", "spent"])
    s.add_argument("path", nargs="?"); s.add_argument("--file"); s.add_argument("--plan"); s.add_argument("--src"); s.add_argument("--shot")
    s.add_argument("--prompt"); s.add_argument("--model"); s.add_argument("--credits", type=float); s.add_argument("--kind", default="broll")
    s.set_defaults(fn=cmd_higgsfield)
    s = sp.add_parser("screen", help="screenshots / simple input when no computer-use MCP is attached")
    s.add_argument("action", choices=["shot", "click", "keys", "focus", "foreground"]); s.add_argument("--out", default="screen.png")
    s.add_argument("--max-width", type=int, default=1600); s.add_argument("--x", type=int); s.add_argument("--y", type=int)
    s.add_argument("--clicks", type=int, default=1); s.add_argument("--keys"); s.add_argument("--name", default="CapCut")
    s.add_argument("--expect", default="CapCut", help="only send input if this process owns the foreground ('' = no check)")
    s.set_defaults(fn=cmd_screen)
    s = sp.add_parser("mcp", help="run the MCP server (stdio)"); s.set_defaults(fn=cmd_mcp)
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if args.cmd == "capcut" and args.action in ("resources", "aliases"):
        args.category = args.path
    if args.cmd == "capcut" and args.action == "set-alpha" and not args.mode:
        args.mode = args.path
    try:
        args.fn(args)
        return 0
    except VeditError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
