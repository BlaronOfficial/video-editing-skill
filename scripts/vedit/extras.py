"""Extras: grids, audiograms and waveform videos, Ken Burns on stills, batch over a folder (cached,
parallel), and an HTML report of a job (before / after, delivery check, frames).

    vedit grid a.mp4 b.mp4 c.mp4 d.mp4 --cols 2 --out grid.mp4
    vedit audiogram episode.m4a --image cover.png --title "Episode 12" --out ep12.mp4 [--size 1080x1080]
    vedit waveform track.wav --out wave.mp4
    vedit kenburns <p> photo.jpg --at 12 --duration 6 --zoom in --pan right      (b-roll in the edit)
    vedit batch <folder> --recipe recipe.json [--jobs auto]
    vedit report --before raw.mov --after final.mp4 [--platform reels] --out report.html
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .media import ffmpeg, list_media, probe
from .util import VeditError, read_json, run, write_json, write_text


def _guard(out: Path, inputs: list[Path], overwrite: bool) -> Path:
    if any(out.resolve() == Path(i).resolve() for i in inputs):
        raise VeditError("Refusing to overwrite an original.")
    if out.exists() and not overwrite:
        raise VeditError(f"{out} exists (--overwrite to replace it)")
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def grid(files: list[str], out: str, *, cols: int = 2, rows: int | None = None, cell: str = "960x540",
         audio: str = "first", gap: int = 8, overwrite: bool = False) -> dict:
    """Videos side by side (xstack). Each cell keeps its picture (contain); sound from the first or mixed."""
    if len(files) < 2:
        raise VeditError("A grid needs at least two videos.")
    rows = rows or -(-len(files) // cols)
    cw, ch = (int(x) for x in cell.lower().split("x"))
    o = _guard(Path(out), [Path(f) for f in files], overwrite)
    infos = [probe(f) for f in files]
    dur = min(i.duration for i in infos)
    parts, layout = [], []
    for k, f in enumerate(files):
        parts.append(f"[{k}:v]scale={cw}:{ch}:force_original_aspect_ratio=decrease,pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:"
                     f"color=black,setsar=1,fps=30[v{k}]")
        r, c = divmod(k, cols)
        layout.append(f"{c * (cw + gap)}_{r * (ch + gap)}")
    for k in range(len(files), rows * cols):                 # empty cells
        parts.append(f"color=c=black:s={cw}x{ch}:r=30:d={dur:.3f}[v{k}]")
        r, c = divmod(k, cols)
        layout.append(f"{c * (cw + gap)}_{r * (ch + gap)}")
    n = rows * cols
    parts.append("".join(f"[v{k}]" for k in range(n)) + f"xstack=inputs={n}:layout={'|'.join(layout)}:fill=black[v]")
    with_audio = [k for k, i in enumerate(infos) if i.has_audio]
    amap = []
    if with_audio and audio == "mix":
        parts.append("".join(f"[{k}:a]" for k in with_audio) + f"amix=inputs={len(with_audio)}:normalize=1[a]")
        amap = ["-map", "[a]"]
    elif with_audio:
        amap = ["-map", f"{with_audio[0]}:a:0"]
    args = [ffmpeg(), "-y", "-v", "error"]
    for f in files:
        args += ["-i", f]
    run(args + ["-filter_complex", ";".join(parts), "-map", "[v]", *amap, "-t", f"{dur:.3f}", "-c:v", "libx264", "-crf", "18",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(o)], timeout=14400)
    return {"output": str(o), "cells": len(files), "size": f"{cols * cw + (cols - 1) * gap}x{rows * ch + (rows - 1) * gap}",
            "duration": round(dur, 3)}


def _title_ass(title: str, W: int, H: int, dur: float, work: Path, y: float = 0.62) -> Path | None:
    if not title:
        return None
    from .captions import titles_to_ass
    from .timeline import Canvas, Edit, TextItem, Transform
    e = Edit(canvas=Canvas(width=W, height=H))
    e.texts = [TextItem(id="t", text=title, start=0.0, duration=dur, transform=Transform(y=y),
                        style={"size": 0.06, "bold": True, "color": "#FFFFFF", "stroke": "#000000"})]
    return titles_to_ass(e, work / "audiogram_title.ass")


def audiogram(audio: str, out: str, *, image: str | None = None, color: str = "#101418", wave: str = "#FFE14D",
              title: str = "", size: str = "1080x1080", style: str = "line", overwrite: bool = False) -> dict:
    """Sound as a picture: waveform over a cover image or a colour plate, with an optional title."""
    from .paths import fonts_dir
    W, H = (int(x) for x in size.lower().split("x"))
    o = _guard(Path(out), [Path(audio)] + ([Path(image)] if image else []), overwrite)
    info = probe(audio)
    if not info.has_audio:
        raise VeditError("input has no audio stream")
    dur = info.duration
    work = o.parent / f".ag_{os.getpid()}"
    work.mkdir(exist_ok=True)
    wh = int(H * 0.22)
    mode = {"line": "cline", "bars": "p2p", "dots": "point"}.get(style, "cline")
    bg = (f"[1:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,loop=-1:1,fps=30,"
          f"trim=0:{dur:.3f}[bg]" if image else f"color=c={color.replace('#', '0x')}:s={W}x{H}:r=30:d={dur:.3f}[bg]")
    parts = [bg, f"[0:a]aformat=channel_layouts=mono,showwaves=s={W}x{wh}:mode={mode}:rate=30:"
                 f"colors={wave.replace('#', '0x')}:scale=sqrt,format=rgba,colorkey=0x000000:0.01:0[w]",
             f"[bg][w]overlay=0:{int(H * 0.72 - wh / 2)}:shortest=1[v0]"]
    ass = _title_ass(title, W, H, dur, work)
    last = "[v0]"
    if ass:
        fdir = os.path.relpath(fonts_dir(), work).replace("\\", "/")
        parts.append(f"[v0]subtitles={ass.name}:fontsdir='{fdir}'[v1]")
        last = "[v1]"
    args = [ffmpeg(), "-y", "-v", "error", "-i", str(Path(audio).resolve())]
    if image:
        args += ["-i", str(Path(image).resolve())]
    run(args + ["-filter_complex", ";".join(parts), "-map", last, "-map", "0:a:0", "-t", f"{dur:.3f}", "-c:v", "libx264",
                "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                str(o.resolve())], cwd=work, timeout=14400)
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    return {"output": str(o), "duration": round(probe(o).duration, 3), "size": f"{W}x{H}"}


def waveform(audio: str, out: str, *, size: str = "1920x1080", overwrite: bool = False) -> dict:
    return audiogram(audio, out, size=size, overwrite=overwrite)


def kenburns(proj, image: str, *, at: float, duration: float, zoom: str = "in", pan: str = "none",
             track: str = "broll") -> dict:
    """A still with a slow zoom (and drift) as b-roll at `at` (or appended to the main track)."""
    from .project import add_source
    from .timeline import Clip, Zoom
    sid = add_source(proj, image, origin="still")
    e = proj.edit()
    ax, ay = {"left": (-0.7, 0), "right": (0.7, 0), "up": (0, 0.7), "down": (0, -0.7)}.get(pan, (0, 0))
    z = Zoom(start_scale=1.0 if zoom == "in" else 1.15, end_scale=1.15 if zoom == "in" else 1.0, ease="inout",
             anchor_x=ax, anchor_y=ay)
    c = Clip(id=f"kb_{sid}", source=sid, src_in=0.0, src_out=duration, zoom=z, fit="cover", label=f"still: {Path(image).stem}")
    if track == "main":
        e.main.append(c)
    else:
        c.start = at
        e.broll.append(c)
    proj.save_edit(e)
    return {"clip": c.id, "source": sid, "track": track, "start": at, "duration": duration}


# ------------------------------------------------------------------ batch

def batch(folder: str, recipe: str | dict, *, jobs: str | int = "auto", dry_run: bool = False, pattern: str | None = None) -> dict:
    """Run a recipe over every media file in a folder, in parallel, skipping files already done with the same
    recipe (cache in <folder>/.vedit_batch.json).

    recipe: {"steps": [["delivery", "export", "{file}", "--preset", "reels", "--out", "{out_dir}/{stem}_reels.mp4"], ...],
             "outputs": ["{out_dir}/{stem}_reels.mp4"], "out_dir": "{folder}/out", "kinds": ["video"]}
    Placeholders: {file} {stem} {name} {folder} {out_dir}. Each step is a vedit command line."""
    folder_p = Path(folder).resolve()
    r = read_json(recipe) if isinstance(recipe, str) else recipe
    if not r or not r.get("steps"):
        raise VeditError("A batch recipe needs 'steps' (vedit command lines with {file} placeholders).")
    rhash = hashlib.sha1(json.dumps(r, sort_keys=True).encode()).hexdigest()[:12]
    out_dir = Path(str(r.get("out_dir", "{folder}/out")).format(folder=folder_p))
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_f = folder_p / ".vedit_batch.json"
    cache = read_json(cache_f, default={}) or {}
    kinds = set(r.get("kinds", ["video"]))
    files = [f for f in list_media(folder_p) if (not pattern or f.match(pattern)) and probe(f).kind in kinds
             and out_dir not in f.parents]
    n = (os.cpu_count() or 2) // 2 if jobs == "auto" else int(jobs)
    n = max(1, min(n, 4))

    def one(f: Path) -> dict:
        st = f.stat()
        key = f"{f.name}:{st.st_size}:{int(st.st_mtime)}:{rhash}"
        ph = {"file": str(f), "stem": f.stem, "name": f.name, "folder": str(folder_p), "out_dir": str(out_dir)}
        outs = [o.format(**ph) for o in r.get("outputs", [])]
        if cache.get(f.name) == key and outs and all(Path(o).exists() for o in outs):
            return {"file": f.name, "status": "cached", "outputs": outs}
        steps = [[str(a).format(**ph) for a in step] for step in r["steps"]]
        if dry_run:
            return {"file": f.name, "status": "planned", "steps": steps}
        t0 = time.time()
        for step in steps:
            proc = subprocess.run([sys.executable, "-m", "vedit.cli", *step], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", cwd=Path(__file__).resolve().parents[1],
                                  env={**os.environ, "PYTHONUTF8": "1"})
            if proc.returncode != 0:
                return {"file": f.name, "status": "failed", "step": " ".join(step[:3]),
                        "error": (proc.stderr or proc.stdout).strip()[-400:]}
        cache[f.name] = key
        return {"file": f.name, "status": "done", "outputs": outs, "seconds": round(time.time() - t0, 1)}

    with ThreadPoolExecutor(max_workers=n) as ex:
        res = list(ex.map(one, files))
    if not dry_run:
        write_json(cache_f, cache)
    return {"folder": str(folder_p), "files": len(files), "jobs": n, "recipe": rhash,
            "done": sum(1 for x in res if x["status"] == "done"), "cached": sum(1 for x in res if x["status"] == "cached"),
            "failed": [x for x in res if x["status"] == "failed"], "results": res}


# ------------------------------------------------------------------ report

def _img64(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def report(after: str, out: str, *, before: str | None = None, platform: str | None = None, title: str = "",
           steps: list[str] | None = None) -> dict:
    """A self-contained HTML page: what went in, what came out, the delivery check and frames of both."""
    from .view import frames_at
    o = Path(out)
    o.parent.mkdir(parents=True, exist_ok=True)
    work = o.parent / f".report_{os.getpid()}"
    work.mkdir(exist_ok=True)

    def facts(p: str) -> dict:
        i = probe(p)
        from .media import measure_loudness
        lm = measure_loudness(p) if i.has_audio else None
        return {"file": Path(p).name, "duration": f"{i.duration:.2f} s", "picture": f"{i.width}x{i.height} @ {i.fps:.3f}"
                if i.width else "none", "codecs": f"{i.vcodec or '-'} / {i.acodec or '-'}",
                "loudness": f"{lm['lufs']:.1f} LUFS, {lm['true_peak']:.1f} dBTP" if lm else "-",
                "size": f"{Path(p).stat().st_size / 1048576:.1f} MB"}

    def sheet(p: str, name: str) -> str:
        i = probe(p)
        if not i.width:
            return ""
        ts = [i.duration * k / 7 for k in range(1, 7)]
        return _img64(frames_at(p, ts, work / f"{name}.png", width=240))

    cols = [("Before", before), ("After", after)] if before else [("Result", after)]
    chk = None
    if platform:
        from .delivery import check
        chk = check(after, platform)
    rows = "".join(f"<tr><th>{k}</th>" + "".join(f"<td>{html.escape(str(facts(p)[k]))}</td>" for _, p in cols) + "</tr>"
                   for k in ("file", "duration", "picture", "codecs", "loudness", "size"))
    imgs = {n: sheet(p, n) for n, p in cols}
    sheets = "".join(f"<h3>{n}</h3><img src='{imgs[n]}' alt='{n} frames'>" for n, _ in cols if imgs[n])
    chk_html = ""
    if chk:
        chk_html = (f"<h2>Delivery check: {chk['platform']} - {chk['verdict']} ({chk['passed']}/{chk['total']})</h2><table>"
                    + "".join(f"<tr class='{r['status'].lower()}'><td>{r['status']}</td><th>{html.escape(r['check'])}</th>"
                              f"<td>{html.escape(str(r['value']))}</td><td>{html.escape(str(r['expect']))}</td>"
                              f"<td>{html.escape(r['fix'] if r['status'] != 'PASS' else '')}</td></tr>" for r in chk["rows"])
                    + "</table>")
    st = "".join(f"<li>{html.escape(s)}</li>" for s in steps or [])
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title or Path(after).stem)}</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:2em auto;padding:0 16px;color:#1b1f24}}
table{{border-collapse:collapse;width:100%;margin:1em 0}}td,th{{border-bottom:1px solid #dde2e8;padding:6px 8px;text-align:left}}
tr.fail td:first-child{{color:#b3261e;font-weight:600}}tr.warn td:first-child{{color:#9a6700;font-weight:600}}
tr.pass td:first-child{{color:#1a7f37}}img{{max-width:100%;border-radius:6px}}</style></head><body>
<h1>{html.escape(title or Path(after).stem)}</h1><p>{time.strftime('%Y-%m-%d %H:%M')} · vedit</p>
{f'<h2>Steps</h2><ol>{st}</ol>' if st else ''}<h2>Files</h2><table><tr><th></th>{''.join(f'<th>{n}</th>' for n, _ in cols)}</tr>{rows}</table>
{chk_html}<h2>Frames</h2>{sheets}</body></html>"""
    write_text(o, page)
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    return {"report": str(o), "verdict": chk["verdict"] if chk else None}
