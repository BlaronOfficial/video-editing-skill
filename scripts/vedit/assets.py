"""Asset library (user's own b-roll/music/SFX/logos) with search, plus per-project provenance logging.

Every file that enters an edit from outside the camera (library, Pinterest, Higgsfield, CapCut, generated)
gets a provenance record so a copyright claim can be traced and the asset swapped quickly.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .media import AUDIO_EXT, IMAGE_EXT, VIDEO_EXT, extract_frame, probe
from .paths import personal_dir
from .util import VeditError, file_fingerprint, read_json, write_json

KIND_HINTS = {"music": "music", "song": "music", "bgm": "music", "sfx": "sfx", "sound": "sfx", "whoosh": "sfx",
              "broll": "broll", "b-roll": "broll", "b_roll": "broll", "stock": "broll", "logo": "logo", "overlay": "overlay",
              "lut": "lut", "luts": "lut", "font": "font"}


def _index_path() -> Path:
    return personal_dir() / "assets" / "index.json"


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^\wঀ-৿]+", text.lower()) if len(t) > 1]


def _guess_kind(path: Path, kind: str) -> str:
    for part in [p.lower() for p in path.parts[-4:-1]]:
        for hint, k in KIND_HINTS.items():
            if hint in part:
                return k
    ext = path.suffix.lower()
    if ext == ".cube":
        return "lut"
    if ext in AUDIO_EXT:
        return "music" if kind == "video" else "sfx" if probe(path).duration < 6 else "music"
    if ext in IMAGE_EXT:
        return "image"
    return "broll"


def index(folder: str | Path, *, recursive: bool = True) -> dict:
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise VeditError(f"Not a folder: {folder}")
    db = read_json(_index_path(), default={"items": {}, "roots": []}) or {"items": {}, "roots": []}
    thumbs = personal_dir() / "assets" / "thumbs"
    added = 0
    exts = VIDEO_EXT | AUDIO_EXT | IMAGE_EXT | {".cube"}
    for f in (folder.rglob("*") if recursive else folder.glob("*")):
        if not f.is_file() or f.suffix.lower() not in exts:
            continue
        fid = file_fingerprint(f)
        if fid in db["items"]:
            continue
        item = {"id": fid, "path": str(f), "kind": "lut" if f.suffix.lower() == ".cube" else "", "tags": [], "added": time.strftime("%Y-%m-%d")}
        if f.suffix.lower() != ".cube":
            info = probe(f)
            item.update({"kind": _guess_kind(f, info.kind), "duration": round(info.duration, 2), "w": info.width, "h": info.height})
            if info.kind == "video":
                try:
                    item["thumb"] = str(extract_frame(f, info.duration * 0.4, thumbs / f"{fid}.jpg", width=320))
                except Exception:
                    pass
        item["tags"] = sorted(set(_tokens(f.stem) + _tokens(" ".join(f.relative_to(folder).parts[:-1]))))
        db["items"][fid] = item
        added += 1
    if str(folder) not in db["roots"]:
        db["roots"].append(str(folder))
    write_json(_index_path(), db)
    return {"added": added, "total": len(db["items"]), "index": str(_index_path())}


def search(query: str = "", *, kind: str | None = None, min_duration: float = 0, limit: int = 20) -> list[dict]:
    db = read_json(_index_path(), default={"items": {}}) or {"items": {}}
    q = _tokens(query)
    scored = []
    for item in db["items"].values():
        if kind and item.get("kind") != kind:
            continue
        if item.get("duration", 0) < min_duration:
            continue
        if not Path(item["path"]).exists():
            continue
        hay = set(item.get("tags", [])) | set(_tokens(item.get("description", "")))
        score = sum(2 if t in hay else (1 if any(t in h for h in hay) else 0) for t in q) if q else 1
        if score:
            scored.append((score, item))
    scored.sort(key=lambda x: -x[0])
    return [i for _, i in scored[:limit]]


def tag(asset_id: str, tags: list[str], description: str | None = None) -> dict:
    db = read_json(_index_path(), default={"items": {}})
    item = db["items"].get(asset_id)
    if not item:
        raise VeditError(f"Unknown asset id {asset_id}")
    item["tags"] = sorted(set(item.get("tags", [])) | {t.lower() for t in tags})
    if description:
        item["description"] = description
    write_json(_index_path(), db)
    return item


# ------------------------------------------------------------------ provenance

def add_provenance(project_root: Path, file: str | Path, *, source: str, url: str | None = None,
                   license: str | None = None, notes: str = "", credits: float | None = None) -> dict:
    path = project_root / "assets" / "provenance.json"
    log = read_json(path, default=[]) or []
    rec = {"file": str(Path(file).resolve()), "source": source, "url": url, "license": license or "unknown",
           "notes": notes, "added": time.strftime("%Y-%m-%d %H:%M")}
    if credits is not None:
        rec["credits"] = credits
    log = [r for r in log if r["file"] != rec["file"]] + [rec]
    write_json(path, log)
    return rec


def download(url: str, dest_dir: Path, *, name: str | None = None) -> Path:
    import httpx
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = name or re.sub(r"[^\w.\-]+", "_", url.split("?")[0].rstrip("/").split("/")[-1]) or f"asset_{int(time.time())}"
    out = dest_dir / fname
    with httpx.stream("GET", url, follow_redirects=True, timeout=120,
                      headers={"User-Agent": "Mozilla/5.0 (video-editing-skill)"}) as r:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "." not in fname:
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
                   "video/mp4": ".mp4", "audio/mpeg": ".mp3"}.get(ctype.split(";")[0], "")
            out = out.with_suffix(ext)
        with open(out, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    return out
