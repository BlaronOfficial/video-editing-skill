"""Frame pipes: read the exact frames a clip decodes (footage chain included), write mask / RGBA layers.

Layers are FFV1 in Matroska: lossless, fast, alpha-capable, and read back by FFmpeg's `movie` source
inside a clip's filter graph. They are written at a constant frame rate from 0, the same timing the
clip's decode starts at after `-ss`.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from ..media import ffmpeg, probe
from ..util import VeditError


@dataclass
class FrameSpec:
    width: int          # size of the frames delivered (after the optional downscale)
    height: int
    src_width: int      # decoded source size (what redaction boxes and tracks are expressed in)
    src_height: int
    fps: float

    @property
    def scale(self) -> float:
        return self.width / max(1, self.src_width)


def source_size(path: str) -> tuple[int, int, float]:
    info = probe(path)
    w, h = info.display_size
    return w, h, info.fps or 30.0


def spec_for(path: str, *, max_side: int | None = None, fps: float | None = None) -> FrameSpec:
    w, h, f = source_size(path)
    sc = 1.0
    if max_side and max(w, h) > max_side:
        sc = max_side / max(w, h)
    ow, oh = max(2, int(round(w * sc / 2)) * 2), max(2, int(round(h * sc / 2)) * 2)
    return FrameSpec(ow, oh, w, h, fps or f)


def read(path: str, *, ss: float, t: float, spec: FrameSpec, chain: list[str] | None = None,
         cwd: str | Path | None = None, gray: bool = False) -> Iterator[np.ndarray]:
    """BGR (or gray) frames of [ss, ss+t] at spec.fps and spec size, after the footage chain."""
    vf = [*(chain or []), f"fps={spec.fps:.6f}"]
    if (spec.width, spec.height) != (spec.src_width, spec.src_height):
        vf.append(f"scale={spec.width}:{spec.height}:flags=area")
    pix = "gray" if gray else "bgr24"
    vf.append(f"format={pix}")
    cmd = [ffmpeg(), "-v", "error", "-nostdin", "-ss", f"{max(0.0, ss):.4f}", "-t", f"{t:.4f}", "-i", str(path),
           "-vf", ",".join(vf), "-an", "-f", "rawvideo", "-pix_fmt", pix, "-"]
    ch = 1 if gray else 3
    size = spec.width * spec.height * ch
    if cwd is not None:
        Path(cwd).mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    finished = False
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                finished = True
                break
            frame = np.frombuffer(buf, np.uint8)
            yield frame.reshape(spec.height, spec.width) if gray else frame.reshape(spec.height, spec.width, 3)
    finally:
        if not finished:                     # the caller stopped early: stop ffmpeg quietly
            proc.kill()
        proc.stdout.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        proc.stderr.close()
        rc = proc.wait()
        if finished and rc not in (0, None):
            raise VeditError(f"Frame reader failed: {err[-800:]}")


def read_image(path: str, max_side: int | None = None) -> np.ndarray:
    import cv2
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise VeditError(f"Could not read image {path}")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if max_side and max(img.shape[:2]) > max_side:
        sc = max_side / max(img.shape[:2])
        img = cv2.resize(img, (int(img.shape[1] * sc), int(img.shape[0] * sc)), interpolation=cv2.INTER_AREA)
    return img


def write_image(path: str | Path, img: np.ndarray) -> Path:
    import cv2
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(path.suffix or ".png", img)
    if not ok:
        raise VeditError(f"Could not encode {path}")
    buf.tofile(str(path))
    return path


class Writer:
    """Raw frames -> FFV1 .mkv (gray masks or BGRA layers), or H.264 .mp4 for plain video (`kind="bgr"`)."""

    def __init__(self, out: str | Path, width: int, height: int, fps: float, kind: str = "gray"):
        self.out = Path(out)
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.tmp = self.out.with_name(self.out.stem + ".part" + self.out.suffix)
        pix_in = {"gray": "gray", "bgra": "bgra", "bgr": "bgr24"}[kind]
        if kind == "bgr":
            enc = ["-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        else:
            enc = ["-c:v", "ffv1", "-level", "3", "-slices", "4", "-pix_fmt", "gray" if kind == "gray" else "bgra"]
        cmd = [ffmpeg(), "-y", "-v", "error", "-nostdin", "-f", "rawvideo", "-pix_fmt", pix_in, "-s", f"{width}x{height}",
               "-framerate", f"{fps:.6f}", "-i", "-", *enc, str(self.tmp)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.n = 0
        self.size = (width, height)

    def write(self, frame: np.ndarray) -> None:
        if frame.shape[1] != self.size[0] or frame.shape[0] != self.size[1]:
            raise VeditError(f"Frame size {frame.shape[1]}x{frame.shape[0]} != layer size {self.size[0]}x{self.size[1]}")
        self.proc.stdin.write(np.ascontiguousarray(frame).tobytes())
        self.n += 1

    def close(self) -> Path:
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace")
        if self.proc.wait() != 0:
            raise VeditError(f"Layer encode failed: {err[-800:]}")
        self.tmp.replace(self.out)
        return self.out

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.close()
        else:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=10)
            finally:
                self.tmp.unlink(missing_ok=True)
