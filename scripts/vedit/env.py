"""Where vedit runs and what works there, plus the two bridges to the Claude app.

Surfaces
  claude-code-windows   Claude Code (or a terminal) on the owner's Windows PC: everything
  claude-app-mcp        the Claude desktop app calling vedit as a local MCP server: everything, natively
  claude-app-vm         the Claude app's remote device tools: a Linux VM with the skill folder mounted
                        (no CapCut, screen control or Resolve live; the engine keeps its own VM venv)
  macos                 works in principle, untested
  lite                  no engine reachable (phone / web): planning, writing, Studio review (launcher only)

    vedit env                 detect, report what works and what to set up
    vedit env mcp [--install] register vedit in the Claude desktop app's config (backup first; ask the owner)
    vedit env launcher        build the Claude-app launcher skill (zip to upload in claude.ai settings)
"""

from __future__ import annotations

import glob
import json
import os
import platform
import re
import shutil
import time
import zipfile
from pathlib import Path

from .paths import IS_MAC, IS_WINDOWS, SKILL_ROOT
from .util import VeditError, read_json, write_json

LAUNCHER_VERSION = "v2.1"
LAUNCHER_SRC = SKILL_ROOT / "app" / "claude-app" / "video-editing" / "SKILL.md"

WORKS = {
    "claude-code-windows": {"everything": True, "limits": []},
    "claude-app-mcp": {"everything": True, "limits": ["looking at images goes through view_image"]},
    "claude-app-vm": {"everything": False, "limits": ["CapCut build/learn", "screen control", "Resolve live import",
                                                      "installing fonts into Windows"]},
    "macos": {"everything": False, "limits": ["untested", "CapCut and Resolve paths not verified"]},
    "linux": {"everything": False, "limits": ["CapCut and Resolve are not available on Linux"]},
}


def surface() -> str:
    if os.environ.get("VEDIT_SURFACE"):
        return os.environ["VEDIT_SURFACE"]
    system = platform.system()
    if system == "Windows":
        return "claude-code-windows"
    if system == "Darwin":
        return "macos"
    shared = "/mnt/" in str(SKILL_ROOT) or (SKILL_ROOT / "scripts" / ".venv" / "Scripts" / "python.exe").exists()
    return "claude-app-vm" if shared else "linux"


# ------------------------------------------------------------------ Claude desktop app (local MCP)

def desktop_config_path() -> Path:
    """The Claude desktop app's config file. The Microsoft Store build keeps it under
    %LOCALAPPDATA%\\Claude-Data\\claude_<id>\\ (not %APPDATA%\\Claude)."""
    home = Path.home()
    if IS_WINDOWS:
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        cands = [Path(p) for p in sorted(glob.glob(str(local / "Claude-Data" / "claude_*" / "claude_desktop_config.json")))]
        cands += [roaming / "Claude" / "claude_desktop_config.json"]
        cands += [Path(p) for p in glob.glob(str(local / "Packages" / "Claude_*" / "LocalCache" / "Roaming" / "Claude" /
                                                 "claude_desktop_config.json"))]
        existing = [c for c in cands if c.exists()]
        if existing:
            return existing[0]
        data_dirs = sorted(glob.glob(str(local / "Claude-Data" / "claude_*")))
        return Path(data_dirs[0]) / "claude_desktop_config.json" if data_dirs else roaming / "Claude" / "claude_desktop_config.json"
    if IS_MAC:
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def mcp_entry() -> dict:
    """How the app should start vedit: uv runs the engine from this skill folder (no batch file, quiet stdio)."""
    uv = shutil.which("uv")
    if not uv:
        raise VeditError("uv is required to run vedit (https://docs.astral.sh/uv/)")
    return {"command": str(Path(uv).resolve()),
            "args": ["run", "--frozen", "--quiet", "--project", str(SKILL_ROOT / "scripts"), "vedit", "mcp"],
            "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}}


def mcp_status() -> dict:
    path = desktop_config_path()
    cfg = read_json(path, default=None) if path.exists() else None
    entry = ((cfg or {}).get("mcpServers") or {}).get("vedit")
    want = mcp_entry() if shutil.which("uv") else None
    return {"config": str(path), "config_exists": path.exists(), "registered": bool(entry),
            "current": bool(entry) and want is not None and entry.get("args") == want["args"]
                      and Path(entry.get("command", "")).resolve() == Path(want["command"]).resolve()}


def desktop_app_running() -> bool:
    """Is the Claude desktop app open? It keeps its config in memory and writes it back when settings change,
    which drops an entry added while it runs (seen with the Microsoft Store build)."""
    import subprocess
    if IS_WINDOWS:
        p = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-Process -Name Claude -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }"],
                           capture_output=True, text=True, timeout=60)
        return any(("WindowsApps" in l or "AnthropicClaude" in l) and l.lower().endswith("claude.exe")
                   for l in (p.stdout or "").splitlines())
    if IS_MAC:
        p = subprocess.run(["pgrep", "-x", "Claude"], capture_output=True, text=True)
        return bool(p.stdout.strip())
    return False


