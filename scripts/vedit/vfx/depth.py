"""Monocular depth (Depth-Anything-V2-Small, Apache-2.0; the Base/Large weights are non-commercial and
never used): 3D-photo parallax from a still, fake depth of field on stills and clips.

Depth here is relative inverse depth normalised to 0..1 per image (1 = nearest). Good for ordering
and soft falloffs, not for measurement.
"""

from __future__ import annotations

import math
import time
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from .. import models
from ..footage import input_chain
from ..util import VeditError
from . import frames
from .matte import MATTE_SIDE, guided_filter

models.register(models.Model(
    "depth_small", "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model_int8.onnx",
    27.3, "Apache-2.0 (Depth-Anything-V2-Small; ONNX by onnx-community)",
    "depth: 3D photo parallax, fake depth of field", "depth/depth_anything_v2_small_int8.onnx"))

MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


@lru_cache(maxsize=2)
def _session():
    from .matte import session
    return session(str(models.ensure("depth_small")))


def raw_depth(img_bgr: np.ndarray, *, size: int = 518) -> np.ndarray:
    """Model output (relative inverse depth, larger = nearer) resized to the image."""
    import cv2
    h, w = img_bgr.shape[:2]
    sc = size / max(h, w)
    rh, rw = max(14, round(h * sc / 14) * 14), max(14, round(w * sc / 14) * 14)
    x = cv2.resize(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB), (rw, rh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    x = ((x - MEAN) / STD).transpose(2, 0, 1)[None]
    sess = _session()
    d = np.squeeze(sess.run(None, {sess.get_inputs()[0].name: x})[0]).astype(np.float32)
    return cv2.resize(d, (w, h), interpolation=cv2.INTER_CUBIC)


def normalize(d: np.ndarray, lo: float | None = None, hi: float | None = None) -> np.ndarray:
    lo = float(np.percentile(d, 2)) if lo is None else lo
    hi = float(np.percentile(d, 98)) if hi is None else hi
    return np.clip((d - lo) / max(1e-6, hi - lo), 0, 1)


def depth_image(image: str, out: str | Path | None = None, *, size: int = 518) -> tuple[np.ndarray, Path | None]:
    import cv2
    img = frames.read_image(image)[..., :3]
    d = normalize(raw_depth(img, size=size))
    d = np.clip(guided_filter(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), d, r=max(4, min(img.shape[:2]) // 150), eps=1e-3), 0, 1)
    if out:
        p = frames.write_image(Path(out).with_suffix(".png"), (d * 65535).astype(np.uint16))
        return d, p
    return d, None


# ------------------------------------------------------------------ 3D photo

MOVES = ("dolly_in", "dolly_out", "pan_left", "pan_right", "rise", "orbit", "zoom_through")


def _ease(p: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * min(1.0, max(0.0, p)))


def parallax(image: str, out: str | Path, *, duration: float = 5.0, fps: float = 30.0, move: str = "dolly_in",
             amount: float = 1.0, size: tuple[int, int] | None = None, focus: float | None = None) -> dict:
    """A moving camera inside a still: pixels shift by their depth (near moves more). Writes H.264 MP4."""
    import cv2
    if move not in MOVES:
        raise VeditError(f"Unknown move '{move}'. Use one of: {', '.join(MOVES)}")
    img = frames.read_image(image)[..., :3]
    d, _ = depth_image(image)
    h, w = img.shape[:2]
    # protect edges: near objects grow a little so the background stretches behind them, not into them
    k = max(3, int(min(h, w) * 0.012) | 1)
    dm = cv2.dilate(d, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    dm = cv2.GaussianBlur(dm, (0, 0), k / 3)
    f = float(np.median(d)) if focus is None else focus
    ow, oh = size or (w // 2 * 2, h // 2 * 2)
    # output grid in source coordinates, cover-fitted and pre-zoomed so moves never reveal the border
    base = max(ow / w, oh / h) / 1.08
    gx, gy = np.meshgrid(np.arange(ow, dtype=np.float32), np.arange(oh, dtype=np.float32))
    cx, cy = w / 2, h / 2
    X0, Y0 = cx + (gx - ow / 2) / base, cy + (gy - oh / 2) / base
    A = 0.035 * amount * max(w, h)          # max parallax shift, source px
    Z = 0.14 * amount
    n = max(2, int(round(duration * fps)))
    started = time.time()
    with frames.Writer(out, ow, oh, fps, "bgr") as wr:
        for i in range(n):
            p = _ease(i / (n - 1))
            sx = sy = 0.0
            zoom = 0.0
            if move in ("dolly_in", "zoom_through"):
                zoom = Z * p
            elif move == "dolly_out":
                zoom = Z * (1 - p)
            elif move == "pan_left":
                sx = A * (p - 0.5) * 2
            elif move == "pan_right":
                sx = -A * (p - 0.5) * 2
            elif move == "rise":
                sy = A * (p - 0.5) * 2
            elif move == "orbit":
                sx, sy = A * math.sin(2 * math.pi * p), 0.5 * A * math.cos(2 * math.pi * p)
            xs, ys = X0.copy(), Y0.copy()
            for _ in range(3):               # fixed point: the depth at the pixel we end up sampling
                dd = cv2.remap(dm, xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT) - f
                s = 1 + zoom * (0.35 + (1.6 if move == "zoom_through" else 1.0) * np.maximum(dd + f, 0))
                xs = cx + (X0 - cx) / s - sx * dd
                ys = cy + (Y0 - cy) / s - sy * dd
            wr.write(cv2.remap(img, xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT))
    return {"output": str(out), "frames": n, "size": [ow, oh], "move": move, "seconds": round(time.time() - started, 1)}


def auto_focus(img_bgr: np.ndarray, d: np.ndarray) -> float:
    """Focus depth for "auto": the largest face if there is one, else the middle of the picture."""
    from .. import faces
    h, w = d.shape[:2]
    small = img_bgr if max(img_bgr.shape[:2]) <= 1280 else __import__("cv2").resize(img_bgr, (w // 2, h // 2))
    k = small.shape[1] / img_bgr.shape[1]
    found = faces.detect(small)
    if found:
        x, y, fw, fh, _ = found[0]
        x0, y0, x1, y1 = (int(v / k) for v in (x, y, x + fw, y + fh))
        return float(np.median(d[max(0, y0):y1, max(0, x0):x1]))
    return float(np.median(d[h // 3:2 * h // 3, w // 3:2 * w // 3]))


def dof_image(image: str, out: str | Path, *, focus: float | str = "auto", range_: float = 0.15, blur: float = 10.0) -> dict:
    """Depth of field on a still: sharp around `focus` (1 = nearest, "auto" = the face or the centre)."""
    import cv2
    img = frames.read_image(image)[..., :3]
    d, _ = depth_image(image)
    if focus in (None, "auto"):
        focus = auto_focus(img, d)
    m = defocus(d, float(focus), range_)
    blurred = cv2.GaussianBlur(img, (0, 0), blur * max(img.shape[:2]) / 1080)
    res = (img * (1 - m[..., None]) + blurred * m[..., None]).astype(np.uint8)
    p = frames.write_image(out, res)
    return {"output": str(p), "focus": round(float(focus), 3), "sharp_fraction": round(float((m < 0.5).mean()), 3)}


def defocus(d: np.ndarray, focus: float, range_: float) -> np.ndarray:
    """0 = in focus, 1 = fully blurred: smooth ramp starting half a range away from the focus depth."""
    x = (np.abs(d - focus) - range_ * 0.5) / max(1e-3, range_)
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def focus_at(dof: dict, u: float, auto: float | None = None) -> float:
    pull = dof.get("pull") or []
    if not pull:
        f = dof.get("focus", "auto")
        return float(auto if f in (None, "auto") and auto is not None else (0.8 if f in (None, "auto") else f))
    ts, fs = zip(*sorted((float(a), float(b)) for a, b in pull))
    return float(np.interp(u, ts, fs))


def dof_layer(src_path: str, src_color, out: Path, dof: dict, *, ss: float, t: float, clip_in: float, speed: float = 1.0,
              work: Path | None = None, step: int = 2, progress: bool = True) -> Path:
    """Gray FFV1 layer of the defocus amount for [ss, ss+t]. Depth every `step` frames (interpolated
    between), temporally smoothed, edge-snapped with a guided filter."""
    import cv2
    spec = frames.spec_for(src_path, max_side=MATTE_SIDE)
    chain = input_chain(SimpleNamespace(color=src_color, lut=None))
    rng = float(dof.get("range", 0.25))
    lo = hi = None
    last_d = None
    prev_raw = next_raw = None
    started, n = time.time(), 0
    buf: list[np.ndarray] = []
    auto_f: list[float | None] = [None]
    with frames.Writer(out, spec.width, spec.height, spec.fps, "gray") as wr:
        def flush(frames_buf, d0, d1):
            nonlocal last_d, n
            for j, fr in enumerate(frames_buf):
                f = j / max(1, len(frames_buf))
                raw = d0 if d1 is None else d0 * (1 - f) + d1 * f
                dn = normalize(raw, lo, hi)
                if last_d is not None:
                    dn = 0.6 * dn + 0.4 * last_d
                last_d = dn
                g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
                dg = np.clip(guided_filter(g, dn, r=6, eps=2e-3), 0, 1)
                st = ss + n / spec.fps
                u = (st - clip_in) / max(speed, 1e-6)
                if auto_f[0] is None and dof.get("focus", "auto") in (None, "auto"):
                    auto_f[0] = auto_focus(fr, dg)         # locked on the first frame: no focus hunting
                m = defocus(dg, focus_at(dof, u, auto_f[0]), rng)
                wr.write((m * 255 + 0.5).astype(np.uint8))
                n += 1

        for i, fr in enumerate(frames.read(src_path, ss=ss, t=t, spec=spec, chain=chain, cwd=work)):
            if i % step == 0:
                small = cv2.resize(fr, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA) if max(fr.shape[:2]) > 900 else fr
                next_raw = raw_depth(small, size=392)
                next_raw = cv2.resize(next_raw, (spec.width, spec.height))
                plo, phi = float(np.percentile(next_raw, 2)), float(np.percentile(next_raw, 98))
                lo = plo if lo is None else 0.8 * lo + 0.2 * plo
                hi = phi if hi is None else 0.8 * hi + 0.2 * phi
                if prev_raw is not None:
                    flush(buf, prev_raw, next_raw)
                    buf = []
                prev_raw = next_raw
            buf.append(fr)
            if progress and i and i % 60 == 0:
                print(f"  depth: {i} frames ({i / max(1e-3, time.time() - started):.1f} fps)", flush=True)
        if buf and prev_raw is not None:
            flush(buf, prev_raw, None)
    if n == 0:
        raise VeditError(f"No frames decoded from {src_path} at {ss:.2f}s")
    return out
