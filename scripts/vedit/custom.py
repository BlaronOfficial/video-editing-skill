"""Custom FX and personal reuse: what Claude builds when no template or built-in effect fits.

`prepare()` runs every enabled CustomFX that needs a file (python / html / blender) and caches by content.
`materialize()` turns them into ordinary timeline items for one render: overlays, audio clips, swapped
sources, plus ffmpeg filter chains for the render hooks. edit.json keeps only the CustomFX entries.

Reuse: `vedit template save` / `vedit fx save` copy a project's creation into personal/templates or
personal/fx; `vedit technique save` keeps a recipe (how a look was achieved) in personal/techniques.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from .paths import SKILL_ROOT, mg_dir, personal_dir, presets_dir
from .timeline import AudioClip, CustomFX, Edit, Overlay, Source
from .util import VeditError, read_json, run, short_hash, write_json

HOOKS = ("video_pre_overlays", "video_pre_captions", "video_post", "audio_voice", "audio_master")
EXT = {"overlay": ".mov", "audio": ".wav", "source": ".mp4", "none": ".json"}


def resolve_file(ref: str, project_root: Path) -> Path:
    if ref.startswith("personal:"):
        return personal_dir() / ref.split(":", 1)[1]
    p = Path(ref)
    return p if p.is_absolute() else (project_root / p)


def _input_path(edit: Edit, ref: str, project_root: Path) -> str:
    if ref in edit.sources:
        return edit.sources[ref].path
    p = resolve_file(ref, project_root)
    return str(p) if p.exists() else ref


def _key(edit: Edit, fx: CustomFX, project_root: Path) -> str:
    parts: list = [fx.model_dump(mode="json", exclude={"path", "cache_key", "start", "anchor", "label"}),
                   edit.canvas.model_dump(mode="json")]
    if fx.file:
        f = resolve_file(fx.file, project_root)
        parts.append(f.read_text(encoding="utf-8", errors="replace") if f.exists() else fx.file)
    for ref in fx.inputs:
        p = Path(_input_path(edit, ref, project_root))
        parts.append([p.name, p.stat().st_size, int(p.stat().st_mtime)] if p.exists() else ref)
    return short_hash(*parts)


def _duration(edit: Edit, fx: CustomFX) -> float:
    return round(fx.duration if fx.duration else max(0.1, edit.duration - fx.start), 3)


def run_fx(edit: Edit, fx: CustomFX, project_root: Path, *, force: bool = False) -> Path | None:
    if fx.kind == "ffmpeg" or fx.output == "none" and fx.kind != "python":
        return None
    key = _key(edit, fx, project_root)
    out_dir = project_root / "custom" / "out"
    out = out_dir / f"{fx.id}_{key}{EXT[fx.output]}"
    if out.exists() and not force:
        fx.path, fx.cache_key = str(out), key
        return out
    out_dir.mkdir(parents=True, exist_ok=True)
    dur = _duration(edit, fx)
    W, H, fps = edit.canvas.width, edit.canvas.height, edit.canvas.fps
    if fx.kind == "python":
        if not fx.file:
            raise VeditError(f"CustomFX {fx.id}: kind=python needs `file`")
        script = resolve_file(fx.file, project_root)
        if not script.exists():
            raise VeditError(f"CustomFX {fx.id}: script not found: {script}")
        params_file = out_dir / f"{fx.id}_{key}.params.json"
        write_json(params_file, fx.params)
        inp = _input_path(edit, fx.inputs[0], project_root) if fx.inputs else ""
        env = {**os.environ, "PYTHONPATH": str(SKILL_ROOT / "scripts") + os.pathsep + os.environ.get("PYTHONPATH", ""),
               "PYTHONUTF8": "1"}
        run([sys.executable, str(script), "--in", inp, "--out", str(out), "--params", str(params_file),
             "--width", str(W), "--height", str(H), "--fps", str(fps), "--duration", f"{dur:.3f}",
             "--start", f"{fx.start:.3f}", "--project", str(project_root)], cwd=project_root, env=env, timeout=7200)
    elif fx.kind == "html":
        from .mg import render_html
        comp = resolve_file(fx.file or "", project_root)
        outs = render_html(comp, out.with_suffix(""), width=W, height=H, fps=fps, duration=dur, data=fx.params,
                           formats=["prores"])
        outs[0].replace(out) if outs[0] != out else None
    elif fx.kind == "blender":
        raise VeditError("CustomFX kind=blender arrives with the Blender add-on (phase 4).")
    if not out.exists():
        raise VeditError(f"CustomFX {fx.id} did not write {out}")
    fx.path, fx.cache_key = str(out), key
    return out


def prepare(edit: Edit, proj, *, force: bool = False, only: list[str] | None = None) -> list[dict]:
    """Run every enabled CustomFX that produces a file. Mutates fx.path/cache_key (caller saves the edit)."""
    done = []
    for fx in edit.custom_fx:
        if not fx.enabled or (only and fx.id not in only):
            continue
        t0 = time.time()
        path = run_fx(edit, fx, proj.root, force=force)
        done.append({"id": fx.id, "kind": fx.kind, "output": fx.output, "path": str(path) if path else None,
                     "seconds": round(time.time() - t0, 1)})
    return done


def materialize(edit: Edit, project_root: Path) -> tuple[Edit, dict[str, list[str]]]:
    """A render-ready copy: FX outputs become overlays / audio / sources; ffmpeg FX become hook chains."""
    e = edit.model_copy(deep=True)
    hooks: dict[str, list[str]] = {h: [] for h in HOOKS}
    for fx in e.custom_fx:
        if not fx.enabled:
            continue
        if fx.kind == "ffmpeg":
            if not fx.hook or not fx.filter:
                raise VeditError(f"CustomFX {fx.id}: kind=ffmpeg needs `hook` and `filter`")
            if any(ch in fx.filter for ch in ";[]"):
                raise VeditError(f"CustomFX {fx.id}: the filter must be one chain with no labels (no ';' or '[...]').")
            hooks[fx.hook].append(fx.filter)
            continue
        path = run_fx(e, fx, project_root)
        if path is None:
            continue
        dur = _duration(e, fx)
        if fx.output == "overlay":
            e.overlays.append(Overlay(id=f"fx_{fx.id}", start=fx.start, duration=dur, path=str(path), fit=fx.fit,
                                      transform=fx.transform, layer=fx.layer, fx=fx.id, label=fx.label or fx.id))
        elif fx.output == "audio":
            sid = f"fx_{fx.id}"
            e.sources[sid] = Source(id=sid, path=str(path), kind="audio", origin="custom_fx")
            e.audio.append(AudioClip(id=sid, source=sid, start=fx.start, volume=fx.volume,
                                     role=fx.params.get("role", "sfx"), fx=fx.id, label=fx.label or fx.id))
        elif fx.output == "source":
            from .media import probe
            info = probe(path)
            sid = f"fx_{fx.id}"
            dw, dh = info.display_size
            e.sources[sid] = Source(id=sid, path=str(path), kind="video", duration=info.duration, width=dw, height=dh,
                                    fps=info.fps, has_audio=info.has_audio, origin="custom_fx")
            targets = set(fx.params.get("targets", []))
            for clip in [*e.main, *e.broll]:
                if clip.id in targets:
                    clip.source = sid
    return e.layout(), hooks


# ------------------------------------------------------------------ personal reuse

def personal_templates_dir() -> Path:
    path = personal_dir() / "templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_template(proj, overlay_id: str, name: str, description: str = "") -> dict:
    """Promote a project's custom composition into a reusable personal template."""
    edit = proj.edit()
    ov = next((o for o in edit.overlays if o.id == overlay_id), None)
    if ov is None or ov.mg is None:
        raise VeditError(f"No motion-graphics overlay '{overlay_id}' in this edit.")
    src = Path(ov.mg.file) if ov.mg.file else mg_dir() / "templates" / f"{ov.mg.template}.html"
    if not src.is_absolute():
        src = proj.root / src
    if not src.exists():
        raise VeditError(f"Composition not found: {src}")
    dest = personal_templates_dir() / f"{name}.html"
    shutil.copy2(src, dest)
    index_path = personal_templates_dir() / "index.json"
    index = read_json(index_path, default={}) or {}
    index[name] = {"use": description or ov.label or f"saved from {edit.name}", "duration": ov.duration,
                   "data": {k: type(v).__name__ for k, v in ov.mg.data.items()}, "personal": True,
                   "saved": time.strftime("%Y-%m-%d"), "from_project": edit.name}
    write_json(index_path, index)
    from . import learn
    learn.event("template", {"name": name, "from": overlay_id}, project=edit.name)
    return {"template": name, "file": str(dest)}


