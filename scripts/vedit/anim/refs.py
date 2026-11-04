"""References for a look, measured before anything is drawn (anim/grammar/new-style.md), and the style gallery.

    measure   reference stills: the picture inside letterboxing (writes <name>.trim.png beside it), the palette
              (16-level buckets, bucket means = exact colours), 5x5 medians at points, and the accents (bright,
              saturated colours by hue family: neon, inks on black, which are < 1 % of the pixels)
    shotlog   a reference video's editing and sound per second: hard cuts (outside on-2s stepped and A/B flicker
              runs), motion, held frames, loudness median / p90, onsets, brightness (spectral centroid)
    compare   a reference beside a rendered frame at the same height, with a 10 % proportion grid and both
              palettes: a look is matched by proportions, line weight and palette, not pixels
    gallery   every style's sample in one sheet, plus the "your references" tile
Adapted from animate's tools/measure/refs.mjs, measure/shotlog.py, compare.mjs and gallery.mjs (MIT, (c) 2026
cth9191). Reference media is other people's work: it stays on this PC, uncommitted, unnamed in published output.
"""

from __future__ import annotations

import colorsys
import subprocess
from pathlib import Path

import numpy as np

from ..media import ffmpeg, probe
from . import ANIM, styles

FAMILIES = [("red", 0, 15), ("orange", 15, 45), ("yellow", 45, 70), ("green", 70, 160), ("cyan", 160, 200),
            ("blue", 200, 255), ("purple", 255, 290), ("magenta", 290, 340), ("red", 340, 361)]


def _img(path: str | Path):
    from PIL import Image
    return Image.open(path).convert("RGB")


