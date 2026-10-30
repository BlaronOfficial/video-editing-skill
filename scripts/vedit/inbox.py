"""Inbox: bring files downloaded in the browser (web AI generations, Pinterest/Google finds, stock sites) into a
project with provenance.

Web AI tools and websites save into the owner's Downloads folder. `pull` takes what arrived since a time (the
moment Claude started generating), skips half-finished downloads and duplicates, copies each file into
edit/assets/inbox/ and logs where it came from (service, prompt, page URL, licence note). The Downloads
folder is the owner's: files are copied, not moved, unless --move.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from pathlib import Path

from .assets import add_provenance
from .util import VeditError, read_json, write_json

MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif", ".mp4", ".mov", ".webm", ".m4v", ".mp3",
         ".wav", ".m4a", ".ogg", ".flac", ".json", ".lottie", ".ttf", ".otf", ".zip"}
PARTIAL = {".crdownload", ".part", ".tmp", ".download", ".partial"}
# short reminders of how each service's terms treat outputs. Terms and tiers change: re-check the service's
# current terms before commercial use and tell the owner what applies.
SERVICE_LICENCE = {
    "gemini": "Google generative AI terms: owner may use outputs; SynthID watermark; check tier",
    "chatgpt": "OpenAI terms: outputs assigned to the user",
    "ideogram": "Ideogram terms: free tier images are public; paid tiers private",
    "firefly": "Adobe Firefly: commercially safe per Adobe terms (non-beta features)",
    "adobe_express": "Adobe Express terms",
    "leonardo": "Leonardo terms: free tier outputs public, ownership depends on plan",
    "krea": "Krea terms: check plan for commercial use",
    "freepik": "Freepik licence: free assets need attribution; Premium does not",
    "canva": "Canva content licence (free / Pro elements differ)",
    "suno": "Suno: commercial use only on paid plans; free tier is non-commercial",
    "udio": "Udio terms: check plan for commercial use",
    "runway": "Runway terms: outputs owned by the user on paid plans",
    "kling": "Kling terms: check plan",
    "luma": "Luma terms: free tier non-commercial",
    "pinterest": "Pinterest pins belong to their creators: reference/inspiration only unless the source allows use",
    "google": "found via search: rights belong to the site's owner; reference only unless the page grants a licence",
}


def downloads_dir() -> Path:
    from . import config
    custom = config.load().get("downloads", {}).get("folder")
    if custom:
        return Path(custom).expanduser()
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
                return Path(winreg.QueryValueEx(k, "{374DE290-123F-4565-9164-39C4925E467B}")[0])
        except OSError:
            pass
    return Path.home() / "Downloads"


def mark() -> dict:
    """Remember 'now' before generating/downloading, so pull takes only what arrives after."""
    return {"since": time.time(), "at": time.strftime("%Y-%m-%d %H:%M:%S"), "folder": str(downloads_dir())}


def _since(value: str | float | None) -> float:
    if value is None:
        return time.time() - 15 * 60
    if isinstance(value, (int, float)):
        return float(value)
    v = str(value).strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(s|m|h)?", v)
    if m:
        n = float(m.group(1))
        unit = m.group(2) or "m"
        if n > 1e9:
            return n                                      # epoch seconds
        return time.time() - n * {"s": 1, "m": 60, "h": 3600}[unit]
    return time.mktime(time.strptime(v[:19], "%Y-%m-%d %H:%M:%S" if len(v) > 16 else "%Y-%m-%d %H:%M"))


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def pending(since: str | float | None = None, folder: Path | None = None) -> list[Path]:
    folder = folder or downloads_dir()
    t0 = _since(since)
    if not folder.exists():
        raise VeditError(f"Downloads folder not found: {folder} (`vedit config set downloads.folder <path>`)")
    out = []
    for f in folder.iterdir():
        if not f.is_file() or f.suffix.lower() in PARTIAL or f.suffix.lower() not in MEDIA:
            continue
        if f.stat().st_mtime >= t0:
            out.append(f)
    return sorted(out, key=lambda f: f.stat().st_mtime)


def pull(project_root: Path, *, since: str | float | None = None, service: str | None = None,
         prompt: str | None = None, url: str | None = None, licence: str | None = None, folder: Path | None = None,
         move: bool = False, match: str | None = None, wait: float = 0.0) -> dict:
    """Copy new downloads into edit/assets/inbox/ with provenance. `wait` seconds for a download to finish."""
    deadline = time.time() + wait
    files = pending(since, folder)
    while not files and time.time() < deadline:
        time.sleep(1.0)
        files = pending(since, folder)
    if match:
        files = [f for f in files if re.search(match, f.name, re.I)]
    dest = project_root / "assets" / "inbox"
    dest.mkdir(parents=True, exist_ok=True)
    seen_path = dest / ".hashes.json"
    seen = read_json(seen_path, default={}) or {}
    got, dup = [], []
    for f in files:
        size = f.stat().st_size
        time.sleep(0.3)
        if f.stat().st_size != size or size == 0:            # still being written
            continue
        h = _sha1(f)
        if h in seen:
            dup.append(f.name)
            continue
        target = dest / f.name
        n = 2
        while target.exists():
            target = dest / f"{f.stem}_{n}{f.suffix}"
            n += 1
        (shutil.move if move else shutil.copy2)(str(f), target)
        seen[h] = target.name
        svc = (service or "").lower() or None
        lic = licence or (SERVICE_LICENCE.get(svc) if svc else None) or "unknown"
        notes = "; ".join(x for x in [f"service: {service}" if service else "", f"prompt: {prompt}" if prompt else "",
                                      f"downloaded as {f.name}"] if x)
        rec = add_provenance(project_root, target, source=svc or "download", url=url, license=lic, notes=notes)
        got.append({"file": str(target), "bytes": size, "provenance": rec})
    write_json(seen_path, seen)
    return {"pulled": got, "duplicates": dup, "from": str(folder or downloads_dir()), "since": _since(since)}


def vectorize(image: Path, out: Path | None = None, *, colors: int = 6) -> Path:
    """Raster icon -> SVG with vtracer (MIT), installed on first use into .cache/tools/vtracer (~3 MB)."""
    from . import addons
    from .paths import cache_dir
    from .util import run
    py = addons.tool_python("vtracer")
    if not py:
        uv = shutil.which("uv")
        if not uv:
            raise VeditError("uv is required")
        venv = cache_dir() / "tools" / "vtracer" / "venv"
        run([uv, "venv", "--python", "3.12", str(venv)], timeout=600)
        py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run([uv, "pip", "install", "--python", str(py), "vtracer>=0.6"], timeout=900)
    out = out or image.with_suffix(".svg")
    code = ("import sys, vtracer; vtracer.convert_image_to_svg_py(sys.argv[1], sys.argv[2], colormode='color', "
            f"color_precision={max(1, min(8, colors))}, filter_speckle=6, mode='spline')")
    run([py, "-I", "-c", code, str(image), str(out)], timeout=600)
    return out


def cmd_inbox(a) -> None:
    from .project import find
    from .util import print_json
    if a.action == "mark":
        print_json(mark())
        return
    if a.action == "list":
        print_json([{"file": str(f), "bytes": f.stat().st_size,
                     "modified": time.strftime("%H:%M:%S", time.localtime(f.stat().st_mtime))}
                    for f in pending(a.since, Path(a.folder) if a.folder else None)])
        return
    if a.action == "vectorize":
        print_json({"svg": str(vectorize(Path(a.target), colors=a.colors))})
        return
    p = find(a.target)
    res = pull(p.root, since=a.since, service=a.service, prompt=a.prompt, url=a.url, licence=a.licence,
               folder=Path(a.folder) if a.folder else None, move=a.move, match=a.match, wait=a.wait)
    if a.register:
        from .project import add_source
        for g in res["pulled"]:
            if Path(g["file"]).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".webm",
                                                  ".m4v", ".mp3", ".wav", ".m4a", ".ogg", ".flac"}:
                g["source_id"] = add_source(p, g["file"], origin=f"{a.service or 'download'}:{a.url or ''}")
    print_json(res)


def register_cli(sp) -> None:
    s = sp.add_parser("inbox", help="bring browser downloads (web AI, Pinterest, stock) into a project with provenance")
    s.add_argument("action", choices=["mark", "list", "pull", "vectorize"])
    s.add_argument("target", nargs="?", default="", help="project (pull) or image (vectorize)")
    s.add_argument("--since", help="'10m', '2h', epoch seconds from `inbox mark`, or 'YYYY-MM-DD HH:MM'")
    s.add_argument("--service", help="gemini, chatgpt, ideogram, firefly, canva, pinterest, google, ...")
    s.add_argument("--prompt"); s.add_argument("--url"); s.add_argument("--licence"); s.add_argument("--folder")
    s.add_argument("--match", help="regex on file names"); s.add_argument("--move", action="store_true")
    s.add_argument("--wait", type=float, default=0.0, help="seconds to wait for a download to land")
    s.add_argument("--register", action="store_true"); s.add_argument("--colors", type=int, default=6)
    s.set_defaults(fn=cmd_inbox)
