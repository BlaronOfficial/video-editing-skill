"""Resolve Studio live control through Blackmagic's scripting API (external scripting must be set to Local in
Preferences > System > General). Resolve 21.1+ allows it in Studio only; the free edition gets the package.

Runs `resolve_bridge.py` in a child process with Resolve's module path, so a crash or hang inside
fusionscript never takes vedit down. Everything is add-only: a new project (or a new timeline in the open
project when asked), never a delete, never an overwrite; the result is read back from Resolve and compared
with the hand-off (tracks, clip counts, duration).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ..addons import find_resolve, resolve_is_studio
from ..paths import IS_MAC, IS_WINDOWS, cache_dir
from ..util import VeditError, read_json, write_json


def api_paths() -> tuple[Path | None, Path | None]:
    if IS_WINDOWS:
        apis = [Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Blackmagic Design" / "DaVinci Resolve" / "Support"
                / "Developer" / "Scripting",
                Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Blackmagic Design" / "DaVinci Resolve" / "Developer"
                / "Scripting"]
        libs = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Blackmagic Design" / "DaVinci Resolve" / "fusionscript.dll"]
    elif IS_MAC:
        apis = [Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"),
                Path("/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Resources/Developer/Scripting")]
        libs = [Path("/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"),
                Path("/Applications/DaVinci Resolve Studio.app/Contents/Libraries/Fusion/fusionscript.so")]
    else:
        apis = [Path("/opt/resolve/Developer/Scripting")]
        libs = [Path("/opt/resolve/libs/Fusion/fusionscript.so")]
    api = next((p for p in apis if p.is_dir()), None)
    lib = next((p for p in libs if p.is_file()), None)
    if os.environ.get("RESOLVE_SCRIPT_LIB"):
        lib = Path(os.environ["RESOLVE_SCRIPT_LIB"])
    if os.environ.get("RESOLVE_SCRIPT_API"):
        api = Path(os.environ["RESOLVE_SCRIPT_API"])
    return api, lib


def _call(command: str, payload: dict, timeout: float = 600) -> dict:
    exe = find_resolve()
    if not exe:
        raise VeditError("DaVinci Resolve is not installed. Use `vedit handoff make <project> --to resolve` (works "
                         "with the free edition) and import the package.")
    if resolve_is_studio(exe) is False:
        raise VeditError("This is DaVinci Resolve (free): since 21.1 scripting is Studio-only. Use the import package "
                         "(`vedit handoff make <project> --to resolve`), or `vedit resolve screen-import` with the owner's OK.")
    api, lib = api_paths()
    if not api or not lib:
        raise VeditError("Resolve's scripting files were not found (Developer/Scripting, fusionscript). Reinstall "
                         "Resolve Studio or set RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB.")
    work = cache_dir() / "resolve"
    work.mkdir(parents=True, exist_ok=True)
    req, out = work / f"{command}.in.json", work / f"{command}.out.json"
    write_json(req, payload)
    out.unlink(missing_ok=True)
    env = {**os.environ, "RESOLVE_SCRIPT_API": str(api), "RESOLVE_SCRIPT_LIB": str(lib),
           "PYTHONPATH": str(api / "Modules")}
    try:
        subprocess.run([sys.executable, str(Path(__file__).with_name("resolve_bridge.py")), command, str(req), str(out)],
                       env=env, timeout=timeout, check=False, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        raise VeditError("Resolve did not answer in time (is a dialog open in Resolve?).")
    res = read_json(out)
    if not res:
        raise VeditError("No answer from Resolve. Is Resolve Studio running, and is Preferences > System > General > "
                         "External scripting using set to Local?")
    if res.get("error"):
        raise VeditError(f"Resolve: {res['error']}")
    return res


def status() -> dict:
    return _call("status", {}, timeout=60)


def import_package(package_dir: str | Path, *, project: str | None = None, into_current: bool = False,
                   apply_lut: bool = True) -> dict:
    """Import a `--to resolve` package into Resolve Studio and verify it from Resolve's side."""
    package_dir = Path(package_dir)
    manifest = read_json(package_dir / "handoff.json")
    if not manifest or "fcpxml" not in manifest.get("files", {}):
        raise VeditError(f"{package_dir} is not a Resolve hand-off package (make one with --to resolve).")
    h = manifest["handoff"]
    payload = {"fcpxml": manifest["files"]["fcpxml"], "name": h["name"], "project": project, "into_current": into_current,
               "lut": manifest["files"].get("lut") if apply_lut else None, "srt": manifest["files"].get("srt"),
               "expect": {"video_tracks": sum(1 for t in h["tracks"] if t["kind"] == "video"),
                          "main_clips": len(h["tracks"][0]["items"]), "duration": h["duration"], "fps": h["fps"]}}
    res = _call("import", payload, timeout=1800)
    exp = payload["expect"]
    got = res.get("timeline", {})
    res["verified"] = (got.get("video_tracks", 0) >= exp["video_tracks"] and got.get("main_clips") == exp["main_clips"]
                       and abs(got.get("duration", 0) - exp["duration"]) <= 2 / exp["fps"])
    return res


def summary_json(res: dict) -> str:
    return json.dumps(res, indent=2, ensure_ascii=False)
