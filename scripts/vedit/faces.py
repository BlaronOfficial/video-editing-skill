"""Face detection shared by auto-reframe and thumbnails.

OpenCV 5 removed the Haar cascades; YuNet (cv2.FaceDetectorYN, a small DNN) is more accurate anyway.
Its ~230 KB model is downloaded once into .cache/models. Haar is used only on older OpenCV builds.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from .util import VeditError


def _yunet_model() -> str:
    from . import models
    return str(models.ensure("yunet"))      # 230 KB: below the ask threshold, downloads on first use


@lru_cache(maxsize=4)
def _detector(width: int, height: int):
    import cv2
    if hasattr(cv2, "FaceDetectorYN"):
        det = cv2.FaceDetectorYN.create(_yunet_model(), "", (width, height), score_threshold=0.75, nms_threshold=0.3)
        return "yunet", det
    if hasattr(cv2, "CascadeClassifier"):
        return "haar", cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    raise VeditError("This OpenCV build has no face detector (need FaceDetectorYN or CascadeClassifier).")


def detect(img_bgr: np.ndarray) -> list[tuple[float, float, float, float, float]]:
    """Faces as (x, y, w, h, score) in pixels, largest first."""
    import cv2
    h, w = img_bgr.shape[:2]
    kind, det = _detector(w, h)
    if kind == "yunet":
        _, faces = det.detect(img_bgr)
        out = [(float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[-1])) for f in (faces if faces is not None else [])]
    else:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        out = [(float(x), float(y), float(fw), float(fh), 1.0)
               for x, y, fw, fh in det.detectMultiScale(gray, 1.1, 5, minSize=(w // 20, w // 20))]
    return sorted(out, key=lambda f: -f[2] * f[3])
