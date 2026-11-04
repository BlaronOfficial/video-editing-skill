"""`vedit anim review`: "done" is measured. Adapted from animate's tools/review.mjs (MIT, (c) 2026 cth9191).

    sheets      a contact sheet per shot (every 0.25 s) and review/phone.jpg (one frame a second at 360 px: read
                every caption at the size people watch)
    cut grid    every TIMELINE cut on its beat grid (8ths, or 16ths inside [fastFrom, fastTo)), confirmed by the
                picture actually changing there; morph centres on the 8th grid
    dead beats  stretches over review.deadMax (3 s) where the picture barely changes (silence acts exempt)
    narration   words per second of each line (<= 3.5 English)
    story arc   per act: cut rate, motion, loudness (mix and music stem) against the roles journey / peak / silence /
                gift / goodbye (silence before the payoff, the loudest on it; the busiest moment is not the loudest)
    anchor      how often the hero sits on its screen spot (TIMELINE.anchor + window.anchorAt)
    text        strings cut off, overlapping, or under the phone UI (morph windows and review.textIgnore skipped)
    sound       the loudest 100 ms and the silence before it; integrated loudness and true peak of the share mix
You can't hear the score: the numbers stand in, and the owner listens.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .. import checks
from ..media import ffmpeg, measure_loudness
from ..util import read_json, write_json
from . import FPS
from .pieces import _page, _renderer, main_format, meta, piece_dir, render


def _grid_ok(t: float, step: float, g0: float, fps: float) -> tuple[bool, float]:
    k = round((t - g0) / step)
    off = t - (g0 + k * step)
    return abs(off) <= 0.5 / fps + 1e-6, off


def review(proj, name: str, *, fmt: str | None = None) -> dict:
    pd = piece_dir(proj, name)
    m = meta(pd)
    fmt = fmt or main_format(pd)
    r = render(proj, name, fmt=fmt)
    video = Path(r["video"])
    rv = pd / ("review" if fmt == main_format(pd) else f"review-{r['width']}x{r['height']}")
    rv.mkdir(parents=True, exist_ok=True)
    args, _ = _page(pd, fmt)
    every = max(1, FPS // 4)
    pr = _renderer([*args, "--probe-text", str(rv / "text_probe.json"), "--probe-every", str(every)], timeout=3600)
    probe_data = read_json(rv / "text_probe.json")
    T = pr.get("timeline") or {}
    fps = float(T.get("fps") or FPS)
    rep: dict = {"piece": name, "format": fmt, "video": str(video), "share": r.get("share"), "sections": {}}
    S = rep["sections"]

    # pixels: frames at the piece's own rate
    frames = checks.gray_frames(video, width=96)
    curve, rate = checks.change_curve(frames)
    n = len(curve)

    # cut grid
    bpm = float(T.get("bpm") or 120)
    e8, e16, g0 = 30.0 / bpm, 15.0 / bpm, float(T.get("gridOffset") or 0)
    fast = (float(T.get("fastFrom", -1)), float(T.get("fastTo", -1)))
    rows = []
    for c in T.get("cuts", []):
        step = e16 if fast[0] <= c < fast[1] else e8
        ok, off = _grid_ok(c, step, g0, fps)
        fc = int(round(c * rate))
        win = curve[max(1, fc - 2):min(n, fc + 3)]
        peak = (max(1, fc - 2) + int(np.argmax(win))) if len(win) else fc
        rows.append({"cut": c, "grid": "16th" if step == e16 else "8th", "off_frames": round(off * fps, 2),
                     "on_grid": ok, "change_at_cut": abs(peak - fc) <= 1})
    morphs = [{"morph": t, "on_grid": _grid_ok(t, e8, g0, fps)[0]} for t in T.get("morphs", [])]
    S["cuts"] = {"rows": rows, "morphs": morphs,
                 "pass": all(x["on_grid"] and x["change_at_cut"] for x in rows) and all(x["on_grid"] for x in morphs)}

    # dead beats
    acts = T.get("acts") or []
    held = [(float(a["t0"]), float(a["t1"])) for a in acts if a.get("role") == "silence"]
    dead_max = float(((m.get("review") or {}).get("deadMax")) or (T.get("review") or {}).get("deadMax") or 3.0)
    st = checks.still_stretches(video, limit=dead_max, exempt=held, frames=checks.gray_frames(video, fps=12.0))
    S["dead_beats"] = {**st, "limit": dead_max, "pass": not st["runs"]}

    # narration pace
    narr = T.get("narration") or []
    lang = "bn" if any(any("ঀ" <= ch <= "৿" for ch in str(x.get("text", ""))) for x in narr) else "en"
    pace = checks.line_pace(narr, lang) if narr else []
    S["narration"] = {"lines": pace, "pass": all(p["ok"] for p in pace)}

    # story arc
    mix = (r.get("audio") or {}).get("mix")
    music = (r.get("audio") or {}).get("music")
    db_mix = checks.db_windows(mix) if mix else np.zeros(0)
    db_mus = checks.db_windows(music) if music else np.zeros(0)

    def lvl(db, a, b, q=50):
        seg = db[int(a * 10):max(int(a * 10) + 1, int(b * 10))]
        return float(np.percentile(seg, q)) if len(seg) else None

    arc_rows = []
    for a in acts:
        t0, t1 = float(a["t0"]), float(a["t1"])
        cuts = sum(1 for c in T.get("cuts", []) if t0 <= c < t1)
        arc_rows.append({"name": a.get("name", ""), "role": a.get("role"), "t0": t0, "t1": t1, "cuts": cuts,
                         "cps": round(cuts / max(1e-6, t1 - t0), 2),
                         "motion": round(float(np.mean(curve[int(t0 * rate) + 1:int(t1 * rate)] if n else 0) or 0), 2),
                         "med": lvl(db_mix, t0, t1), "p90": lvl(db_mix, t0, t1, 90), "music": lvl(db_mus, t0, t1)})
    role = {x["role"]: x for x in arc_rows if x["role"]}
    rules = []

    def rule(ok, text):
        rules.append({"ok": bool(ok), "rule": text})

    g, pk, si, jo, gb = (role.get(k) for k in ("gift", "peak", "silence", "journey", "goodbye"))
    if g and g["p90"] is not None:
        others = [x for x in arc_rows if x is not g and x["p90"] is not None]
        rule(all(g["p90"] > x["p90"] for x in others), "the gift (payoff) act is the loudest")
        if pk and pk["p90"] is not None:
            rule(g["p90"] >= pk["p90"] + 1, "gift p90 >= peak p90 + 1 dB: the busiest moment is not the loudest")
        rule(g["cps"] <= 0.5, "the gift is held (<= 0.5 cuts/s)")
    if si and pk and si["med"] is not None and pk["med"] is not None:
        rule(si["med"] <= pk["med"] - 15, "silence median <= peak median - 15 dB")
    if jo and g and jo["music"] is not None and g["music"] is not None and narr:
        rule(jo["music"] >= g["music"] - 8, "the journey's music stays present under the voice")
    if pk and T.get("cuts") and not T.get("morphs"):
        rule(all(x is pk or pk["cps"] > x["cps"] for x in arc_rows), "the peak has the highest cut rate")
    if gb and g and gb["med"] is not None and g["med"] is not None:
        rule(gb["med"] <= g["med"] - 6, "goodbye decays: median <= gift median - 6 dB")
    S["story_arc"] = {"acts": arc_rows, "rules": rules, "pass": all(x["ok"] for x in rules)}

    # anchor
    A = T.get("anchor")
    if A:
        tol = float(A.get("tolerance", 40))
        pts = [s for s in probe_data.get("samples", []) if float(A["t0"]) <= s["t"] < float(A["t1"])]
        offs = [np.hypot(s["anchor"]["x"] - A["x"], s["anchor"]["y"] - A["y"]) if s.get("anchor") else None for s in pts]
        present = [o for o in offs if o is not None]
        share = sum(1 for o in present if o <= tol) / max(1, len(offs))
        S["anchor"] = {"samples": len(offs), "share": round(share, 2), "max_offset": round(max(present), 1) if present else None,
                       "pass": share >= float(A.get("minShare", 0.95))}

    # text
    bd = 0.6
    skip = [(t - bd, t + bd) for t in T.get("morphs", [])]
    skip += [(float(a), float(b)) for a, b, *_ in ((m.get("review") or {}).get("textIgnore") or [])]
    safe = T.get("safe") if isinstance(T.get("safe"), dict) else None
    if safe:
        safe = {"top": safe.get("top", 0), "bottom": safe.get("bottom", 0), "right": safe.get("right", 0), "left": 0}
    txt = checks.text_issues(probe_data, safe=safe, skip=skip)
    S["text"] = {"issues": txt, "pass": not txt}

    # sound
    snd = {}
    if mix:
        gift = role.get("gift")
        snd = checks.payoff(mix, window=(gift["t0"], gift["t1"]) if gift else None)
        if r.get("share"):
            snd["loudness"] = measure_loudness(r["share"])
    S["sound"] = {**snd, "pass": (not snd) or (snd.get("silence_ok", True) if role.get("gift") else True)
                  and snd.get("in_window", True) is not False}

    # sheets: per shot, and the phone sheet
    from ..view import frames_at
    sheets = []
    for i, sh in enumerate(T.get("shots") or []):
        t0, t1 = float(sh["t0"]), float(sh["t1"])
        times = list(np.arange(t0, max(t0 + 0.01, t1 - 0.02), 0.25))[:16] or [t0]
        out = rv / f"shot{i + 1:02d}.png"
        frames_at(video, [float(t) for t in times], out, width=180, labels=[f"{t:.2f}" for t in times])
        sheets.append(str(out))
    phone = rv / "phone.jpg"
    cols = 6
    rows_n = max(1, int(np.ceil((r.get("duration") or 1) / cols)))
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(video), "-vf", f"fps=1,scale=360:-2,tile={cols}x{rows_n}",
                    "-frames:v", "1", "-q:v", "3", str(phone)], capture_output=True, timeout=600)
    rep["sheets"] = sheets
    rep["phone"] = str(phone) if phone.exists() else None
    rep["pass"] = all(v.get("pass", True) for v in S.values())
    rep["summary"] = {k: ("PASS" if v.get("pass", True) else "WARN") for k, v in S.items()}
    rep["next"] = ("look at the sheets and phone.jpg, write a per-shot PASS table in LOG.md, name the weakest shot; "
                   "the owner listens to renders/" + Path(r.get("share") or "").name)
    write_json(rv / "report.json", rep)
    return rep
