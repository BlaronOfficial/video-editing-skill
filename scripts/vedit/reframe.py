"""Auto-reframe: follow the speaker's face so one edit exports in 9:16, 1:1, 4:5 and 16:9.

Faces are detected on sampled frames, smoothed (median + dead-zone + easing) so the virtual camera
moves like an operator rather than jittering, and stored as `crop` keys on each clip. The renderer
crops with them; the CapCut builder turns them into position keyframes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .media import ffmpeg, probe
from .project import RATIOS
from .timeline import Canvas, CropKey, Edit


def face_track(src: str | Path, start: float, end: float, *, step: float = 0.25) -> list[tuple[float, float, float]]:
    """(t, cx, cy) of the most prominent face, normalised 0..1; NaN where none was found.

    Frames are read in one FFmpeg pass (fps filter) instead of one seek per sample.
    """
    from .faces import detect
    w, h = 480, 270
    info = probe(src)
    if info.display_size[0] < info.display_size[1]:
        w, h = 270, 480
    dur = max(0.05, end - start)
    proc = subprocess.run([ffmpeg(), "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
                           "-vf", f"fps={1 / step:.4f},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                          capture_output=True)
    raw = proc.stdout
    frame_bytes = w * h * 3
    out = []
    for i in range(len(raw) // frame_bytes):
        img = np.frombuffer(raw[i * frame_bytes:(i + 1) * frame_bytes], dtype=np.uint8).reshape(h, w, 3)
        faces = detect(img)
        t = start + i * step
        if faces:
            x, y, fw, fh, _ = faces[0]
            out.append((t, (x + fw / 2) / w, (y + fh * 0.45) / h))
        else:
            out.append((t, float("nan"), float("nan")))
    return out


def smooth_path(track: list[tuple[float, float, float]], *, dead_zone: float = 0.06, max_keys: int = 40) -> list[tuple[float, float, float]]:
    if not track:
        return [(0.0, 0.5, 0.5)]
    ts = np.array([p[0] for p in track])
    xs = np.array([p[1] for p in track])
    ys = np.array([p[2] for p in track])
    for arr in (xs, ys):
        good = ~np.isnan(arr)
        if not good.any():
            arr[:] = 0.5
        else:
            arr[~good] = np.interp(np.flatnonzero(~good), np.flatnonzero(good), arr[good])
    k = 5
    xs = np.array([np.median(xs[max(0, i - k // 2): i + k // 2 + 1]) for i in range(len(xs))])
    ys = np.array([np.median(ys[max(0, i - k // 2): i + k // 2 + 1]) for i in range(len(ys))])
    keys = [(float(ts[0]), float(xs[0]), float(ys[0]))]
    for t, x, y in zip(ts[1:], xs[1:], ys[1:]):
        if abs(x - keys[-1][1]) > dead_zone or abs(y - keys[-1][2]) > dead_zone * 1.5:
            # ease into the new framing over ~0.6 s instead of snapping
            keys.append((float(max(keys[-1][0] + 0.05, t - 0.6)), keys[-1][1], keys[-1][2]))
            keys.append((float(t), float(x), float(y)))
    keys.append((float(ts[-1]), keys[-1][1], keys[-1][2]))
    if len(keys) > max_keys:
        idx = np.linspace(0, len(keys) - 1, max_keys).astype(int)
        keys = [keys[i] for i in idx]
    return keys


def reframe_edit(edit: Edit, *, ratio: str | None = None, step: float = 0.25) -> Edit:
    """Add crop paths to every main/b-roll video clip whose aspect differs from the canvas."""
    if ratio:
        w, h = RATIOS[ratio]
        edit = edit.model_copy(deep=True)
        edit.canvas = Canvas(width=w, height=h, fps=edit.canvas.fps, background=edit.canvas.background)
    target = edit.canvas.width / edit.canvas.height
    for clip in [*edit.main, *edit.broll]:
        src = edit.sources[clip.source]
        if src.kind != "video" or not src.width or not src.height:
            continue
        if abs(src.width / src.height - target) < 0.02:
            clip.crop = []
            continue
        track = face_track(src.path, clip.src_in, clip.src_out, step=step)
        keys = smooth_path(track)
        clip.crop = [CropKey(t=round((t - clip.src_in) / clip.speed, 3), cx=round(cx, 4), cy=round(cy, 4)) for t, cx, cy in keys]
    return edit.layout()


def ratio_variant_path(edit_path: Path, ratio: str) -> Path:
    return edit_path.with_name(f"edit_{ratio.replace(':', 'x')}.json")
