"""One-time setup: fonts (OFL, from google/fonts), renderer deps, Whisper model, optional per-user font install."""

from __future__ import annotations

import shutil
from pathlib import Path

from .paths import IS_WINDOWS, cache_dir, fonts_dir, mg_dir
from .util import VeditError, run, which

GF = "https://raw.githubusercontent.com/google/fonts/main/"
FONTS = {
    # Display / captions (Latin)
    "Poppins-Medium.ttf": "ofl/poppins/Poppins-Medium.ttf",
    "Poppins-SemiBold.ttf": "ofl/poppins/Poppins-SemiBold.ttf",
    "Poppins-Bold.ttf": "ofl/poppins/Poppins-Bold.ttf",
    "Poppins-ExtraBold.ttf": "ofl/poppins/Poppins-ExtraBold.ttf",
    "Poppins-Black.ttf": "ofl/poppins/Poppins-Black.ttf",
    "Anton-Regular.ttf": "ofl/anton/Anton-Regular.ttf",
    "BebasNeue-Regular.ttf": "ofl/bebasneue/BebasNeue-Regular.ttf",
    "ArchivoBlack-Regular.ttf": "ofl/archivoblack/ArchivoBlack-Regular.ttf",
    "LuckiestGuy-Regular.ttf": "apache/luckiestguy/LuckiestGuy-Regular.ttf",
    "Bangers-Regular.ttf": "ofl/bangers/Bangers-Regular.ttf",
    "DMSerifDisplay-Regular.ttf": "ofl/dmserifdisplay/DMSerifDisplay-Regular.ttf",
    "DMSerifDisplay-Italic.ttf": "ofl/dmserifdisplay/DMSerifDisplay-Italic.ttf",
    "InstrumentSerif-Regular.ttf": "ofl/instrumentserif/InstrumentSerif-Regular.ttf",
    "InstrumentSerif-Italic.ttf": "ofl/instrumentserif/InstrumentSerif-Italic.ttf",
    "PermanentMarker-Regular.ttf": "apache/permanentmarker/PermanentMarker-Regular.ttf",
    "CaveatBrush-Regular.ttf": "ofl/caveatbrush/CaveatBrush-Regular.ttf",
    "RubikMonoOne-Regular.ttf": "ofl/rubikmonoone/RubikMonoOne-Regular.ttf",
    # Bangla
    "HindSiliguri-Medium.ttf": "ofl/hindsiliguri/HindSiliguri-Medium.ttf",
    "HindSiliguri-SemiBold.ttf": "ofl/hindsiliguri/HindSiliguri-SemiBold.ttf",
    "HindSiliguri-Bold.ttf": "ofl/hindsiliguri/HindSiliguri-Bold.ttf",
    "TiroBangla-Regular.ttf": "ofl/tirobangla/TiroBangla-Regular.ttf",
    "Galada-Regular.ttf": "ofl/galada/Galada-Regular.ttf",
    "Atma-Bold.ttf": "ofl/atma/Atma-Bold.ttf",
}


def download_fonts(force: bool = False) -> dict:
    import httpx
    out = fonts_dir()
    got, failed = [], []
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for name, rel in FONTS.items():
            dest = out / name
            if dest.exists() and dest.stat().st_size > 10_000 and not force:
                got.append(name)
                continue
            try:
                resp = client.get(GF + rel)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                got.append(name)
            except Exception as exc:  # network hiccup or upstream rename: report, keep going
                failed.append(f"{name}: {exc}")
    return {"dir": str(out), "ok": len(got), "failed": failed}


def install_fonts_for_user() -> list[str]:
    """Make the fonts visible to CapCut and other apps (per-user install, no admin)."""
    if not IS_WINDOWS:
        raise VeditError("Per-user font install is implemented for Windows; on macOS double-click the .ttf files.")
    import winreg
    import os
    target = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts"
    target.mkdir(parents=True, exist_ok=True)
    installed = []
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows NT\CurrentVersion\Fonts")
    for f in sorted(fonts_dir().glob("*.ttf")):
        dest = target / f.name
        if not dest.exists():
            shutil.copy(f, dest)
        winreg.SetValueEx(key, f"{f.stem} (TrueType)", 0, winreg.REG_SZ, str(dest))
        installed.append(f.name)
    winreg.CloseKey(key)
    return installed


def install_renderer() -> str:
    npm = which("npm")
    if not npm:
        raise VeditError("npm not found. Install Node.js 20+ (https://nodejs.org) and rerun `vedit setup`.")
    run([npm, "install", "--no-audit", "--no-fund"], cwd=mg_dir() / "renderer", timeout=1800)
    return str(mg_dir() / "renderer" / "node_modules")


def prefetch_whisper(model: str) -> str:
    import os
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")   # plain resumable HTTP; chunked transfer stalls on slow links
    from faster_whisper import WhisperModel
    WhisperModel(model, device="cpu", compute_type="int8", download_root=str(cache_dir() / "whisper"))
    return model