def trim_box(a: np.ndarray, tol: float = 6.0) -> tuple[int, int, int, int]:
    """The picture inside flat borders (letterboxing, screenshot chrome of one colour): x0, y0, x1, y1."""
    H, W = a.shape[:2]
    corner = np.median(np.stack([a[0, 0], a[0, -1], a[-1, 0], a[-1, -1]]), axis=0)
    flat = np.abs(a.astype(np.int16) - corner.astype(np.int16)).max(axis=2) <= tol
    rows, cols = np.where(~flat.all(axis=1))[0], np.where(~flat.all(axis=0))[0]
    if not len(rows) or not len(cols):
        return 0, 0, W, H
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def palette(a: np.ndarray, top: int = 10) -> list[dict]:
    px = a.reshape(-1, 3).astype(np.int64)
    key = (px[:, 0] // 16) * 256 + (px[:, 1] // 16) * 16 + px[:, 2] // 16
    cnt = np.bincount(key, minlength=4096)
    out = []
    for k in np.argsort(-cnt)[:top]:
        if not cnt[k]:
            break
        mean = px[key == k].mean(axis=0).round().astype(int)
        out.append({"hex": "#%02x%02x%02x" % tuple(mean), "rgb": mean.tolist(), "share": round(float(cnt[k] / len(px)), 4)})
    return out


def accents(a: np.ndarray) -> dict:
    f = a.reshape(-1, 3).astype(np.float64) / 255
    mx, mn = f.max(axis=1), f.min(axis=1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-9), 0)
    sel = (mx > 0.6) & (sat > 0.5)
    share = float(sel.mean())
    fams: dict[str, list] = {}
    for rgb in f[sel][:: max(1, int(sel.sum() // 20000))]:
        h = colorsys.rgb_to_hsv(*rgb)[0] * 360
        name = next(n for n, a0, a1 in FAMILIES if a0 <= h < a1)
        fams.setdefault(name, []).append(rgb)
    rows = []
    for name, v in sorted(fams.items(), key=lambda kv: -len(kv[1])):
        arr = np.asarray(v)
        core = arr[np.argmax(arr.max(axis=1))]
        rows.append({"family": name, "share": round(len(v) / max(1, sum(len(x) for x in fams.values())), 3),
                     "core": "#%02x%02x%02x" % tuple((core * 255).round().astype(int)),
                     "halo": "#%02x%02x%02x" % tuple((arr.mean(axis=0) * 255).round().astype(int))})
    return {"share": round(share, 4), "families": rows}


def measure(paths: list[str | Path], *, top: int = 10, points: list[tuple[int, int]] = (), accent: bool = False) -> list[dict]:
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
                            and not f.name.endswith(".trim.png") and not f.name.startswith("cmp-"))
        else:
            files.append(p)
    out = []
    for f in files:
        im = _img(f)
        a = np.asarray(im)
        x0, y0, x1, y1 = trim_box(a)
        t = a[y0:y1, x0:x1]
        trimmed = f.with_name(f.stem + ".trim.png")
        im.crop((x0, y0, x1, y1)).save(trimmed)
        row = {"file": str(f), "size": [im.width, im.height], "picture": [x0, y0, x1 - x0, y1 - y0],
               "aspect": round((x1 - x0) / max(1, y1 - y0), 3), "trimmed": str(trimmed), "palette": palette(t, top)}
        if points:
            row["points"] = [{"x": x, "y": y, "rgb": np.median(t[max(0, y - 2):y + 3, max(0, x - 2):x + 3].reshape(-1, 3),
                                                             axis=0).round().astype(int).tolist()} for x, y in points]
        if accent:
            row["accents"] = accents(t)
        out.append(row)
    return out


# ------------------------------------------------------------------ a reference video, second by second

def shotlog(video: str | Path, *, fps: float | None = None) -> dict:
    """Editing and sound per second of a reference video (adapted from animate's measure/shotlog.py)."""
    info = probe(video)
    rate = max(1, round(fps or info.fps or 24))
    S = 270
    raw = subprocess.run([ffmpeg(), "-v", "error", "-i", str(video), "-vf", f"fps={rate},scale={S}:{S}:flags=area,format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, timeout=3600).stdout
    F = np.frombuffer(raw, np.uint8)[: len(raw) // (S * S) * S * S].reshape(-1, S, S).astype(np.int16)
    n = len(F)
    d = np.zeros(n)
    d2 = np.zeros(n)
    if n > 1:
        d[1:] = np.abs(np.diff(F, axis=0)).mean(axis=(1, 2))
    if n > 4:
        d2[4:] = np.abs(F[4:] - F[:-4]).mean(axis=(1, 2))
    med = np.array([np.median(d[max(1, f - 12):f + 13]) for f in range(n)]) if n else np.zeros(0)
    cuts = [f for f in range(1, n) if d[f] > max(8, 4 * med[f]) and d[f] >= d[f - 1] and d[f] >= d[min(n - 1, f + 1)]]
    step = np.zeros(n, bool)
    for f in range(12, n):
        w = d[f - 11:f + 1]
        a, b = w[0::2].mean(), w[1::2].mean()
        hi, lo = max(a, b), min(a, b)
        if hi > 6.0 and lo < hi / 4:
            step[f - 11:f + 1] = True
    flick = np.zeros(n, bool)
    for f in range(4, n):
        if d[f] > 8 and d2[f] < 0.35 * d[f]:
            flick[f] = True
    real = [c for c in cuts if not step[c] and not flick[c]]
    sr = 16000
    au = subprocess.run([ffmpeg(), "-v", "error", "-i", str(video), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                        capture_output=True, timeout=3600).stdout
    x = np.frombuffer(au, np.int16).astype(np.float32) / 32768
    win = sr // 10
    nw = len(x) // win
    rms = np.sqrt((x[: nw * win].reshape(nw, win) ** 2).mean(axis=1) + 1e-12) if nw else np.zeros(0)
    db = 20 * np.log10(rms + 1e-9)
    flux = np.maximum(0, np.diff(rms, prepend=rms[:1])) if nw else np.zeros(0)
    onset = (flux > 2.5 * (np.median(flux) + 1e-6)) & (flux > 0.01) if nw else np.zeros(0, bool)
    rows = []
    for s in range(int(np.ceil(n / rate))):
        f0, f1 = s * rate, min(n, (s + 1) * rate)
        w0, w1 = s * 10, min(nw, (s + 1) * 10)
        seg = x[s * sr:(s + 1) * sr]
        cen = 0.0
        if len(seg) > 256:
            spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
            fr = np.fft.rfftfreq(len(seg), 1 / sr)
            cen = float((spec * fr).sum() / (spec.sum() + 1e-9))
        row = {"s": s, "cuts": sum(1 for c in real if f0 <= c < f1), "motion": round(float(d[f0:f1].mean()), 1),
               "held": round(float((d[f0:f1] < 0.8).mean() * 100))}
        if w1 > w0:
            row.update({"db_med": round(float(np.median(db[w0:w1])), 1), "db_p90": round(float(np.percentile(db[w0:w1], 90)), 1),
                        "onsets": int(onset[w0:w1].sum()), "bright_hz": round(cen)})
        rows.append(row)

    def runs(mask, minlen):
        out, start = [], None
        for i, m in enumerate(list(mask) + [False]):
            if m and start is None:
                start = i
            if not m and start is not None:
                if i - start >= minlen:
                    out.append([round(start / rate, 2), round(i / rate, 2)])
                start = None
        return out

    loud = int(np.argmax(db)) if nw else 0
    return {"video": str(video), "fps": rate, "frames": n, "duration": round(n / rate, 2),
            "cuts": [round(c / rate, 2) for c in real], "stepped_on_2s": runs(step, 12), "flicker": runs(flick, 4),
            "per_second": rows, "loudest": {"t": round(loud / 10, 1), "db": round(float(db[loud]), 1)} if nw else None}


# ------------------------------------------------------------------ side by side

def compare(ref: str | Path, frame: str | Path, out: str | Path, *, crop: tuple[int, int, int, int] | None = None,
            crop_ours: tuple[int, int, int, int] | None = None, auto_trim: bool = False, grid: bool = True) -> dict:
    from PIL import Image, ImageDraw
    a, b = _img(ref), _img(frame)
    if auto_trim:
        a = a.crop(trim_box(np.asarray(a)))
    if crop:
        x, y, w, h = crop
        a = a.crop((x, y, x + w, y + h))
    if crop_ours:
        x, y, w, h = crop_ours
        b = b.crop((x, y, x + w, y + h))
    H = 960
    a = a.resize((max(1, round(a.width * H / a.height)), H), Image.LANCZOS)
    b = b.resize((max(1, round(b.width * H / b.height)), H), Image.LANCZOS)
    gap = 24
    sheet = Image.new("RGB", (a.width + b.width + 3 * gap, H + 2 * gap + 30), (30, 28, 26))
    sheet.paste(a, (gap, gap))
    sheet.paste(b, (a.width + 2 * gap, gap))
    d = ImageDraw.Draw(sheet)
    if grid:
        for ox, im in ((gap, a), (a.width + 2 * gap, b)):
            for k in range(1, 10):
                x = ox + im.width * k / 10
                y = gap + im.height * k / 10
                d.line([(x, gap), (x, gap + im.height)], fill=(255, 0, 128), width=1)
                d.line([(ox, y), (ox + im.width, y)], fill=(255, 0, 128), width=1)
    d.text((gap, H + gap + 6), "reference", fill=(230, 220, 200))
    d.text((a.width + 2 * gap, H + gap + 6), "our frame", fill=(230, 220, 200))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return {"image": str(out), "reference_palette": palette(np.asarray(a), 6), "our_palette": palette(np.asarray(b), 6)}


def gallery(out: str | Path, *, extra: list[str | Path] = ()) -> dict:
    """Every style's sample (shipped, personal, and any extra style folders) plus the 'your references' tile."""
    from PIL import Image, ImageDraw
    items = [(s["name"], s["sample"]) for s in styles() if s["sample"]]
    for d in map(Path, extra):
        if d.exists():
            for s in sorted(d.iterdir()):
                smp = next((p for p in (s / "sample.jpg", s / "sample.png") if p.exists()), None)
                if smp and (s / "kit.js").exists():
                    items.append((s.name, str(smp)))
    tw, th, gap, lab = 270, 480, 18, 36
    cols = 4
    n = len(items) + 1
    rows = (n + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + gap) + gap, rows * (th + lab + gap) + gap), (28, 25, 22))
    d = ImageDraw.Draw(sheet)
    for i, (name, smp) in enumerate(items + [("custom: your references", None)]):
        x, y = gap + (i % cols) * (tw + gap), gap + (i // cols) * (th + lab + gap)
        if smp:
            im = _img(smp)
            im = im.resize((tw, round(im.height * tw / im.width)), Image.LANCZOS).crop((0, 0, tw, th))
            sheet.paste(im, (x, y))
        else:
            d.rectangle([x, y, x + tw, y + th], outline=(200, 190, 170), width=3)
            d.text((x + 20, y + th // 2 - 10), "any other look:\nshow a video, stills\nor a web page", fill=(220, 210, 190))
        d.text((x, y + th + 8), f"{i + 1}. {name}", fill=(236, 226, 206))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return {"image": str(out), "styles": [n for n, _ in items]}


def sample_path(style: str) -> Path | None:
    d = ANIM / "styles" / style
    return next((p for p in (d / "sample.jpg", d / "sample.png") if p.exists()), None)
