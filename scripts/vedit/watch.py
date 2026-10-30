"""Eyes and memory: watch footage as deduplicated scene frames, label speakers, cut multicam by speaker,
remember everything ever transcribed, fetch videos from links.

Watching uses claude-real-video (MIT, isolated venv `.cache/tools/crv`, `vedit setup crv`): scene changes
plus a one-frame-per-second floor, near-duplicates dropped by its two-channel comparator, 3x3 grids Claude
reads in one look. Without it a simpler native pass (scene + floor + 16x16 signature dedup) does the same
job, so the core stays standalone. Speaker labels come from crv's sherpa-onnx diarization (offline).

Footage memory is a local SQLite FTS5 index (trigram, so Bangla and substrings match; the design follows
claude-real-video's memory) in personal/memory.db: every transcript you edit is searchable later with
`vedit memory ask "pricing"` -> file, time, line.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path

from . import addons
from .media import ffmpeg, ffprobe, probe
from .paths import cache_dir, personal_dir
from .util import VeditError, read_json, run, write_json

CRV_PIN = ("claude-real-video[speakers] @ git+https://github.com/HUANGCHIHHUNGLeo/claude-real-video"
           "@0b4149d5c68fe3a5d6b01d6601c322378e703a89")      # v0.10.7


# ------------------------------------------------------------------ claude-real-video (isolated venv)

def crv_python() -> Path | None:
    return addons.tool_python("crv")


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PATH"] = os.pathsep.join([str(Path(ffmpeg()).parent), str(Path(ffprobe()).parent), env.get("PATH", "")])
    return env


def bridge(command: str, payload: dict, timeout: float = 3600) -> dict:
    py = crv_python()
    if not py:
        raise VeditError("claude-real-video is not installed: `vedit setup crv`")
    work = cache_dir() / "crv" / "bridge"
    work.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]
    req, out = work / f"{command}_{key}.in.json", work / f"{command}_{key}.out.json"
    write_json(req, payload)
    run([py, "-I", Path(__file__).with_name("crv_bridge.py"), command, req, out], timeout=timeout, env=_env())
    return read_json(out) or {}


def setup() -> dict:
    uv = shutil.which("uv")
    if not uv:
        raise VeditError("uv is required (https://docs.astral.sh/uv/)")
    venv = cache_dir() / "tools" / "crv" / "venv"
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        run([uv, "venv", "--python", "3.12", str(venv)], timeout=900)
    run([uv, "pip", "install", "--python", str(py), CRV_PIN], timeout=3600)
    return {"venv": str(venv)}


# ------------------------------------------------------------------ watching

def frames(video: str | Path, out: str | Path, *, start: float | None = None, end: float | None = None,
           scene: float = 0.3, fps_floor: float = 1.0, width: int = 480, max_frames: int | None = None) -> dict:
    """Scene-aware, deduplicated frames + 3x3 grids of a video (or a window of it)."""
    out = Path(out)
    dur = (end or probe(video).duration) - (start or 0)
    max_frames = max_frames or int(min(600, max(60, dur * 1.2)))
    if crv_python():
        res = bridge("frames", {"video": str(Path(video).resolve()), "out": str(out.resolve()), "scene": scene,
                                "fps_floor": fps_floor, "start": start, "end": end, "width": width,
                                "max_frames": max_frames})
        res["engine"] = "claude-real-video"
        res["grids"] = make_grids(out, res.get("frames", []))
    else:
        res = _native_frames(Path(video), out, start=start, end=end, scene=scene, fps_floor=fps_floor,
                             width=width, max_frames=max_frames)
        res["engine"] = "native"
    write_json(out / "watch.json", {**res, "video": str(video), "start": start, "end": end})
    return res


def _native_frames(video: Path, out: Path, *, start, end, scene, fps_floor, width, max_frames) -> dict:
    import numpy as np
    from PIL import Image
    fdir = out / "frames"
    shutil.rmtree(fdir, ignore_errors=True)
    shutil.rmtree(out / "grids", ignore_errors=True)
    fdir.mkdir(parents=True, exist_ok=True)
    every = max(1, round((probe(video).fps or 25) * fps_floor))
    pre = ["-ss", f"{start:.3f}"] if start else []
    post = ["-t", f"{(end - (start or 0)):.3f}"] if end else []
    proc = run([ffmpeg(), "-hide_banner", *pre, "-i", str(video), *post, "-vf",
                f"select='gt(scene,{scene})+not(mod(n,{every}))',showinfo,scale={width}:-1", "-vsync", "vfr",
                str(fdir / "raw_%05d.jpg")], check=False)
    times = [float(t) + (start or 0) for t in re.findall(r"pts_time:([\d.]+)", proc.stderr or "")]
    raws = sorted(fdir.glob("raw_*.jpg"))
    kept, sigs = [], []
    for i, f in enumerate(raws):
        sig = np.asarray(Image.open(f).convert("RGB").resize((16, 16)), dtype=np.int16)
        if any((np.abs(sig - s) > 25).any(axis=2).mean() * 100 < 8 for s in sigs[-4:]):
            f.unlink()
            continue
        sigs.append(sig)
        kept.append((f, times[i] if i < len(times) else None))
    if len(kept) > max_frames:
        step = len(kept) / max_frames
        keep_idx = {int(k * step) for k in range(max_frames)}
        for k, (f, _) in enumerate(kept):
            if k not in keep_idx:
                f.unlink()
        kept = [kv for k, kv in enumerate(kept) if k in keep_idx]
    recs = []
    for n, (f, t) in enumerate(kept, start=1):
        dest = fdir / f"frame_{n:03d}.jpg"
        f.rename(dest)
        recs.append({"file": dest.name, "timestamp_sec": round(t, 3) if t is not None else None})
    write_json(out / "frames.json", {"frames": recs})
    return {"extracted": len(raws), "kept": len(recs), "frames": recs, "grids": make_grids(out, recs)}


def make_grids(out: Path, recs: list[dict], cell: int = 480) -> list[str]:
    """3x3 contact sheets, each frame labelled with its time in the source (m:ss.s) so Claude can cite it."""
    from PIL import Image, ImageDraw
    from .view import _font
    fdir, gdir = out / "frames", out / "grids"
    shutil.rmtree(gdir, ignore_errors=True)
    gdir.mkdir(parents=True, exist_ok=True)
    font = _font(18)
    grids = []
    for g in range(0, len(recs), 9):
        batch = recs[g:g + 9]
        first = Image.open(fdir / batch[0]["file"])
        cw, ch = cell, int(first.height * cell / first.width) + 26
        sheet = Image.new("RGB", (3 * cw, 3 * ch), "black")
        draw = ImageDraw.Draw(sheet)
        for i, r in enumerate(batch):
            im = Image.open(fdir / r["file"]).convert("RGB").resize((cw, ch - 26))
            x, y = (i % 3) * cw, (i // 3) * ch
            sheet.paste(im, (x, y + 26))
            t = r.get("timestamp_sec")
            label = f"{int(t // 60)}:{t % 60:04.1f}  ·  {r['file']}" if t is not None else r["file"]
            draw.text((x + 6, y + 3), label, fill="white", font=font)
        dest = gdir / f"grid_{g // 9 + 1:02d}.jpg"
        sheet.save(dest, quality=85)
        grids.append(str(dest))
    return grids


def watch_project(p, *, sources: list[str] | None = None, render: bool = False, **kw) -> dict:
    """Watch a project's sources (plan mode: know the footage before cutting) or its render (QA)."""
    e = p.edit()
    out = {}
    if render:
        path = p.root / "render" / f"{e.name}.mp4"
        if not path.exists():
            path = p.root / "render" / "preview.mp4"
        out["render"] = frames(path, p.sub("watch") / "render", **kw)
        return out
    for sid, src in e.sources.items():
        if src.kind != "video" or (sources and sid not in sources) or sid.startswith("sfx_"):
            continue
        out[sid] = frames(src.path, p.sub("watch") / sid, **kw)
    return out


