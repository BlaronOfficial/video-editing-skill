"""Storyboard: a self-contained HTML page (images inlined) showing the planned edit for approval.

Shows each main clip with a frame, its transcript, captions, graphics, b-roll, SFX and music cues,
plus what was cut. The user approves or asks for changes in plain words before anything renders.
"""

from __future__ import annotations

import base64
import html
from pathlib import Path

from . import captions as caps
from .cuts import removed_summary
from .media import ffmpeg
from .timeline import Edit
from .util import fmt_ts, run, write_text


def _thumb(src: str, t: float, out: Path, width: int = 360, *, aspect: float | None = None, cx: float = 0.5) -> str:
    """Frame at t, cropped to the canvas aspect around cx (so reframed clips look like the output)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        vf = f"scale={width}:-2"
        if aspect:
            vf = (f"crop='min(iw,ih*{aspect:.5f})':'min(ih,iw/{aspect:.5f})':"
                  f"'max(0,min(iw-ow,{cx:.4f}*iw-ow/2))':'(ih-oh)/2',scale={width}:-2")
        run([ffmpeg(), "-y", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", src, "-frames:v", "1", "-vf", vf,
             "-q:v", "4", str(out)], check=False)
    if not out.exists():
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(out.read_bytes()).decode()


def _in_range(start: float, end: float, t0: float, t1: float) -> bool:
    return start < t1 and (end if end > start else start + 0.01) > t0


def _starts_in(start: float, t0: float, t1: float, first: bool) -> bool:
    """Cue belongs to the card where it starts (first card also takes cues starting before 0)."""
    return t0 <= start < t1 or (first and start < t0)


def build(edit: Edit, out_dir: Path, *, title: str | None = None) -> Path:
    edit = edit.layout()
    frames = out_dir / "frames"
    chunks = edit.captions.chunks or (caps.build_chunks(edit) if edit.captions.enabled else [])
    cards = []
    for i, clip in enumerate(edit.main):
        src = edit.sources[clip.source]
        t0, t1 = clip.start or 0, clip.end
        first = i == 0
        canvas_aspect = edit.canvas.width / edit.canvas.height
        src_aspect = (src.width / src.height) if src.width and src.height else canvas_aspect
        crop_aspect = canvas_aspect if abs(src_aspect - canvas_aspect) > 0.02 and (clip.crop or clip.fit == "cover") else None
        cx = clip.crop[len(clip.crop) // 2].cx if clip.crop else 0.5
        img = (_thumb(src.path, (clip.src_in + clip.src_out) / 2, frames / f"{i:03d}_{clip.id}.jpg", aspect=crop_aspect, cx=cx)
               if src.kind != "audio" else "")
        words = []
        if src.transcript:
            words = [w["w"] for w in caps.transcript_words(src.transcript) if clip.src_in <= (w["s"] + w["e"]) / 2 <= clip.src_out]
        cues = []
        for b in edit.broll:
            if b.start is not None and _starts_in(b.start, t0, t1, first):
                cues.append(("B-roll", f"{edit.sources[b.source].id} {fmt_ts(b.start)} ({b.duration:.1f}s) {b.label}"))
        for o in edit.overlays:
            if _starts_in(o.start, t0, t1, first):
                what = o.mg.template or Path(o.mg.file or "").name if o.mg else Path(o.path or "").name
                data = ""
                if o.mg and o.mg.data:
                    data = " · " + ", ".join(f"{k}: {v}" for k, v in list(o.mg.data.items())[:3] if not isinstance(v, (dict, list)))
                cues.append(("Graphic", f"{what} @{fmt_ts(o.start)} {o.duration:.1f}s{data}"))
        for x in edit.texts:
            if _starts_in(x.start, t0, t1, first):
                cues.append(("Text", f"“{x.text}” @{fmt_ts(x.start)}"))
        for a in edit.audio:
            if a.role == "sfx" and _starts_in(a.start, t0, t1, first):
                cues.append(("SFX", f"{edit.sources[a.source].id} @{fmt_ts(a.start)}"))
        for fx in edit.effects:
            if _starts_in(fx.start, t0, t1, first):
                cues.append(("Effect", f"{fx.render or fx.capcut} @{fmt_ts(fx.start)}"))
        caps_here = [c.text for c in chunks if _in_range(c.start, c.end, t0, t1)]
        extras = []
        if clip.zoom:
            extras.append(f"zoom {clip.zoom.start_scale:.2f}→{clip.zoom.end_scale:.2f}")
        if clip.transition_in:
            extras.append(f"transition in: {clip.transition_in.type}")
        if abs(clip.speed - 1) > 1e-3:
            extras.append(f"speed {clip.speed:g}x")
        cards.append(f"""
