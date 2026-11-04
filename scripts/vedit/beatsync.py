"""A music clip's beat grid on the timeline: snap cuts onto it (`vedit beats snap`) and measure how well the cuts
sit on it (QA `beat_grid`, for music clips marked `sync: "beats" | "bars" | "8ths"`).

Snapping ripples like an editor's trim: a moved main-track cut lengthens or shortens the clip before it and
everything after it moves with the picture (overlays, texts, effects, b-roll, sound effects, VO, markers, captions), while
music stays put, because the music is the grid. A cut never moves into a word: extending must not reveal a word
that was cut out, and trimming must not cut a kept word.
"""

from __future__ import annotations

from .timeline import AudioClip, Edit

GRIDS = ("beats", "bars", "8ths")


def _grid_name(g: str) -> str:
    g = (g or "beats").lower()
    return {"beat": "beats", "bar": "bars", "8th": "8ths", "eighths": "8ths"}.get(g, g)


def music_span(edit: Edit, a: AudioClip) -> tuple[float, float]:
    src = edit.sources[a.source]
    used = (a.src_out if a.src_out is not None else src.duration) - a.src_in
    end = edit.duration if a.loop else a.start + max(0.0, used)
    return a.start, min(end, edit.duration) if edit.duration else end


def clip_grid(edit: Edit, a: AudioClip, grid: str = "beats", *, beat_map: dict | None = None) -> list[float]:
    """Grid times (timeline seconds) of music clip `a`: its beats, bar starts or 8ths inside the clip's span."""
    from .audio import beats
    src = edit.sources[a.source]
    if beat_map is None:
        used = (a.src_out - a.src_in) if a.src_out is not None else None
        beat_map = beats(src.path, start=a.src_in, dur=used)
    g = _grid_name(grid)
    b = beat_map.get("beats") or []
    if g == "bars":
        times = beat_map.get("downbeats") or []
    elif g == "8ths":
        per = beat_map.get("period") or 0
        times = sorted(b + [t + per / 2 for t in b]) if per else b
    else:
        times = b
    t0, t1 = music_span(edit, a)
    out = []
    length = beat_map.get("duration") or 0
    reps = int((t1 - t0) / length) + 1 if a.loop and length > 0 else 1
    for r in range(reps):
        for t in times:
            tl = a.start + r * length + t
            if t0 - 1e-6 <= tl <= t1 + 1e-6:
                out.append(round(tl, 4))
    return out


def cut_times(edit: Edit) -> list[tuple[str, float]]:
    """Every visible cut: main-track boundaries and b-roll starts/ends, as (label, timeline seconds)."""
    e = edit.layout()
    cuts = [(f"cut {c.id}", c.start) for c in e.main[1:] if c.start is not None]
    for c in e.broll:
        if c.start is None:
            continue
        cuts.append((f"broll {c.id} in", c.start))
        cuts.append((f"broll {c.id} out", c.start + (c.src_out - c.src_in) / (c.speed or 1.0)))
    return sorted(cuts, key=lambda x: x[1])


def measure(edit: Edit, a: AudioClip, grid: str | None = None, *, beat_map: dict | None = None) -> dict:
    """How well the cuts inside music clip `a` sit on its grid (QA)."""
    g = _grid_name(grid or a.sync or "beats")
    pts = clip_grid(edit, a, g, beat_map=beat_map)
    t0, t1 = music_span(edit, a)
    fps = edit.canvas.fps or 30.0
    tol = max(0.5 / fps, 0.025)
    rows = []
    for label, t in cut_times(edit):
        if not (t0 + 0.05 <= t <= t1 - 0.05) or not pts:
            continue
        g_near = min(pts, key=lambda p: abs(p - t))
        rows.append({"cut": label, "at": round(t, 3), "grid": g_near, "off_ms": round((t - g_near) * 1000, 1),
                     "on": abs(t - g_near) <= tol})
    on = sum(r["on"] for r in rows)
    return {"music": a.id, "grid": g, "cuts": len(rows), "on_grid": on,
            "share": round(on / len(rows), 2) if rows else None, "tolerance_ms": round(tol * 1000, 1),
            "off": [r for r in rows if not r["on"]]}


# ------------------------------------------------------------------ snapping

def _source_words(edit: Edit, sid: str) -> list[dict]:
    from .captions import transcript_words
    src = edit.sources.get(sid)
    if not src or not src.transcript:
        return []
    try:
        return transcript_words(src.transcript)
    except Exception:
        return []


def _safe_out(words: list[dict], old_out: float, new_out: float, src_in: float) -> tuple[bool, str]:
    """Can a clip's out point move from old_out to new_out (source seconds) without touching words?"""
    if new_out <= src_in + 0.2:
        return False, "the clip would get too short"
    lo, hi = sorted((old_out, new_out))
    for w in words:
        s, e = float(w["s"]), float(w["e"])
        if s < hi and e > lo:
            what = "reveals a cut word" if new_out > old_out else "cuts a kept word"
            return False, f"{what} ('{w.get('w', '').strip()}' at {s:.2f}s)"
    return True, ""


