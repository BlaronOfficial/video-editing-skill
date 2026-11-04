"""Studio: the engine side of the Artifact Studio (the plan-mode mini editor).

One pinned Studio artifact per owner shows every project. This module prepares what it needs and
applies what the owner does in it. The Artifact itself is published by Claude with the Artifact tool,
data goes in with ArtifactData, the owner's edits come back as op documents.

  vedit studio build <p>      proxies (480p, keyframe every 0.5 s, <= 18 MB chunks), waveform peaks,
                              filmstrip sprites, audio/still previews  ->  edit/studio/ + upload list
  vedit studio register <p>   record asset URLs returned by the Artifact upload (path=url pairs or --map)
  vedit studio docs <p>       database documents (projects/<id>/docs/*) + ready-made ArtifactData batches
  vedit studio apply <p>      apply op documents the Studio wrote (read with ArtifactData list + out_dir)
  vedit studio status <p>     what is built, uploaded and pending

Database layout (collections are odd paths):
  projects/<pid>                     project card (name, revision, status, duration, thumb)
  projects/<pid>/docs/<doc>          meta, edit, words_<sid>_<n>, media, library, suggestions, directions,
                                     comp_<overlay>, tpl_<name>
  projects/<pid>/ops/<op>            owner's operations, written by the page, deleted after apply
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path

from . import config
from .media import ffmpeg, probe
from .paths import SKILL_ROOT, mg_dir, personal_dir
from .project import Project
from .util import VeditError, read_json, run, short_hash, write_json

DOC_LIMIT = 200_000                 # bytes per database document (hard cap 256 KiB)
BATCH_BYTES = 900_000               # ArtifactData batch body cap is 1 MiB
WORDS_PER_DOC = 2500
APP_DIR = SKILL_ROOT / "studio"
CAPABILITIES = {"db": {}, "assets": {}, "comments": {}, "sample": {}, "user": {}}
# Declare the live link only from a session that has vedit's MCP server connected (tools named mcp__vedit__*):
# the page then calls it as host:vedit when opened in the Claude desktop app with that server configured.
LIVE_LINK = {"mcp": {"servers": [{"server": "host:vedit",
                                  "tools": ["studio_apply", "studio_state", "proxy_build", "sfx_preview"]}]}}


# ------------------------------------------------------------------ identity + state

def project_id(p: Project) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", p.edit().name)[:40].strip("_") or "project"
    return f"{name}-{short_hash(str(p.root.resolve()), length=6)}"


def _state_path() -> Path:
    return personal_dir() / "studio.json"


def owner_state() -> dict:
    st = read_json(_state_path(), default={}) or {}
    st.setdefault("projects", {})
    return st


def save_owner_state(st: dict) -> None:
    write_json(_state_path(), st)


def _bundle(p: Project) -> Path:
    return p.sub("studio")


def _uploaded(p: Project) -> dict:
    return read_json(_bundle(p) / "uploaded.json", default={}) or {}


def _file_hash(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


# ------------------------------------------------------------------ media previews

FULL_PROXY_MAX = 600.0      # sources up to 10 min get a full proxy; longer ones only around the kept parts
RANGE_MARGIN = 60.0


def _proxy_ranges(edit, sid: str, duration: float) -> list[tuple[float, float]] | None:
    if duration <= FULL_PROXY_MAX:
        return None
    spans = sorted((max(0.0, c.src_in - RANGE_MARGIN), min(duration, c.src_out + RANGE_MARGIN))
                   for c in [*edit.main, *edit.broll] if c.source == sid)
    merged: list[list[float]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(round(s, 3), round(e, 3)) for s, e in merged] or [(0.0, min(duration, FULL_PROXY_MAX))]


def _proxy(src_path: str, out_dir: Path, sid: str, ranges: list[tuple[float, float]] | None = None,
           pre: list[str] | None = None) -> list[dict]:
    """480p H.264 chunks small enough for the 20 MiB asset cap, with exact source start times per chunk."""
    cfg = config.load()["studio"]
    info = probe(src_path)
    size, kbps = int(cfg["proxy_size"]), int(cfg["proxy_kbps"])
    worst_kbps = kbps * 1.5 + 96
    seg = max(20, int(cfg["chunk_mb"] * 8e6 / (worst_kbps * 1000)))
    fps = min(30.0, info.fps or 30.0)
    gop = max(1, int(round(fps / 2)))
    st = Path(src_path).stat()
    chunks = []
    for r, (r0, r1) in enumerate(ranges or [(0.0, info.duration)]):
        key = short_hash(Path(src_path).name, st.st_size, int(st.st_mtime), size, kbps, seg, r0, r1, pre or [])
        listing = out_dir / f"{sid}_{key}.csv"
        if not listing.exists():
            w, h = info.display_size
            scale = f"scale='if(gte(iw,ih),{size},-2)':'if(gte(iw,ih),-2,{size})'" if w and h else f"scale={size}:-2"
            args = [ffmpeg(), "-y", "-v", "error"]
            if ranges:
                args += ["-ss", f"{r0:.3f}", "-t", f"{r1 - r0:.3f}"]
            args += ["-i", src_path, "-map", "0:v:0"]
            if info.has_audio:
                args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "96k", "-ac", "2"]
            args += ["-vf", ",".join([*(pre or []), scale, f"fps={fps}"]), "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "main",
                     "-pix_fmt", "yuv420p", "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
                     "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.5)}k", "-bufsize", f"{kbps * 2}k",
                     "-f", "segment", "-segment_time", str(seg), "-reset_timestamps", "1",
                     "-segment_format_options", "movflags=+faststart", "-segment_list", str(listing),
                     "-segment_list_type", "csv", str(out_dir / f"{sid}_{key}_%03d.mp4")]
            run(args, timeout=7200, cwd=out_dir)
        for line in listing.read_text(encoding="utf-8").splitlines():
            name, start, end = line.rsplit(",", 2)
            f = out_dir / name
            if f.stat().st_size > 20 * 1024 * 1024:
                raise VeditError(f"Proxy chunk {f.name} exceeds 20 MiB; lower studio.proxy_kbps or chunk_mb.")
            chunks.append({"file": str(f), "start": round(r0 + float(start), 3),
                           "duration": round(float(end) - float(start), 3)})
    return chunks


def _peaks(src_path: str, out: Path, rate: int = 50) -> Path:
    """Waveform peaks, `rate` per second, 0..127, as a JSON asset."""
    if out.exists():
        return out
    import subprocess

    import numpy as np
    proc = subprocess.run([ffmpeg(), "-v", "error", "-i", src_path, "-map", "0:a:0", "-ac", "1", "-ar", "8000",
                           "-f", "s16le", "-"], capture_output=True)
    data = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    step = 8000 // rate
    n = len(data) // step
    peaks = np.abs(data[: n * step]).reshape(n, step).max(axis=1) if n else np.zeros(0)
    vals = np.clip(np.sqrt(peaks) * 127, 0, 127).astype(int).tolist()     # sqrt: quiet speech stays visible
    write_json(out, {"rate": rate, "peaks": vals}, indent=None)
    return out


def _sprites(src_path: str, out_dir: Path, sid: str, every: float = 2.0, height: int = 90) -> list[dict]:
    info = probe(src_path)
    key = short_hash(Path(src_path).name, Path(src_path).stat().st_size, every, height)
    pattern = out_dir / f"{sid}_{key}_%03d.jpg"
    first = out_dir / f"{sid}_{key}_001.jpg"
    cols, rows = 10, 10
    if not first.exists():
        run([ffmpeg(), "-y", "-v", "error", "-i", src_path, "-vf",
             f"fps=1/{every},scale=-2:{height},tile={cols}x{rows}", "-q:v", "5", str(pattern)], timeout=3600)
    w, h = info.display_size
    tile_w = int(round(height * (w / h) / 2) * 2) if w and h else 160
    sheets = sorted(out_dir.glob(f"{sid}_{key}_*.jpg"))
    total = int(math.ceil((info.duration or 0) / every))
    return [{"file": str(f), "start": i * cols * rows * every, "interval": every, "tile_w": tile_w, "tile_h": height,
             "cols": cols, "rows": rows, "count": min(cols * rows, max(0, total - i * cols * rows))}
            for i, f in enumerate(sheets)]


def _audio_preview(src_path: str, out: Path) -> Path:
    """AAC in an audio-only .mp4: the artifact asset store takes mp4/webm, not mp3, and every browser decodes it."""
    if not out.exists():
        run([ffmpeg(), "-y", "-v", "error", "-i", src_path, "-vn", "-ac", "2", "-ar", "44100", "-c:a", "aac",
             "-b:a", "128k", "-movflags", "+faststart", str(out)])
    return out


def _still(src_path: str, out: Path) -> Path:
    if not out.exists():
        run([ffmpeg(), "-y", "-v", "error", "-i", src_path, "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(out)])
    return out


def _web_preview(path: Path, out_dir: Path) -> Path:
    """Images and WebM play in the browser as they are; anything else (ProRes 4444, GIF...) -> VP9 WebM with alpha."""
    if path.suffix.lower() in (".webm", ".png", ".jpg", ".jpeg", ".webp", ".svg"):
        return path
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{path.stem}_{short_hash(path.name, path.stat().st_size, int(path.stat().st_mtime))}.webm"
    if not out.exists():
        run([ffmpeg(), "-y", "-v", "error", "-i", str(path), "-vf", "scale='min(720,iw)':-2", "-c:v", "libvpx-vp9",
             "-pix_fmt", "yuva420p", "-b:v", "1M", "-deadline", "realtime", "-cpu-used", "8", "-an", str(out)], timeout=3600)
    return out


def _sources_needed(edit) -> list[str]:
    used = {c.source for c in [*edit.main, *edit.broll]} | {a.source for a in edit.audio}
    used |= {sid for sid, s in edit.sources.items() if s.transcript}
    return [sid for sid in edit.sources if sid in used]


def build(p: Project, *, only: list[str] | None = None) -> dict:
    """Make every preview the Studio needs and report which files still have to be uploaded."""
    edit = p.edit()
    root = _bundle(p)
    media: dict[str, dict] = {}
    for sid in _sources_needed(edit):
        if only and sid not in only:
            continue
        src = edit.sources[sid]
        if not Path(src.path).exists():
            media[sid] = {"kind": src.kind, "missing": True}
            continue
        entry: dict = {"kind": src.kind, "duration": src.duration, "width": src.width, "height": src.height,
                       "fps": src.fps, "has_audio": src.has_audio}
        if src.kind == "video":
            (root / "proxies").mkdir(parents=True, exist_ok=True)
            (root / "sprites").mkdir(parents=True, exist_ok=True)
            ranges = _proxy_ranges(edit, sid, src.duration or probe(src.path).duration)
            from .footage import input_chain
            entry["proxy"] = _proxy(src.path, root / "proxies", sid, ranges,
                                    pre=input_chain(src, lut_dir=root / "proxies"))   # HDR/Log/interlaced look right
            if ranges:
                entry["proxy_ranges"] = ranges          # restoring words outside these needs a rebuild
            entry["sprites"] = _sprites(src.path, root / "sprites", sid)
        elif src.kind == "audio":
            (root / "audio").mkdir(parents=True, exist_ok=True)
            entry["audio"] = {"file": str(_audio_preview(src.path, root / "audio" / f"{sid}.mp4"))}
        elif src.kind == "image":
            (root / "stills").mkdir(parents=True, exist_ok=True)
            entry["still"] = {"file": str(_still(src.path, root / "stills" / f"{sid}.jpg"))}
        if src.kind == "video" and src.has_audio:          # the waveform is drawn on picture clips
            (root / "peaks").mkdir(parents=True, exist_ok=True)
            entry["peaks"] = {"file": str(_peaks(src.path, root / "peaks" / f"{sid}.json"))}
        media[sid] = entry
    # Rendered overlays that are not live HTML (images, gifs, custom FX output, animated pieces too big for a
    # database document) need a preview file too.
    overlays = {}
    for ov in edit.overlays:
        if ov.path and Path(ov.path).exists() and not _live_html(p, ov):
            overlays[ov.id] = {"file": str(_web_preview(Path(ov.path), root / "overlays"))}
    write_json(root / "media.local.json", {"sources": media, "overlays": overlays})
    pending = pending_uploads(p)
    return {"project_id": project_id(p), "bundle": str(root), "sources": list(media),
            "uploads": pending, "upload_mb": round(sum(u["bytes"] for u in pending) / 1e6, 1),
            "next": "Upload each file with the Artifact tool (url=<studio>, asset: true, file_paths: [...] up to 25), "
                    "then `vedit studio register <p> --map <json {path: url}>`, then `vedit studio docs <p>`."}


def _media_files(p: Project) -> list[tuple[str, str]]:
    local = read_json(_bundle(p) / "media.local.json", default={}) or {}
    out = []
    for sid, m in (local.get("sources") or {}).items():
        for c in m.get("proxy", []):
            out.append(("proxy", c["file"]))
        for s in m.get("sprites", []):
            out.append(("sprite", s["file"]))
        for k in ("audio", "still", "peaks"):
            if m.get(k):
                out.append((k, m[k]["file"]))
    for oid, o in (local.get("overlays") or {}).items():
        out.append(("overlay", o["file"]))
    return out


def pending_uploads(p: Project) -> list[dict]:
    up = _uploaded(p)
    rows = []
    for kind, f in _media_files(p):
        path = Path(f)
        if not path.exists():
            continue
        if path.stat().st_size > 20 * 1024 * 1024:
            raise VeditError(f"{path.name} is over the 20 MiB asset cap.")
        if _file_hash(path) not in up:
            rows.append({"kind": kind, "file": str(path), "bytes": path.stat().st_size})
    return rows


def register(p: Project, mapping: dict[str, str]) -> dict:
    """Record the URLs the Artifact tool returned for uploaded files (keyed by content hash)."""
    up = _uploaded(p)
    for local, url in mapping.items():
        path = Path(local)
        if not path.exists():
            raise VeditError(f"Not a local file: {local}")
        up[_file_hash(path)] = {"url": url, "file": path.name, "at": time.strftime("%Y-%m-%d %H:%M")}
    write_json(_bundle(p) / "uploaded.json", up)
    return {"registered": len(mapping), "still_pending": len(pending_uploads(p))}


def _url(p: Project, local: str, up: dict | None = None) -> str | None:
    up = up if up is not None else _uploaded(p)
    path = Path(local)
    if not path.exists():
        return None
    rec = up.get(_file_hash(path))
    return rec["url"] if rec else None


# ------------------------------------------------------------------ documents

def _library(edit) -> dict:
    from .captions import list_presets, resolve_style
    from .knobs import definitions
    from .mg import templates
    from .render import GRADES
    from .styles import brand_mg_data, load_brand
    styles = {}
    for name in list_presets():
        try:
            styles[name] = resolve_style(name)
        except Exception:
            continue
    brand = None
    if edit.brand:
        try:
            brand = brand_mg_data(load_brand(edit.brand))
        except Exception:
            brand = None
    return {"caption_styles": styles, "templates": templates(), "grades": sorted(GRADES), "knobs": definitions(),
            "brand": brand}


def _words_docs(edit) -> dict[str, dict]:
    from .captions import transcript_words, word_key
    docs = {}
    for sid, src in edit.sources.items():
        if not src.transcript or not Path(src.transcript).exists():
            continue
        from .pack import HARD_FILLERS, _norm
        words = transcript_words(src.transcript)
        rows = [[round(w["s"], 3), round(w["e"], 3), w["w"].strip(),
                 ("f" if _norm(w["w"]) in HARD_FILLERS else "") + ("?" if w.get("p", 1) < 0.45 else ""),
                 word_key(sid, w["s"])] for w in words]
        for n in range(0, max(1, len(rows)), WORDS_PER_DOC):
            docs[f"words_{sid}_{n // WORDS_PER_DOC}"] = {"source": sid, "part": n // WORDS_PER_DOC,
                                                         "words": rows[n:n + WORDS_PER_DOC]}
    return docs


def _is_piece(ov) -> bool:
    """An animated piece (vedit anim): edit/anim/<piece>/index.html."""
    return bool(ov.mg and ov.mg.file and Path(ov.mg.file).parent.parent.name == "anim")


def _live_html(p: Project, ov) -> bool:
    """Does this overlay play live in the Studio (as HTML), or from its rendered file?"""
    if not ov.mg:
        return False
    if ov.mg.template:
        return True
    if not (ov.mg.file or "").endswith(".html"):
        return False
    if _is_piece(ov):   # pieces embed the owner's screenshots: too big for one database document -> rendered proxy
        f = Path(ov.mg.file)
        f = f if f.is_absolute() else p.root / f
        doc = {"overlay": ov.id, "html": f.read_text(encoding="utf-8")} if f.exists() else {}
        return bool(doc) and len(json.dumps(doc, ensure_ascii=False).encode("utf-8")) <= DOC_LIMIT
    return True


def _comp_docs(p: Project, edit) -> dict[str, dict]:
    """Project-specific compositions and personal templates travel as HTML text in the database."""
    docs = {}
    personal_tpl = personal_dir() / "templates"
    for ov in edit.overlays:
        if not ov.mg:
            continue
        if ov.mg.file and ov.mg.file.endswith(".html"):
            if _is_piece(ov) and not _live_html(p, ov):
                continue                       # played from its rendered video (see the overlays previews)
            f = Path(ov.mg.file)
            f = f if f.is_absolute() else p.root / f
            if f.exists():
                docs[f"comp_{ov.id}"] = {"overlay": ov.id, "html": f.read_text(encoding="utf-8")}
        elif ov.mg.template and (personal_tpl / f"{ov.mg.template}.html").exists():
            docs[f"tpl_{ov.mg.template}"] = {"template": ov.mg.template,
                                             "html": (personal_tpl / f"{ov.mg.template}.html").read_text(encoding="utf-8")}
    for name, doc in docs.items():
        if len(json.dumps(doc, ensure_ascii=False).encode("utf-8")) > DOC_LIMIT:
            raise VeditError(f"{name}: composition HTML is over 200 KB; move big data (images) into assets.")
    return docs


def _edit_docs(edit) -> dict[str, dict]:
    d = edit.model_dump(mode="json", exclude_none=True)
    if edit.captions.from_words:
        d.get("captions", {}).pop("chunks", None)     # the Studio rebuilds chunks from words, like bake()
    docs = {"edit": d}
    if len(json.dumps(d, ensure_ascii=False).encode("utf-8")) > DOC_LIMIT:
        for key in ("main", "broll", "overlays", "texts", "audio", "effects", "custom_fx", "sources"):
            if key in d:
                docs[f"edit_{key}"] = {"items": d.pop(key)}
        d["_split"] = True
    return docs


def documents(p: Project) -> dict[str, dict]:
    from . import modes
    from .knobs import bake
    from .suggest import load_directions, load_suggestions
    edit = p.edit()
    up = _uploaded(p)
    local = read_json(_bundle(p) / "media.local.json", default={}) or {}
    media: dict = {"sources": {}, "overlays": {}}
    for sid, m in (local.get("sources") or {}).items():
        out = {k: v for k, v in m.items() if k not in ("proxy", "sprites", "audio", "still", "peaks")}
        out["proxy"] = [{"url": _url(p, c["file"], up), "start": c["start"], "duration": c["duration"]}
                        for c in m.get("proxy", [])]
        out["sprites"] = [{**{k: v for k, v in s.items() if k != "file"}, "url": _url(p, s["file"], up)}
                          for s in m.get("sprites", [])]
        for k in ("audio", "still", "peaks"):
            if m.get(k):
                out[k] = _url(p, m[k]["file"], up)
        media["sources"][sid] = out
    for oid, o in (local.get("overlays") or {}).items():
        media["overlays"][oid] = _url(p, o["file"], up)
    baked = bake(edit)
    wf = modes.state(p)
    meta = {"id": project_id(p), "name": edit.name, "canvas": edit.canvas.model_dump(mode="json"),
            "duration": round(baked.duration, 3), "revision": edit.revision, "mode": wf["mode"],
            "plan_status": wf["plan_status"], "stage": wf["stage"], "approved_stages": wf["approved_stages"],
            "updated": time.strftime("%Y-%m-%d %H:%M"), "style": edit.style, "brand": edit.brand,
            "root": str(p.root)}
    docs = {"meta": meta, **_edit_docs(edit), **_words_docs(edit), "media": media, "library": _library(edit),
            "suggestions": load_suggestions(p), "directions": load_directions(p), **_comp_docs(p, edit)}
    for name, doc in docs.items():
        size = len(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
        if size > DOC_LIMIT:
            raise VeditError(f"Document {name} is {size // 1000} KB (> 200 KB). Split it before syncing.")
    return docs


def write_documents(p: Project, *, only: list[str] | None = None) -> dict:
    pid = project_id(p)
    out_dir = _bundle(p) / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    docs = documents(p)
    if only:
        docs = {k: v for k, v in docs.items() if k in only or any(k.startswith(o + "_") for o in only)}
    writes = []
    for name, doc in docs.items():
        f = out_dir / f"{name}.json"
        write_json(f, doc, indent=None)
        writes.append({"op": "set", "collection": f"projects/{pid}/docs", "doc_id": name, "file_path": str(f),
                       "bytes": f.stat().st_size})
    card = out_dir / "_card.json"
    meta = docs.get("meta") or documents(p)["meta"]
    write_json(card, {**meta, "thumb": _thumb_url(p)}, indent=None)
    writes.insert(0, {"op": "set", "collection": "projects", "doc_id": pid, "file_path": str(card),
                      "bytes": card.stat().st_size})
    batches, cur, size = [], [], 0
    for w in writes:
        if cur and (len(cur) >= 50 or size + w["bytes"] > BATCH_BYTES):
            batches.append(cur)
            cur, size = [], 0
        cur.append({k: v for k, v in w.items() if k != "bytes"})
        size += w["bytes"]
    if cur:
        batches.append(cur)
    st = owner_state()
    st["projects"][pid] = {"name": p.edit().name, "root": str(p.root), "synced": time.strftime("%Y-%m-%d %H:%M")}
    save_owner_state(st)
    return {"project_id": pid, "artifact_url": st.get("url"), "batches": batches,
            "note": "Existing documents need if_version: list projects/<pid>/docs first and pin each write."}


def _thumb_url(p: Project) -> str | None:
    local = read_json(_bundle(p) / "media.local.json", default={}) or {}
    for m in (local.get("sources") or {}).values():
        for s in m.get("sprites", []):
            return _url(p, s["file"])
    return None


# ------------------------------------------------------------------ the app itself

def studio_base_css() -> Path:
    """mg/lib/base.css without its @font-face rules: in the Studio the same families come from Google Fonts,
    and a failing @font-face (the renderer's /__fonts/ path) would otherwise win and fall back to a wrong face."""
    import re as _re
    from .paths import cache_dir
    src = (mg_dir() / "lib" / "base.css").read_text(encoding="utf-8")
    out = cache_dir() / "studio" / "base.css"
    out.parent.mkdir(parents=True, exist_ok=True)
    stripped = _re.sub(r"@font-face\s*\{[^}]*\}\s*", "", src)
    if not out.exists() or out.read_text(encoding="utf-8") != stripped:
        out.write_text(stripped, encoding="utf-8")
    return out


def app_files() -> dict[str, str]:
    """Files published with the Studio artifact: the app, plus shipped templates and their runtime."""
    files: dict[str, str] = {}
    for f in sorted(APP_DIR.rglob("*")):
        if f.is_file() and f.name != "index.html" and not f.name.startswith("."):
            files[f.relative_to(APP_DIR).as_posix()] = str(f)
    for f in sorted((mg_dir() / "templates").glob("*.html")):
        files[f"mg/templates/{f.name}"] = str(f)
    files["mg/templates/index.json"] = str(mg_dir() / "templates" / "index.json")
    files["mg/lib/vedit.js"] = str(mg_dir() / "lib" / "vedit.js")
    files["mg/lib/three-kit.js"] = str(mg_dir() / "lib" / "three-kit.js")   # 3D templates (three.js from jsDelivr)
    files["mg/lib/base.css"] = str(studio_base_css())
    return files


def app_hash() -> str:
    h = hashlib.sha1()
    for rel, path in sorted({**app_files(), "index.html": str(APP_DIR / "index.html")}.items()):
        h.update(rel.encode())
        h.update(Path(path).read_bytes())
    return h.hexdigest()[:12]


def publish_plan() -> dict:
    st = owner_state()
    current = app_hash()
    return {"publish_needed": st.get("app_hash") != current or not st.get("url"), "app_hash": current,
            "url": st.get("url"), "file_path": str(APP_DIR / "index.html"), "files": app_files(),
            "capabilities": CAPABILITIES, "capabilities_with_live_link": {**CAPABILITIES, **LIVE_LINK}, "icon": "film",
            "description": "vedit Studio: plan, tune and approve video edits live before rendering."}


def published(url: str, app_hash_value: str | None = None) -> dict:
    st = owner_state()
    st["url"] = url
    st["app_hash"] = app_hash_value or app_hash()
    st["published"] = time.strftime("%Y-%m-%d %H:%M")
    save_owner_state(st)
    config.set_value("studio.artifact_url", url)
    return st


# ------------------------------------------------------------------ applying the owner's edits

def read_ops(source: Path) -> list[dict]:
    """Op documents from an ArtifactData `list ... out_dir` dump (a folder of <doc_id>.json) or one JSON file."""
    files = sorted(source.glob("*.json")) if source.is_dir() else [source]
    rows = []
    for f in files:
        data = read_json(f, default=None)
        if data is None:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            doc = it.get("data", it) if isinstance(it, dict) else it
            if isinstance(doc, dict) and doc.get("op"):
                rows.append({"doc_id": it.get("id", f.stem) if isinstance(it, dict) else f.stem,
                             "seq": doc.get("seq", 0), "at": doc.get("at", ""), "op": doc["op"],
                             "status": doc.get("status", "new")})
    rows.sort(key=lambda r: (r["seq"], r["at"]))
    return [r for r in rows if r["status"] in ("new", "pending", None)]


def apply(p: Project, source: Path) -> dict:
    from . import learn, modes
    from .captions import build_chunks
    from .ops import apply_ops
    from .suggest import load_directions, load_suggestions, save_directions, save_suggestions
    rows = read_ops(source)
    if not rows:
        return {"applied": 0, "note": "no new ops"}
    edit = p.edit()
    _snapshot(p, edit)
    reverts = [r for r in rows if r["op"].get("op") == "revert"]
    if reverts:
        target = int(reverts[-1]["op"].get("revision", edit.revision - 1))
        snap = _bundle(p) / "history" / f"rev_{target}.json"
        if not snap.exists():
            return {"applied": 0, "errors": [{"op": reverts[-1]["op"], "error": f"no snapshot of revision {target}"}],
                    "op_doc_ids": [r["doc_id"] for r in rows]}
        from .timeline import Edit
        old = Edit.model_validate(read_json(snap)).layout()
        old.revision = edit.revision            # save_edit bumps it: revisions only move forward
        p.save_edit(old)
        rows = [r for r in rows if r["op"].get("op") != "revert"]
        edit = p.edit()
        if not rows:
            return {"applied": 1, "reverted_to": target, "revision": edit.revision, "errors": [], "for_claude": [],
                    "op_doc_ids": [r["doc_id"] for r in reverts]}
    sug, dirs = load_suggestions(p), load_directions(p)
    new, report = apply_ops(edit, [r["op"] for r in rows], suggestions=sug, directions=dirs)
    for wf in report.get("workflow", []):
        modes.approve(p, wf.get("stage"))
    if report["captions_dirty"] and new.captions.from_words and new.captions.enabled:
        new.captions.chunks = build_chunks(new)
    p.save_edit(new)
    if report["suggestions_dirty"]:
        save_suggestions(p, sug)
    if report["directions_dirty"]:
        save_directions(p, dirs)
    scope = {"style": new.style or "", "brand": new.brand or "", "format": new.canvas.ratio}
    contexts = iter(report.get("learn_context", []))
    for op in report["applied"]:
        extra = next(contexts, {}) if op.get("op") in ("accept", "reject", "choose_direction") else {}
        learn.event("studio", {"op": op, **extra}, project=new.name, scope=scope)
    if report["pending"]:
        p.log("studio notes for Claude: " + "; ".join(str(o.get("text") or o.get("what")) for o in report["pending"]))
    if report["applied"]:
        modes.set_status(p, "in_review") if modes.state(p)["plan_status"] == "draft" else None
    return {"applied": len(report["applied"]), "errors": report["errors"], "for_claude": report["pending"],
            "workflow": report.get("workflow", []), "revision": new.revision,
            "op_doc_ids": [r["doc_id"] for r in rows],
            "next": "Run `vedit studio docs <p>` and sync the changed documents; delete the applied op documents; "
                    "answer the notes in for_claude and reply in the Studio thread."}


def _snapshot(p: Project, edit) -> None:
    """Keep the edit as it was before each Studio change (last 60 revisions) so undo can revert."""
    hist = _bundle(p) / "history"
    hist.mkdir(parents=True, exist_ok=True)
    write_json(hist / f"rev_{edit.revision}.json", edit.model_dump(mode="json", exclude_none=True), indent=None)
    snaps = sorted(hist.glob("rev_*.json"), key=lambda f: int(f.stem.split("_")[1]))
    for old in snaps[:-60]:
        old.unlink(missing_ok=True)


def status(p: Project) -> dict:
    from . import modes
    pend = pending_uploads(p) if (_bundle(p) / "media.local.json").exists() else None
    st = owner_state()
    return {"project_id": project_id(p), "artifact_url": st.get("url"), "app": publish_plan()["publish_needed"],
            "built": (_bundle(p) / "media.local.json").exists(), "pending_uploads": len(pend) if pend is not None else None,
            "workflow": modes.state(p), "revision": p.edit().revision}


# ------------------------------------------------------------------ CLI

def register_cli(sp) -> None:
    s = sp.add_parser("studio", help="the Artifact Studio: build previews, sync data, apply the owner's edits")
    s.add_argument("action", choices=["build", "register", "docs", "apply", "status", "app", "published"])
    s.add_argument("path", nargs="?")
    s.add_argument("pairs", nargs="*", help="register: local_path=url pairs")
    s.add_argument("--map", help="register: JSON file {local_path: url}")
    s.add_argument("--ops", help="apply: folder from ArtifactData list out_dir, or a JSON file")
    s.add_argument("--only", nargs="*")
    s.add_argument("--url", help="published: the Studio artifact URL"); s.add_argument("--hash")
    s.set_defaults(fn=_cmd)


def _cmd(a) -> None:
    from .project import find
    from .util import print_json
    if a.action == "app":
        print_json(publish_plan())
        return
    if a.action == "published":
        print_json(published(a.url, a.hash))
        return
    p = find(a.path)
    if a.action == "build":
        print_json(build(p, only=a.only))
    elif a.action == "register":
        mapping = read_json(a.map, default={}) if a.map else {}
        for pair in a.pairs:
            local, _, url = pair.partition("=")
            mapping[local] = url
        print_json(register(p, mapping))
    elif a.action == "docs":
        print_json(write_documents(p, only=a.only))
    elif a.action == "apply":
        if not a.ops:
            raise VeditError("Give --ops <folder or file> (ArtifactData list of projects/<pid>/ops with out_dir).")
        print_json(apply(p, Path(a.ops)))
    else:
        print_json(status(p))
