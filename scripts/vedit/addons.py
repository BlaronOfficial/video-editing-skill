"""Optional add-ons: everything beyond the free standalone core.

Each entry says what it is for, whether it costs money, its licence and size, and how to check and
install it. `vedit doctor` and `vedit capabilities` report them; nothing here is required for READY.
The route planner (routes.py) reads availability from here when ranking ways to make something.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config
from .paths import IS_MAC, IS_WINDOWS, SKILL_ROOT, cache_dir, mg_dir, personal_dir


@dataclass
class Addon:
    id: str
    name: str
    kind: str                      # app | service | model | tool | engine
    cost: str                      # free | paid | freemium
    used_for: str
    licence: str = ""
    size_mb: float | None = None
    install: str = ""
    check: Callable[[], tuple[bool, str]] = field(default=lambda: (False, "not checked"))


# ------------------------------------------------------------------ finders

def _first_existing(paths: list[Path]) -> Path | None:
    return next((p for p in paths if p and p.exists()), None)


def find_resolve() -> Path | None:
    if IS_WINDOWS:
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        return _first_existing([Path(pf) / "Blackmagic Design" / "DaVinci Resolve" / "Resolve.exe"])
    if IS_MAC:
        return _first_existing([Path("/Applications/DaVinci Resolve/DaVinci Resolve.app"),
                                Path("/Applications/DaVinci Resolve Studio/DaVinci Resolve.app")])
    return _first_existing([Path("/opt/resolve/bin/resolve")])


def resolve_is_studio(exe: Path) -> bool | None:
    """Studio vs free from the executable's product name (Windows) or app folder (macOS)."""
    if IS_MAC:
        return "Studio" in str(exe)
    if not IS_WINDOWS:
        return None
    from .util import run
    ps = f"(Get-Item '{exe}').VersionInfo.ProductName"
    try:
        out = run(["powershell", "-NoProfile", "-Command", ps], check=False, timeout=20).stdout or ""
    except Exception:
        return None
    return "studio" in out.lower() if out.strip() else None


def find_losslesscut() -> Path | None:
    on_path = shutil.which("LosslessCut") or shutil.which("losslesscut")
    if on_path:
        return Path(on_path)
    cands: list[Path] = [cache_dir() / "tools" / "losslesscut" / "LosslessCut.exe"]
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        cands += [Path(local) / "Programs" / "LosslessCut" / "LosslessCut.exe",
                  Path(pf) / "LosslessCut" / "LosslessCut.exe",
                  Path(local) / "Microsoft" / "WindowsApps" / "LosslessCut.exe"]
    elif IS_MAC:
        cands.append(Path("/Applications/LosslessCut.app/Contents/MacOS/LosslessCut"))
    return _first_existing(cands)


def find_blender() -> Path | None:
    on_path = shutil.which("blender")
    if on_path:
        return Path(on_path)
    if IS_WINDOWS:
        root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Blender Foundation"
        if root.is_dir():
            versions = sorted((d for d in root.iterdir() if (d / "blender.exe").exists()), reverse=True)
            if versions:
                return versions[0] / "blender.exe"
    if IS_MAC:
        return _first_existing([Path("/Applications/Blender.app/Contents/MacOS/Blender")])
    return None


def tool_python(name: str) -> Path | None:
    """Python of an isolated tool venv under .cache/tools/<name>/ (heavy or GPL tools live there)."""
    base = cache_dir() / "tools" / name / "venv"
    exe = base / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
    return exe if exe.exists() else None


# ------------------------------------------------------------------ checks

def _capcut() -> tuple[bool, str]:
    from .capcut import store
    try:
        root = store.drafts_root()
    except Exception as exc:
        return False, f"not found ({exc})"
    calibrated = (personal_dir() / "capcut" / "calibration.json").exists()
    ver = store.installed_version() or "unknown"
    return calibrated, f"CapCut {ver}, drafts at {root}" + ("" if calibrated else "; not calibrated (`vedit capcut calibrate`)")


def _resolve() -> tuple[bool, str]:
    exe = find_resolve()
    if not exe:
        return False, "not installed (free: blackmagicdesign.com/products/davinciresolve)"
    studio = resolve_is_studio(exe)
    edition = "Studio" if studio else "Free" if studio is False else "edition unknown"
    return True, f"{edition} at {exe}"


def _resolve_studio() -> tuple[bool, str]:
    exe = find_resolve()
    if not exe:
        return False, "Resolve not installed"
    studio = resolve_is_studio(exe)
    return bool(studio), "Studio: live scripting + built-in MCP" if studio else "free edition: use the import package"


def _which(name: str, detail: str = "") -> Callable[[], tuple[bool, str]]:
    def check() -> tuple[bool, str]:
        exe = shutil.which(name)
        return (True, exe) if exe else (False, detail or "not on PATH")
    return check


def _found(fn: Callable[[], Path | None], missing: str) -> Callable[[], tuple[bool, str]]:
    def check() -> tuple[bool, str]:
        p = fn()
        return (True, str(p)) if p else (False, missing)
    return check


