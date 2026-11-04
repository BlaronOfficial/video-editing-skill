"""Self-extension: find, vet and install an open-source tool when the engine lacks something.

The vetting rules come from a real incident: a repo the owner asked for ("humanizer-cli") turned out to
be a malware lure (deleted account, bot forks, a launcher that ran an opaque bundled .exe). So:
  * source code only: bundled executables, DLLs or archives block the install;
  * install hooks are read, not trusted: npm installs run with --ignore-scripts, and setup files that
    download things are flagged;
  * the account and licence are checked, recent activity is reported;
  * tools go into an isolated venv under .cache/tools/<name>/, never into the core venv, never as admin;
  * the owner approves every install (Claude asks first; `add` refuses without a passing `vet` report).
Adapters that wire a tool into vedit live in personal/extensions/ and survive `git pull`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from .paths import IS_WINDOWS, cache_dir, personal_dir, tools_dir
from .util import VeditError, read_json, run, write_json

BINARY_EXT = {".exe", ".dll", ".so", ".dylib", ".msi", ".scr", ".com", ".bin", ".appimage", ".pkg", ".dmg", ".jar"}
ARCHIVE_EXT = {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".tgz"}
SCRIPT_EXT = {".bat", ".cmd", ".ps1", ".sh", ".vbs"}
MAGIC = {b"MZ": "Windows executable", b"\x7fELF": "Linux executable", b"\xcf\xfa\xed\xfe": "macOS executable",
         b"PK\x03\x04": "zip archive"}
FETCH_RE = re.compile(r"(curl|wget|Invoke-WebRequest|iwr |urlretrieve|requests\.get|httpx\.get|fetch\()", re.I)
LICENCES = {"MIT": r"\bMIT License\b|Permission is hereby granted, free of charge",
            "Apache-2.0": r"Apache License,?\s+Version 2\.0", "GPL-3.0": r"GNU GENERAL PUBLIC LICENSE\s+Version 3",
            "GPL-2.0": r"GNU GENERAL PUBLIC LICENSE\s+Version 2", "LGPL": r"GNU LESSER GENERAL PUBLIC",
            "BSD": r"Redistribution and use in source and binary forms", "MPL-2.0": r"Mozilla Public License",
            "CC-BY-NC": r"NonCommercial", "Unlicense": r"This is free and unencumbered software"}


def _tools_dir() -> Path:
    path = tools_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _registry_path() -> Path:
    return personal_dir() / "tools.json"


def _name_from_url(url: str) -> str:
    return re.sub(r"\.git$", "", url.rstrip("/").split("/")[-1]).lower()


def _owner_exists(url: str) -> bool | None:
    m = re.match(r"https?://github\.com/([^/]+)/", url)
    if not m:
        return None
    import httpx
    try:
        r = httpx.get(f"https://github.com/{m.group(1)}", follow_redirects=True, timeout=20)
        return r.status_code == 200
    except Exception:
        return None


def vet(url: str, *, name: str | None = None) -> dict:
    """Clone (shallow) into .cache/tools/src/<name> and inspect without running anything."""
    name = name or _name_from_url(url)
    src = _tools_dir() / "src" / name
    if src.exists():
        shutil.rmtree(src)
    src.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", "--depth", "1", url, str(src)], timeout=900)
    findings: dict[str, list[str]] = {"block": [], "caution": [], "info": []}
    files = [p for p in src.rglob("*") if p.is_file() and ".git" not in p.parts]
    for f in files:
        rel = str(f.relative_to(src))
        ext = f.suffix.lower()
        head = f.open("rb").read(4)
        kind = next((v for k, v in MAGIC.items() if head.startswith(k)), None)
        if ext in BINARY_EXT or (kind and "executable" in kind):
            findings["block"].append(f"bundled executable: {rel}")
        elif ext in ARCHIVE_EXT or kind == "zip archive":
            findings["block" if f.stat().st_size > 5_000_000 else "caution"].append(f"bundled archive: {rel}")
        elif ext in SCRIPT_EXT:
            findings["caution"].append(f"shell script (read before running): {rel}")
    for hook_file in ("setup.py", "package.json", "install.sh", "install.ps1", "postinstall.js", "postinstall.mjs"):
        for f in src.rglob(hook_file):
            text = f.read_text(encoding="utf-8", errors="replace")
            if hook_file == "package.json" and re.search(r'"(pre|post)?install"\s*:', text):
                findings["caution"].append(f"npm install hook in {f.relative_to(src)} (installed with --ignore-scripts)")
            if FETCH_RE.search(text) and hook_file != "package.json":
                findings["caution"].append(f"install file downloads at install time: {f.relative_to(src)}")
    licence = "unknown"
    for f in [p for p in src.iterdir() if p.is_file() and p.name.lower().startswith(("license", "licence", "copying"))]:
        text = f.read_text(encoding="utf-8", errors="replace")
        licence = next((k for k, pat in LICENCES.items() if re.search(pat, text)), "other")
        break
    if licence in ("unknown", "other"):
        findings["caution"].append(f"licence: {licence} (check before using in commercial work)")
    if licence == "CC-BY-NC":
        findings["caution"].append("non-commercial licence: ideas only, do not ship it in the owner's paid work")
    owner = _owner_exists(url)
    if owner is False:
        findings["block"].append("the GitHub account no longer exists")
    last = subprocess.run(["git", "-C", str(src), "log", "-1", "--format=%cs"], capture_output=True, text=True).stdout.strip()
    findings["info"].append(f"last commit {last or 'unknown'}; {len(files)} files")
    kind = "python" if (src / "pyproject.toml").exists() or (src / "setup.py").exists() else \
        "node" if (src / "package.json").exists() else "other"
    verdict = "block" if findings["block"] else "caution" if findings["caution"] else "ok"
    report = {"name": name, "url": url, "kind": kind, "licence": licence, "verdict": verdict, "findings": findings,
              "src": str(src), "vetted": time.strftime("%Y-%m-%d %H:%M")}
    write_json(_tools_dir() / "src" / f"{name}.vet.json", report)
    return report


def add(name: str, *, accept_caution: bool = False) -> dict:
    report = read_json(_tools_dir() / "src" / f"{name}.vet.json")
    if not report:
        raise VeditError(f"Run `vedit tools vet <url>` first; there is no vetting report for '{name}'.")
    if report["verdict"] == "block":
        raise VeditError(f"'{name}' failed vetting: {report['findings']['block']}. Not installing.")
    if report["verdict"] == "caution" and not accept_caution:
        raise VeditError(f"'{name}' has cautions: {report['findings']['caution']}. Show them to the owner; install "
                         "only after a yes, with --accept-caution.")
    src = Path(report["src"])
    home = _tools_dir() / name
    home.mkdir(parents=True, exist_ok=True)
    if report["kind"] == "python":
        uv = shutil.which("uv")
        if not uv:
            raise VeditError("uv is required to create the isolated venv.")
        run([uv, "venv", "--python", "3.12", str(home / "venv")], timeout=600)
        py = home / "venv" / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
        run([uv, "pip", "install", "--python", str(py), str(src)], timeout=3600)
        entry = str(py)
    elif report["kind"] == "node":
        npm = shutil.which("npm")
        if not npm:
            raise VeditError("Node/npm is required for this tool.")
        dest = home / "pkg"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"))
        run([npm, "install", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=dest, timeout=3600)
        entry = str(dest)
    else:
        raise VeditError("Only Python and Node tools can be installed automatically; wire others by hand.")
    reg = read_json(_registry_path(), default={}) or {}
    reg[name] = {"url": report["url"], "licence": report["licence"], "kind": report["kind"], "entry": entry,
                 "installed": time.strftime("%Y-%m-%d %H:%M"), "verdict": report["verdict"]}
    write_json(_registry_path(), reg)
    return {"installed": name, **reg[name],
            "next": f"Write an adapter in {personal_dir() / 'extensions'} if vedit should call it."}


def remove(name: str) -> dict:
    reg = read_json(_registry_path(), default={}) or {}
    reg.pop(name, None)
    write_json(_registry_path(), reg)
    home = _tools_dir() / name
    if home.exists():
        shutil.rmtree(home)
    return {"removed": name}


# ------------------------------------------------------------------ CLI

def register_cli(sp) -> None:
    s = sp.add_parser("tools", help="vet and install open-source tools into isolated venvs (asks the owner first)")
    s.add_argument("action", choices=["vet", "add", "list", "remove"])
    s.add_argument("target", nargs="?", help="vet: git URL; add/remove: tool name")
    s.add_argument("--name"); s.add_argument("--accept-caution", action="store_true")
    s.set_defaults(fn=_cmd)


def _cmd(a) -> None:
    from .util import print_json
    if a.action == "vet":
        print_json(vet(a.target, name=a.name))
    elif a.action == "add":
        print_json(add(a.target, accept_caution=a.accept_caution))
    elif a.action == "remove":
        print_json(remove(a.target))
    else:
        print_json(read_json(_registry_path(), default={}) or {})
