"""Cut lists in and out: the main-track cut and chapter markers in the formats other tools speak.

Export: csv (LosslessCut's start,end,name in source seconds, one file per source), chapters (YouTube
description lines from chapter markers), llc, srt (captions), and the timeline formats (edl, otio, xml,
fcpxml) through exports/. Import: the same formats back into the main track (`--as main`) or as
markers (`--as markers`; chapters always become markers).
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from .project import Project
from .timeline import Edit, Marker
from .util import VeditError, write_text


def _ts(t: float) -> str:
    t = int(round(t))
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def parse_time(s: str) -> float:
    s = s.strip()
    if re.fullmatch(r"[\d.]+", s):
        return float(s)
    parts = [float(p) for p in s.split(":")]
    out = 0.0
    for p in parts:
        out = out * 60 + p
    return out


def chapters_text(edit: Edit) -> tuple[str, list[str]]:
    """YouTube chapters from chapter markers. Returns (text, problems): YouTube needs the first at 0:00,
    at least three, each at least 10 s long."""
    edit.layout()
    ch = sorted((m for m in edit.markers if m.kind == "chapter"), key=lambda m: m.t)
    problems = []
    if not ch:
        return "", ["no chapter markers (add them with `vedit marker add <p> --t 0 --name Intro --kind chapter`)"]
    if ch[0].t > 0.5:
        problems.append("the first chapter must start at 0:00 (YouTube)")
    if len(ch) < 3:
        problems.append("YouTube shows chapters only when there are at least three")
    ends = [m.t for m in ch[1:]] + [edit.duration]
    short = [m.name for m, e in zip(ch, ends) if e - m.t < 10]
    if short:
        problems.append("chapters shorter than 10 s: " + ", ".join(short))
    text = "\n".join(f"{_ts(0 if i == 0 and m.t <= 0.5 else m.t)} {m.name}" for i, m in enumerate(ch))
    return text, problems


def export(proj: Project, fmt: str, out_dir: str | Path | None = None) -> dict:
    e = proj.edit()
    out_dir = Path(out_dir) if out_dir else proj.sub("handoff") / "cutlists"
    out_dir.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        files = []
        by_src: dict[str, list] = {}
        for c in e.main:
            by_src.setdefault(c.source, []).append(c)
        for sid, clips in by_src.items():
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            for c in clips:
                w.writerow([f"{c.src_in:.3f}", f"{c.src_out:.3f}", c.label or c.id])
            files.append(str(write_text(out_dir / f"{Path(e.sources[sid].path).stem}.csv", buf.getvalue())))
        return {"format": "csv", "files": files}
    if fmt == "chapters":
        text, problems = chapters_text(e)
        f = write_text(out_dir / "chapters.txt", text + "\n") if text else None
        return {"format": "chapters", "file": str(f) if f else None, "text": text, "problems": problems}
    if fmt == "llc":
        from .llc import from_edit
        return {"format": "llc", "projects": from_edit(e, out_dir, footage_dir=proj.footage_dir)}
    if fmt == "srt":
        from . import captions as caps
        chunks = e.captions.chunks or caps.build_chunks(e)
        return {"format": "srt", "file": str(caps.to_srt(chunks, out_dir / f"{e.name}.srt"))}
    if fmt in ("edl", "otio", "xml", "fcpxml", "kdenlive", "mlt"):
        from .exports import flatten
        from .exports.package import write_timeline
        return {"format": fmt, "file": str(write_timeline(flatten(e), out_dir / e.name, fmt))}
    raise VeditError(f"Unknown cut-list format '{fmt}'")


def import_file(proj: Project, path: str | Path, *, source: str | None = None, as_: str = "main") -> dict:
    path = Path(path)
    e = proj.edit()
    ext = path.suffix.lower()
    if ext == ".txt" and as_ != "main" or (ext == ".txt" and _looks_like_chapters(path)):
        added = []
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*((?:\d+:)?\d{1,2}:\d{2}(?:\.\d+)?)\s+[-–]?\s*(.+)", line)
            if m:
                t = parse_time(m.group(1))
                mk = Marker(id=f"ch{len(e.markers) + 1:03d}", t=t, name=m.group(2).strip(), kind="chapter", color="orange")
                src = e.timeline_to_source(t)
                if src:
                    from .timeline import Anchor
                    mk.anchor = Anchor(source=src[0], t=round(src[1], 3))
                e.markers.append(mk)
                added.append(mk.name)
        proj.save_edit(e)
        return {"markers_added": added}
    if ext == ".csv":
        if not source:
            if len(e.sources) == 1 or len({c.source for c in e.main}) == 1:
                source = e.main[0].source if e.main else next(iter(e.sources))
            else:
                raise VeditError("This project has several sources: pass --source <id> for the CSV's file.")
        ranges = []
        for row in csv.reader(path.read_text(encoding="utf-8").splitlines()):
            if len(row) < 2 or not row[0].strip() or row[0].strip().lower() == "start":
                continue
            ranges.append({"source": source, "src_in": parse_time(row[0]), "src_out": parse_time(row[1]),
                           "name": row[2].strip() if len(row) > 2 else ""})
    elif ext == ".llc":
        from .llc import read, to_ranges
        data = read(path)
        media = path.parent / (data.get("mediaFileName") or "")
        ranges = to_ranges(data, media)
        if source:
            for r in ranges:
                r["source"] = source
    else:
        from .exports.diff import read_any
        cur = read_any(path, fps=e.canvas.fps)
        items = cur["tracks"][0]["items"] if cur["tracks"] else []
        ranges = [{"path": i["path"], "src_in": i["src_in"], "duration": i["duration"], "speed": i.get("speed", 1.0),
                   "name": i.get("name", "")} for i in items]
        if as_ == "markers":
            for m in cur.get("markers", []):
                e.markers.append(Marker(id=f"mk{len(e.markers) + 1:03d}", t=m["t"], name=m.get("name", ""),
                                        note=m.get("note", "")))
            proj.save_edit(e)
            return {"markers_added": len(cur.get("markers", []))}
    from .exports.diff import main_from_ranges
    e, skipped = main_from_ranges(e, ranges)
    proj.save_edit(e)
    proj.log(f"main track imported from {path.name} ({len(e.main)} clips)")
    return {"main_clips": len(e.main), "duration": round(e.duration, 3), "skipped": skipped}


def _looks_like_chapters(path: Path) -> bool:
    lines = [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return bool(lines) and all(re.match(r"\s*(?:\d+:)?\d{1,2}:\d{2}", x) for x in lines)