def save_fx(proj, fx_id: str, name: str, description: str = "") -> dict:
    edit = proj.edit()
    fx = next((f for f in edit.custom_fx if f.id == fx_id), None)
    if fx is None or not fx.file:
        raise VeditError(f"No file-based CustomFX '{fx_id}' in this edit.")
    src = resolve_file(fx.file, proj.root)
    dest_dir = personal_dir() / "fx"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{name}{src.suffix}"
    shutil.copy2(src, dest)
    meta_path = dest_dir / "index.json"
    meta = read_json(meta_path, default={}) or {}
    meta[name] = {"use": description or fx.label, "kind": fx.kind, "output": fx.output, "params": fx.params,
                  "file": f"personal:fx/{dest.name}", "saved": time.strftime("%Y-%m-%d")}
    write_json(meta_path, meta)
    return {"fx": name, "file": f"personal:fx/{dest.name}"}


def list_fx() -> dict:
    return read_json(personal_dir() / "fx" / "index.json", default={}) or {}


def technique_dirs() -> list[Path]:
    return [presets_dir() / "techniques", personal_dir() / "techniques"]


def list_techniques() -> list[dict]:
    rows = []
    for d in technique_dirs():
        for f in sorted(d.glob("*.md")) if d.is_dir() else []:
            text = f.read_text(encoding="utf-8")
            head = {}
            if text.startswith("---"):
                for line in text.split("---", 2)[1].strip().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        head[k.strip()] = v.strip()
            rows.append({"name": head.get("name", f.stem), "tags": head.get("tags", ""), "description":
                         head.get("description", ""), "personal": d.parent == personal_dir(), "file": str(f)})
    return rows


