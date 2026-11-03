"""Synthetic footage with ground truth for the phase 4 tests (generated, never committed).

plane.mp4   a textured "screen" (four corners known every frame) moving with perspective over a busy,
            slowly panning background, handheld-style jitter
box.mp4     a textured patch translating and scaling over a textured background (object tracking)
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import numpy as np

W, H, FPS, SECONDS = 1280, 720, 30, 4.0


def _writer(path: Path):
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-framerate", str(FPS),
           "-i", "-", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(path)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def _texture(w: int, h: int, seed: int) -> np.ndarray:
    import cv2
    rng = np.random.default_rng(seed)
    img = (rng.random((h // 8, w // 8, 3)) * 255).astype(np.uint8)
    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_CUBIC)
    for _ in range(40):
        c = tuple(int(v) for v in rng.integers(0, 255, 3))
        p = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        cv2.circle(img, p, int(rng.integers(8, 60)), c, -1)
        cv2.line(img, p, (int(rng.integers(0, w)), int(rng.integers(0, h))), c, 3)
    return img


def make(out_dir: Path) -> dict:
    import cv2
    out_dir.mkdir(parents=True, exist_ok=True)
    bg = _texture(W + 400, H + 200, 1)
    screen = _texture(400, 700, 2)
    cv2.rectangle(screen, (0, 0), (399, 699), (20, 20, 20), 26)            # a bezel the tracker can hold on to
    patch = _texture(160, 160, 3)
    n = int(SECONDS * FPS)
    truth = {"plane": [], "box": []}
    wp, wb = _writer(out_dir / "plane.mp4"), _writer(out_dir / "box.mp4")
    sq = np.float32([[0, 0], [400, 0], [400, 700], [0, 700]])
    for i in range(n):
        t = i / FPS
        jx, jy = 6 * math.sin(t * 11.0), 5 * math.cos(t * 9.0)              # handheld jitter
        ox, oy = int(100 + 60 * t / SECONDS + jx), int(80 + jy)
        frame = bg[oy:oy + H, ox:ox + W].copy()
        # plane: centre drifts, yaw changes (perspective), slight roll
        cx, cy = 640 + 160 * math.sin(t * 0.9) + jx, 360 + 40 * math.sin(t * 1.3) + jy
        yaw, roll, sc = 0.35 * math.sin(t * 0.7), 0.08 * math.sin(t * 1.1), 0.55 + 0.05 * math.sin(t)
        hw, hh = 200 * sc, 350 * sc
        pts = []
        for x, y in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
            z = 1 + 0.35 * yaw * x / hw
            xr, yr = x * math.cos(roll) - y * math.sin(roll), x * math.sin(roll) + y * math.cos(roll)
            pts.append([cx + xr / z, cy + yr / z])
        q = np.float32(pts)
        M = cv2.getPerspectiveTransform(sq, q)
        warped = cv2.warpPerspective(screen, M, (W, H))
        mask = cv2.warpPerspective(np.full((700, 400), 255, np.uint8), M, (W, H))
        pf = frame.copy()
        pf[mask > 127] = warped[mask > 127]
        wp.stdin.write(pf.tobytes())
        truth["plane"].append([round(t, 4), *q.ravel().round(2).tolist()])
        # box: patch moving on a path, growing
        s = 1 + 0.4 * t / SECONDS
        bw = int(160 * s)
        bx, by = int(200 + 700 * t / SECONDS + jx), int(300 + 120 * math.sin(t * 1.5) + jy)
        bf = frame.copy()
        bf[by:by + bw, bx:bx + bw] = cv2.resize(patch, (bw, bw))
        wb.stdin.write(bf.tobytes())
        truth["box"].append([round(t, 4), bx, by, bw, bw])
    for w in (wp, wb):
        w.stdin.close()
        w.wait()
    (out_dir / "truth.json").write_text(json.dumps(truth))
    return truth


if __name__ == "__main__":
    make(Path(__file__).parent / "out" / "p4" / "synth")
