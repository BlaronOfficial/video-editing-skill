"""Tracking: objects (VitTrack or optical flow), faces (YuNet, several at once), smoothing, and the mapping
from source pixels to canvas pixels that lets an overlay follow what was tracked.

A track file (edit/vfx/tracks/<id>.json):
  {"id", "source", "kind": "object"|"face"|"planar", "fps", "size": [w, h],
   "samples": [[t, x, y, w, h, conf], ...]}             boxes, source pixels, source seconds
   (planar tracks store [t, x1, y1, ... x4, y4, conf]; see planar.py)
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from .. import models
from ..footage import input_chain
from ..timeline import Clip, Edit, Track
from ..util import VeditError, read_json, write_json
from . import frames

TRACK_SIDE = 960          # tracking resolution (long side): fast, and plenty for boxes

models.register(models.Model(
    "vittrack", "https://github.com/opencv/opencv_zoo/raw/main/models/object_tracking_vittrack/"
    "object_tracking_vittrack_2023sep.onnx", 0.72, "Apache-2.0 (opencv_zoo VitTrack)",
    "object tracking (labels that follow things, tracked blur)", "object_tracking_vittrack_2023sep.onnx"))


# ------------------------------------------------------------------ files

def tracks_dir(root: Path) -> Path:
    d = Path(root) / "vfx" / "tracks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get(edit: Edit, track_id: str) -> Track:
    t = next((t for t in edit.tracks if t.id == track_id), None)
    if t is None:
        raise VeditError(f"No track '{track_id}'. Tracks: {', '.join(x.id for x in edit.tracks) or 'none'}")
    return t


def load(track: Track | str) -> dict:
    path = track.file if isinstance(track, Track) else track
    data = read_json(path)
    if not data:
        raise VeditError(f"Track file missing: {path}")
    return data


def save(root: Path, edit: Edit, data: dict, *, label: str = "") -> Track:
    path = tracks_dir(root) / f"{data['id']}.json"
    write_json(path, data)
    s = data["samples"]
    tr = Track(id=data["id"], source=data["source"], kind=data["kind"], t0=round(s[0][0], 4) if s else 0.0,
               t1=round(s[-1][0], 4) if s else 0.0, file=str(path), label=label)
    edit.tracks = [t for t in edit.tracks if t.id != tr.id] + [tr]
    return tr


def unique_id(edit: Edit, base: str) -> str:
    ids = {t.id for t in edit.tracks}
    if base not in ids:
        return base
    n = 2
    while f"{base}_{n}" in ids:
        n += 1
    return f"{base}_{n}"


# ------------------------------------------------------------------ sampling and smoothing

def arrays(data: dict) -> tuple[np.ndarray, np.ndarray]:
    a = np.asarray(data["samples"], dtype=np.float64)
    if a.size == 0:
        return np.zeros(0), np.zeros((0, 5))
    return a[:, 0], a[:, 1:]


def value_at(data: dict, t: float, *, hold: float = 0.0) -> np.ndarray | None:
    """Linearly interpolated sample (box or quad + conf) at source time t; None outside the track
    (`hold` seconds of grace at both ends)."""
    ts, vals = arrays(data)
    if not len(ts) or t < ts[0] - hold or t > ts[-1] + hold:
        return None
    t = min(max(t, ts[0]), ts[-1])
    i = int(np.searchsorted(ts, t))
    if i <= 0:
        return vals[0]
    if i >= len(ts):
        return vals[-1]
    a, b = ts[i - 1], ts[i]
    f = 0.0 if b - a < 1e-9 else (t - a) / (b - a)
    return vals[i - 1] * (1 - f) + vals[i] * f


def smooth(values: np.ndarray, sigma_frames: float) -> np.ndarray:
    """Centered gaussian smoothing per column (offline: no lag), edges reflected."""
    if sigma_frames <= 0 or len(values) < 3:
        return values
    r = max(1, int(3 * sigma_frames))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma_frames) ** 2)
    k /= k.sum()
    out = np.empty_like(values)
    for c in range(values.shape[1]):
        col = np.pad(values[:, c], r, mode="reflect")
        out[:, c] = np.convolve(col, k, mode="valid")
    return out


# ------------------------------------------------------------------ object tracking

class _Flow:
    """Optical-flow box tracker: Lucas-Kanade on corners inside the box, forward-backward checked;
    the box moves by the median shift and scales by the median change in point spread."""

    def __init__(self, frame, box):
        import cv2
        self.cv2 = cv2
        self.prev = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self.box = np.array(box, dtype=np.float64)
        self.pts = self._seed(self.prev)
        self.score = 1.0

    def _seed(self, gray):
        x, y, w, h = self.box
        mask = np.zeros_like(gray)
        x0, y0 = int(max(0, x + w * 0.1)), int(max(0, y + h * 0.1))
        x1, y1 = int(min(gray.shape[1], x + w * 0.9)), int(min(gray.shape[0], y + h * 0.9))
        mask[y0:y1, x0:x1] = 255
        pts = self.cv2.goodFeaturesToTrack(gray, 80, 0.01, 4, mask=mask)
        return pts if pts is not None else np.zeros((0, 1, 2), np.float32)

    def update(self, frame):
        cv2 = self.cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if len(self.pts) < 6:
            self.pts = self._seed(self.prev)
        if len(self.pts) < 3:
            self.prev, self.score = gray, 0.0
            return False, tuple(self.box)
        lk = dict(winSize=(21, 21), maxLevel=3, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
        nxt, st, _ = cv2.calcOpticalFlowPyrLK(self.prev, gray, self.pts, None, **lk)
        back, st2, _ = cv2.calcOpticalFlowPyrLK(gray, self.prev, nxt, None, **lk)
        fb = np.linalg.norm((self.pts - back).reshape(-1, 2), axis=1)
        good = (st.ravel() == 1) & (st2.ravel() == 1) & (fb < 1.0)
        p0, p1 = self.pts.reshape(-1, 2)[good], nxt.reshape(-1, 2)[good]
        self.score = float(good.mean()) if len(good) else 0.0
        if len(p0) >= 3:
            d = np.median(p1 - p0, axis=0)
            s0 = np.linalg.norm(p0 - p0.mean(0), axis=1).mean()
            s1 = np.linalg.norm(p1 - p1.mean(0), axis=1).mean()
            sc = float(np.clip(s1 / s0, 0.9, 1.1)) if s0 > 1e-3 else 1.0
            x, y, w, h = self.box
            cx, cy = x + w / 2 + d[0], y + h / 2 + d[1]
            w, h = w * sc, h * sc
            self.box = np.array([cx - w / 2, cy - h / 2, w, h])
            self.pts = p1.reshape(-1, 1, 2).astype(np.float32)
        self.prev = gray
        if len(self.pts) < 20:                       # refresh points inside the moved box
            fresh = self._seed(gray)
            if len(fresh):
                self.pts = np.concatenate([self.pts, fresh]).astype(np.float32)[:120]
        return self.score > 0.2, tuple(self.box)


class _Vit:
    def __init__(self, frame, box):
        import cv2
        p = cv2.TrackerVit_Params()
        p.net = str(models.ensure("vittrack"))
        self.t = cv2.TrackerVit_create(p)
        self.t.init(frame, tuple(int(round(v)) for v in box))
        self.score = 1.0

    def update(self, frame):
        ok, box = self.t.update(frame)
        self.score = float(self.t.getTrackingScore())
        return bool(ok) and self.score > 0.3, tuple(float(v) for v in box)


class _Hybrid:
    """Flow for precision (2.4 px mean error on the synthetic test vs 7 px for VitTrack), VitTrack to recover:
    when flow loses its points (occlusion, fast turn, motion blur) it restarts on VitTrack's box."""

    def __init__(self, frame, box):
        self.flow = _Flow(frame, box)
        self.vit = _Vit(frame, box)
        self.score = 1.0

    def update(self, frame):
        ok_f, bf = self.flow.update(frame)
        ok_v, bv = self.vit.update(frame)
        if ok_f and self.flow.score >= 0.45:
            self.score = self.flow.score
            return True, bf
        if ok_v:
            self.flow = _Flow(frame, bv)
            self.score = self.vit.score
            return True, bv
        self.score = 0.0
        return False, bf


