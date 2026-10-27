"""Motion-graphics orchestration: pick an engine, render to alpha video, wire results into edit.json.

Engines
  html        mg/renderer (headless Chrome, frame-accurate, real alpha). Templates + custom compositions.
  hyperframes `npx hyperframes render` for full HyperFrames projects (MP4, no alpha) - full-screen scenes.
  remotion    mg/remotion project (React). Alpha via ProRes 4444. Remotion licence applies (see README).
  pil         pure-Python fallback for simple shapes/text when Node/Chrome are unavailable.
`auto` -> html for templates and .html files, remotion for .tsx/.jsx, hyperframes for directories with
hyperframes.json, pil if Chrome is missing.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .media import ffmpeg, probe
from .paths import IS_WINDOWS, chrome_candidates, mg_dir
from .timeline import Edit, MGSpec, Overlay
from .util import VeditError, read_json, run, short_hash, which, write_json

OVERLAY_FORMATS = {"prores": ".mov", "webm": ".webm", "key": "_key.mp4", "mp4": ".mp4"}


def templates() -> dict:
    return read_json(mg_dir() / "templates" / "index.json", default={}) or {}


def _node() -> str:
    exe = which("node")
    if not exe:
        raise VeditError("Node.js not found (needed for motion graphics). Install Node 20+ and run `vedit setup`.")
    return exe


def chrome() -> Path | None:
    return next((p for p in chrome_candidates() if p.exists()), None)


def renderer_ready() -> bool:
    return (mg_dir() / "renderer" / "node_modules" / "puppeteer-core").exists() and chrome() is not None


def pick_engine(spec: MGSpec) -> str:
    if spec.engine != "auto":
        return spec.engine
    if spec.file:
        f = Path(spec.file)
        if f.suffix in (".tsx", ".jsx", ".ts"):
            return "remotion"
        if f.is_dir() and (f / "hyperframes.json").exists():
            return "hyperframes"
    return "html" if renderer_ready() else "pil"


def render_html(comp: Path, out_stem: Path, *, width: int, height: int, fps: float, duration: float, data: dict,
                formats: list[str], workers: int | None = None) -> list[Path]:
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    data_file = out_stem.with_suffix(".data.json")
    write_json(data_file, {**data, "duration": duration})
    cmd = [_node(), str(mg_dir() / "renderer" / "render.mjs"), "--input", str(comp), "--out", str(out_stem) + ".mov",
           "--formats", ",".join(formats), "--width", str(width), "--height", str(height), "--fps", str(fps),
           "--duration", f"{duration:.3f}", "--data", str(data_file)]
    if workers:
        cmd += ["--workers", str(workers)]
    proc = run(cmd, check=False, timeout=3600)
    lines = [l for l in (proc.stdout or "").splitlines() if l.startswith("{")]
    if proc.returncode != 0 or not lines:
        errs = [l for l in (proc.stderr or "").splitlines() if "[missing]" not in l and "404" not in l]
        raise VeditError("Motion-graphics render failed:\n" + "\n".join(errs[-25:]))
    missing = sorted({l.split("] ", 1)[-1] for l in (proc.stderr or "").splitlines() if l.startswith("[missing]")})
    if missing:
        print("warning: missing resources (fonts not downloaded? run `vedit setup fonts`):", ", ".join(missing[:8]))
    return [Path(p) for p in json.loads(lines[-1])["outputs"]]


def still(comp: Path, out_png: Path, *, width: int, height: int, t: float, data: dict) -> Path:
    data_file = out_png.with_suffix(".data.json")
    write_json(data_file, data)
    run([_node(), str(mg_dir() / "renderer" / "render.mjs"), "--input", str(comp), "--out", str(out_png), "--still", str(t),
         "--width", str(width), "--height", str(height), "--data", str(data_file)], timeout=300)
    return out_png


def render_remotion(entry: Path, composition: str, out: Path, *, props: dict, width: int, height: int, fps: float,
                    duration: float, alpha: bool = True) -> Path:
    project = mg_dir() / "remotion"
    if not (project / "node_modules").exists():
        run(["npm", "install", "--no-audit", "--no-fund"], cwd=project, timeout=1800)
    props_file = out.with_suffix(".props.json")
    write_json(props_file, {**props, "width": width, "height": height, "fps": fps, "durationInFrames": round(duration * fps)})
    npx = "npx.cmd" if IS_WINDOWS else "npx"
    cmd = [npx, "remotion", "render", str(entry), composition, str(out), f"--props={props_file}",
           f"--width={width}", f"--height={height}"]
    if alpha:
        cmd += ["--codec=prores", "--prores-profile=4444", "--pixel-format=yuva444p10le", "--image-format=png"]
    if c := chrome():
        cmd.append(f"--browser-executable={c}")
    run(cmd, cwd=project, timeout=3600)
    return out


def render_hyperframes(project_dir: Path, out: Path) -> Path:
    npx = "npx.cmd" if IS_WINDOWS else "npx"
    run([npx, "hyperframes", "render"], cwd=project_dir, timeout=3600)
    produced = sorted(project_dir.glob("**/*.mp4"), key=lambda p: p.stat().st_mtime)
    if not produced:
        raise VeditError("HyperFrames produced no MP4.")
    shutil.copy(produced[-1], out)
    return out


def render_pil(spec: MGSpec, out_stem: Path, *, width: int, height: int, fps: float, duration: float) -> list[Path]:
    """Minimal fallback: animated text card (fade + rise) rendered with Pillow."""
    from PIL import Image, ImageDraw, ImageFont
    from .paths import fonts_dir
    text = str(spec.data.get("text") or spec.data.get("title") or "")
    frames_dir = out_stem.parent / (out_stem.name + "_frames")
    frames_dir.mkdir(parents=True, exist_ok=True)
    font_path = fonts_dir() / "Poppins-ExtraBold.ttf"
    size = int(min(width, height) * 0.09)
    font = ImageFont.truetype(str(font_path), size) if font_path.exists() else ImageFont.load_default()
    n = max(1, round(duration * fps))
    for i in range(n):
        t = i / fps
        p = min(1.0, t / 0.4)
        out_a = min(1.0, max(0.0, (duration - t) / 0.3))
        alpha = int(255 * min(p, out_a))
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        y = int(height * float(spec.data.get("y", 0.45)) + (1 - p) * 40)
        d.text((width // 2, y), text, font=font, fill=(255, 255, 255, alpha), anchor="mm", stroke_width=max(2, size // 12),
               stroke_fill=(0, 0, 0, alpha))
        img.save(frames_dir / f"f_{i:05d}.png")
    out = Path(str(out_stem) + ".mov")
    run([ffmpeg(), "-y", "-v", "error", "-framerate", str(fps), "-i", str(frames_dir / "f_%05d.png"), "-c:v", "prores_ks",
         "-profile:v", "4", "-pix_fmt", "yuva444p10le", str(out)])
    shutil.rmtree(frames_dir, ignore_errors=True)
    return [out]


def overlay_formats(capcut_alpha: str) -> list[str]:
    """Render formats for overlays: WebM alpha for our renderer (small), plus what CapCut can import.

    Until `vedit capcut probe-alpha` has been answered, CapCut gets the cheap green-key MP4 (works in
    every build via chroma key); ProRes 4444 is only rendered once CapCut is known to read it.
    """
    if capcut_alpha == "prores":
        return ["webm", "prores"]
    if capcut_alpha == "webm":
        return ["webm"]
    return ["webm", "key"]


def render_overlay(edit: Edit, ov: Overlay, out_dir: Path, *, capcut_alpha: str = "unknown", force: bool = False) -> Overlay:
    spec = ov.mg
    if spec is None:
        return ov
    W = spec.width or edit.canvas.width
    H = spec.height or edit.canvas.height
    fps = edit.canvas.fps
    key = short_hash(spec.model_dump(mode="json"), ov.duration, W, H, fps)
    stem = out_dir / f"{ov.id}_{key}"
    engine = pick_engine(spec)
    formats = overlay_formats(capcut_alpha)
    existing = [Path(str(stem) + OVERLAY_FORMATS[f]) for f in formats]
    if not force and all(p.exists() for p in existing):
        outputs = existing
    elif engine == "html":
        comp = Path(spec.file) if spec.file else mg_dir() / "templates" / f"{spec.template}.html"
        if not comp.exists():
            raise VeditError(f"Composition not found: {comp}")
        outputs = render_html(comp, stem, width=W, height=H, fps=fps, duration=ov.duration, data=spec.data, formats=formats)
    elif engine == "remotion":
        out = render_remotion(Path(spec.file), spec.data.get("composition", "Main"), Path(str(stem) + ".mov"),
                              props=spec.data, width=W, height=H, fps=fps, duration=ov.duration, alpha=spec.alpha)
        outputs = [out]
    elif engine == "hyperframes":
        outputs = [render_hyperframes(Path(spec.file), Path(str(stem) + ".mp4"))]
    else:
        outputs = render_pil(spec, stem, width=W, height=H, fps=fps, duration=ov.duration)
    by_ext = {p.name[len(stem.name):]: p for p in outputs}
    ov.path = str(by_ext.get(".webm") or by_ext.get(".mov") or outputs[0])
    ov.renders = {k: str(v) for k, v in by_ext.items()}
    return ov


def render_all(edit: Edit, out_dir: Path, *, capcut_alpha: str = "unknown", only: list[str] | None = None,
               force: bool = False) -> list[str]:
    done = []
    for ov in edit.overlays:
        if ov.mg and (not only or ov.id in only):
            render_overlay(edit, ov, out_dir, capcut_alpha=capcut_alpha, force=force)
            done.append(ov.id)
    return done


def capcut_path(ov: Overlay, mode: str) -> str | None:
    """Which render CapCut should import for this overlay (alpha mov vs green-key mp4)."""
    renders = ov.renders
    if mode == "chroma":
        return renders.get("_key.mp4") or ov.path
    if mode in ("prores", "alpha", "auto", "unknown"):
        return renders.get(".mov") or ov.path
    if mode == "webm":
        return renders.get(".webm") or ov.path
    return ov.path


def contact_sheet(video: str | Path, out_png: str | Path, *, times: list[float] | None = None, width: int = 270,
                  bg: str = "0x3a4a5a") -> Path:
    """Frames of a (possibly transparent) render composited over a slate background, side by side."""
    from PIL import Image, ImageDraw
    info = probe(video)
    times = times or [info.duration * f for f in (0.15, 0.35, 0.55, 0.8)]
    tiles = []
    tmp = Path(out_png).with_suffix("")
    for i, t in enumerate(times):
        frame = Path(f"{tmp}_{i}.png")
        run([ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={bg}:s={info.width}x{info.height}",
             "-ss", f"{t:.3f}", "-i", str(video), "-filter_complex", f"[0:v][1:v]overlay=format=auto,scale={width}:-2",
             "-frames:v", "1", str(frame)])
        tiles.append((t, Image.open(frame)))
    w, h = tiles[0][1].size
    sheet = Image.new("RGB", (w * len(tiles), h + 24), "black")
    draw = ImageDraw.Draw(sheet)
    for i, (t, im) in enumerate(tiles):
        sheet.paste(im, (i * w, 24))
        draw.text((i * w + 6, 5), f"{t:.2f}s", fill="white")
    sheet.save(out_png)
    for i in range(len(tiles)):
        Path(f"{tmp}_{i}.png").unlink(missing_ok=True)
    return Path(out_png)
