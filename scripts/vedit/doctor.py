"""Environment check: what works, what is missing, and the exact fix for each item."""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

from . import config
from .paths import IS_WINDOWS, SKILL_ROOT, fonts_dir, mg_dir, personal_dir
from .util import read_json, which


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
        optional = {"zscale": "HDR to SDR", "vidstabdetect": "stabilize", "minterpolate": "smooth slow motion",
                    "nlmeans": "strong denoise", "v360": "360 reframe", "lut3d": "LUTs"}
        missing = [f"{k} ({v})" for k, v in optional.items() if f" {k} " not in filters]
        add("ffmpeg footage/FX filters", not missing, "all present" if not missing else "missing: " + ", ".join(missing),
            "Install a full FFmpeg build (gyan.dev 'full'); the missing features fail with a clear error until then.",
            required=False)
    add("node", bool(which("node")), _version(["node", "--version"]) or "", "Install Node.js 20+ from nodejs.org")
    add("mg renderer deps", (mg_dir() / "renderer" / "node_modules" / "puppeteer-core").exists(), "",
        "Run `vedit setup renderer`")
    from .mg import chrome
    c = chrome()
    add("chrome/edge (mg rendering)", c is not None, str(c or ""), "Install Google Chrome or Microsoft Edge")
    try:                                      # measured by `vedit capabilities` (not re-probed here: doctor stays fast)
        from .capabilities import _path as caps_path
        wg = (((read_json(caps_path(), default={}) or {}).get("engine") or {}).get("core") or {}).get("webgl")
    except Exception:
        wg = None
    if wg:
        add("WebGL on the GPU (3D templates, animated pieces)", bool(wg.get("ok")), wg.get("renderer", ""),
            "Update the graphics driver: rendering still works in software, many times slower", required=False)
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

    # Optional add-ons (CapCut, DaVinci Resolve, LosslessCut, Blender, earshot, paid services, ...):
    # reported, never required. The skill is standalone without them.
    from . import addons
    for row in addons.check_all():
        add(f"add-on: {row['name']}", row["ok"], row["detail"] + ("" if row["enabled"] else " (disabled)"),
            row.get("install", ""), required=False)
    if IS_WINDOWS:
        add("screen control", True, "Use Claude Code Desktop computer use, or add Windows-MCP: "
            "`claude mcp add --scope user --transport stdio windows-mcp -- uvx windows-mcp serve`", required=False)
    free = shutil.disk_usage(str(SKILL_ROOT)).free / 1e9
    add("disk space", free > 10, f"{free:.0f} GB free", "Free up space: renders and caches need room", required=False)
    ok = all(i["ok"] for i in items if i["required"])
    return {"ready": ok, "items": items, "skill_root": str(SKILL_ROOT), "personal": str(personal_dir())}


def fonts_path_note() -> Path:
    return fonts_dir()