# ------------------------------------------------------------------ speakers

def speakers(p, source_id: str, *, num_speakers: int = -1, threshold: float = 0.9) -> dict:
    """Diarize one source and label its transcript words with speakers (SPEAKER_00, ...)."""
    e = p.edit()
    src = e.sources.get(source_id)
    if not src:
        raise VeditError(f"unknown source {source_id}")
    from . import models
    seg, emb = models.ensure("speaker_seg"), models.ensure("speaker_emb")     # asks first (~47 MB)
    res = bridge("speakers", {"audio": str(Path(src.path).resolve()), "num_speakers": num_speakers,
                              "threshold": threshold, "seg": str(seg), "emb": str(emb)}, timeout=7200)
    turns = res.get("turns", [])
    write_json(p.sub("transcripts") / f"{source_id}.speakers.json", {"turns": turns})
    labelled = 0
    tpath = Path(src.transcript) if src.transcript else p.root / "transcripts" / f"{source_id}.json"
    doc = read_json(tpath)
    if doc and turns:
        for w in doc.get("words", []):
            mid = (w["s"] + w["e"]) / 2
            hit = next((t for t in turns if t["start"] - 0.15 <= mid <= t["end"] + 0.15), None)
            if hit and not w.get("speaker"):
                w["speaker"] = hit["speaker"]
                labelled += 1
        doc["speakers"] = sorted({t["speaker"] for t in turns})
        write_json(tpath, doc)
    talk: dict[str, float] = {}
    for t in turns:
        talk[t["speaker"]] = round(talk.get(t["speaker"], 0) + t["end"] - t["start"], 1)
    return {"source": source_id, "turns": len(turns), "speakers": talk, "words_labelled": labelled}


