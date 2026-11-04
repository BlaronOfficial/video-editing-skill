"""Measured checks shared by QA (`qa.check`) and the animation review (`vedit anim review`).

Adapted from animate's tools/review.mjs and tools/textcheck.mjs (MIT, (c) 2026 cth9191): numbers instead of
"looks good". A model reading contact sheets misses a label cut off at the frame edge; these don't.

    text      strings cut off by the frame, overlapping other text, or under the platform UI (from the renderer's
              --probe-text pass: canvas fillText/strokeText and DOM text, in screen pixels)
    stills    stretches where the picture barely changes (the change over 0.5 s, against the piece's own median)
    pace      voice-over lines faster than people can follow
    sound     the loudest 100 ms, the silence before it (the payoff), integrated loudness
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

from .media import ffmpeg, probe

PACE_WPS = {"en": 3.5, "bn": 3.0}      # words per second a listener can follow (Bangla words are longer)


def safe_zone(width: int, height: int) -> dict:
    """What the platform UI covers, in pixels (vertical video: Shorts / Reels / TikTok chrome)."""
    if height > width * 1.2:
        k = height / 1920
        return {"top": round(240 * k), "bottom": round(420 * k), "right": round(140 * width / 1080), "left": 0}
    k = min(width, height) / 1080
    return {"top": round(60 * k), "bottom": round(110 * k), "right": round(60 * k), "left": 0}


# ------------------------------------------------------------------ text

def _area(b: tuple[float, float, float, float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inter(a, b) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def text_issues(probe_data: dict, *, offset: float = 0.0, safe: dict | None = None,
                skip: list[tuple[float, float]] = (), min_dur: float = 0.4, label: str = "") -> list[dict]:
    """Text problems that last at least `min_dur` (entrances and exits through the frame edge are not issues)."""
    W, H = probe_data["width"], probe_data["height"]
    safe = safe or safe_zone(W, H)
    vertical = H > W * 1.2
    found: dict[tuple[str, str], list[float]] = {}
    for smp in probe_data.get("samples", []):
        t = float(smp["t"])
        if any(a <= t <= b for a, b in skip):
            continue
        items = [it for it in smp.get("items", []) if it.get("s", "").strip()]
        boxes = [(it["x0"], it["y0"], it["x1"], it["y1"]) for it in items]
        for it, b in zip(items, boxes):
            s = it["s"].strip()[:60]
            if b[2] <= 0 or b[0] >= W or b[3] <= 0 or b[1] >= H:
                continue                                       # entirely off screen: not visible, not an issue
            if b[0] < -2 or b[1] < -2 or b[2] > W + 2 or b[3] > H + 2:
                found.setdefault(("text_cut", s), []).append(t)
            elif vertical and (b[1] < safe["top"] or b[3] > H - safe["bottom"] or b[2] > W - safe["right"]):
                found.setdefault(("text_ui", s), []).append(t)
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                si, sj = items[i]["s"].strip(), items[j]["s"].strip()
                if si == sj or si in sj or sj in si:
                    continue                                   # a shadow, a stroke pass, a highlight of the same words
                small = min(_area(boxes[i]), _area(boxes[j])) or 1.0
                if _inter(boxes[i], boxes[j]) > 0.25 * small:
                    found.setdefault(("text_overlap", f"{si[:30]} / {sj[:30]}"), []).append(t)
    ts_all = sorted(float(s["t"]) for s in probe_data.get("samples", []))
    step = float(np.median(np.diff(ts_all))) if len(ts_all) > 1 else 0.25     # the probe's sampling interval
    out = []
    for (kind, s), ts in found.items():
        ts.sort()
        runs, a, prev = [], ts[0], ts[0]
        for t in ts[1:] + [None]:
            if t is None or t - prev > step * 1.6:
                runs.append((a, prev))
                if t is not None:
                    a = t
            if t is not None:
                prev = t
        for a, b in runs:
            if b - a + step < min_dur:
                continue
            what = {"text_cut": "is cut off by the frame", "text_ui": "sits under the platform UI",
                    "text_overlap": "overlap"}[kind]
            out.append({"kind": kind, "at": round(offset + a, 2), "until": round(offset + b + step, 2),
                        "text": s, "msg": f"{label + ': ' if label else ''}\"{s}\" {what} "
                                          f"({offset + a:.2f}-{offset + b + step:.2f}s)"})
    return sorted(out, key=lambda r: r["at"])


def _ass_em(path: Path) -> float:
    """libass sizes a font by its Windows cell height (OS/2 usWinAscent + usWinDescent), not by its em, so a
    Fontsize of N draws glyphs at N * unitsPerEm / (winAscent + winDescent) px (0.71 for Poppins)."""
    import struct
    try:
        b = Path(path).read_bytes()
        n = struct.unpack(">H", b[4:6])[0]
        tabs = {b[12 + 16 * i:16 + 16 * i]: struct.unpack(">I", b[20 + 16 * i:24 + 16 * i])[0] for i in range(n)}
        upem = struct.unpack(">H", b[tabs[b"head"] + 18:tabs[b"head"] + 20])[0]
        win = sum(struct.unpack(">HH", b[tabs[b"OS/2"] + 74:tabs[b"OS/2"] + 78]))
        return upem / win if upem and win else 1.0
    except Exception:
        return 1.0


def caption_word_overflow(edit, chunks) -> list[dict]:
    """A caption word wider than the frame can't wrap (libass wraps between words, not inside one)."""
    from PIL import ImageFont
    from .captions import _display, is_bangla, resolve_style
    from .paths import fonts_dir
    style = resolve_style(edit.captions.style, edit.captions.overrides)
    if edit.captions.uppercase is not None:
        style = {**style, "uppercase": edit.captions.uppercase}
    W, H = edit.canvas.width, edit.canvas.height
    px = max(12, round(style["size"] * min(W, H)))                 # the ASS Fontsize captions.to_ass writes
    limit = W - 80                                                 # MarginL + MarginR = 40 + 40
    outline = style["stroke_width"] * px if style.get("stroke") else 0.0
    spacing = float(style.get("letter_spacing", 0) or 0)

    files = sorted(fonts_dir().glob("*.ttf"))                      # bundled as Family-Style.ttf

    def font_for(name: str):
        key = name.replace(" ", "").replace("-", "").lower()
        fam = {f: f.stem.split("-")[0].lower() for f in files}
        sty = {f: (f.stem.split("-")[1] if "-" in f.stem else "regular").lower() for f in files}
        pick = (next((f for f in files if fam[f] + sty[f] == key), None)             # "Poppins ExtraBold"
                or next((f for f in files if fam[f] == key and sty[f] == "regular"), None)   # "Anton"
                or next((f for f in files if fam[f] == key), None))                   # "Atma" (Bold only)
        return ImageFont.truetype(str(pick), max(6, round(px * _ass_em(pick)))) if pick else None

    fonts = {False: font_for(style["font"]), True: font_for(style.get("font_bangla", style["font"]))}
    out = []
    for c in chunks:
        bn = is_bangla(c.text)
        font = fonts[bn]
        if font is None:
            continue
        for w in _display(c.text, style).split():
            width = font.getlength(w) + spacing * max(0, len(w) - 1) + 2 * outline
            if width > limit:
                out.append({"kind": "text_cut", "at": round(c.start, 2), "text": w,
                            "msg": f"caption word \"{w}\" is {width:.0f}px wide on a {W}px frame: it can't wrap; "
                                   "shorten it or lower the caption size"})
    return out


