"""Self-check a render before showing it: duration, black/frozen frames, loudness, pops at cuts,
long silences, caption safe zones, plus frame sheets around every cut for Claude to look at.
"""

from __future__ import annotations

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
    report = {"render": str(render_path), "duration": round(info.duration, 2), "loudness": loud, "issues": issues,
              "sfx": sfx, "ears": ears, "delivery": delivery,
              "errors": sum(1 for i in issues if i["severity"] == "error"), "sheets": sheets, "pops": pops,
              "silences": silences, "black": blacks}
    write_json(out_dir / "report.json", report)
    return report