def _audio16(path: str, seconds: float | None = None):
    import subprocess

    import numpy as np
    cmd = [ffmpeg(), "-v", "error", "-i", str(path)] + (["-t", f"{seconds:.1f}"] if seconds else []) + \
          ["-f", "f32le", "-ac", "1", "-ar", "8000", "-"]
    return np.frombuffer(subprocess.run(cmd, stdout=subprocess.PIPE).stdout, dtype=np.float32)


def sync_offset(ref: str, other: str, *, seconds: float = 240.0) -> dict:
    """Audio cross-correlation: other_time = ref_time + offset (seconds), with a confidence ratio."""
    import numpy as np
    a, b = _audio16(ref, seconds), _audio16(other, seconds)
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    fa, fb = np.fft.rfft(a - a.mean(), n), np.fft.rfft(b - b.mean(), n)
    cc = np.fft.irfft(np.conj(fa) * fb / (np.abs(np.conj(fa) * fb) + 1e-9), n)   # PHAT: sharp peak
    k = int(np.argmax(cc))
    lag = k if k < n // 2 else k - n
    peak = float(cc[k])
    conf = peak / (float(np.sort(np.abs(cc))[-50]) + 1e-12)
    return {"offset": round(lag / 8000, 4), "confidence": round(conf, 2)}


def multicam(p, angles: list[str], mapping: dict[str, str], *, min_shot: float = 1.2) -> dict:
    """Cut between camera angles by who is talking. `angles` are extra source ids recorded at the same time
    as the main track's source; `mapping` is speaker -> source id (e.g. SPEAKER_00=a_roll, SPEAKER_01=cam_b).
    Each main clip is split at speaker turns and each piece uses the angle of its speaker (sync from audio)."""
    from .timeline import Clip
    e = p.edit()
    if not e.main:
        raise VeditError("no main track to switch")
    base = e.main[0].source
    offsets = {base: 0.0}
    for sid in angles:
        r = sync_offset(e.sources[base].path, e.sources[sid].path)
        if r["confidence"] < 3:
            raise VeditError(f"could not sync {sid} to {base} by audio (confidence {r['confidence']})")
        offsets[sid] = r["offset"]
    turns = (read_json(p.root / "transcripts" / f"{base}.speakers.json") or {}).get("turns")
    if not turns:
        raise VeditError(f"run `vedit speakers {p.root} {base}` first")
    new_main, n = [], 0
    for clip in e.main:
        if clip.source != base:
            new_main.append(clip)
            continue
        cuts = [clip.src_in]
        for t in turns:
            if clip.src_in + min_shot < t["start"] < clip.src_out - min_shot and t["start"] - cuts[-1] >= min_shot:
                cuts.append(t["start"])
        cuts.append(clip.src_out)
        pieces: list[list] = []                       # [a, b, angle, speaker]
        for a, b in zip(cuts, cuts[1:]):
            mid = (a + b) / 2
            spk = next((t["speaker"] for t in turns if t["start"] <= mid <= t["end"]), None)
            sid = mapping.get(spk or "") or (pieces[-1][2] if pieces else base)    # pauses hold the angle
            if pieces and pieces[-1][2] == sid:
                pieces[-1][1] = b
                continue
            pieces.append([a, b, sid, spk])
        for k, (a, b, sid, spk) in enumerate(pieces):
            off = offsets.get(sid, 0.0)
            n += 1
            piece = clip.model_copy(deep=True, update={"id": f"{clip.id}_{n}", "source": sid, "src_in": a + off,
                                                       "src_out": b + off,
                                                       "transition_in": clip.transition_in if k == 0 else None})
            piece.label = f"{clip.label} [{spk or 'no speaker'}]".strip()
            new_main.append(piece)
    e.main = [Clip.model_validate(c.model_dump()) for c in new_main]
    p.save_edit(e)
    return {"offsets": offsets, "clips": len(e.main), "switches": n}