def _secret(name: str) -> Callable[[], tuple[bool, str]]:
    def check() -> tuple[bool, str]:
        return (True, "key set") if config.secret(name) else (False, f"no key (`vedit secret set {name} <key>`)")
    return check


def _remotion() -> tuple[bool, str]:
    ok = (mg_dir() / "remotion" / "node_modules" / "remotion").exists()
    return ok, "installed" if ok else "installs on first use (npm, ~150 MB)"


def _earshot_kits() -> tuple[bool, str]:
    py = tool_python("earshot")
    return (True, f"tool venv {py.parent.parent}") if py else (False, "`vedit setup earshot` (~60 MB, no models)")


def _earshot_ears() -> tuple[bool, str]:
    hub = cache_dir() / "earshot" / "hf"
    ok = hub.is_dir() and any(hub.glob("models--*"))
    return ok, "listening models cached" if ok else "`vedit setup earshot --ears` (~1.3 GB incl. torch CPU)"


ADDONS: list[Addon] = [
    Addon("capcut", "CapCut desktop", "app", "freemium", "editable CapCut project hand-off; CapCut-only effects",
          "proprietary (Pro resources paid)", None, "Install CapCut, make one empty project, `vedit capcut calibrate`",
          _capcut),
    Addon("resolve", "DaVinci Resolve", "app", "free", "FCPXML/OTIO import package; screen control; learn from edits",
          "proprietary (free edition)", 3000, "blackmagicdesign.com -> DaVinci Resolve (free)", _resolve),
    Addon("resolve_studio", "DaVinci Resolve Studio", "app", "paid", "live timeline/grade/render control, Fusion, MCP",
          "proprietary ($295 one-time)", None, "Studio licence; Preferences > System > General > External scripting: Local",
          _resolve_studio),
    Addon("losslesscut", "LosslessCut", "app", "free", "fine-tune cuts in a free app (.llc round trip, HTTP API)",
          "GPL-2.0 (separate app)", 110, "github.com/mifi/lossless-cut/releases (portable) or winget mifi.losslesscut",
          _found(find_losslesscut, "not installed")),
    Addon("blender", "Blender", "app", "free", "real 3D titles, logos, product shots, fly-throughs (headless)",
          "GPL (separate app)", 350, "winget install BlenderFoundation.Blender", _found(find_blender, "not installed")),
    Addon("earshot_kits", "earshot sound kits", "tool", "free", "252 code-made SFX with measured sync points",
          "MIT", 60, "`vedit setup earshot`", _earshot_kits),
    Addon("earshot_ears", "earshot ears", "model", "free", "listening QA, pick sounds by description",
          "MIT code; CLAP Apache-2.0, AST BSD-3", 1300, "`vedit setup earshot --ears`", _earshot_ears),
    Addon("remotion", "Remotion", "engine", "freemium", "React motion graphics",
          "Remotion licence (free for individuals / teams up to 3)", 150, "auto on first use", _remotion),
    Addon("elevenlabs", "ElevenLabs", "service", "paid", "Scribe transcription, premium TTS, voice clone",
          "commercial API", None, "`vedit secret set elevenlabs <key>`", _secret("elevenlabs")),
    Addon("higgsfield", "Higgsfield", "service", "paid", "AI B-roll, VFX, hero shots (credits)",
          "commercial", None, "`npm i -g @higgsfield/cli && higgsfield auth login`",
          _which("higgsfield", "CLI not installed")),
    Addon("pexels", "Pexels API", "service", "free", "free stock video/photos", "Pexels licence", None,
          "free key at pexels.com/api, then `vedit secret set pexels <key>`", _secret("pexels")),
    Addon("pixabay", "Pixabay API", "service", "free", "free stock video/photos", "Pixabay licence", None,
          "free key at pixabay.com/api/docs, then `vedit secret set pixabay <key>`", _secret("pixabay")),
    Addon("gemini_api", "Gemini API", "service", "freemium", "image generation / video critique via API",
          "Google terms", None, "free key at aistudio.google.com, then `vedit secret set gemini <key>`",
          _secret("gemini")),
    Addon("git", "git (updates)", "tool", "free", "`vedit update`", "GPL", None, "install git; clone the skill",
          lambda: (bool(shutil.which("git")) and (SKILL_ROOT / ".git").exists(), "")),
]


def get(addon_id: str) -> Addon | None:
    return next((a for a in ADDONS if a.id == addon_id), None)


def enabled(addon_id: str) -> bool:
    return config.load().get("addons", {}).get(addon_id, {}).get("enabled", True)


def status(addon: Addon) -> dict:
    try:
        ok, detail = addon.check()
    except Exception as exc:          # a broken optional integration must never break the core
        ok, detail = False, f"check failed: {exc}"
    return {"id": addon.id, "name": addon.name, "ok": ok, "detail": detail, "kind": addon.kind, "cost": addon.cost,
            "used_for": addon.used_for, "licence": addon.licence, "size_mb": addon.size_mb,
            "enabled": enabled(addon.id), "install": "" if ok else addon.install}


def check_all() -> list[dict]:
    from . import extensions
    rows = [status(a) for a in ADDONS]
    rows += extensions.addon_rows()
    return rows
