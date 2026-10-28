"""Helpers for custom Python FX scripts (CustomFX kind=python). Scripts run in the vedit venv with
`from vedit.fxkit import ...`, so numpy, OpenCV and Pillow are available.

A script receives:
  --in <file or "">  --out <file>  --params <json file>  --width W --height H --fps F --duration D
  --start S  --project <edit folder>
and must write --out: an alpha video (.mov ProRes 4444) for overlays, a .wav for audio, an .mp4 for sources.

Minimal overlay script:

    from vedit.fxkit import args, AlphaWriter
    import numpy as np
    a = args()
    with AlphaWriter(a.out, a.width, a.height, a.fps) as w:
        for i in range(a.frames):
            rgba = np.zeros((a.height, a.width, 4), np.uint8)
            ...draw...
            w.write(rgba)
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np


@dataclass
class FxArgs:
    inp: str
    out: str
    params: dict
    width: int
    height: int
    fps: float
    duration: float
    start: float
    project: str

    @property
    def frames(self) -> int:
        return max(1, int(round(self.duration * self.fps)))


def args(argv: list[str] | None = None) -> FxArgs:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--params", default="")
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--duration", type=float, default=3)
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--project", default=".")
    a = ap.parse_args(argv)
    params = json.loads(Path(a.params).read_text(encoding="utf-8")) if a.params else {}
    return FxArgs(a.inp, a.out, params, a.width, a.height, a.fps, a.duration, a.start, a.project)


class AlphaWriter:
    """Pipe RGBA frames into ProRes 4444 (alpha kept; imports into CapCut, Resolve, Premiere)."""

    def __init__(self, out: str, width: int, height: int, fps: float):
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{width}x{height}",
             "-r", f"{fps}", "-i", "-", "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
             "-vendor", "apl0", out], stdin=subprocess.PIPE)
        self.size = (height, width)

    def write(self, rgba: np.ndarray) -> None:
        if rgba.shape[:2] != self.size or rgba.shape[2] != 4:
            raise ValueError(f"frame must be {self.size[0]}x{self.size[1]}x4 RGBA, got {rgba.shape}")
        self.proc.stdin.write(np.ascontiguousarray(rgba, dtype=np.uint8).tobytes())

    def __enter__(self) -> "AlphaWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.proc.stdin.close()
        if self.proc.wait() != 0:
            raise RuntimeError("ffmpeg failed while writing the FX overlay")


def read_frames(path: str, width: int, height: int, fps: float, *, start: float = 0.0,
                duration: float | None = None) -> Iterator[np.ndarray]:
    """Decode a video into RGB frames scaled to width x height (cover-fit), at the edit's fps."""
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}"]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-i", path, "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps}",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    n = width * height * 3
    try:
        while True:
            buf = proc.stdout.read(n)
            if len(buf) < n:
                break
            yield np.frombuffer(buf, np.uint8).reshape(height, width, 3)
    finally:
        proc.stdout.close()
        proc.wait()


def write_wav(samples: np.ndarray, out: str, sr: int = 48000) -> None:
    import wave
    data = np.clip(samples, -1, 1)
    if data.ndim == 1:
        data = np.stack([data, data], axis=1)
    with wave.open(out, "wb") as w:
        w.setnchannels(data.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((data * 32767).astype("<i2").tobytes())
