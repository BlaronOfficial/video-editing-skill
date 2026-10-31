"""LosslessCut hand-off: .llc projects both ways, and the app driven through its HTTP API.

LosslessCut (GPL-2.0, mifi/lossless-cut) is a separate free app: vedit only writes and reads its project
files and talks to it over 127.0.0.1, never links its code. A .llc project is one media file plus cut
segments (JSON5, version 2):

    {version: 2, mediaFileName: 'a.mp4', cutSegments: [{start: 1.2, end: 4.5, name: 'hook', tags: {...}}]}

`vedit llc write` gives the owner the main-track cut of one source to fine-tune in LosslessCut;
`vedit llc import` (or `vedit handoff diff ... --apply-cuts`) brings the tuned segments back. `vedit llc open`
starts LosslessCut with its HTTP API on our own --config-dir (the owner's own settings are untouched);
`vedit llc export` asks the running app to export and waits for the files.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .addons import find_losslesscut
from .paths import cache_dir
from .timeline import Edit
from .util import VeditError

PORT = 18080


# ------------------------------------------------------------------ JSON5 (what LosslessCut writes)

_TOKEN = re.compile(r"""
    (?P<ws>\s+|//[^\n]*|/\*.*?\*/)
  | (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<num>[+-]?(?:Infinity|NaN|0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?))
  | (?P<punc>[{}\[\]:,])
  | (?P<word>[A-Za-z_$][\w$]*)
""", re.S | re.X)


def json5_loads(text: str) -> Any:
    """Enough JSON5 for .llc files: comments, unquoted keys, single quotes, trailing commas, hex, Infinity."""
    toks: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ValueError(f"JSON5: unexpected character at {pos}: {text[pos:pos + 20]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind != "ws":
            toks.append((kind, m.group(kind)))
    i = 0

    def string(raw: str) -> str:
        body = raw[1:-1]
        if raw[0] == "'":
            body = body.replace("\\'", "'").replace('"', '\\"')
        return json.loads('"' + body.replace("\\\n", "") + '"')

    def value() -> Any:
        nonlocal i
        kind, tok = toks[i]
        i += 1
        if tok == "{":
            obj = {}
            while toks[i][1] != "}":
                k_kind, k = toks[i]
                i += 1
                key = string(k) if k_kind == "str" else k
                if toks[i][1] != ":":
                    raise ValueError("JSON5: expected ':'")
                i += 1
                obj[key] = value()
                if toks[i][1] == ",":
                    i += 1
            i += 1
            return obj
        if tok == "[":
            arr = []
            while toks[i][1] != "]":
                arr.append(value())
                if toks[i][1] == ",":
                    i += 1
            i += 1
            return arr
        if kind == "str":
            return string(tok)
        if kind == "num":
            t = tok.lstrip("+")
            if t.lstrip("-") == "Infinity":
                return float("-inf") if t.startswith("-") else float("inf")
            if t.lstrip("-") == "NaN":
                return float("nan")
            if t.lstrip("-")[:2].lower() == "0x":
                return int(t, 16)
            return float(t) if any(c in t for c in ".eE") else int(t)
        if kind == "word":
            return {"true": True, "false": False, "null": None}.get(tok, tok)
        raise ValueError(f"JSON5: unexpected {tok!r}")

    out = value()
    return out


# ------------------------------------------------------------------ .llc files

def read(path: str | Path) -> dict:
    data = json5_loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "cutSegments" not in data:
        raise VeditError(f"{path} is not a LosslessCut project")
    for seg in data["cutSegments"]:
        seg.setdefault("start", 0.0)
        seg.setdefault("name", "")
    return data


def write(path: str | Path, media: str | Path, segments: list[dict]) -> Path:
    """segments: [{"start", "end", "name"?, "tags"?}] in source seconds, in playback order."""
    path = Path(path)
    data = {"version": 2, "mediaFileName": Path(media).name,
            "cutSegments": [{"start": round(float(s["start"]), 6), "end": round(float(s["end"]), 6),
                             "name": s.get("name", ""), "tags": s.get("tags") or {}, "selected": True} for s in segments]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")   # JSON is valid JSON5
    return path


def from_edit(edit: Edit, out_dir: str | Path, *, footage_dir: str | Path | None = None) -> list[dict]:
    """One .llc per source used on the main track. LosslessCut finds the media by name beside the project, so
    a copy goes next to sources that live in the project's footage folder (`<name>-proj.llc`, which LosslessCut
    also loads automatically when the video is opened); sources elsewhere (the owner's library) are not
    touched: their .llc stays in out_dir."""
    out_dir = Path(out_dir)
    root = Path(footage_dir).resolve() if footage_dir else None
    edit.layout()
    by_source: dict[str, list[dict]] = {}
    for c in edit.main:
        if edit.sources[c.source].kind != "video" and edit.sources[c.source].kind != "audio":
            continue
        by_source.setdefault(c.source, []).append({"start": c.src_in, "end": c.src_out, "name": c.label or c.id,
                                                   "tags": {"vedit": c.id, "timeline": f"{c.start:.3f}"}})
    written = []
    for sid, segs in by_source.items():
        media = Path(edit.sources[sid].path)
        target = media.with_name(f"{media.stem}-proj.llc")         # LosslessCut's own naming
        beside = root is not None and root in media.resolve().parents
        try:
            if not beside:
                raise OSError
            write(target, media, segs)
        except OSError:
            target, beside = out_dir / f"{media.stem}-proj.llc", False
            write(target, media, segs)
        copy = out_dir / target.name
        if beside and copy != target:
            write(copy, media, segs)
        written.append({"source": sid, "llc": str(target), "media": str(media), "segments": len(segs),
                        "beside_media": beside})
    return written


def to_ranges(data: dict, media: str | Path) -> list[dict]:
    return [{"path": str(media), "src_in": s["start"], "src_out": s["end"], "name": s.get("name", "")}
            for s in data["cutSegments"] if s.get("end") is not None and s.get("selected", True) is not False]


# ------------------------------------------------------------------ the app

def _config_dir() -> Path:
    d = cache_dir() / "losslesscut" / "config"
    d.mkdir(parents=True, exist_ok=True)
    return d


def open_app(files: list[str | Path], *, port: int = PORT, wait: float = 60.0) -> dict:
    exe = find_losslesscut()
    if not exe:
        raise VeditError("LosslessCut is not installed (free: github.com/mifi/lossless-cut/releases, portable zip, or "
                         "`winget install mifi.losslesscut`). Ask the owner before installing.")
    # our own config dir, and no export-options page: `vedit llc export` must not wait on a click
    args = [str(exe), "--http-api", str(port), "--config-dir", str(_config_dir()), "--disable-networking",
            "--settings-json", json.dumps({"exportConfirmEnabled": False}), *[str(Path(f).resolve()) for f in files]]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + wait
    while time.time() < deadline:
        if ping(port):
            return {"pid": proc.pid, "port": port, "exe": str(exe), "api": True}
        time.sleep(1.0)
    return {"pid": proc.pid, "port": port, "exe": str(exe), "api": False,
            "note": "LosslessCut started but its HTTP API did not answer (older version without --http-api?)"}


def _post(path: str, body: Any = None, *, port: int = PORT, timeout: float = 30.0):
    import httpx
    # The API refuses requests that carry an Origin header (browsers); httpx sends none.
    r = httpx.post(f"http://127.0.0.1:{port}{path}", json=body, timeout=timeout)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return r.text


def ping(port: int = PORT) -> bool:
    import httpx
    try:
        httpx.get(f"http://127.0.0.1:{port}/", timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


def action(name: str, body: Any = None, *, port: int = PORT, timeout: float = 120.0):
    return _post(f"/api/action/{name}", body, port=port, timeout=timeout)


def export(*, port: int = PORT, timeout: float = 1800.0) -> dict:
    """Export the open file with its segments (LosslessCut's current export settings) and wait for the paths."""
    import threading
    result: dict = {}

    def waiter():
        try:
            result.update(_post("/api/await-event/export-complete", port=port, timeout=timeout) or {})
        except Exception as exc:              # noqa: BLE001 - reported to the caller
            result["error"] = str(exc)

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    time.sleep(0.5)
    action("export", port=port, timeout=timeout)
    t.join(timeout)
    return result