def _make(method: str, frame, box):
    import cv2
    has_vit = hasattr(cv2, "TrackerVit_create")
    if method == "auto":
        return _Hybrid(frame, box) if has_vit else _Flow(frame, box)
    return (_Vit if method == "vit" else _Flow)(frame, box)


def _chunks_backward(t0: float, at: float, size: float = 2.0):
    end = at
    while end > t0 + 1e-6:
        start = max(t0, end - size)
        yield start, end
        end = start


def track_box(src_path: str, src_color, *, at: float, box: tuple[float, float, float, float], t0: float, t1: float,
              method: str = "auto", work: Path | None = None, progress: bool = True) -> list[list[float]]:
    """Samples [t, x, y, w, h, conf] (source px) from t0 to t1, starting from `box` at time `at`, tracking
    forward then backward. Lost frames keep the last box with conf 0 (callers decide how to treat them)."""
    from types import SimpleNamespace
    spec = frames.spec_for(src_path, max_side=TRACK_SIDE)
    k = spec.scale
    chain = input_chain(SimpleNamespace(color=src_color, lut=None))
    b0 = [v * k for v in box]
    out: dict[float, list[float]] = {}

    def run(frame_iter, times, first_box):
        tracker = None
        for t, fr in zip(times, frame_iter):
            if tracker is None:
                tracker = _make(method, fr, first_box)
                out[round(t, 4)] = [t, *[v / k for v in first_box], 1.0]
                continue
            ok, bx = tracker.update(fr)
            out[round(t, 4)] = [t, *[v / k for v in bx], tracker.score if ok else 0.0]

    started = time.time()
    n_fwd = int(round((t1 - at) * spec.fps))
    run(frames.read(src_path, ss=at, t=max(0.04, t1 - at), spec=spec, chain=chain, cwd=work),
        (at + i / spec.fps for i in range(n_fwd + 2)), b0)
    if at - t0 > 0.5 / spec.fps:
        cur = b0
        for a, b in _chunks_backward(t0, at):
            buf = list(frames.read(src_path, ss=a, t=b - a + 1 / spec.fps, spec=spec, chain=chain, cwd=work))
            times = [a + i / spec.fps for i in range(len(buf))]
            if not buf:
                break
            # start the backward pass at the frame nearest the current anchor
            last = min(range(len(times)), key=lambda i: abs(times[i] - b))
            seq = list(zip(times[:last + 1], buf[:last + 1]))[::-1]
            run((f for _, f in seq), [t for t, _ in seq], cur)
            first = out[round(seq[-1][0], 4)]
            cur = [v * k for v in first[1:5]]
    if progress:
        print(f"  tracked {len(out)} frames in {time.time() - started:.1f}s", flush=True)
    return [out[key] for key in sorted(out)]


