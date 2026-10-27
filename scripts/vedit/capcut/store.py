"""CapCut draft store: find drafts, calibrate a seed, create/register projects, read them back.

Why a seed: CapCut 8.4+ rejects drafts whose version markers don't match the installed app, and 9.x
keeps the authoritative copy in Timelines/<timeline_id>/ with mirrors at the project root. So we
never write a draft from scratch: we copy a blank project that the user's own CapCut created
(`calibrate`), give it fresh IDs, inject our tracks/materials, and write every mirror.
Seeds contain the user's device id / MAC address, so they live in personal/ and are never shipped.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import config
from ..paths import IS_MAC, IS_WINDOWS, capcut_app_candidates, capcut_drafts_root_default, personal_dir
from ..util import VeditError, new_uuid, read_json, write_json

CONTENT_MIRRORS = ("draft_content.json", "draft_content.json.bak", "template-2.tmp")
SEED_DIRNAME = "seed"


# ------------------------------------------------------------------ locations

def drafts_root() -> Path:
    cfg = config.load()["capcut"]
    root = Path(cfg["drafts_root"]) if cfg.get("drafts_root") else capcut_drafts_root_default()
    if not root or not root.is_dir():
        raise VeditError(
            "CapCut drafts folder not found. Install CapCut desktop, open it once and create an empty project, "
            "or set it with `vedit config set capcut.drafts_root <path>`."
        )
    return root


def app_path() -> Path | None:
    cfg = config.load()["capcut"]
    if cfg.get("app_path") and Path(cfg["app_path"]).exists():
        return Path(cfg["app_path"])
    cands = capcut_app_candidates()
    return cands[0] if cands else None


def installed_version() -> str | None:
    exe = app_path()
    if exe and IS_WINDOWS and exe.parent.name[:1].isdigit():
        return exe.parent.name
    return None


def seed_dir() -> Path:
    return personal_dir() / "capcut" / SEED_DIRNAME


# ------------------------------------------------------------------ app process

def is_running() -> bool:
    if IS_WINDOWS:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe", "/NH"], capture_output=True, text=True)
        return "CapCut.exe" in (out.stdout or "")
    if IS_MAC:
        return subprocess.run(["pgrep", "-x", "CapCut"], capture_output=True).returncode == 0
    return False


def close_app(*, force: bool = False, timeout: float = 20.0) -> bool:
    """Ask CapCut to close like a user would (it autosaves drafts). Returns True when it is gone."""
    if not is_running():
        return True

    def gone_within(seconds: float) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if not is_running():
                return True
            time.sleep(0.5)
        return False

    if IS_WINDOWS:
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-Process CapCut -ErrorAction SilentlyContinue | ForEach-Object { [void]$_.CloseMainWindow() }"],
                       capture_output=True)
        if gone_within(min(6.0, timeout)):
            return True
        # The editor window ignores WM_CLOSE; Alt+F4 behaves like the user closing it. focus() only
        # succeeds when CapCut really owns the foreground, and send_keys re-checks, so the keystroke can
        # never close the user's own window.
        from .. import screen
        for _ in range(3):
            if screen.focus("CapCut"):
                try:
                    screen.send_keys("%{F4}", expect="CapCut")
                except VeditError:
                    pass
            if gone_within(timeout / 3):
                return True
    elif IS_MAC:
        subprocess.run(["osascript", "-e", 'quit app "CapCut"'], capture_output=True)
        if gone_within(timeout):
            return True
    if force:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/IM", "CapCut.exe", "/F"], capture_output=True)
        elif IS_MAC:
            subprocess.run(["pkill", "-x", "CapCut"], capture_output=True)
        time.sleep(1.0)
    return not is_running()


def launch_app() -> None:
    exe = app_path()
    if not exe:
        raise VeditError("CapCut executable not found; set `capcut.app_path` in config.")
    if IS_WINDOWS:
        subprocess.Popen([str(exe)], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0), close_fds=True)
    elif IS_MAC:
        subprocess.Popen(["open", "-a", str(exe)])


# ------------------------------------------------------------------ project inspection

@dataclass
class ProjectInfo:
    name: str
    path: Path
    duration: float
    modified: float
    timeline_id: str | None
    registered: bool

    def to_dict(self) -> dict:
        return {"name": self.name, "path": str(self.path), "duration_s": round(self.duration, 3),
                "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(self.modified)),
                "timeline_id": self.timeline_id, "registered": self.registered}


def _main_timeline_dir(project: Path) -> Path | None:
    pj = read_json(project / "Timelines" / "project.json")
    if pj and pj.get("main_timeline_id"):
        cand = project / "Timelines" / pj["main_timeline_id"]
        if cand.is_dir():
            return cand
    return None


def content_path(project: Path) -> Path:
    """Authoritative draft_content.json: nested main timeline when present, else the root copy."""
    nested = _main_timeline_dir(project)
    if nested and (nested / "draft_content.json").exists():
        return nested / "draft_content.json"
    return project / "draft_content.json"


def read_content(project: str | Path) -> dict:
    p = resolve_project(project)
    data = read_json(content_path(p))
    if data is None:
        raise VeditError(f"No draft_content.json in {p}")
    return data


def resolve_project(name_or_path: str | Path) -> Path:
    p = Path(name_or_path)
    if p.is_dir():
        return p
    cand = drafts_root() / str(name_or_path)
    if cand.is_dir():
        return cand
    raise VeditError(f"CapCut project not found: {name_or_path}")


def list_projects() -> list[ProjectInfo]:
    root = drafts_root()
    meta = read_json(root / "root_meta_info.json", default={}) or {}
    registered = {Path(e.get("draft_fold_path", "")).name for e in meta.get("all_draft_store", [])}
    out = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if not (d / "draft_content.json").exists() and not (d / "draft_meta_info.json").exists():
            continue
        dm = read_json(d / "draft_meta_info.json", default={}) or {}
        pj = read_json(d / "Timelines" / "project.json", default={}) or {}
        out.append(ProjectInfo(
            name=d.name, path=d, duration=(dm.get("tm_duration") or 0) / 1e6,
            modified=(dm.get("tm_draft_modified") or 0) / 1e6 or d.stat().st_mtime,
            timeline_id=pj.get("main_timeline_id"), registered=d.name in registered,
        ))
    return sorted(out, key=lambda p: p.modified, reverse=True)


# ------------------------------------------------------------------ calibration

def calibrate(project: str | None = None) -> dict:
    """Copy a blank, app-created project into personal/capcut/seed and record the app's schema markers."""
    root = drafts_root()
    projects = list_projects()
    if not projects:
        raise VeditError("No CapCut projects found. Open CapCut, click 'Create project', then close it and retry.")
    if project:
        chosen = resolve_project(project)
    else:
        blanks = [p for p in projects if p.duration == 0]
        chosen = (blanks or projects)[0].path
    content = read_content(chosen)
    if content.get("tracks"):
        print(f"note: '{chosen.name}' is not empty; its tracks are stripped from the seed.")
    seed = seed_dir()
    if seed.exists():
        shutil.rmtree(seed)
    shutil.copytree(chosen, seed, ignore=shutil.ignore_patterns("*.jpg", "*.png", "Resources", "*.log"))
    # Strip any media so the seed is a clean blank timeline.
    for mirror in _content_files(seed):
        data = read_json(mirror)
        if isinstance(data, dict) and "materials" in data:
            data["tracks"] = []
            data["materials"] = {k: [] if isinstance(v, list) else v for k, v in data["materials"].items()}
            data["duration"] = 0
            write_json(mirror, data, indent=None)
    meta_root = read_json(root / "root_meta_info.json", default={}) or {}
    entry = next((e for e in meta_root.get("all_draft_store", []) if Path(e.get("draft_fold_path", "")).name == chosen.name),
                 None)
    info = {
        "seed_from": chosen.name,
        "app_version": (content.get("platform") or {}).get("app_version"),
        "draft_version": content.get("version"),
        "new_version": content.get("new_version"),
        "nested_timelines": (seed / "Timelines" / "project.json").exists(),
        "root_meta_entry_template": entry,
        "calibrated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    write_json(personal_dir() / "capcut" / "calibration.json", info)
    config.save_user_values({"capcut": {"seed": str(seed), "app_version": info["app_version"]}})
    return info


def calibration() -> dict:
    info = read_json(personal_dir() / "capcut" / "calibration.json")
    if not info or not seed_dir().exists():
        raise VeditError("CapCut is not calibrated yet. Run `vedit capcut calibrate` (needs one empty CapCut project).")
    return info


def _content_files(project: Path) -> list[Path]:
    files = [project / m for m in CONTENT_MIRRORS if (project / m).exists()]
    tdir = project / "Timelines"
    if tdir.is_dir():
        for sub in tdir.iterdir():
            if sub.is_dir():
                files += [sub / m for m in CONTENT_MIRRORS if (sub / m).exists()]
    return files


def seed_content() -> dict:
    calibration()
    return read_json(content_path(seed_dir()))


# ------------------------------------------------------------------ create / register

def _fwd(p: Path) -> str:
    return str(p).replace("\\", "/")


def create_project(name: str, built: dict[str, Any], *, overwrite: bool = False, register: bool = True,
                   allow_running: bool = False) -> Path:
    """Materialise `built` (tracks + materials + canvas from builder.py) as a new CapCut project."""
    info = calibration()
    root = drafts_root()
    if is_running() and not allow_running:
        raise VeditError("CapCut is running. Close it first (`vedit capcut close`) so it does not overwrite the "
                         "project index, then retry. CapCut autosaves, so closing is safe.")
    dest = root / name
    if dest.exists():
        if not overwrite:
            raise VeditError(f"CapCut project '{name}' already exists (use --overwrite to replace it).")
        _unregister(dest)
        shutil.rmtree(dest)
    shutil.copytree(seed_dir(), dest)

    now_us = int(time.time() * 1e6)
    timeline_id = new_uuid()
    project_id = new_uuid()
    meta_id = new_uuid()

    # Rename the nested timeline folder and point project.json / layout at it.
    old_tid = None
    pj_path = dest / "Timelines" / "project.json"
    if pj_path.exists():
        pj = read_json(pj_path)
        old_tid = pj.get("main_timeline_id")
        if old_tid and (dest / "Timelines" / old_tid).is_dir():
            (dest / "Timelines" / old_tid).rename(dest / "Timelines" / timeline_id)
        pj["id"] = project_id
        pj["main_timeline_id"] = timeline_id
        pj["create_time"] = pj["update_time"] = now_us
        for tl in pj.get("timelines", []):
            if tl.get("id") == old_tid or len(pj.get("timelines", [])) == 1:
                tl["id"] = timeline_id
                tl["create_time"] = tl["update_time"] = now_us
        for target in (pj_path, pj_path.with_name("project.json.bak")):
            if target.exists() or target == pj_path:
                write_json(target, pj, indent=None)
    layout_path = dest / "timeline_layout.json"
    if layout_path.exists():
        layout = read_json(layout_path)
        for dock in layout.get("dockItems", []):
            dock["timelineIds"] = [timeline_id if t == old_tid else t for t in dock.get("timelineIds", [])] or [timeline_id]
        write_json(layout_path, layout, indent=None)

    content = merge_content(read_json(content_path(seed_dir())), built, timeline_id=timeline_id, now_us=now_us)
    for mirror in _content_files(dest):
        write_json(mirror, content, indent=None)
    if not (dest / "draft_content.json").exists():
        write_json(dest / "draft_content.json", content, indent=None)

    duration_us = int(content.get("duration", 0))
    meta_path = dest / "draft_meta_info.json"
    meta = read_json(meta_path, default={}) or {}
    meta.update({
        "draft_id": meta_id, "draft_name": name,
        "draft_fold_path": _fwd(dest), "draft_root_path": str(root),
        "tm_draft_create": now_us, "tm_draft_modified": now_us, "tm_duration": duration_us,
    })
    write_json(meta_path, meta, indent=None)
    settings = dest / "draft_settings"
    if settings.exists():
        secs = int(now_us / 1e6)
        settings.write_text(f"[General]\ndraft_create_time={secs}\ndraft_last_edit_time={secs}\n"
                            f"real_edit_seconds=0\nreal_edit_keys=0\n", encoding="utf-8")
    if register:
        _register(dest, meta, info)
    return dest


def merge_content(seed: dict, built: dict, *, timeline_id: str, now_us: int) -> dict:
    out = copy.deepcopy(seed)
    out["id"] = timeline_id
    out["duration"] = int(built.get("duration", 0))
    out["fps"] = float(built.get("fps", out.get("fps", 30.0)))
    canvas = dict(out.get("canvas_config") or {})
    canvas.update({k: v for k, v in (built.get("canvas_config") or {}).items() if k in ("width", "height", "ratio")})
    out["canvas_config"] = canvas
    out.setdefault("config", {})
    for key, value in (built.get("config") or {}).items():
        out["config"][key] = value
    materials = out.setdefault("materials", {})
    for key, value in (built.get("materials") or {}).items():
        materials[key] = value
    out["tracks"] = built.get("tracks", [])
    out["keyframes"] = built.get("keyframes", out.get("keyframes"))
    for key in ("create_time", "update_time"):
        if key in out:
            out[key] = int(now_us / 1e6) if (out.get(key) or 0) < 1e11 else now_us
    return out


def _register(project: Path, meta: dict, info: dict) -> None:
    root = project.parent
    index_path = root / "root_meta_info.json"
    index = read_json(index_path, default=None) or {"all_draft_store": [], "draft_ids": 0, "root_path": _fwd(root)}
    template = copy.deepcopy(info.get("root_meta_entry_template") or {})
    entry = template or {}
    entry.update({
        "draft_cover": f"{_fwd(project)}\\draft_cover.jpg",
        "draft_fold_path": _fwd(project),
        "draft_id": meta["draft_id"],
        "draft_json_file": f"{_fwd(project)}\\draft_content.json",
        "draft_name": meta["draft_name"],
        "draft_root_path": str(root),
        "tm_draft_create": meta["tm_draft_create"],
        "tm_draft_modified": meta["tm_draft_modified"],
        "tm_draft_removed": 0,
        "tm_duration": meta["tm_duration"],
    })
    store = [e for e in index.get("all_draft_store", []) if Path(e.get("draft_fold_path", "")).name != project.name]
    store.insert(0, entry)
    index["all_draft_store"] = store
    index["draft_ids"] = len(store)
    write_json(index_path, index, indent=None)


def _unregister(project: Path) -> None:
    index_path = project.parent / "root_meta_info.json"
    index = read_json(index_path)
    if not index:
        return
    store = [e for e in index.get("all_draft_store", []) if Path(e.get("draft_fold_path", "")).name != project.name]
    index["all_draft_store"] = store
    index["draft_ids"] = len(store)
    write_json(index_path, index, indent=None)


def snapshot(project: str | Path, dest: str | Path) -> Path:
    """Save the current authoritative content (for learn-from-edits diffs)."""
    return write_json(dest, read_content(project), indent=None)


def dumps_pretty(project: str | Path) -> str:
    return json.dumps(read_content(project), ensure_ascii=False, indent=2)