# ------------------------------------------------------------------ pictures

def gray_frames(video: str | Path, *, width: int = 96, fps: float | None = None) -> tuple[np.ndarray, float]:
    """Small grayscale frames for pixel-change measurements: (frames [n, h, w] uint8, frames per second)."""
    info = probe(video)
    W, H = info.display_size
    h = max(2, round(width * H / max(1, W) / 2) * 2)
    rate = fps or info.fps or 30.0
    vf = f"fps={rate},scale={width}:{h},format=gray" if fps else f"scale={width}:{h},format=gray"
    p = subprocess.run([ffmpeg(), "-v", "error", "-i", str(video), "-vf", vf, "-f", "rawvideo", "-"],
                       capture_output=True, timeout=3600)
    raw = np.frombuffer(p.stdout, np.uint8)
    n = len(raw) // (width * h)
    return raw[: n * width * h].reshape(n, h, width), float(rate)


def still_stretches(video: str | Path, *, limit: float = 3.0, exempt: list[tuple[float, float]] = (),
                    frames: tuple[np.ndarray, float] | None = None) -> dict:
    """Stretches of at least `limit` seconds where the picture barely changes: the change over 0.5 s, sampled
    four times a second, below max(0.8, a quarter of the piece's median change)."""
    fr, rate = frames or gray_frames(video, fps=12.0)
    lag, step = max(1, round(rate / 2)), max(1, round(rate / 4))
    pts = [(f / rate, float(np.abs(fr[f].astype(np.int16) - fr[f - lag].astype(np.int16)).mean()))
           for f in range(lag, len(fr), step)]
    if not pts:
        return {"runs": [], "median": 0.0, "threshold": 0.0}
    med = float(np.median([d for _, d in pts]))
    thr = max(0.8, 0.25 * med)
    runs, r0 = [], None
    for t, d in pts + [(len(fr) / rate, 1e9)]:
        still = d < thr and not any(a <= t < b for a, b in exempt)
        if still and r0 is None:
            r0 = t
        elif not still and r0 is not None:
            if t - r0 >= limit:
                runs.append((round(r0, 2), round(t, 2)))
            r0 = None
    return {"runs": runs, "median": round(med, 2), "threshold": round(thr, 2)}


