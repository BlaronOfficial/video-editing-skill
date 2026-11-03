"""Blender (optional add-on, free, GPL as a separate app): headless 3D renders with real geometry.

Templates live in blender/*.py (index in blender/index.json); Claude can also write a project bpy script
and run it as CustomFX kind=blender. Both follow one contract (see blender/common.py): RGBA PNG frames
with a transparent background, encoded here like any other graphic (WebM alpha for our renderer,
ProRes 4444 / green key for editors).

Use it for hero shots that need real light and depth (bevelled metal titles, extruded logos, product
turntables). For Bangla text, live preview in the Studio, or speed, use the Three.js templates.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .media import ffmpeg
from .paths import SKILL_ROOT, fonts_dir
from .util import VeditError, read_json, run, write_json


def blender_dir() -> Path:
    return SKILL_ROOT / "blender"


def exe() -> Path:
    from .addons import find_blender
    b = find_blender()
    if not b:
        raise VeditError("Blender is not installed (optional add-on, ~350 MB). Ask the owner first, then: "
                         "`winget install BlenderFoundation.Blender` (or blender.org). The Three.js 3D templates need nothing.")
    return Path(b)


def templates() -> dict:
    return read_json(blender_dir() / "index.json", default={}) or {}


def script_path(name_or_file: str, project_root: Path | None = None) -> Path:
    p = Path(name_or_file)
    if p.suffix == ".py":
        if not p.is_absolute() and project_root:
            p = project_root / p
        if p.exists():
            return p
    cand = blender_dir() / f"{name_or_file}.py"
    if cand.exists():
        return cand
    raise VeditError(f"No Blender template or script '{name_or_file}'. Templates: {', '.join(templates())}")


def render_frames(script: Path, frames_dir: Path, *, data: dict, width: int, height: int, fps: float, duration: float,
                  engine: str = "eevee", samples: int = 0, still: float | None = None, timeout: int = 7200) -> Path:
    frames_dir.mkdir(parents=True, exist_ok=True)
    params = frames_dir / "params.json"
    write_json(params, {"fonts_dir": str(fonts_dir()), **data})
    cmd = [str(exe()), "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(script), "--",
           "--params", str(params), "--out", str(frames_dir), "--width", str(width), "--height", str(height),
           "--fps", f"{fps:g}", "--duration", f"{duration:.3f}", "--engine", engine]
    if samples:
        cmd += ["--samples", str(samples)]
    if still is not None:
        cmd += ["--still", f"{still:.3f}"]
    proc = run(cmd, check=False, timeout=timeout)
    if proc.returncode != 0:
        lines = [l for l in (proc.stdout or "").splitlines() + (proc.stderr or "").splitlines()
                 if any(k in l for k in ("Error", "error", "SystemExit", "Traceback", "raise"))]
        raise VeditError("Blender render failed:\n" + "\n".join(lines[-20:] or (proc.stderr or proc.stdout or "")[-1500:].splitlines()))
    return frames_dir


def encode(frames_dir: Path, out_stem: Path, *, fps: float, formats: list[str]) -> list[Path]:
    """PNG frames -> the overlay formats mg uses (webm alpha, prores 4444, green key mp4, mp4)."""
    pattern = str(frames_dir / "f_%05d.png")
    outs = []
    for fmt in formats:
        if fmt == "webm":
            out = Path(str(out_stem) + ".webm")
            args = ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-crf", "22", "-b:v", "0", "-row-mt", "1",
                    "-deadline", "good", "-cpu-used", "4", "-auto-alt-ref", "0"]
            vf = []
        elif fmt == "prores":
            out = Path(str(out_stem) + ".mov")
            args = ["-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le", "-vendor", "apl0"]
            vf = []
        elif fmt == "key":
            out = Path(str(out_stem) + "_key.mp4")
            args = ["-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p"]
            vf = None
        else:
            out = Path(str(out_stem) + ".mp4")
            args = ["-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p"]
            vf = []
        if vf is None:      # composite over green for editors without alpha
            run([ffmpeg(), "-y", "-v", "error", "-framerate", f"{fps:g}", "-i", pattern, "-filter_complex",
                 "color=c=0x00FF00:s=16x16[g];[g][0:v]scale2ref[g2][f];[g2][f]overlay=shortest=1,format=yuv420p",
                 *args, str(out)], timeout=3600)
        else:
            run([ffmpeg(), "-y", "-v", "error", "-framerate", f"{fps:g}", "-i", pattern, *args, str(out)], timeout=3600)
        outs.append(out)
    return outs


def render(template: str, out_stem: Path, *, data: dict, width: int, height: int, fps: float, duration: float,
           formats: list[str] | None = None, engine: str = "eevee", samples: int = 0, project_root: Path | None = None,
           keep_frames: bool = False) -> dict:
    script = script_path(template, project_root)
    frames_dir = Path(str(out_stem) + "_frames")
    t0 = time.time()
    render_frames(script, frames_dir, data=data, width=width, height=height, fps=fps, duration=duration, engine=engine,
                  samples=samples)
    n = len(list(frames_dir.glob("f_*.png")))
    if n == 0:
        raise VeditError("Blender wrote no frames")
    outs = encode(frames_dir, out_stem, fps=fps, formats=formats or ["webm"])
    if not keep_frames:
        shutil.rmtree(frames_dir, ignore_errors=True)
    return {"outputs": [str(o) for o in outs], "frames": n, "seconds": round(time.time() - t0, 1), "engine": engine}


def still(template: str, out_png: Path, *, data: dict, width: int, height: int, t: float, fps: float = 30.0,
          duration: float = 3.0, engine: str = "eevee", project_root: Path | None = None) -> Path:
    script = script_path(template, project_root)
    frames_dir = out_png.with_suffix("")
    render_frames(script, frames_dir, data=data, width=width, height=height, fps=fps, duration=duration, engine=engine,
                  still=t)
    shutil.move(str(frames_dir / "still.png"), out_png)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return out_png


# ------------------------------------------------------------------ CLI

def register_cli(sp) -> None:
    s = sp.add_parser("blender", help="Blender 3D renders (optional add-on): templates, stills, project scripts")
    s.add_argument("action", choices=["check", "templates", "render", "still"])
    s.add_argument("template", nargs="?", help="template name or a .py bpy script")
    s.add_argument("--data", default="{}", help="JSON object or a .json file"); s.add_argument("--out")
    s.add_argument("--size", default="1080x1920"); s.add_argument("--fps", type=float, default=30.0)
    s.add_argument("--duration", type=float, default=3.0); s.add_argument("--at", type=float, default=1.5)
    s.add_argument("--engine", default="eevee", choices=["eevee", "cycles"]); s.add_argument("--samples", type=int, default=0)
    s.add_argument("--formats", default="webm")
    s.set_defaults(fn=_cmd)


def _cmd(a) -> None:
    from .util import print_json
    if a.action == "check":
        from .addons import find_blender
        b = find_blender()
        ver = ""
        if b:
            proc = run([str(b), "-b", "--factory-startup", "--version"], check=False, timeout=120)
            ver = next((l for l in (proc.stdout or "").splitlines() if l.startswith("Blender")), "")
        print_json({"blender": str(b or ""), "version": ver, "templates": sorted(templates())})
        return
    if a.action == "templates":
        print_json(templates())
        return
    if not a.template:
        raise VeditError("vedit blender render|still <template> --data '{...}' --out <file>")
    data = read_json(a.data) if a.data.endswith(".json") else json.loads(a.data)
    w, h = (int(v) for v in a.size.lower().split("x"))
    if a.action == "still":
        out = Path(a.out or f"{a.template}_still.png").resolve()
        print_json({"still": str(still(a.template, out, data=data, width=w, height=h, t=a.at, fps=a.fps,
                                       duration=a.duration, engine=a.engine))})
        return
    stem = Path(a.out or a.template).resolve()
    stem = stem.with_suffix("") if stem.suffix else stem
    print_json(render(a.template, stem, data=data, width=w, height=h, fps=a.fps, duration=a.duration,
                      formats=a.formats.split(","), engine=a.engine, samples=a.samples))
