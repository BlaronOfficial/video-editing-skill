"""Capability map: what this machine and this Claude session can use right now.

Two halves:
  engine   probed here: OS, core tools, encoders, add-ons, models, hardware, measured bandwidth.
  session  recorded by Claude, which can see what the engine cannot: its own tool list (MCP connectors
           such as Canva or Google Drive, Claude in Chrome / the Claude app browser / Kapture / browser-use,
           computer use) and which web AI services the owner is logged into (checked in a new tab).
           `vedit capabilities record ...` stores it; `vedit capabilities outcome ...` keeps a worked/failed
           history so the route planner learns which routes are reliable here.
Everything lands in personal/capabilities.json (git-ignored).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .paths import IS_MAC, IS_WINDOWS, SKILL_ROOT, fonts_dir, mg_dir, personal_dir
from .util import read_json, which, write_json

CACHE_TTL = 6 * 3600


def _path() -> Path:
    return personal_dir() / "capabilities.json"


def environment() -> dict:
    env = {"os": f"{platform.system()} {platform.release()}", "python": platform.python_version(),
           "machine": platform.machine(), "skill_root": str(SKILL_ROOT)}
    # The Claude app runs vedit in a Linux VM with the owner's folders mounted under ~/mnt.
    if platform.system() == "Linux" and Path.home().joinpath("mnt").is_dir():
        env["surface"] = "claude-app-device-vm"
    elif platform.system() == "Linux" and os.environ.get("CLAUDE_CODE_REMOTE"):
        env["surface"] = "cloud-sandbox"
    else:
        env["surface"] = "local"
    return env


def hardware() -> dict:
    out: dict = {"cpus": os.cpu_count()}
    try:
        import psutil  # optional
        out["ram_gb"] = round(psutil.virtual_memory().total / 1e9, 1)
    except Exception:
        pass
    if IS_WINDOWS:
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "(Get-CimInstance Win32_VideoController).Name -join '; '"],
                               capture_output=True, text=True, timeout=20)
            out["gpu"] = (r.stdout or "").strip()
        except Exception:
            pass
    free = shutil.disk_usage(str(SKILL_ROOT)).free / 1e9
    out["disk_free_gb"] = round(free, 1)
    return out


def core() -> dict:
    from .media import available_encoders, encoder_works
    from .mg import chrome, renderer_ready
    ff = which("ffmpeg")
    filters = ""
    if ff:
        filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    encoders = sorted(e for e in available_encoders() if e in ("h264_qsv", "h264_nvenc", "h264_amf",
                                                              "h264_videotoolbox", "hevc_qsv", "av1_qsv"))
    working = [e for e in encoders if encoder_works(e)]
    whisper_root = SKILL_ROOT / ".cache" / "whisper"
    whisper = sorted(p.name.split("--")[-1] for p in whisper_root.glob("models--*")) if whisper_root.is_dir() else []
    return {
        "ffmpeg": bool(ff), "libass": " subtitles " in filters, "vidstab": "vidstabdetect" in filters,
        "hw_encoders": working, "node": bool(which("node")), "chrome": str(chrome() or ""),
        "mg_renderer": renderer_ready(), "fonts": len(list(fonts_dir().glob("*.ttf"))),
        "whisper_models": whisper, "three_js": (mg_dir() / "renderer" / "node_modules" / "three").exists(),
    }


def collect(*, refresh: bool = False) -> dict:
    """Engine half (cached for a few hours) merged with the session half Claude recorded."""
    from . import addons, models
    data = read_json(_path(), default={}) or {}
    engine = data.get("engine")
    if refresh or not engine or time.time() - engine.get("probed_ts", 0) > CACHE_TTL:
        engine = {"probed": time.strftime("%Y-%m-%d %H:%M"), "probed_ts": time.time(), "environment": environment(),
                  "hardware": hardware(), "core": core(), "addons": addons.check_all(),
                  "models": models.status_all(), "bandwidth_mbps": models.bandwidth_mbps()}
        data["engine"] = engine
        write_json(_path(), data)
    return {"engine": engine, "session": data.get("session", {}), "outcomes": data.get("outcomes", {})}


def record(*, connectors: list[str] | None = None, browser: list[str] | None = None,
           webai: dict[str, str] | None = None, tools: list[str] | None = None, note: str | None = None) -> dict:
    """Claude's view of this session: connectors, browser tools, web AI login states ("logged_in" | "logged_out")."""
    data = read_json(_path(), default={}) or {}
    s = data.setdefault("session", {})
    stamp = time.strftime("%Y-%m-%d %H:%M")
    if connectors is not None:
        s["connectors"] = sorted(set(connectors))
    if browser is not None:
        s["browser"] = browser
    if tools is not None:
        s["tools"] = sorted(set(tools))
    if webai:
        w = s.setdefault("webai", {})
        for service, state in webai.items():
            w[service] = {"state": state, "checked": stamp}
    if note:
        s.setdefault("notes", []).append({"at": stamp, "note": note})
    s["recorded"] = stamp
    write_json(_path(), data)
    return s


