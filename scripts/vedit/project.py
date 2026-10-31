"""Edit projects: a workspace folder `<footage>/edit/` holding everything for one video.

  edit/
    project.json     settings, decision log, workflow (mode, plan status, stage)
    edit.json        the timeline (single source of truth)
    transcripts/     normalised word-level transcripts per source
    takes_packed.md  compact transcript view Claude reads to plan the edit
    storyboard/      approval page + frames
    mg/              motion-graphics compositions and renders
    assets/          b-roll, music, sfx, generated + downloaded media (with provenance.json)
    render/          final.mp4, preview.mp4, captions.ass/.srt
    qa/              self-check frames + report
    capcut/          snapshot of the generated CapCut content (learn-from-edits)
    studio/          Studio bundle: proxies, peaks, sprites, data docs, upload map
    custom/          code Claude wrote for this edit (compositions, python FX)
    inbox/           files pulled in from the browser's Downloads (web AI, research)
    suggestions.json / directions.json   Studio suggestion cards and creative directions
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .media import list_media, probe
from .timeline import Canvas, Edit, Source, load_edit, save_edit
from .util import VeditError, read_json, write_json

RATIOS = {
    "9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350),
    "4:3": (1440, 1080), "21:9": (2560, 1080), "4k": (3840, 2160), "9:16-4k": (2160, 3840),
}

SUBDIRS = ("transcripts", "storyboard", "mg", "assets", "render", "qa", "capcut", "studio", "custom", "inbox",
           "watch", "sound", "handoff")


def slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^\w\-]+", "_", text.strip(), flags=re.U).strip("_").lower()
    return (s or "item")[:max_len]


class Project:
    def __init__(self, root: Path, edit_file: Path | None = None):
        self.root = root
        self._edit_file = edit_file      # e.g. edit_1x1.json ratio variants

    # ---------------------------------------------------------- paths
    @property
    def edit_path(self) -> Path:
        return self._edit_file or self.root / "edit.json"

    @property
    def meta_path(self) -> Path:
        return self.root / "project.json"

    def sub(self, name: str) -> Path:
        p = self.root / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def footage_dir(self) -> Path:
        return self.root.parent

    # ---------------------------------------------------------- data
    def meta(self) -> dict:
        return read_json(self.meta_path, default={}) or {}

    def save_meta(self, meta: dict) -> None:
        meta["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        write_json(self.meta_path, meta)

    def log(self, decision: str) -> None:
        """Append to the decision log so a later session knows what was agreed."""
        meta = self.meta()
        meta.setdefault("decisions", []).append({"at": time.strftime("%Y-%m-%d %H:%M"), "note": decision})
        self.save_meta(meta)

    def edit(self) -> Edit:
        if not self.edit_path.exists():
            raise VeditError(f"No edit.json in {self.root}. Run `vedit project init` first.")
        return load_edit(self.edit_path)

    def save_edit(self, edit: Edit) -> Path:
        return save_edit(edit, self.edit_path)


def find(path: str | Path) -> Project:
    """Accept a footage folder, an edit/ folder, or an edit JSON file (edit.json or a variant like edit_1x1.json)."""
    p = Path(path).resolve()
    if p.is_file() and p.suffix == ".json":
        return Project(p.parent, edit_file=None if p.name == "edit.json" else p)
    if (p / "edit.json").exists() or (p / "project.json").exists():
        return Project(p)
    if (p / "edit" / "project.json").exists():
        return Project(p / "edit")
    raise VeditError(f"No edit project at {p}. Create one with `vedit project init <footage-folder>`.")


def init(footage: str | Path, *, name: str | None = None, ratio: str = "9:16", fps: float | None = None,
         recursive: bool = False, force: bool = False) -> Project:
    footage = Path(footage).resolve()
    if footage.is_file():
        files = [footage]
        footage = footage.parent
    else:
        files = list_media(footage, recursive=recursive)
    root = footage / "edit"
    if (root / "edit.json").exists() and not force:
        raise VeditError(f"Project already exists at {root} (use --force to re-initialise).")
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    if ratio not in RATIOS:
        raise VeditError(f"Unknown ratio {ratio}. Use one of: {', '.join(RATIOS)}")
    w, h = RATIOS[ratio]
    sources: dict[str, Source] = {}
    first_fps = None
    for f in files:
        if "edit" in f.relative_to(footage).parts[:1]:
            continue
        info = probe(f)
        if info.kind not in ("video", "audio", "image"):
            continue
        sid = slug(f.stem)
        base, n = sid, 2
        while sid in sources:
            sid, n = f"{base}_{n}", n + 1
        dw, dh = info.display_size
        sources[sid] = Source(id=sid, path=str(f), kind=info.kind, duration=round(info.duration, 3), width=dw, height=dh,
                              fps=round(info.fps, 3), has_audio=info.has_audio, origin="camera", **_footage(f, info.kind))
        if info.kind == "video" and first_fps is None and info.fps:
            first_fps = info.fps
    edit = Edit(name=name or slug(footage.name), canvas=Canvas(width=w, height=h, fps=fps or _snap_fps(first_fps or 30)),
                sources=sources)
    proj = Project(root)
    proj.save_edit(edit)
    from . import config
    proj.save_meta({"name": edit.name, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "ratio": ratio,
                    "footage": str(footage), "decisions": [], "settings": {},
                    "workflow": {"mode": config.load().get("mode", {}).get("default", "plan"), "plan_status": "draft",
                                 "stage": "cut", "approved_stages": [], "history": []}})
    return proj


def _footage(path, kind: str) -> dict:
    """HDR / Log / VFR / interlacing / black bars / device, measured once when a video source comes in."""
    if kind != "video":
        return {}
    from .footage import analyze, notes
    try:
        a = analyze(path)
    except Exception as exc:             # analysis must never block a project
        return {"notes": [f"footage analysis failed: {exc}"]}
    return {"color": a, "notes": notes(a)}


def _snap_fps(fps: float) -> float:
    for std in (23.976, 24, 25, 29.97, 30, 50, 59.94, 60):
        if abs(fps - std) < 0.05:
            return float(std if std in (24, 25, 30, 50, 60) else round(std))
    return float(round(fps))


def add_source(proj: Project, path: str | Path, *, origin: str = "library", sid: str | None = None) -> str:
    """Register extra media (b-roll, music, sfx, generated) in edit.json and return its id."""
    edit = proj.edit()
    info = probe(path)
    sid = sid or slug(Path(path).stem)
    base, n = sid, 2
    while sid in edit.sources and edit.sources[sid].path != str(Path(path).resolve()):
        sid, n = f"{base}_{n}", n + 1
    dw, dh = info.display_size
    edit.sources[sid] = Source(id=sid, path=str(Path(path).resolve()), kind=info.kind, duration=round(info.duration, 3),
                               width=dw, height=dh, fps=round(info.fps, 3), has_audio=info.has_audio, origin=origin,
                               **_footage(path, info.kind))
    proj.save_edit(edit)
    return sid
