"""Person matting for video (MODNet) and cut-outs for stills (MODNet for people, BiRefNet for objects).

MODNet (Apache-2.0, ~26 MB) runs per frame on the CPU at ~512 px, then:
  * a guided filter against the full-resolution frame snaps the soft mask to real edges (hair, fingers);
  * temporal smoothing blends each pixel with the previous mask where the picture did not move, which
    removes most frame-to-frame shimmer without lagging behind motion.
Masks are cached as gray FFV1 layers for exactly the frames a clip decodes.
"""

from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from .. import models
from ..footage import input_chain
from ..util import VeditError
from . import frames

models.register(models.Model(
    "modnet", "https://huggingface.co/Xenova/modnet/resolve/main/onnx/model.onnx", 25.9,
    "Apache-2.0 (MODNet, ZHKKKe; ONNX export by Xenova)", "person cut-outs: text behind people, background blur/swap",
    "matte/modnet.onnx"))
models.register(models.Model(
    "birefnet_lite", "https://huggingface.co/onnx-community/BiRefNet_lite-ONNX/resolve/main/onnx/model.onnx", 224.0,
    "MIT (BiRefNet, ZhengPeng7; ONNX export by onnx-community)", "best object / product cut-outs for stills",
    "matte/birefnet_lite.onnx"))

MATTE_SIDE = 1280        # mask layer resolution (long side); scaled to the source in the graph


def ort_threads() -> int:
    """Intra-op threads for CPU inference. More is not faster on hybrid CPUs: MODNet at 512 px measured
    409 ms with the default, 250 ms with 8, 1115 ms with all 18 logical cores. VEDIT_ORT_THREADS overrides."""
    import os
    env = os.environ.get("VEDIT_ORT_THREADS")
    if env and env.isdigit():
        return max(1, int(env))
    return max(1, min(8, (os.cpu_count() or 4) // 2))


def session(path: str):
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.intra_op_num_threads = ort_threads()
    return ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])


@lru_cache(maxsize=4)
def _session(model_id: str):
    return session(str(models.ensure(model_id)))