# ------------------------------------------------------------------ footage memory (SQLite FTS5)

def _db() -> sqlite3.Connection:
    path = personal_dir() / "memory.db"
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("create table if not exists files(id integer primary key, path text unique, project text, "
                "duration real, indexed text)")
    con.execute("create table if not exists lines(id integer primary key, file integer, s real, e real, "
                "speaker text, text text)")
    try:
        con.execute("create virtual table if not exists lines_fts using fts5(text, content='lines', "
                    "content_rowid='id', tokenize='trigram')")
    except sqlite3.OperationalError:          # old SQLite without trigram: English still works
        con.execute("create virtual table if not exists lines_fts using fts5(text, content='lines', content_rowid='id')")
    return con


def remember(p) -> dict:
    """Index a project's transcripts (sentences with times and speakers) into personal/memory.db."""
    e = p.edit()
    con = _db()
    n_lines = 0
    for sid, src in e.sources.items():
        tpath = Path(src.transcript) if src.transcript else p.root / "transcripts" / f"{sid}.json"
        doc = read_json(tpath)
        if not doc:
            continue
        path = str(Path(src.path).resolve())
        old = con.execute("select id from files where path=?", (path,)).fetchone()
        if old:
            for r in con.execute("select id, text from lines where file=?", (old["id"],)).fetchall():
                con.execute("insert into lines_fts(lines_fts, rowid, text) values('delete', ?, ?)", (r["id"], r["text"]))
            con.execute("delete from lines where file=?", (old["id"],))
            con.execute("delete from files where id=?", (old["id"],))
        cur = con.execute("insert into files(path, project, duration, indexed) values(?,?,?,?)",
                          (path, str(p.root), doc.get("duration"), time.strftime("%Y-%m-%d %H:%M")))
        fid = cur.lastrowid
        words = [w for w in doc.get("words", []) if w.get("type", "word") == "word"]
        line: list[dict] = []
        def flush():
            nonlocal n_lines
            if not line:
                return
            text = " ".join(w["w"] for w in line)
            spk = line[0].get("speaker")
            rid = con.execute("insert into lines(file, s, e, speaker, text) values(?,?,?,?,?)",
                              (fid, line[0]["s"], line[-1]["e"], spk, text)).lastrowid
            con.execute("insert into lines_fts(rowid, text) values(?, ?)", (rid, text))
            n_lines += 1
        for w in words:
            if line and (w["s"] - line[-1]["e"] > 0.8 or len(line) >= 24 or w.get("speaker") != line[-1].get("speaker")
                         or line[-1]["w"].endswith((".", "?", "!", "।"))):
                flush()
                line = []
            line.append(w)
        flush()
    con.commit()
    return {"lines": n_lines, "db": str(personal_dir() / "memory.db")}


def ask(query: str, *, limit: int = 12) -> list[dict]:
    con = _db()
    q = query.strip()
    rows = []
    if len(q) >= 3:
        try:
            rows = con.execute("select lines.*, files.path, files.project from lines_fts join lines on "
                               "lines.id = lines_fts.rowid join files on files.id = lines.file where lines_fts match ? "
                               "order by rank limit ?", ('"' + q.replace('"', '""') + '"', limit)).fetchall()
        except sqlite3.OperationalError:
            rows = []
    if not rows:                              # short or odd queries: plain substring
        rows = con.execute("select lines.*, files.path, files.project from lines join files on files.id = lines.file "
                           "where lines.text like ? limit ?", (f"%{q}%", limit)).fetchall()
    return [{"file": r["path"], "project": r["project"], "s": r["s"], "e": r["e"], "speaker": r["speaker"],
             "text": r["text"]} for r in rows]


# ------------------------------------------------------------------ fetch (links)

