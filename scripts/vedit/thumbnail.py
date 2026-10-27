"""Thumbnails / covers: pick the strongest frames, then compose title + frame with the mg renderer."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .media import ffmpeg, probe
from .paths import mg_dir
from .util import write_json


def best_frames(src: str | Path, out_dir: Path, *, count: int = 6, samples: int = 60) -> list[dict]:
    """Score sampled frames by sharpness, face size and exposure; keep the best distinct ones."""
    import cv2

    from .faces import detect
    info = probe(src)
    out_dir.mkdir(parents=True, exist_ok=True)
    w = 480
    h = int(round(w * info.display_size[1] / max(1, info.display_size[0]) / 2) * 2) or 270
    scored = []
    for t in np.linspace(info.duration * 0.03, info.duration * 0.97, samples):
        raw = subprocess.run([ffmpeg(), "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", "-vf", f"scale={w}:{h}",
                              "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True).stdout
        if len(raw) < w * h * 3:
            continue
        img = np.frombuffer(raw[: w * h * 3], dtype=np.uint8).reshape(h, w, 3)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        faces = detect(img)
        face = (faces[0][2] * faces[0][3]) / (w * h) if faces else 0.0
        expo = 1 - abs(float(gray.mean()) / 255 - 0.5) * 2
        score = np.log1p(sharp) * 0.5 + min(face * 12, 2.0) + expo
        scored.append((score, float(t), img))
    scored.sort(key=lambda s: -s[0])
    picked = []
    for score, t, img in scored:
        if all(abs(t - p["t"]) > info.duration / (count * 2) for p in picked):
            path = out_dir / f"frame_{t:07.2f}.jpg"
            subprocess.run([ffmpeg(), "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1", "-q:v", "2",
                            str(path)], capture_output=True)
            picked.append({"t": round(t, 2), "score": round(float(score), 2), "path": str(path)})
        if len(picked) >= count:
            break
    write_json(out_dir / "frames.json", picked)
    return picked


def compose(frame: str | Path, title: str, out_png: Path, *, size: str = "youtube", highlight: list[str] | None = None,
            accent: str = "#FFE14D", emoji: str = "", layout: str = "left") -> Path:
    from .mg import still
    w, h = (1280, 720) if size == "youtube" else (1080, 1920)
    data = {"image": str(Path(frame).resolve()), "title": title, "highlight": highlight or [], "emoji": emoji, "layout": layout,
            "brand": {"accent": accent}}
    return still(mg_dir() / "templates" / "thumbnail.html", out_png, width=w, height=h, t=0.0, data=data)
