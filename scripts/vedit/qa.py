"""Self-check a render before showing it: duration, black/frozen frames, loudness, pops at cuts,
long silences, caption safe zones, plus frame sheets around every cut for Claude to look at.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from . import captions as caps
from .audio import load_mono
from .media import detect_scenes, ffmpeg, luma_at, measure_loudness, probe
from .timeline import Edit
from .util import run, write_json
from .view import frames_at


def _detect(src: Path, video_filter: str, pattern: str) -> list[tuple[float, float]]:
    proc = run([ffmpeg(), "-v", "info", "-i", str(src), "-vf", video_filter, "-an", "-f", "null", "-"], check=False)
    return [(float(a), float(b)) for a, b in re.findall(pattern, proc.stderr or "")]


def check(edit: Edit, render_path: str | Path, out_dir: str | Path, *, target_lufs: float = -14.0,
          listen: bool = True, platform: str | None = None) -> dict:
    from .knobs import bake
    edit = bake(edit.layout()).active()
    render_path, out_dir = Path(render_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    info = probe(render_path)
    issues: list[dict] = []

    def issue(kind: str, msg: str, at: float | None = None, severity: str = "warn") -> None:
        issues.append({"kind": kind, "severity": severity, "at": round(at, 2) if at is not None else None, "msg": msg})

    if abs(info.duration - edit.duration) > 0.15:
        issue("duration", f"render is {info.duration:.2f}s but the edit is {edit.duration:.2f}s", severity="error")

    blacks = _detect(render_path, "blackdetect=d=0.25:pix_th=0.06", r"black_start:([\d.]+) black_end:([\d.]+)")
    for a, b in blacks:
        issue("black", f"black frames {a:.2f}–{b:.2f}s", a)
    freezes = []
    proc = run([ffmpeg(), "-v", "info", "-i", str(render_path), "-vf", "freezedetect=n=0.003:d=1.5", "-map", "0:v", "-f", "null", "-"], check=False)
    for a in re.findall(r"freeze_start: ([\d.]+)", proc.stderr or ""):
        freezes.append(float(a))
        issue("freeze", f"frozen picture from {float(a):.2f}s (intended still?)", float(a), "info")

    silences = []
    proc = run([ffmpeg(), "-v", "info", "-i", str(render_path), "-af", "silencedetect=noise=-45dB:d=1.2", "-f", "null", "-"], check=False)
    for a, b in zip(re.findall(r"silence_start: ([\d.]+)", proc.stderr or ""), re.findall(r"silence_end: ([\d.]+)", proc.stderr or "")):
        silences.append((float(a), float(b)))
        issue("silence", f"{float(b) - float(a):.1f}s of silence", float(a))

    loud = measure_loudness(render_path)
    if loud:
        if abs(loud["lufs"] - target_lufs) > 1.5:
            issue("loudness", f"integrated {loud['lufs']:.1f} LUFS (target {target_lufs})")
        if loud["true_peak"] > -0.5:
            issue("peak", f"true peak {loud['true_peak']:.1f} dBTP (clipping risk)")

    # Clicks/pops: high-frequency spikes right at cut points.
    cut_times = [c.start for c in edit.main[1:]]
    pops = []
    if info.has_audio and cut_times:
        sr = 22050
        y = load_mono(render_path, sr)
        hp = np.diff(y, prepend=0.0)
        for t in cut_times:
            i = int(t * sr)
            near = hp[max(0, i - int(0.01 * sr)): i + int(0.01 * sr)]
            ctx = hp[max(0, i - int(0.12 * sr)): i + int(0.12 * sr)]
            if near.size and ctx.size:
                ratio = float(np.abs(near).max() / (np.sqrt(np.mean(ctx ** 2)) + 1e-6))
                if ratio > 9:
                    pops.append(round(t, 2))
                    issue("pop", f"possible click at cut ({ratio:.0f}x local level)", t)

    # Source-side problems at clip boundaries: the kept words may sit on a title card, a shot change or a
    # fade in the ORIGINAL footage (word-based cuts can't see pictures). Flag them for a trim.
    for clip in edit.main:
        src = edit.sources[clip.source]
        if src.kind != "video":
            continue
        dur = clip.src_out - clip.src_in
        for c in detect_scenes(src.path, threshold=0.25, start=clip.src_in, duration=dur):
            if c < 0.8 or dur - c < 0.8:
                where = "start" if c < 0.8 else "end"
                issue("source_cut", f"clip {clip.id}: the source picture changes {c:.2f}s into the clip ({where}) - "
                      f"title card or shot change; trim the {where} (look with `vedit view`)", (clip.start or 0) + c)
        edge_in, mid, edge_out = luma_at(src.path, [clip.src_in + 0.05, clip.src_in + dur / 2, clip.src_out - 0.05])
        if mid > 0.08:
            if edge_in < 0.55 * mid:
                issue("source_fade", f"clip {clip.id}: starts on a fade/dark frame in the source; start later", clip.start)
            if edge_out < 0.55 * mid:
                issue("source_fade", f"clip {clip.id}: ends on a fade/dark frame in the source; end earlier", clip.end)

    # Caption safe zone (vertical video: platform UI covers the bottom ~20% and the right edge).
    if edit.captions.enabled and edit.canvas.height > edit.canvas.width:
        style = caps.resolve_style(edit.captions.style, edit.captions.overrides)
        y_units = style.get("y", -0.42)
        y_frac = 0.5 - y_units / 2            # 0 top .. 1 bottom
        if y_frac > 0.8:
            issue("safe_zone", f"captions sit at {y_frac:.0%} height, under TikTok/Reels UI (keep above ~78%)")
        if y_frac < 0.12:
            issue("safe_zone", "captions too close to the top UI")

    # Frame sheets around cuts for visual review (Claude looks at these).
    sheets = []
    for k in range(0, len(cut_times), 6):
        group = cut_times[k:k + 6]
        times, labels = [], []
        for t in group:
            times += [max(0, t - 0.08), t + 0.08]
            labels += [f"cut {t:.2f} −", f"cut {t:.2f} +"]
        sheets.append(str(frames_at(render_path, times, out_dir / f"cuts_{k // 6 + 1:02d}.png", width=240, labels=labels)))
    ov_times = [o.start + o.duration * 0.55 for o in edit.overlays][:12]
    if ov_times:
        sheets.append(str(frames_at(render_path, ov_times, out_dir / "graphics.png", width=300,
                                    labels=[o.id for o in edit.overlays][:12])))
    # Sound effects: does each one sound where it was placed? (earshot's detector, or a simple onset search)
    sfx = None
    if any(a.sfx for a in edit.audio):
        from . import sound
        try:
            sfx = sound.check(edit, render_path, out_dir)
            for it in sfx.get("items", []):
                if it.get("status") in ("no sound", "off"):
                    issue("sfx_sync", f"{it.get('id')} ({it.get('kind')}): no audible sound at its cue "
                          "(buried under voice/music, or placed wrong)", it.get("t"))
                elif it.get("offset_ms") is not None and abs(it["offset_ms"]) > 60:
                    issue("sfx_sync", f"{it.get('id')}: sounds {it['offset_ms']:+.0f} ms from its cue", it.get("t"), "info")
        except Exception as exc:          # listening is a check, never a blocker
            sfx = {"error": str(exc)}
    ears = None
    if listen:
        from . import sound
        if sound.ears_installed():
            cue_items = [{"t": round(a.sfx.cue_time(a.start), 3), "kind": a.sfx.role, "id": a.id}
                         for a in edit.audio if a.sfx]
            try:
                ears = sound.ears(render_path, out_dir, cue_items)
                if ears.get("sheet"):
                    sheets.append(ears["sheet"])
            except Exception as exc:
                ears = {"error": str(exc)}
    delivery = None
    platform = platform or edit.output.platform
    if platform:                          # the destination's own limits (format rows are fixable, judgement rows are the owner's)
        from .delivery import check as dcheck, safe_frame
        try:
            delivery = dcheck(render_path, platform, content=False)
            for r in delivery["rows"]:
                if r["status"] != "PASS":
                    issue(f"delivery_{r['check'].replace(' ', '_')}", f"{delivery['platform']}: {r['check']} {r['value']} "
                          f"(expected {r['expect']}){' - ' + r['fix'] if r['fix'] else ''}",
                          severity="error" if r["status"] == "FAIL" and r["kind"] == "format" else "warn")
            mid = (edit.captions.chunks[len(edit.captions.chunks) // 2].start + 0.2) if edit.captions.chunks else info.duration / 2
            sheets.append(str(safe_frame(render_path, platform, out_dir / f"safe_{delivery['platform']}.png", at=mid)))
        except Exception as exc:
            delivery = {"error": str(exc)}
    # Measured checks (text on screen, still stretches, VO pace, cuts on the beat, the payoff)
    try:
        measured = measured_checks(edit, render_path, out_dir)
        for i in measured.pop("issues"):
            issue(i["kind"], i["msg"], i.get("at"), i.get("severity", "warn"))
    except Exception as exc:              # a measurement is a check, never a blocker
        measured = {"error": str(exc)}
    report = {"render": str(render_path), "duration": round(info.duration, 2), "loudness": loud, "issues": issues,
              "sfx": sfx, "ears": ears, "delivery": delivery, "measured": measured,
              "errors": sum(1 for i in issues if i["severity"] == "error"), "sheets": sheets, "pops": pops,
              "silences": silences, "black": blacks}
    write_json(out_dir / "report.json", report)
    return report


def _overlay_probe(edit: Edit, ov, mg_dir: Path) -> dict | None:
    """The text an MG overlay shows over its duration (renderer --probe-text), cached beside its render."""
    from . import mg
    from .util import read_json
    spec = ov.mg
    if not spec or mg.pick_engine(spec) != "html" or not mg.renderer_ready():
        return None
    comp = Path(spec.file) if spec.file else mg.template_path(spec.template)
    if spec.file and not comp.is_absolute():
        comp = mg_dir.parent / comp
    if not comp.exists():
        return None
    stem, _, W, H, fps = mg.overlay_target(edit, ov, mg_dir)
    cache = Path(f"{stem}.text.json")
    if cache.exists():
        return read_json(cache)
    data = Path(f"{stem}.probe-data.json")
    write_json(data, {**spec.data, "duration": ov.duration})
    every = max(1, round(fps / 4))                       # four looks a second
    proc = run([mg._node(), str(mg.mg_dir() / "renderer" / "render.mjs"), "--input", str(comp), "--probe-text", str(cache),
                "--probe-every", str(every), "--width", str(W), "--height", str(H), "--fps", str(fps),
                "--duration", f"{ov.duration:.3f}", "--data", str(data)], check=False, timeout=1800)
    return read_json(cache) if proc.returncode == 0 and cache.exists() else None


def measured_checks(edit: Edit, render_path: Path, out_dir: Path) -> dict:
    """Numbers instead of 'looks good' (adapted from animate's review, MIT): text, stills, pace, beat grid, payoff."""
    from . import checks
    from .beatsync import measure as beat_measure
    issues: list[dict] = []
    rep: dict = {}
    W, H = edit.canvas.width, edit.canvas.height
    safe = checks.safe_zone(W, H)
    mg_dir = Path(out_dir).parent / "mg"                   # out_dir is the project's qa/ (the render may be anywhere)

    # text: every live-HTML overlay drawn at the frame's own size, and caption words that can't wrap
    texts = []
    for ov in edit.overlays:
        tr = ov.transform
        if not ov.mg or (ov.mg.width and ov.mg.width != W) or (ov.mg.height and ov.mg.height != H) or \
                (tr.scale, tr.x, tr.y, tr.rotation) != (1.0, 0.0, 0.0, 0.0):
            continue                                       # moved or resized on the canvas: not measured here
        pr = _overlay_probe(edit, ov, mg_dir)
        if not pr:
            continue
        tl = pr.get("timeline") or {}
        skip = [(m - 0.6, m + 0.6) for m in tl.get("morphs", [])]          # a morph shows the world through a window
        skip += [(float(a), float(b)) for a, b, *_ in ((tl.get("review") or {}).get("textIgnore") or [])]
        found = checks.text_issues(pr, offset=ov.start, safe=safe, skip=skip, label=ov.id)
        texts += found
    if edit.captions.enabled and edit.captions.chunks:
        texts += checks.caption_word_overflow(edit, edit.captions.chunks)
    for t in texts:
        issues.append({"kind": t["kind"], "msg": t["msg"], "at": t["at"]})
    rep["text"] = {"issues": len(texts)}

    # still stretches: no visual event (cut, b-roll, graphic, text, effect, moving zoom/reframe) and no motion
    shorts = edit.duration <= 75 or H > W
    limit = float(edit.knobs.get("qa_static_max") or (4.0 if shorts else 8.0))
    events = [0.0, edit.duration]
    moving: list[tuple[float, float]] = []
    for c in edit.main:
        if c.start is None:
            continue
        events.append(c.start)
        if c.zoom or len(c.crop) > 1:
            moving.append((c.start, c.start + c.duration))
    for c in edit.broll:
        if c.start is not None:
            events += [c.start, c.start + (c.src_out - c.src_in) / (c.speed or 1.0)]
    events += [o.start for o in edit.overlays if o.enabled] + [t.start for t in edit.texts if t.enabled]
    events += [e.start for e in edit.effects if e.enabled]
    events = sorted(set(round(e, 2) for e in events if 0 <= e <= edit.duration))
    gaps = [(a, b) for a, b in zip(events, events[1:]) if b - a >= limit
            and not any(m0 <= a + 0.1 and b - 0.1 <= m1 for m0, m1 in moving)]
    still = []
    if gaps:
        frames = checks.gray_frames(render_path, fps=8.0)
        curve, rate = checks.change_curve(frames)
        med = float(np.median(curve[1:])) if len(curve) > 1 else 0.0
        for a, b in gaps:
            seg = curve[int(a * rate) + 1:int(b * rate)]
            if len(seg) and float(np.mean(seg)) < max(0.8, 0.25 * med):
                still.append((a, b))
                issues.append({"kind": "static", "at": a, "msg": f"{b - a:.1f}s with nothing new on screen "
                               f"({a:.1f}-{b:.1f}s): add a cut, a punch-in, b-roll or a graphic (limit {limit:.0f}s)"})
    rep["static"] = {"limit": limit, "stretches": still}

    # voice-over pace (generated voices: the script can be rewritten)
    pace = []
    for a in edit.audio:
        src = edit.sources.get(a.source)
        if a.role != "vo" or not src or not src.transcript or not Path(src.transcript).exists():
            continue
        tr = json.loads(Path(src.transcript).read_text(encoding="utf-8"))
        if not str(tr.get("engine", "")).startswith("voice:"):
            continue
        lines = tr.get("lines") or [{"t0": s["s"], "t1": s["e"], "text": s["text"]} for s in tr.get("segments", [])]
        for r in checks.line_pace(lines, tr.get("language", "en")):
            if not r["ok"]:
                at = a.start + r["t0"] - a.src_in
                pace.append(r)
                issues.append({"kind": "pace", "at": round(at, 2), "msg": f"VO line at {r['wps']} words/s (limit "
                               f"{r['limit']}): \"{r['text'][:50]}\" - shorten it or give it more time"})
    rep["pace"] = pace

    # cuts on the beat (music clips marked `sync`)
    grids = []
    for a in edit.audio:
        if a.role == "music" and a.sync and a.enabled and a.source in edit.sources:
            m = beat_measure(edit, a)
            grids.append(m)
            if m["off"]:
                worst = max(m["off"], key=lambda r: abs(r["off_ms"]))
                issues.append({"kind": "beat_grid", "at": worst["at"],
                               "msg": f"{len(m['off'])} of {m['cuts']} cuts are off the {m['grid']} grid of '{a.id}' "
                                      f"(worst {worst['off_ms']:+.0f} ms at {worst['at']:.2f}s): `vedit beats snap`"})
    rep["beat_grid"] = grids

    # the payoff: silence before it, the loudest hit on it (when the edit marks one)
    pm = next((m for m in edit.markers if m.name.lower().startswith("payoff") or "payoff" in m.note.lower()), None)
    if pm:
        po = checks.payoff(render_path, window=(pm.t, pm.t + max(0.5, pm.duration)))
        rep["payoff"] = po
        if po and not po.get("silence_ok"):
            issues.append({"kind": "sound_arc", "at": po["loudest_t"], "msg": f"no silence before the payoff: "
                           f"{po['silence_before_s']}s at <= -40 dBFS in the 2 s before the loudest moment (needs 0.4 s)"})
        if po and po.get("in_window") is False:
            issues.append({"kind": "sound_arc", "at": po["loudest_t"], "msg": f"the loudest moment is at "
                           f"{po['loudest_t']}s, not on the payoff marker ({pm.t:.2f}s)"})
    rep["issues"] = issues
    return rep
