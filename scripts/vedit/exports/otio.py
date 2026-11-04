"""OpenTimelineIO hand-offs: .otio, FCP7 XML (Premiere Pro, also Resolve/Avid), CMX 3600 EDL, Kdenlive.

OpenTimelineIO (Apache-2.0, Academy Software Foundation) and its adapters live in an isolated tool venv
(.cache/tools/otio, ~10 MB with lxml): `vedit setup otio`. They install on first use without asking
because they are small. The same tool reads any of these formats back for verification and for
learning from the owner's re-exports (`vedit handoff diff`).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from ..addons import tool_python
from ..paths import cache_dir, tools_dir
from ..util import VeditError, read_json, run, write_json
from . import Handoff, rate

PINS = ["opentimelineio==0.18.1", "otio-fcp-adapter==1.0.0", "otio-fcpx-xml-adapter==1.0.0",
        "otio-cmx3600-adapter==1.0.0", "otio-kdenlive-adapter==0.0.3", "lxml==5.3.0"]
ADAPTERS = {"otio": ("otio_json", ".otio"), "xml": ("fcp_xml", ".xml"), "edl": ("cmx_3600", ".edl"),
            "kdenlive": ("kdenlive", ".kdenlive")}


def setup() -> dict:
    uv = shutil.which("uv")
    if not uv:
        raise VeditError("uv is required (https://docs.astral.sh/uv/)")
    venv = tools_dir() / "otio" / "venv"
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        run([uv, "venv", "--python", "3.12", str(venv)], timeout=900)
    run([uv, "pip", "install", "--python", str(py), *PINS], timeout=1800)
    return {"venv": str(venv), "packages": PINS}


def python() -> Path:
    py = tool_python("otio")
    if not py:
        setup()                                   # ~10 MB: under the ask-first threshold
        py = tool_python("otio")
    return py


def bridge(command: str, payload: dict, timeout: float = 600) -> dict:
    work = cache_dir() / "otio" / "bridge"
    work.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:12]
    req, out = work / f"{command}_{key}.in.json", work / f"{command}_{key}.out.json"
    write_json(req, payload)
    try:
        run([python(), "-I", Path(__file__).resolve().parents[1] / "otio_bridge.py", command, req, out], timeout=timeout)
        return read_json(out) or {}
    finally:
        for f in (req, out):
            f.unlink(missing_ok=True)


def write(h: Handoff, out: str | Path, fmt: str) -> Path:
    """fmt: otio | xml | edl | kdenlive. EDL carries the main track only (one video track by definition)."""
    if fmt not in ADAPTERS:
        raise VeditError(f"Unknown OTIO format '{fmt}'. Use one of: {', '.join(ADAPTERS)}")
    adapter, _ext = ADAPTERS[fmt]
    payload = h.to_dict()
    payload["fps_exact"] = float(rate(h.fps))
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    bridge("write", {"handoff": payload, "out": str(out), "adapter": adapter, "only_main": fmt == "edl"})
    return out


def read(path: str | Path, *, fps: float | None = None) -> dict:
    return bridge("read", {"path": str(Path(path).resolve()), "rate": fps})


def validate_fcpxml(path: str | Path, dtd: str | Path | None = None) -> dict:
    """DTD check of an FCPXML file. Apple's DTD is not redistributable: pass the one inside Final Cut Pro
    (Contents/Frameworks/Interchange.framework/.../FCPXMLv1_10.dtd) or put it in .cache/tools/otio/dtd/."""
    dtd = Path(dtd) if dtd else cache_dir() / "tools" / "otio" / "dtd" / "FCPXMLv1_10.dtd"
    if not dtd.exists():
        return {"valid": None, "errors": [f"no DTD at {dtd}"]}
    return bridge("validate", {"path": str(Path(path).resolve()), "dtd": str(dtd)})
