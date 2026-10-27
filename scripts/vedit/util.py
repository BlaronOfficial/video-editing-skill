"""Small shared helpers: JSON IO, subprocess, hashing, time formatting."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterable


class VeditError(RuntimeError):
    """An error with a message meant for the user (and Claude) to act on."""


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | Path, data: Any, *, indent: int | None = 2, ensure_ascii: bool = False) -> Path:
    """Atomic JSON write (temp file + replace) so a crash never leaves half a file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii, separators=None if indent else (",", ":"))
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return p


def write_text(path: str | Path, text: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def which(name: str) -> str | None:
    return shutil.which(name)


def run(cmd: Iterable[str | Path], *, check: bool = True, capture: bool = True, cwd: str | Path | None = None,
        timeout: float | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    args = [str(c) for c in cmd]
    proc = subprocess.run(
        args, cwd=cwd, timeout=timeout, env=env,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True, encoding="utf-8", errors="replace",
    )
    if check and proc.returncode != 0:
        tail = (proc.stderr or "")[-2000:]
        raise VeditError(f"Command failed ({proc.returncode}): {' '.join(args[:6])}...\n{tail}")
    return proc


def new_uuid(upper: bool = True) -> str:
    u = str(uuid.uuid4())
    return u.upper() if upper else u


def short_hash(*parts: Any, length: int = 12) -> str:
    h = hashlib.sha1()
    for part in parts:
        h.update(json.dumps(part, sort_keys=True, default=str).encode("utf-8"))
    return h.hexdigest()[:length]


def file_fingerprint(path: str | Path) -> str:
    """Cheap identity for cache keys: size + mtime + name (no full read of large videos)."""
    p = Path(path)
    st = p.stat()
    return short_hash(p.name, st.st_size, int(st.st_mtime))


def fmt_ts(seconds: float, *, ms: bool = True) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if ms:
        return f"{h:d}:{m:02d}:{s:06.3f}" if h else f"{m:d}:{s:06.3f}"
    return f"{h:d}:{m:02d}:{int(s):02d}" if h else f"{m:d}:{int(s):02d}"


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
