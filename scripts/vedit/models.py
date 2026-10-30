"""Optional model downloads: registry, ask-first policy, resumable fetches.

The owner's connection can be slow (~1 MB/s), and a 1 GB model that silently starts downloading
mid-edit is a bad surprise. So `ensure(id)` raises NeedsDownload (size, ETA, licence, purpose) unless the
model is small or the policy allows it; Claude asks, then runs `vedit models get <id>`. Downloads resume
from a `.part` file (HTTP Range), so a dropped connection never restarts from zero.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import config
from .paths import cache_dir, personal_dir
from .util import VeditError, read_json, write_json

AUTO_MB = 5.0          # models up to this size download without asking


@dataclass
class Model:
    id: str
    url: str
    size_mb: float
    licence: str
    used_for: str
    dest: str                      # relative to .cache/models/
    sha256: str | None = None
    archive: str | None = None     # None | "tar.bz2" | "tar.gz" | "zip"
    extracted: str | None = None   # path (relative to .cache/models/) that must exist after extraction
    commercial_ok: bool = True


MODELS: dict[str, Model] = {m.id: m for m in [
    Model("yunet", "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
          0.23, "MIT (opencv_zoo)", "face detection for reframe, thumbnails, tracking",
          "face_detection_yunet_2023mar.onnx"),
    Model("speaker_seg", "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/"
          "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2", 7.0, "MIT (pyannote segmentation 3.0, sherpa-onnx export)",
          "who speaks when: speech turns", "speakers/pyannote-seg-3-0.tar.bz2", archive="tar.bz2",
          extracted="speakers/sherpa-onnx-pyannote-segmentation-3-0/model.onnx"),
    Model("speaker_emb", "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
          "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx", 39.6, "Apache-2.0 (3D-Speaker)",
          "who speaks when: voice fingerprints", "speakers/3dspeaker_eres2net_base_16k.onnx"),
]}


class NeedsDownload(VeditError):
    """Raised when a feature needs a model the owner has not agreed to download yet."""

    def __init__(self, info: dict):
        self.info = info
        super().__init__(json.dumps({"needs_download": info}, ensure_ascii=False))


def register(model: Model) -> None:
    """Later modules (speakers, matting, depth, voices) add their models here."""
    MODELS[model.id] = model


def models_dir() -> Path:
    path = cache_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def path_of(model_id: str) -> Path:
    m = _get(model_id)
    return models_dir() / (m.extracted or m.dest)


def _get(model_id: str) -> Model:
    if model_id not in MODELS:
        raise VeditError(f"Unknown model '{model_id}'. Known: {', '.join(sorted(MODELS))}")
    return MODELS[model_id]


def is_ready(model_id: str) -> bool:
    p = path_of(model_id)
    return p.exists() and (p.is_dir() or p.stat().st_size > 0)


def bandwidth_mbps() -> float | None:
    """Measured download speed (megabytes per second) from recent downloads, if any."""
    stats = read_json(personal_dir() / "net.json", default={}) or {}
    return stats.get("mbps")


def _record_speed(nbytes: int, seconds: float) -> None:
    if nbytes < 2_000_000 or seconds <= 0:
        return
    path = personal_dir() / "net.json"
    stats = read_json(path, default={}) or {}
    mbps = nbytes / 1e6 / seconds
    stats["mbps"] = round(mbps if "mbps" not in stats else 0.6 * stats["mbps"] + 0.4 * mbps, 3)
    stats["measured"] = time.strftime("%Y-%m-%d %H:%M")
    write_json(path, stats)


def info(model_id: str) -> dict:
    m = _get(model_id)
    speed = bandwidth_mbps()
    part = models_dir() / (m.dest + ".part")
    have = part.stat().st_size / 1e6 if part.exists() else 0.0
    eta = round((m.size_mb - have) / speed / 60, 1) if speed else None
    return {"id": m.id, "size_mb": m.size_mb, "already_mb": round(have, 1), "eta_min": eta, "licence": m.licence,
            "commercial_ok": m.commercial_ok, "why": m.used_for, "ready": is_ready(model_id),
            "command": f"vedit models get {m.id}"}


def ensure(model_id: str, *, allow: bool = False) -> Path:
    """Path of a ready model; downloads small ones, otherwise raises NeedsDownload for Claude to ask."""
    if is_ready(model_id):
        return path_of(model_id)
    m = _get(model_id)
    policy = config.load().get("models", {}).get("policy", "ask")
    if allow or m.size_mb <= AUTO_MB or policy == "auto":
        return download(model_id)
    raise NeedsDownload(info(model_id))


def download(model_id: str, *, progress: bool = True) -> Path:
    """Resumable download (HTTP Range) with optional sha256 check and archive extraction."""
    import httpx
    m = _get(model_id)
    final = models_dir() / m.dest
    final.parent.mkdir(parents=True, exist_ok=True)
    part = final.with_name(final.name + ".part")
    done = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    t0, got, last_print = time.time(), 0, 0.0
    try:
        with httpx.stream("GET", m.url, headers=headers, follow_redirects=True, timeout=httpx.Timeout(60, read=120)) as r:
            if r.status_code == 416:            # already complete
                pass
            elif r.status_code not in (200, 206):
                raise VeditError(f"Download of {m.id} failed: HTTP {r.status_code}")
            else:
                mode = "ab" if r.status_code == 206 else "wb"
                if mode == "wb":
                    done = 0
                total = int(r.headers.get("content-length", 0)) + done
                with open(part, mode) as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
                        got += len(chunk)
                        if progress and time.time() - last_print > 5:
                            last_print = time.time()
                            pct = f"{100 * (done + got) / total:.0f}%" if total else f"{(done + got) / 1e6:.0f} MB"
                            print(f"  {m.id}: {pct}", flush=True)
    except httpx.HTTPError as exc:
        raise VeditError(f"Download of {m.id} interrupted ({exc}). Run `vedit models get {m.id}` again: it resumes.") from exc
    _record_speed(got, time.time() - t0)
    if m.sha256:
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        if h.hexdigest() != m.sha256:
            part.unlink(missing_ok=True)
            raise VeditError(f"Checksum mismatch for {m.id}; the partial file was removed. Retry the download.")
    part.replace(final)
    if m.archive:
        _extract(final, m.archive, final.parent)
        final.unlink(missing_ok=True)
    return path_of(model_id)


def _extract(archive: Path, kind: str, dest: Path) -> None:
    if kind == "zip":
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                target = (dest / name).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    raise VeditError(f"Unsafe path in archive: {name}")
            z.extractall(dest)
        return
    mode = {"tar.bz2": "r:bz2", "tar.gz": "r:gz"}[kind]
    with tarfile.open(archive, mode) as tf:
        try:
            tf.extractall(dest, filter="data")
        except TypeError:
            tf.extractall(dest)


def status_all() -> list[dict]:
    return [info(mid) for mid in sorted(MODELS)]


# ------------------------------------------------------------------ CLI

def register_cli(sp) -> None:
    s = sp.add_parser("models", help="optional model downloads (asks first, resumable)")
    s.add_argument("action", choices=["list", "status", "get"])
    s.add_argument("id", nargs="?")
    s.set_defaults(fn=_cmd)


def _cmd(a) -> None:
    from .util import print_json
    if a.action == "list":
        print_json(status_all())
    elif a.action == "status":
        print_json(info(a.id))
    else:
        path = download(a.id)
        print_json({"id": a.id, "path": str(path), "ready": is_ready(a.id)})