def save_technique(name: str, file: str) -> Path:
    src = Path(file)
    if not src.exists():
        raise VeditError(f"No such file: {file}")
    dest = personal_dir() / "techniques" / f"{name}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


# ------------------------------------------------------------------ CLI

def register_cli(sp) -> None:
    s = sp.add_parser("fx", help="custom FX Claude writes for an edit (python / ffmpeg / html)")
    s.add_argument("action", choices=["run", "list", "save"])
    s.add_argument("path", nargs="?"); s.add_argument("--id", nargs="*"); s.add_argument("--force", action="store_true")
    s.add_argument("--name"); s.add_argument("--description", default="")
    s.set_defaults(fn=_cmd_fx)
    s = sp.add_parser("template", help="save a project's custom composition as a personal template")
    s.add_argument("action", choices=["save", "list"])
    s.add_argument("path", nargs="?"); s.add_argument("overlay", nargs="?"); s.add_argument("--name")
    s.add_argument("--description", default="")
    s.set_defaults(fn=_cmd_template)
    s = sp.add_parser("technique", help="recipes for looks Claude learned (shipped + personal)")
    s.add_argument("action", choices=["list", "show", "save"])
    s.add_argument("name", nargs="?"); s.add_argument("--file"); s.add_argument("--tag")
    s.set_defaults(fn=_cmd_technique)


def _cmd_fx(a) -> None:
    from .project import find
    from .util import print_json
    if a.action == "list":
        print_json({"personal_fx": list_fx(), "hooks": HOOKS})
        return
    p = find(a.path)
    if a.action == "save":
        if not (a.id and a.name):
            raise VeditError("vedit fx save <project> --id <fx-id> --name <name>")
        print_json(save_fx(p, a.id[0], a.name, a.description))
        return
    e = p.edit()
    done = prepare(e, p, force=a.force, only=a.id)
    p.save_edit(e)
    print_json(done)


def _cmd_template(a) -> None:
    from .mg import templates
    from .project import find
    from .util import print_json
    if a.action == "list":
        print_json({k: v for k, v in templates().items() if v.get("personal")})
        return
    if not (a.path and a.overlay and a.name):
        raise VeditError("vedit template save <project> <overlay-id> --name <name>")
    print_json(save_template(find(a.path), a.overlay, a.name, a.description))


def _cmd_technique(a) -> None:
    from .util import print_json
    if a.action == "list":
        rows = list_techniques()
        if a.tag:
            rows = [r for r in rows if a.tag.lower() in r["tags"].lower()]
        print_json(rows)
    elif a.action == "show":
        row = next((r for r in list_techniques() if r["name"] == a.name), None)
        if row is None:
            raise VeditError(f"No technique '{a.name}'. See `vedit technique list`.")
        print(Path(row["file"]).read_text(encoding="utf-8"))
    else:
        if not (a.name and a.file):
            raise VeditError("vedit technique save <name> --file <recipe.md>")
        print_json({"saved": str(save_technique(a.name, a.file))})
