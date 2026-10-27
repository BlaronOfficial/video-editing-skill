"""Environment check: what works, what is missing, and the exact fix for each item."""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

from . import config
from .paths import IS_WINDOWS, SKILL_ROOT, fonts_dir, mg_dir, personal_dir
from .util import which


def _version(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        text = (out.stdout or out.stderr).strip().splitlines()
        return text[0][:80] if text else None
    except Exception:
        return None


def check() -> dict:
    cfg = config.load()
    items: list[dict] = []

    def add(name: str, ok: bool, detail: str = "", fix: str = "", required: bool = True) -> None:
        items.append({"item": name, "ok": ok, "detail": detail, "fix": "" if ok else fix, "required": required})

    add("os", True, f"{platform.system()} {platform.release()}")
    ff = which("ffmpeg")
    add("ffmpeg", bool(ff), _version(["ffmpeg", "-version"]) or "",
        "Windows: `winget install Gyan.FFmpeg`; macOS: `brew install ffmpeg`")
    if ff:
        filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        add("ffmpeg libass (captions)", " subtitles " in filters, "", "Install a full FFmpeg build (gyan.dev 'full').")
        add("ffmpeg xfade/sidechaincompress", " xfade " in filters and "sidechaincompress" in filters, "",
            "Update FFmpeg to 5.0+.")
    add("node", bool(which("node")), _version(["node", "--version"]) or "", "Install Node.js 20+ from nodejs.org")
    add("mg renderer deps", (mg_dir() / "renderer" / "node_modules" / "puppeteer-core").exists(), "",
        "Run `vedit setup renderer`")
    from .mg import chrome
    c = chrome()
    add("chrome/edge (mg rendering)", c is not None, str(c or ""), "Install Google Chrome or Microsoft Edge")
    n_fonts = len(list(fonts_dir().glob("*.ttf")))
    add("fonts", n_fonts >= 15, f"{n_fonts} fonts in .cache/fonts", "Run `vedit setup fonts`")
    try:
        import faster_whisper  # noqa: F401
        add("faster-whisper", True, "local transcription available")
    except Exception:
        add("faster-whisper", False, "", "Run `uv sync --project scripts`")
    whisper_cache = list((SKILL_ROOT / ".cache" / "whisper").glob("models--*")) if (SKILL_ROOT / ".cache" / "whisper").exists() else []
    add("whisper model cached", bool(whisper_cache), ", ".join(p.name.split("--")[-1] for p in whisper_cache),
        "First transcription downloads it (~1.5 GB for large-v3), or run `vedit setup whisper`", required=False)
    add("elevenlabs key (Scribe / TTS)", bool(config.secret("elevenlabs")), "",
        "Optional: `vedit secret set elevenlabs <key>` or set ELEVENLABS_API_KEY", required=False)

    # CapCut
    from .capcut import store
    try:
        root = store.drafts_root()
        add("capcut drafts folder", True, str(root))
    except Exception as exc:
        add("capcut drafts folder", False, str(exc), "Install CapCut desktop and create one project")
    ver = store.installed_version()
    add("capcut version", bool(ver), ver or "unknown", "", required=False)
    if ver and ver.split(".")[0].isdigit() and int(ver.split(".")[0]) >= 10:
        add("capcut version support", False, f"{ver}: CapCut 10.x is reported to reject tool-written projects",
            "Projects may fail to open; the MP4 render is unaffected. Consider CapCut 9.x with auto-update off.",
            required=False)
    calib = (personal_dir() / "capcut" / "calibration.json").exists()
    add("capcut calibrated", calib, cfg["capcut"].get("app_version") or "",
        "Create an empty project in CapCut, close CapCut, run `vedit capcut calibrate`")
    if calib and ver and cfg["capcut"].get("app_version") and not ver.startswith(cfg["capcut"]["app_version"]):
        add("capcut calibration current", False, f"calibrated on {cfg['capcut']['app_version']}, installed {ver}",
            "CapCut updated: rerun `vedit capcut calibrate`")
    add("capcut alpha overlays", cfg["capcut"]["alpha_overlays"] != "unknown", cfg["capcut"]["alpha_overlays"],
        "Run `vedit capcut probe-alpha` once (needs a quick look in CapCut)", required=False)

    # Optional integrations
    hf = which("higgsfield")
    add("higgsfield cli", bool(hf), _version(["higgsfield", "--version"]) or "",
        "Optional: `npm i -g @higgsfield/cli && higgsfield auth login && npx skills add higgsfield-ai/skills`",
        required=False)
    add("git (updates)", bool(which("git")) and (SKILL_ROOT / ".git").exists(), "",
        "Install via `git clone` to receive updates with `vedit update`", required=False)
    if IS_WINDOWS:
        add("screen control", True, "Use Claude Code Desktop computer use, or add Windows-MCP: "
            "`claude mcp add --scope user --transport stdio windows-mcp -- uvx windows-mcp serve`", required=False)
    free = shutil.disk_usage(str(SKILL_ROOT)).free / 1e9
    add("disk space", free > 10, f"{free:.0f} GB free", "Free up space: renders and caches need room", required=False)
    ok = all(i["ok"] for i in items if i["required"])
    return {"ready": ok, "items": items, "skill_root": str(SKILL_ROOT), "personal": str(personal_dir())}


def fonts_path_note() -> Path:
    return fonts_dir()