<article class="card">
  <div class="frame">{f'<img src="{img}" alt="">' if img else '<div class="noimg">audio</div>'}
    <span class="tc">{fmt_ts(t0)} – {fmt_ts(t1)}</span></div>
  <div class="body">
    <h3>{i + 1}. {html.escape(clip.label or clip.id)} <small>{html.escape(src.id)} {clip.src_in:.2f}–{clip.src_out:.2f}s
      {' · ' + html.escape(', '.join(extras)) if extras else ''}</small></h3>
    <p class="say">{html.escape(' '.join(words)) or '<em>(no speech)</em>'}</p>
    {f'<p class="caps">CC: {html.escape(" | ".join(caps_here[:6]))}</p>' if caps_here else ''}
    <ul>{''.join(f'<li><b>{k}</b> {html.escape(v)}</li>' for k, v in cues)}</ul>
  </div>
</article>""")
    cut = removed_summary(edit)
    music = [f"{edit.sources[a.source].id} (vol {a.volume:g}{', ducked' if a.ducks else ''})" for a in edit.audio if a.role == "music"]
    stats = [("Length", fmt_ts(edit.duration, ms=False)), ("Canvas", f"{edit.canvas.width}×{edit.canvas.height} @ {edit.canvas.fps:g}"),
             ("Clips", str(len(edit.main))), ("Graphics", str(len(edit.overlays))), ("B-roll", str(len(edit.broll))),
             ("Captions", f"{edit.captions.style} ({len(chunks)})" if edit.captions.enabled else "off"),
             ("Grade", edit.color.preset or edit.color.capcut_filter or "none"), ("Music", ", ".join(music) or "none")]
    cut_rows = "".join(f"<li>{html.escape(k)}: kept {v['kept_s']}s of {v['source_s']}s ({v['removed_pct']}% removed)</li>" for k, v in cut.items())
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title or edit.name)} storyboard</title>
<style>
:root {{ --bg:#f6f6f4; --fg:#16161a; --muted:#6b6b76; --card:#fff; --line:#e4e4e0; --accent:#c7a400; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111114; --fg:#ececf0; --muted:#9a9aa6; --card:#1b1b20; --line:#2a2a31; --accent:#ffe14d; }} }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, "Segoe UI", "Nirmala UI", sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ font-size:26px; margin:0 0 4px; }} .sub {{ color:var(--muted); margin:0 0 18px; }}
.stats {{ display:flex; flex-wrap:wrap; gap:8px; margin:0 0 18px; padding:0; list-style:none; }}
.stats li {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:8px 12px; }}
.stats b {{ display:block; font-size:12px; color:var(--muted); font-weight:600; }}
.card {{ display:grid; grid-template-columns:minmax(140px,240px) 1fr; gap:16px; background:var(--card); border:1px solid var(--line);
        border-radius:14px; padding:12px; margin:0 0 12px; }}
.frame {{ position:relative; }} .frame img {{ width:100%; border-radius:10px; display:block; }}
.noimg {{ aspect-ratio:9/16; display:grid; place-items:center; background:var(--line); border-radius:10px; color:var(--muted); }}
.tc {{ position:absolute; left:6px; bottom:6px; background:rgba(0,0,0,.7); color:#fff; font-size:12px; padding:2px 6px; border-radius:6px; }}
h3 {{ margin:0 0 6px; font-size:16px; }} h3 small {{ color:var(--muted); font-weight:500; font-size:12px; }}
.say {{ margin:0 0 6px; }} .caps {{ margin:0 0 6px; color:var(--accent); font-weight:600; font-size:13px; }}
ul {{ margin:0; padding-left:18px; color:var(--muted); font-size:13px; }} li b {{ color:var(--fg); }}
.notes {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 16px; margin:0 0 18px; white-space:pre-wrap; }}
@media (max-width:640px) {{ .card {{ grid-template-columns:1fr; }} }}
</style></head><body><main>
<h1>{html.escape(title or edit.name)}</h1><p class="sub">Storyboard for approval. Reply with changes in plain words, e.g. “tighter cut”, “bigger captions”, “swap the hook”.</p>
<ul class="stats">{''.join(f'<li><b>{k}</b>{html.escape(v)}</li>' for k, v in stats)}</ul>
{f'<div class="notes">{html.escape(edit.notes)}</div>' if edit.notes else ''}
{f'<ul>{cut_rows}</ul>' if cut_rows else ''}
{''.join(cards)}
</main></body></html>"""
    out = out_dir / "index.html"
    write_text(out, page)
    return out