def finish_box_samples(samples: list[list[float]], *, sigma: float = 2.0, size: tuple[int, int] | None = None) -> list[list[float]]:
    """Fill lost frames (conf 0) by interpolation between good ones, then smooth."""
    a = np.asarray(samples, dtype=np.float64)
    if len(a) == 0:
        return []
    good = a[:, 5] > 0
    if good.any() and not good.all():
        for c in range(1, 5):
            a[~good, c] = np.interp(a[~good, 0], a[good, 0], a[good, c])
    a[:, 1:5] = smooth(a[:, 1:5], sigma)
    if size:
        a[:, 3] = np.clip(a[:, 3], 2, size[0])
        a[:, 4] = np.clip(a[:, 4], 2, size[1])
    return [[round(float(v), 3) for v in row] for row in a]


# ------------------------------------------------------------------ faces

def track_faces(src_path: str, src_color, *, t0: float, t1: float, min_size: float = 0.03, max_gap: float = 1.0,
                work: Path | None = None) -> list[dict]:
    """Every face in [t0, t1]: YuNet on each frame, greedy association by overlap / distance, gaps up to
    `max_gap` seconds filled, centered smoothing. Returns [{"samples": [...], "area": mean area, "frames": n}]."""
    from types import SimpleNamespace
    from .. import faces
    spec = frames.spec_for(src_path, max_side=TRACK_SIDE)
    k = spec.scale
    chain = input_chain(SimpleNamespace(color=src_color, lut=None))
    tracks: list[dict] = []
    min_px = min_size * min(spec.width, spec.height)

    def iou(a, b):
        ax1, ay1, ax2, ay2 = a[0], a[1], a[0] + a[2], a[1] + a[3]
        bx1, by1, bx2, by2 = b[0], b[1], b[0] + b[2], b[1] + b[3]
        iw, ih = max(0, min(ax2, bx2) - max(ax1, bx1)), max(0, min(ay2, by2) - max(ay1, by1))
        inter = iw * ih
        return inter / max(1e-6, a[2] * a[3] + b[2] * b[3] - inter)

    for i, fr in enumerate(frames.read(src_path, ss=t0, t=max(0.04, t1 - t0), spec=spec, chain=chain, cwd=work)):
        t = t0 + i / spec.fps
        dets = [d for d in faces.detect(fr) if d[2] >= min_px]
        used = set()
        live = [tr for tr in tracks if t - tr["last_t"] <= max_gap]
        for tr in sorted(live, key=lambda x: -x["n"]):
            last = tr["last"]
            best, best_s = None, 0.0
            for j, d in enumerate(dets):
                if j in used:
                    continue
                ov = iou(last, d)
                dist = np.hypot((last[0] + last[2] / 2) - (d[0] + d[2] / 2), (last[1] + last[3] / 2) - (d[1] + d[3] / 2))
                s = ov if ov > 0 else (0.01 if dist < 0.8 * max(last[2], d[2]) else 0)
                if s > best_s:
                    best, best_s = j, s
            if best is not None:
                used.add(best)
                d = dets[best]
                tr["raw"].append([t, d[0] / k, d[1] / k, d[2] / k, d[3] / k, float(d[4])])
                tr["last"], tr["last_t"], tr["n"] = d, t, tr["n"] + 1
        for j, d in enumerate(dets):
            if j not in used:
                tracks.append({"raw": [[t, d[0] / k, d[1] / k, d[2] / k, d[3] / k, float(d[4])]], "last": d, "last_t": t, "n": 1})

    out = []
    for tr in tracks:
        if tr["n"] < max(3, int(0.15 * spec.fps)):           # flickers: a few frames are false positives
            continue
        raw = np.asarray(tr["raw"])
        ts = np.round(np.arange(raw[0, 0], raw[-1, 0] + 0.5 / spec.fps, 1 / spec.fps), 4)
        filled = np.stack([ts] + [np.interp(ts, raw[:, 0], raw[:, c]) for c in range(1, 6)], axis=1)
        filled[:, 1:5] = smooth(filled[:, 1:5], 1.5)
        out.append({"samples": [[round(float(v), 3) for v in row] for row in filled], "frames": tr["n"],
                    "area": float(np.mean(raw[:, 3] * raw[:, 4]))})
    return sorted(out, key=lambda x: -x["area"])