def guided_filter(guide: np.ndarray, src: np.ndarray, r: int = 8, eps: float = 1e-3, s: int = 0) -> np.ndarray:
    """He et al. guided filter (gray guide), float32 in/out. `s` subsamples the coefficient pass (fast guided
    filter): s=0 picks 2 above 900 px, which is ~4x faster with no visible change on mattes."""
    import cv2
    I = guide.astype(np.float32) / 255.0 if guide.dtype == np.uint8 else guide
    p = src.astype(np.float32)
    s = s or (2 if max(I.shape) > 900 else 1)
    if s > 1:
        Is = cv2.resize(I, None, fx=1 / s, fy=1 / s, interpolation=cv2.INTER_AREA)
        ps = cv2.resize(p, (Is.shape[1], Is.shape[0]), interpolation=cv2.INTER_AREA)
        r = max(1, r // s)
    else:
        Is, ps = I, p
    k = (2 * r + 1, 2 * r + 1)
    mI, mp = cv2.boxFilter(Is, -1, k), cv2.boxFilter(ps, -1, k)
    cov = cv2.boxFilter(Is * ps, -1, k) - mI * mp
    var = cv2.boxFilter(Is * Is, -1, k) - mI * mI
    a = cov / (var + eps)
    b = mp - a * mI
    ma, mb = cv2.boxFilter(a, -1, k), cv2.boxFilter(b, -1, k)
    if s > 1:
        ma = cv2.resize(ma, (I.shape[1], I.shape[0]), interpolation=cv2.INTER_LINEAR)
        mb = cv2.resize(mb, (I.shape[1], I.shape[0]), interpolation=cv2.INTER_LINEAR)
    return ma * I + mb


def modnet(img_bgr: np.ndarray, *, ref: int = 512) -> np.ndarray:
    """Alpha (float32 0..1, image size) for the people in a frame."""
    import cv2
    h, w = img_bgr.shape[:2]
    sc = ref / max(h, w) if max(h, w) > ref else ref / min(h, w) if min(h, w) < ref / 2 else 1.0
    rh, rw = max(32, int(h * sc) // 32 * 32), max(32, int(w * sc) // 32 * 32)
    x = cv2.resize(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB), (rw, rh), interpolation=cv2.INTER_AREA).astype(np.float32)
    x = ((x / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[None]
    sess = _session("modnet")
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0]
    a = np.squeeze(out).astype(np.float32)
    return np.clip(cv2.resize(a, (w, h), interpolation=cv2.INTER_LINEAR), 0, 1)


def birefnet(img_bgr: np.ndarray, *, size: int = 1024) -> np.ndarray:
    import cv2
    h, w = img_bgr.shape[:2]
    x = cv2.resize(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB), (size, size), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    x = ((x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)).transpose(2, 0, 1)[None]
    sess = _session("birefnet_lite")
    out = np.squeeze(sess.run(None, {sess.get_inputs()[0].name: x})[-1]).astype(np.float32)
    if out.min() < 0 or out.max() > 1:
        out = 1 / (1 + np.exp(-out))
    return np.clip(cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR), 0, 1)


def cutout(image: str, out: str | Path, *, model: str = "auto", refine: bool = True) -> dict:
    """Transparent PNG of the subject. model: auto (people -> modnet, else birefnet if downloaded, else modnet),
    modnet, birefnet."""
    import cv2
    from .. import faces
    img = frames.read_image(image)
    bgr = img[..., :3]
    if model == "auto":
        has_face = bool(faces.detect(bgr if max(bgr.shape[:2]) <= 1600 else cv2.resize(bgr, None, fx=0.5, fy=0.5)))
        model = "modnet" if has_face or not models.is_ready("birefnet_lite") else "birefnet"
    a = modnet(bgr) if model == "modnet" else birefnet(bgr)
    if refine:
        a = np.clip(guided_filter(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), a, r=max(4, min(bgr.shape[:2]) // 200)), 0, 1)
    rgba = np.dstack([bgr, (a * 255).astype(np.uint8)])
    frames.write_image(Path(out).with_suffix(".png"), rgba)
    return {"output": str(Path(out).with_suffix(".png")), "model": model, "coverage": round(float(a.mean()), 3)}


def mask_layer(src_path: str, src_color, out: Path, *, ss: float, t: float, work: Path | None = None,
               temporal: float = 0.6, progress: bool = True) -> Path:
    """Gray FFV1 layer of the person matte for [ss, ss+t] (decode timing, MATTE_SIDE resolution)."""
    import cv2
    spec = frames.spec_for(src_path, max_side=MATTE_SIDE)
    chain = input_chain(SimpleNamespace(color=src_color, lut=None))
    prev_a, prev_g = None, None
    started, n = time.time(), 0
    with frames.Writer(out, spec.width, spec.height, spec.fps, "gray") as wr:
        for fr in frames.read(src_path, ss=ss, t=t, spec=spec, chain=chain, cwd=work):
            g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            a = modnet(fr)
            a = np.clip(guided_filter(g, a, r=6, eps=2e-3), 0, 1)
            if prev_a is not None and temporal > 0:
                still = np.clip(1 - np.abs(g.astype(np.float32) - prev_g) / 12.0, 0, 1)
                still = cv2.GaussianBlur(still, (0, 0), 3)
                a = a * (1 - temporal * still) + prev_a * (temporal * still)
            prev_a, prev_g = a, g.astype(np.float32)
            wr.write((a * 255 + 0.5).astype(np.uint8))
            n += 1
            if progress and n % 60 == 0:
                print(f"  matte: {n} frames ({n / max(1e-3, time.time() - started):.1f} fps)", flush=True)
    if n == 0:
        raise VeditError(f"No frames decoded from {src_path} at {ss:.2f}s")
    return out