def change_curve(frames: tuple[np.ndarray, float]) -> tuple[np.ndarray, float]:
    """Per-frame mean absolute change (consecutive frames)."""
    fr, rate = frames
    if len(fr) < 2:
        return np.zeros(len(fr)), rate
    d = np.empty(len(fr) - 1)
    for i in range(0, len(fr) - 1, 512):          # in chunks: an hour of frames never becomes one int16 copy
        a = fr[i:i + 513].astype(np.int16)
        d[i:i + len(a) - 1] = np.abs(np.diff(a, axis=0)).mean(axis=(1, 2))
    return np.r_[0.0, d], rate


# ------------------------------------------------------------------ sound

def db_windows(path: str | Path, *, win: float = 0.1) -> np.ndarray:
    """RMS level per window (dBFS)."""
    from .audio import load_mono
    y = load_mono(path, 16000).astype(np.float64)
    n = int(16000 * win)
    k = len(y) // n
    if k == 0:
        return np.zeros(0)
    return 10 * np.log10(np.mean(y[: k * n].reshape(k, n) ** 2, axis=1) + 1e-12)


def payoff(path: str | Path, *, window: tuple[float, float] | None = None, floor_db: float = -40.0) -> dict:
    """The loudest 100 ms, and the longest silence (<= floor_db) in the 2 s before it: 'silence before the
    payoff, loudest on the payoff'. `window` = where the payoff should land (seconds)."""
    db = db_windows(path)
    if not len(db):
        return {}
    L = int(np.argmax(db))
    best = run = 0
    for w in range(max(0, L - 20), L):
        run = run + 1 if db[w] <= floor_db else 0
        best = max(best, run)
    out = {"loudest_t": round(L / 10, 1), "loudest_db": round(float(db[L]), 1), "silence_before_s": round(best / 10, 1),
           "silence_ok": best >= 4}
    if window:
        out["in_window"] = window[0] - 0.3 <= L / 10 <= window[1] + 0.3
    return out


# ------------------------------------------------------------------ pace

def line_pace(lines: list[dict], language: str = "en") -> list[dict]:
    """Words per second of each spoken line: [{text, t0, t1}] -> rows with `wps` and `ok`."""
    limit = PACE_WPS.get(language, PACE_WPS["en"])
    rows = []
    for ln in lines:
        words = [w for w in str(ln.get("text", "")).split() if any(ch.isalnum() for ch in w)]
        dur = float(ln["t1"]) - float(ln["t0"])
        wps = len(words) / dur if dur > 0 else 0.0
        rows.append({"t0": round(float(ln["t0"]), 2), "t1": round(float(ln["t1"]), 2), "words": len(words),
                     "wps": round(wps, 2), "ok": wps <= limit, "limit": limit, "text": str(ln.get("text", ""))[:80]})
    return rows


def write(path: str | Path, data: dict) -> Path:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return Path(path)