# ------------------------------------------------------------------ source -> canvas

def _ease(p: float, ease: str) -> float:
    p = min(1.0, max(0.0, p))
    if ease == "in":
        return p * p
    if ease == "out":
        return 1 - (1 - p) ** 2
    if ease == "inout":
        return 3 * p * p - 2 * p * p * p
    if ease == "hold":
        return 0.0
    return p


def source_to_canvas(edit: Edit, clip: Clip, u: float, px: float, py: float) -> tuple[float, float]:
    """Canvas pixel of source pixel (px, py) at clip-local OUTPUT time u, following the render's framing:
    black-bar crop, reframe crop keys, fit, zoom and clip transform (rotation, 360 and stabilization are
    not modelled: an attached overlay on such a clip follows the raw track)."""
    W, H = edit.canvas.width, edit.canvas.height
    src = edit.sources[clip.source]
    iw, ih = float(src.width or W), float(src.height or H)
    if clip.src_crop:
        c = clip.src_crop
        px, py, iw, ih = px - c["x"], py - c["y"], float(c["w"]), float(c["h"])
    if clip.crop:
        cw, ch = min(iw, ih * W / H), min(ih, iw * H / W)
        keys = sorted(clip.crop, key=lambda k: k.t)
        ts = [k.t for k in keys]
        cx = float(np.interp(u, ts, [k.cx for k in keys]))
        cy = float(np.interp(u, ts, [k.cy for k in keys]))
        x0, y0 = min(max(0.0, cx * iw - cw / 2), iw - cw), min(max(0.0, cy * ih - ch / 2), ih - ch)
        X, Y = (px - x0) * W / cw, (py - y0) * H / ch
    else:
        W2, H2 = (W * 2, H * 2) if clip.zoom else (W, H)
        if clip.fit == "stretch":
            X, Y = px * W2 / iw, py * H2 / ih
        else:
            sc = max(W2 / iw, H2 / ih) if clip.fit == "cover" else min(W2 / iw, H2 / ih)
            X, Y = px * sc - (iw * sc - W2) / 2, py * sc - (ih * sc - H2) / 2
        if clip.zoom:
            z = clip.zoom
            prog = _ease(u / max(clip.duration, 1e-3), z.ease)
            zf = z.start_scale + (z.end_scale - z.start_scale) * prog
            X = (X * zf - (W2 * zf - W2) / 2 * (1 + z.anchor_x)) * (W / W2)
            Y = (Y * zf - (H2 * zf - H2) / 2 * (1 - z.anchor_y)) * (H / H2)
    t = clip.transform
    X = (W - W * t.scale) / 2 + X * t.scale + t.x * W / 2
    Y = (H - H * t.scale) / 2 + Y * t.scale - t.y * H / 2
    return X, Y


