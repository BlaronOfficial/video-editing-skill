"""Filesystem locations. All OS-specific paths live here so macOS support is one module away."""

from __future__ import annotations

import os
import platform
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
"""Repository root == skill root (contains SKILL.md)."""

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"


def personal_dir() -> Path:
    """Per-user data (git-ignored). Override with VEDIT_PERSONAL_DIR, e.g. to share across clones."""
    override = os.environ.get("VEDIT_PERSONAL_DIR")
    path = Path(override).expanduser() if override else SKILL_ROOT / "personal"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = SKILL_ROOT / ".cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def fonts_dir() -> Path:
    path = cache_dir() / "fonts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def mg_dir() -> Path:
    return SKILL_ROOT / "mg"


def presets_dir() -> Path:
    return SKILL_ROOT / "presets"


def templates_dir() -> Path:
    return SKILL_ROOT / "templates"


# ---------------------------------------------------------------- CapCut

def capcut_drafts_root_default() -> Path | None:
    """Where CapCut desktop (international) keeps its drafts on this OS."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
    elif IS_MAC:
        return Path.home() / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
    return None


def capcut_app_candidates() -> list[Path]:
    """Possible CapCut executables, newest version folder first."""
    found: list[Path] = []
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA")
        if base:
            apps = Path(base) / "CapCut" / "Apps"
            if apps.is_dir():
                versions = sorted(
                    (p for p in apps.iterdir() if p.is_dir() and (p / "CapCut.exe").exists()),
                    key=lambda p: [int(x) if x.isdigit() else 0 for x in p.name.split(".")],
                    reverse=True,
                )
                found += [v / "CapCut.exe" for v in versions]
                if (apps / "CapCut.exe").exists():
                    found.append(apps / "CapCut.exe")
    elif IS_MAC:
        found.append(Path("/Applications/CapCut.app"))
    return found


def chrome_candidates() -> list[Path]:
    """Chromium-based browsers usable for headless motion-graphics rendering."""
    if IS_WINDOWS:
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        return [
            Path(pf) / "Google/Chrome/Application/chrome.exe",
            Path(pf86) / "Google/Chrome/Application/chrome.exe",
            Path(local) / "Google/Chrome/Application/chrome.exe",
            Path(pf86) / "Microsoft/Edge/Application/msedge.exe",
            Path(pf) / "Microsoft/Edge/Application/msedge.exe",
        ]
    if IS_MAC:
        return [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ]
    return [Path("/usr/bin/google-chrome"), Path("/usr/bin/chromium"), Path("/usr/bin/chromium-browser")]