def _ripple(e: Edit, t: float, d: float, *, keep_music: bool = True) -> None:
    """Move everything that starts at or after timeline time t by d (music stays: it is the grid)."""
    for ov in e.overlays:
        if ov.start >= t - 1e-6 and not ov.anchor:
            ov.start = round(max(0.0, ov.start + d), 4)
    for tx in e.texts:
        if tx.start >= t - 1e-6 and not tx.anchor:
            tx.start = round(max(0.0, tx.start + d), 4)
    for fx in e.effects:
        if fx.start >= t - 1e-6 and not fx.anchor:
            fx.start = round(max(0.0, fx.start + d), 4)
    for c in e.broll:
        if c.start is not None and c.start >= t - 1e-6:
            c.start = round(max(0.0, c.start + d), 4)
    for a in e.audio:
        if keep_music and a.role == "music":
            continue
        if a.start >= t - 1e-6 and not a.anchor:
            a.start = round(max(0.0, a.start + d), 4)
    for m in e.markers:
        if m.t >= t - 1e-6 and not m.anchor:
            m.t = round(max(0.0, m.t + d), 4)
    for fx in e.custom_fx:
        if fx.start >= t - 1e-6 and not fx.anchor:
            fx.start = round(max(0.0, fx.start + d), 4)
    for ch in e.captions.chunks:      # word-built chunks are rebuilt at render; hand-written ones (translations, v1)
        if ch.start >= t - 1e-6:      # keep their times, so they move with the picture
            ch.start, ch.end = round(max(0.0, ch.start + d), 4), round(max(0.0, ch.end + d), 4)
            for w in ch.words:
                w.s, w.e = round(max(0.0, w.s + d), 4), round(max(0.0, w.e + d), 4)


def snap(edit: Edit, music_id: str, *, grid: str = "beats", tolerance: float = 0.12) -> tuple[Edit, list[dict]]:
    """Move cuts inside music clip `music_id` onto its grid. Returns (new edit, a row per cut considered)."""
    e = edit.model_copy(deep=True).layout()
    a = next((x for x in e.audio if x.id == music_id), None)
    if a is None:
        raise ValueError(f"no audio clip '{music_id}'")
    g = _grid_name(grid)
    beat_map = None
    from .audio import beats
    src = e.sources[a.source]
    used = (a.src_out - a.src_in) if a.src_out is not None else None
    beat_map = beats(src.path, start=a.src_in, dur=used)
    pts = clip_grid(e, a, g, beat_map=beat_map)
    fps = e.canvas.fps or 30.0
    half = 0.5 / fps
    rows: list[dict] = []
    if not pts:
        return e, [{"cut": "-", "action": "skip", "reason": "no beats found in the music"}]
    t0, t1 = music_span(e, a)

    # main-track cuts, left to right; each move ripples the rest
    for i in range(1, len(e.main)):
        e = e.layout()
        cut = e.main[i].start
        if cut is None or not (t0 + 0.05 <= cut <= t1 - 0.05):
            continue
        prev = e.main[i - 1]
        near = sorted(pts, key=lambda p: abs(p - cut))[:2]
        row = {"cut": f"cut {e.main[i].id}", "at": round(cut, 3)}
        if abs(near[0] - cut) <= half:
            rows.append({**row, "action": "on beat", "to": near[0], "delta": 0.0})
            continue
        words = _source_words(e, prev.source) if not prev.mute else []
        done = False
        reasons = []
        for target in near:
            d = target - cut
            if abs(d) > tolerance:
                reasons.append(f"nearest beat {d * 1000:+.0f} ms away")
                continue
            new_out = prev.src_out + d * (prev.speed or 1.0)
            src_dur = e.sources[prev.source].duration or float("inf")
            if new_out > src_dur:
                reasons.append("the source ends first")
                continue
            ok, why = _safe_out(words, prev.src_out, new_out, prev.src_in)
            if not ok:
                reasons.append(why)
                continue
            prev.src_out = round(new_out, 4)
            _ripple(e, cut + 1e-6, d)
            rows.append({**row, "action": "moved", "to": round(target, 3), "delta": round(d, 3)})
            done = True
            break
        if not done:
            rows.append({**row, "action": "skip", "reason": "; ".join(reasons) or "no safe beat"})

    # b-roll: snap the start (shift) and the end (trim the out point); b-roll is usually muted
    e = e.layout()
    for c in e.broll:
        if c.start is None or not (t0 + 0.05 <= c.start <= t1 - 0.05):
            continue
        g_in = min(pts, key=lambda p: abs(p - c.start))
        if half < abs(g_in - c.start) <= tolerance:
            rows.append({"cut": f"broll {c.id} in", "at": round(c.start, 3), "action": "moved", "to": g_in,
                         "delta": round(g_in - c.start, 3)})
            c.start = round(g_in, 4)
        end = c.start + (c.src_out - c.src_in) / (c.speed or 1.0)
        g_out = min(pts, key=lambda p: abs(p - end))
        if half < abs(g_out - end) <= tolerance and g_out > c.start + 0.3:
            new_out = c.src_in + (g_out - c.start) * (c.speed or 1.0)
            words = _source_words(e, c.source) if not c.mute else []
            ok, why = _safe_out(words, c.src_out, new_out, c.src_in)
            src_dur = e.sources[c.source].duration or float("inf")
            if ok and new_out <= src_dur:
                rows.append({"cut": f"broll {c.id} out", "at": round(end, 3), "action": "moved", "to": g_out,
                             "delta": round(g_out - end, 3)})
                c.src_out = round(new_out, 4)
            else:
                rows.append({"cut": f"broll {c.id} out", "at": round(end, 3), "action": "skip",
                             "reason": why or "the source ends first"})
    return e.layout(), rows