def install_mcp(*, dry_run: bool = False, force: bool = False, path: Path | None = None,
                while_running: bool = False) -> dict:
    """Add (or update) `mcpServers.vedit` in the desktop app's config, keeping every other key. A dated backup
    is written first. The app must be closed (it overwrites the file from memory); the owner starts it after."""
    if path is None and not dry_run and not while_running and desktop_app_running():
        raise VeditError("The Claude desktop app is open: it rewrites its config from memory and would drop the entry. "
                         "Quit it fully (tray icon too), then run `vedit env mcp --install`, then start it again.")
    path = Path(path) if path else desktop_config_path()
    cfg = (read_json(path, default=None) if path.exists() else None) or {}
    if not isinstance(cfg, dict):
        raise VeditError(f"{path} is not a JSON object; not touching it")
    servers = cfg.get("mcpServers") or {}
    entry = mcp_entry()
    old = servers.get("vedit")
    if old == entry:
        return {"config": str(path), "changed": False, "note": "already registered"}
    if old and not force and Path(old.get("command", "")).name.lower() not in ("uv.exe", "uv", "vedit.cmd", "vedit"):
        raise VeditError(f"A different 'vedit' MCP server is registered ({old.get('command')}); pass --force to replace it")
    plan = {"config": str(path), "add" if not old else "update": {"mcpServers": {"vedit": entry}}}
    if dry_run:
        return {**plan, "dry_run": True}
    backup = None
    if path.exists():
        backup = path.with_name(path.name + time.strftime(".vedit-bak-%Y%m%d-%H%M%S"))
        shutil.copy2(path, backup)
    new = dict(cfg)
    new["mcpServers"] = {**servers, "vedit": entry}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(new, indent=2, ensure_ascii=False), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))            # never leave a broken config behind
    tmp.replace(path)
    return {**plan, "changed": True, "backup": str(backup) if backup else None,
            "next": "Quit the Claude desktop app completely (tray icon too) and start it again; vedit's tools then "
                    "appear in chats, and the Studio's live link works there."}


def code_mcp_status() -> dict:
    """Claude Code's user-scope MCP servers (~/.claude.json)."""
    cfg = read_json(Path.home() / ".claude.json", default={}) or {}
    return {"registered": "vedit" in (cfg.get("mcpServers") or {})}


# ------------------------------------------------------------------ Claude-app launcher skill

def mount_name(skill_path: Path) -> str:
    return skill_path.name


def launcher_text(skill_path: Path | None = None) -> str:
    p = Path(skill_path) if skill_path else SKILL_ROOT
    text = LAUNCHER_SRC.read_text(encoding="utf-8")
    return (text.replace("{{SKILL_PATH}}", str(p)).replace("{{MOUNT_NAME}}", mount_name(p))
            .replace("{{LAUNCHER_VERSION}}", LAUNCHER_VERSION))


def build_launcher(out: str | Path | None = None, skill_path: str | Path | None = None) -> dict:
    """A zip with video-editing/SKILL.md for claude.ai -> Settings -> Capabilities -> Skills (replace the old one)."""
    out = Path(out) if out else SKILL_ROOT / "app" / "claude-app" / "video-editing.zip"
    text = launcher_text(Path(skill_path) if skill_path else None)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("video-editing/SKILL.md", text)
    desc = next((l for l in text.splitlines() if l.startswith("description:")), "")
    return {"zip": str(out), "version": LAUNCHER_VERSION, "description_chars": len(desc) - len("description: "),
            "skill_path": str(Path(skill_path) if skill_path else SKILL_ROOT),
            "next": "Upload it in claude.ai: Settings -> Capabilities -> Skills -> replace 'video-editing'."}


