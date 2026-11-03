"""Planar tracking and screen replacement: a phone or laptop screen, a sign, a poster, a page.

Four corners are given at one moment (Claude reads a frame, the owner clicks them in the Studio, or
`suggest_quads` proposes candidates). Corner features of the plane (the screen plus its bezel) are tracked
with optical flow; every frame gets a homography from the reference frame by RANSAC, so the corners never
accumulate drift as long as enough of the plane stays visible. Lost points are re-seeded inside the
projected quad and mapped back to the reference frame.

The insert (image or video) is warped into the quad per frame and written as a source-space RGBA layer,
merged at decode like any other clip filter.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ..footage import input_chain
from ..util import VeditError
from . import frames
from .track import TRACK_SIDE, _chunks_backward, smooth


def _grow(quad: np.ndarray, f: float) -> np.ndarray:
    c = quad.mean(0)
    return c + (quad - c) * (1 + f)


class _PlaneTracker:
    def __init__(self, gray: np.ndarray, quad: np.ndarray, grow: float):
        import cv2
        self.cv2 = cv2
        self.ref_quad = quad.astype(np.float32)
        self.grow = grow
        self.prev = gray
        self.H = np.eye(3)
        self.ref_pts, self.pts = self._seed(gray, np.eye(3))
        self.score = 1.0

    def _seed(self, gray, H):
        cv2 = self.cv2
        quad = cv2.perspectiveTransform(_grow(self.ref_quad, self.grow).reshape(-1, 1, 2).astype(np.float32), H).reshape(-1, 2)
        mask = np.zeros_like(gray)
        cv2.fillConvexPoly(mask, quad.astype(np.int32), 255)
        pts = cv2.goodFeaturesToTrack(gray, 300, 0.005, 5, mask=mask, blockSize=5)
        if pts is None:
            return np.zeros((0, 2), np.float32), np.zeros((0, 2), np.float32)
        cur = pts.reshape(-1, 2).astype(np.float32)
        ref = cv2.perspectiveTransform(cur.reshape(-1, 1, 2), np.linalg.inv(H)).reshape(-1, 2)
        return ref.astype(np.float32), cur

    def update(self, gray):
        cv2 = self.cv2
        if len(self.pts) >= 8:
            lk = dict(winSize=(25, 25), maxLevel=4, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
            p0 = self.pts.reshape(-1, 1, 2)
            nxt, st, _ = cv2.calcOpticalFlowPyrLK(self.prev, gray, p0, None, **lk)
            back, st2, _ = cv2.calcOpticalFlowPyrLK(gray, self.prev, nxt, None, **lk)
            fb = np.linalg.norm((p0 - back).reshape(-1, 2), axis=1)
            good = (st.ravel() == 1) & (st2.ravel() == 1) & (fb < 1.5)
            ref, cur = self.ref_pts[good], nxt.reshape(-1, 2)[good]
        else:
            ref, cur = self.ref_pts, self.pts
        ok = False
        if len(cur) >= 8:
            H, inl = cv2.findHomography(ref, cur, cv2.RANSAC, 2.5)
            if H is not None and inl is not None and inl.sum() >= 8:
                inl = inl.ravel().astype(bool)
                self.H, self.ref_pts, self.pts = H, ref[inl], cur[inl]
                self.score = float(inl.mean())
                ok = True
        if not ok:
            self.score = 0.0
        self.prev = gray
        if len(self.pts) < 60:
            r2, c2 = self._seed(gray, self.H)
            if len(c2):
                self.ref_pts = np.concatenate([self.ref_pts, r2])[:400]
                self.pts = np.concatenate([self.pts, c2])[:400]
        quad = cv2.perspectiveTransform(self.ref_quad.reshape(-1, 1, 2), self.H).reshape(-1, 2)
        return ok, quad


def track_plane(src_path: str, src_color, *, at: float, corners: list[list[float]], t0: float, t1: float,
                grow: float = 0.25, work: Path | None = None, progress: bool = True) -> list[list[float]]:
    """Samples [t, x1, y1, x2, y2, x3, y3, x4, y4, conf] (source px, corners in the order given)."""
    import cv2
    spec = frames.spec_for(src_path, max_side=TRACK_SIDE)
    k = spec.scale
    chain = input_chain(SimpleNamespace(color=src_color, lut=None))
    q0 = np.asarray(corners, dtype=np.float32).reshape(4, 2) * k
    out: dict[float, list[float]] = {}
    started = time.time()

    def run(seq, quad):
        tr = None
        for t, fr in seq:
            g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            if tr is None:
                tr = _PlaneTracker(g, quad, grow)
                out[round(t, 4)] = [t, *(quad / k).ravel().tolist(), 1.0]
                continue
            ok, q = tr.update(g)
            out[round(t, 4)] = [t, *(q / k).ravel().tolist(), tr.score if ok else 0.0]

    n = int(round((t1 - at) * spec.fps)) + 2
    fwd = frames.read(src_path, ss=at, t=max(0.04, t1 - at), spec=spec, chain=chain, cwd=work)
    run(zip((at + i / spec.fps for i in range(n)), fwd), q0)
    cur = q0
    for a, b in _chunks_backward(t0, at):
        buf = list(frames.read(src_path, ss=a, t=b - a + 1 / spec.fps, spec=spec, chain=chain, cwd=work))
        if not buf:
            break
        times = [a + i / spec.fps for i in range(len(buf))]
        last = min(range(len(times)), key=lambda i: abs(times[i] - b))
        seq = list(zip(times[:last + 1], buf[:last + 1]))[::-1]
        run(seq, cur)
        cur = np.asarray(out[round(seq[-1][0], 4)][1:9], dtype=np.float32).reshape(4, 2) * k
    if progress:
        print(f"  plane tracked over {len(out)} frames in {time.time() - started:.1f}s", flush=True)
    rows = np.asarray([out[key] for key in sorted(out)], dtype=np.float64)
    good = rows[:, 9] > 0
    if good.any() and not good.all():
        for c in range(1, 9):
            rows[~good, c] = np.interp(rows[~good, 0], rows[good, 0], rows[good, c])
    rows[:, 1:9] = smooth(rows[:, 1:9], 0.8)
    return [[round(float(v), 3) for v in r] for r in rows]


def suggest_quads(img: np.ndarray, *, top: int = 4) -> list[dict]:
    """Candidate screens / signs in a frame: large convex four-sided shapes (contours of edges and of
    very bright or very dark regions). Corners clockwise from top-left, source px, with a score."""
    import cv2
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    masks = [cv2.dilate(cv2.Canny(blur, 40, 120), np.ones((3, 3), np.uint8))]
    for thr, inv in ((int(np.percentile(gray, 92)), False), (int(np.percentile(gray, 8)), True)):
        _, m = cv2.threshold(blur, thr, 255, cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY)
        masks.append(cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)))
    cands = []
    for m in masks:
        cnts, _ = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            area = cv2.contourArea(c)
            if area < 0.01 * w * h or area > 0.9 * w * h:
                continue
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue
            q = order_corners(approx.reshape(4, 2).astype(np.float64))
            rect = area / max(1.0, cv2.contourArea(cv2.convexHull(c)))
            cands.append({"corners": q.round(1).tolist(), "area": round(area / (w * h), 4),
                          "score": round(float(area / (w * h)) * rect, 4)})
    cands.sort(key=lambda d: -d["score"])
    picked: list[dict] = []
    for c in cands:
        cen = np.asarray(c["corners"]).mean(0)
        if all(np.linalg.norm(cen - np.asarray(p["corners"]).mean(0)) > 0.05 * max(w, h) for p in picked):
            picked.append(c)
        if len(picked) >= top:
            break
    return picked


def order_corners(q: np.ndarray) -> np.ndarray:
    """Top-left, top-right, bottom-right, bottom-left."""
    c = q.mean(0)
    ang = np.arctan2(q[:, 1] - c[1], q[:, 0] - c[0])
    q = q[np.argsort(ang)]                  # clockwise in image coords, starting near -pi (left)
    start = int(np.argmin(q.sum(1)))        # top-left has the smallest x + y
    return np.roll(q, -start, axis=0)


def draw_quads(img: np.ndarray, quads: list[list[list[float]]], out: Path) -> Path:
    import cv2
    vis = img.copy()
    colors = [(0, 220, 255), (255, 120, 0), (80, 255, 80), (255, 80, 255)]
    for i, q in enumerate(quads):
        pts = np.asarray(q, dtype=np.int32)
        cv2.polylines(vis, [pts], True, colors[i % 4], max(2, img.shape[1] // 400))
        for j, p in enumerate(pts):
            cv2.circle(vis, tuple(int(v) for v in p), max(4, img.shape[1] // 200), colors[i % 4], -1)
            cv2.putText(vis, str(j + 1), (int(p[0]) + 6, int(p[1]) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colors[i % 4], 2)
        cv2.putText(vis, f"#{i + 1}", tuple(int(v) for v in pts.mean(0)), cv2.FONT_HERSHEY_SIMPLEX, 1.0, colors[i % 4], 2)
    return frames.write_image(out, vis)


# ------------------------------------------------------------------ insert layer

class _Media:
    """An image or video for an insert, frame by frame (video loops if shorter than the screen time)."""

    def __init__(self, path: str, fps: float):
        from ..media import probe
        self.path = path
        info = probe(path)
        self.kind = info.kind
        self.fps = fps
        if self.kind == "image":
            img = frames.read_image(path)
            self.still = img if img.shape[2] == 4 else np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
        else:
            w, h = info.display_size
            self.spec = frames.FrameSpec(w, h, w, h, fps)
            self.duration = max(info.duration, 1 / fps)
            self.iter = None

    def frames(self):
        if self.kind == "image":
            while True:
                yield self.still
        while True:
            for fr in frames.read(self.path, ss=0, t=self.duration, spec=self.spec):
                yield np.dstack([fr, np.full(fr.shape[:2], 255, np.uint8)])


def insert_layer(src_path: str, samples: list[list[float]], media: str, out: Path, *, ss: float, t: float,
                 fit: str = "cover", keep_light: float = 0.0, start: float | None = None, end: float | None = None,
                 src_color=None, work: Path | None = None) -> Path:
    """BGRA layer (source size, [ss, ss+t]) with `media` warped into the tracked quad on every frame."""
    import cv2
    from .track import value_at
    spec = frames.spec_for(src_path)
    W, H = spec.src_width, spec.src_height
    med = _Media(media, spec.fps)
    data = {"samples": samples}
    gen = med.frames()
    chain = input_chain(SimpleNamespace(color=src_color, lut=None))
    src_iter = frames.read(src_path, ss=ss, t=t, spec=spec, chain=chain, cwd=work) if keep_light > 0 else None
    n = max(1, int(round(t * spec.fps)))
    with frames.Writer(out, W, H, spec.fps, "bgra") as wr:
        for i in range(n):
            st = ss + i / spec.fps
            base = next(src_iter, None) if src_iter is not None else None
            v = value_at(data, st, hold=1.0 / spec.fps)
            layer = np.zeros((H, W, 4), np.uint8)
            active = v is not None and (start is None or st >= start) and (end is None or st <= end)
            m = next(gen) if active or med.kind == "image" else None
            if active:
                q = np.asarray(v[:8], dtype=np.float32).reshape(4, 2)
                mh, mw = m.shape[:2]
                if fit == "cover":
                    qw = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
                    qh = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
                    ar = qw / max(qh, 1e-3)
                    if mw / mh > ar:
                        cw = int(mh * ar)
                        m = m[:, (mw - cw) // 2:(mw - cw) // 2 + cw]
                    else:
                        ch = int(mw / ar)
                        m = m[(mh - ch) // 2:(mh - ch) // 2 + ch]
                    mh, mw = m.shape[:2]
                srcq = np.float32([[0, 0], [mw, 0], [mw, mh], [0, mh]])
                M = cv2.getPerspectiveTransform(srcq, q)
                layer = cv2.warpPerspective(m, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                                            borderValue=(0, 0, 0, 0))
                if base is not None:
                    # carry the screen's reflections: lift the insert by the original's bright highlights
                    g = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY).astype(np.float32)
                    hi = np.clip((g - np.percentile(g, 85)) / 60.0, 0, 1)[..., None] * keep_light * 255
                    rgb = layer[..., :3].astype(np.float32)
                    layer[..., :3] = np.clip(rgb + hi * (layer[..., 3:4] / 255.0), 0, 255).astype(np.uint8)
            wr.write(layer)
    return out


def check_corners(corners) -> list[list[float]]:
    q = np.asarray(corners, dtype=np.float64)
    if q.size != 8:
        raise VeditError("Corners must be four x,y points: x1,y1,x2,y2,x3,y3,x4,y4 (source pixels)")
    return order_corners(q.reshape(4, 2)).round(2).tolist()