def fetch(url: str, dest: str | Path, *, sub_lang: str | None = "en", project=None) -> dict:
    """Download a video from a link (yt-dlp in crv's venv) with its captions when the platform has them.
    Third-party videos are copyrighted: use them only with permission or for reference/research."""
    dest = Path(dest)
    key = hashlib.sha1(url.encode()).hexdigest()[:10]
    work = dest / f"_fetch_{key}"
    res = bridge("fetch", {"url": url, "out": str(work.resolve()), "sub_lang": sub_lang}, timeout=7200)
    src = Path(res["file"])
    title = re.sub(r"[^\w.\- ]+", "_", (res.get("info") or {}).get("title") or f"video_{key}")[:80].strip() or key
    final = dest / f"{title}{src.suffix}"
    shutil.move(str(src), final)
    subs = []
    for s in res.get("subtitles", []):
        sp = Path(s)
        target = dest / f"{title}{''.join(sp.suffixes[-2:]) if len(sp.suffixes) > 1 else sp.suffix}"
        shutil.move(str(sp), target)
        subs.append(str(target))
    shutil.rmtree(work, ignore_errors=True)
    out = {"file": str(final), "subtitles": subs, "info": res.get("info"),
           "warning": "Third-party video: copyrighted unless the owner says otherwise. Use with permission, or as "
                      "reference only."}
    if project is not None:
        from .assets import add_provenance
        lic = (res.get("info") or {}).get("license")
        out["provenance"] = add_provenance(project.root, final, source="link", url=url, license=lic or "unknown",
                                           notes=json.dumps(res.get("info") or {}, ensure_ascii=False)[:400])
    return out


# ------------------------------------------------------------------ CLI

def _proj(path: str):
    from .project import find as find_project
    return find_project(path)


def cmd_watch(a) -> None:
    from .util import print_json
    if a.file:
        out = Path(a.out) if a.out else Path(a.path).resolve().parent / f"{Path(a.path).stem}_watch"
        print_json(frames(a.path, out, start=a.start, end=a.end, scene=a.scene, max_frames=a.max_frames))
        return
    p = _proj(a.path)
    res = watch_project(p, sources=a.source, render=a.render, start=a.start, end=a.end, scene=a.scene,
                        max_frames=a.max_frames)
    print_json({k: {"engine": v.get("engine"), "kept": v.get("kept"), "grids": v.get("grids")} for k, v in res.items()})


def cmd_speakers(a) -> None:
    from .util import print_json
    print_json(speakers(_proj(a.path), a.source, num_speakers=a.num, threshold=a.threshold))


def cmd_multicam(a) -> None:
    from .util import print_json
    mapping = dict(kv.split("=", 1) for kv in a.map)
    print_json(multicam(_proj(a.path), a.angles, mapping, min_shot=a.min_shot))


def cmd_memory(a) -> None:
    from .util import print_json
    if a.action == "index":
        print_json(remember(_proj(a.target)))
    else:
        print_json(ask(a.target, limit=a.limit))


def cmd_fetch(a) -> None:
    from .util import print_json
    proj = _proj(a.project) if a.project else None
    dest = Path(a.to) if a.to else (proj.root.parent if proj else Path.cwd())
    out = fetch(a.url, dest, sub_lang=a.subs, project=proj)
    if proj and a.register:
        from .project import add_source
        out["source_id"] = add_source(proj, out["file"], origin=f"link:{a.url}")
    print_json(out)


def register_cli(sp) -> None:
    s = sp.add_parser("watch", help="watch footage or a render: scene frames, duplicates dropped, 3x3 grids")
    s.add_argument("path"); s.add_argument("--file", action="store_true", help="PATH is a video file, not a project")
    s.add_argument("--source", nargs="*"); s.add_argument("--render", action="store_true")
    s.add_argument("--start", type=float); s.add_argument("--end", type=float); s.add_argument("--scene", type=float, default=0.3)
    s.add_argument("--max-frames", type=int); s.add_argument("--out"); s.set_defaults(fn=cmd_watch)
    s = sp.add_parser("speakers", help="who speaks when (offline diarization); labels the transcript")
    s.add_argument("path"); s.add_argument("source"); s.add_argument("--num", type=int, default=-1)
    s.add_argument("--threshold", type=float, default=0.9); s.set_defaults(fn=cmd_speakers)
    s = sp.add_parser("multicam", help="cut between synced camera angles by who is talking")
    s.add_argument("path"); s.add_argument("--angles", nargs="+", required=True)
    s.add_argument("--map", nargs="+", required=True, help="SPEAKER_00=a_roll SPEAKER_01=cam_b")
    s.add_argument("--min-shot", type=float, default=1.2); s.set_defaults(fn=cmd_multicam)
    s = sp.add_parser("memory", help="search everything ever transcribed (personal/memory.db)")
    s.add_argument("action", choices=["index", "ask"]); s.add_argument("target")
    s.add_argument("--limit", type=int, default=12); s.set_defaults(fn=cmd_memory)
    s = sp.add_parser("fetch", help="download a video from a link (yt-dlp) with its captions")
    s.add_argument("url"); s.add_argument("--to"); s.add_argument("--project"); s.add_argument("--register", action="store_true")
    s.add_argument("--subs", default="en"); s.set_defaults(fn=cmd_fetch)