def launcher_status(home: Path | None = None) -> dict:
    """Synced copies of the launcher in this account (Claude Code mirrors claude.ai skills under ~/.claude/skills/synced)."""
    rows = []
    for f in glob.glob(str((home or Path.home()) / ".claude" / "skills" / "synced" / "*" / "video-editing" / "SKILL.md")):
        text = Path(f).read_text(encoding="utf-8", errors="replace")
        m = re.search(r"Launcher (v\d+(?:\.\d+)*)", text)
        version = f"official {m.group(1)}" if m else "hand-made (v1)"
        points = next((l.split("`")[1] for l in text.splitlines() if "C:\\" in l and "`" in l), "")
        rows.append({"file": f, "kind": version, "points_to": points,
                     "points_here": str(SKILL_ROOT).lower() in text.lower()})
    current = any(r["kind"].startswith("official") and LAUNCHER_VERSION in r["kind"] and r["points_here"] for r in rows)
    return {"copies": rows, "current": current}


# ------------------------------------------------------------------ report

def report(*, brief: bool = False) -> dict:
    surf = surface()
    out = {"surface": surf, "system": f"{platform.system()} {platform.release()} ({platform.machine()})",
           "python": platform.python_version(), "skill": str(SKILL_ROOT), **WORKS.get(surf, {})}
    venv = os.environ.get("UV_PROJECT_ENVIRONMENT") or os.environ.get("VIRTUAL_ENV") or ""
    out["engine_env"] = venv or str(SKILL_ROOT / "scripts" / ".venv")
    if brief:
        return out
    from .doctor import check
    doc = check()
    out["engine_ready"] = doc["ready"]
    out["missing_core"] = [i["item"] for i in doc["items"] if i["required"] and not i["ok"]]
    if surf in ("claude-code-windows", "macos"):
        out["claude_app_mcp"] = mcp_status()
        out["claude_code_mcp"] = code_mcp_status()
        out["launcher"] = launcher_status()
    todo = []
    if not out["engine_ready"]:
        todo.append("vedit setup (then vedit doctor)")
    if out.get("claude_app_mcp") and not out["claude_app_mcp"]["current"]:
        todo.append("vedit env mcp --install (ask the owner; then restart the Claude app)")
    if out.get("launcher") and not out["launcher"]["current"]:
        todo.append("vedit env launcher, then the owner uploads the zip in claude.ai settings (replaces the old launcher)")
    if out.get("claude_app_mcp") and not out["claude_app_mcp"]["current"]:
        out["claude_app_running"] = desktop_app_running()
    out["next"] = todo
    return out


# ------------------------------------------------------------------ CLI

def register_cli(sp) -> None:
    s = sp.add_parser("env", help="where vedit runs, what works there, Claude-app MCP and launcher")
    s.add_argument("action", nargs="?", default="report", choices=["report", "mcp", "launcher"])
    s.add_argument("--brief", action="store_true"); s.add_argument("--install", action="store_true")
    s.add_argument("--dry-run", action="store_true"); s.add_argument("--force", action="store_true")
    s.add_argument("--config", help="mcp: a config file to edit instead of the app's (tests)")
    s.add_argument("--out"); s.add_argument("--skill-path", help="launcher: the skill folder as the owner's PC sees it")
    s.set_defaults(fn=_cmd)


def _cmd(a) -> None:
    from .util import print_json
    if a.action == "report":
        print_json(report(brief=a.brief))
    elif a.action == "mcp":
        if a.install or a.dry_run:
            print_json(install_mcp(dry_run=a.dry_run or not a.install, force=a.force,
                                   path=Path(a.config) if a.config else None))
        else:
            print_json({**mcp_status(), "entry": mcp_entry()})
    else:
        print_json(build_launcher(a.out, a.skill_path))