def outcome(route: str, ok: bool, note: str = "") -> dict:
    """Remember whether a route (e.g. 'webai:gemini', 'connector:canva', 'addon:blender') worked here."""
    data = read_json(_path(), default={}) or {}
    o = data.setdefault("outcomes", {}).setdefault(route, {"ok": 0, "fail": 0, "last": []})
    o["ok" if ok else "fail"] += 1
    o["last"] = ([{"at": time.strftime("%Y-%m-%d %H:%M"), "ok": ok, "note": note}] + o["last"])[:5]
    write_json(_path(), data)
    return o


def available(requirement: str, caps: dict | None = None) -> bool:
    """Is a route requirement met? Vocabulary:
    core:<key>  addon:<id>  model:<id>  connector:<name>  browser  webai:<service>  secret:<name>  tool:<name>
    Alternatives separated by '|' (any one is enough)."""
    caps = caps or collect()
    if "|" in requirement:
        return any(available(r, caps) for r in requirement.split("|"))
    eng, ses = caps["engine"], caps["session"]
    kind, _, name = requirement.partition(":")
    if kind == "core":
        v = eng["core"].get(name)
        return bool(v)
    if kind == "addon":
        row = next((a for a in eng["addons"] if a["id"] == name), None)
        return bool(row and row["ok"] and row["enabled"])
    if kind == "model":
        row = next((m for m in eng["models"] if m["id"] == name), None)
        return bool(row and row["ready"])
    if kind == "connector":
        return any(name.lower() in c.lower() for c in ses.get("connectors", []))
    if kind == "browser":
        return bool(ses.get("browser"))
    if kind == "webai":
        return ses.get("webai", {}).get(name, {}).get("state") == "logged_in"
    if kind == "secret":
        from . import config
        return bool(config.secret(name))
    if kind == "tool":
        return name in ses.get("tools", []) or bool(which(name))
    if kind == "web":
        return True                         # WebSearch/WebFetch exist in every Claude session
    if kind == "os":
        return {"windows": IS_WINDOWS, "mac": IS_MAC}.get(name, sys.platform.startswith(name))
    return False


# ------------------------------------------------------------------ CLI

def register_cli(sp) -> None:
    s = sp.add_parser("capabilities", help="what this machine + session can use (engine probe + Claude's records)")
    s.add_argument("action", nargs="?", default="show", choices=["show", "record", "outcome", "check"])
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--connectors", help="comma list of MCP connectors Claude sees, e.g. canva,google_drive")
    s.add_argument("--browser", help="comma list of browser tools, best first, e.g. claude-in-chrome,kapture")
    s.add_argument("--webai", help="comma list service=logged_in|logged_out, e.g. gemini=logged_in,chatgpt=logged_out")
    s.add_argument("--tools", help="comma list of other tools Claude has (computer-use, windows-mcp, ...)")
    s.add_argument("--note")
    s.add_argument("--route", help="outcome/check: route id or requirement, e.g. webai:gemini")
    s.add_argument("--ok", choices=["yes", "no"])
    s.set_defaults(fn=_cmd)


def _split(v: str | None) -> list[str] | None:
    return [x.strip() for x in v.split(",") if x.strip()] if v is not None else None


def _cmd(a) -> None:
    from .util import print_json
    if a.action == "record":
        webai = dict(x.split("=", 1) for x in _split(a.webai) or [])
        print_json(record(connectors=_split(a.connectors), browser=_split(a.browser), webai=webai or None,
                          tools=_split(a.tools), note=a.note))
    elif a.action == "outcome":
        print_json(outcome(a.route, a.ok == "yes", a.note or ""))
    elif a.action == "check":
        print_json({"requirement": a.route, "available": available(a.route, collect(refresh=a.refresh))})
    else:
        print_json(collect(refresh=a.refresh))