def attach_path(edit: Edit, ov, fps: float) -> list[tuple[float, float, float]]:
    """[(timeline t, canvas x, canvas y)] for an overlay attached to a track: the point it should sit on,
    sampled every frame of the overlay's life. Frames where the tracked source is not on screen are skipped."""
    att = ov.attach or {}
    tr = get(edit, att["track"])
    data = load(tr)
    off = att.get("offset") or [0.0, 0.0]
    anchor = att.get("point", "center")
    ts, vals = arrays(data)
    if att.get("smooth"):
        sig = float(att["smooth"]) * float(data.get("fps") or fps)
        vals = smooth(vals, sig)
        data = {**data, "samples": [[float(t), *map(float, v)] for t, v in zip(ts, vals)]}
    W, H = edit.canvas.width, edit.canvas.height
    out = []
    n = max(1, int(round(ov.duration * fps)))
    for i in range(n + 1):
        T = ov.start + i / fps
        clip = next((c for c in [*edit.main, *[b for b in edit.broll if b.start is not None]]
                     if c.source == tr.source and c.start is not None and c.start <= T < c.end), None)
        if clip is None:
            continue
        u = T - clip.start
        st = clip.src_out - u * clip.speed if clip.reverse else clip.src_in + u * clip.speed
        v = value_at(data, st, hold=0.25)
        if v is None:
            continue
        if data["kind"] == "planar":
            q = np.asarray(v[:8]).reshape(4, 2)
            px, py = q[:, 0].mean(), q[:, 1].mean()
        else:
            x, y, w, h = v[:4]
            px = x + w / 2
            py = {"top": y, "bottom": y + h}.get(anchor, y + h / 2)
        X, Y = source_to_canvas(edit, clip, u, px, py)
        out.append((round(T, 4), X + off[0] * W / 2, Y - off[1] * H / 2))
    return out
