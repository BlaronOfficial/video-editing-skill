"""Learn from the owner's edits in another editor, and pull trimmed cuts back in.

The owner finishes or fine-tunes a hand-off in Resolve / Premiere / Final Cut / Kdenlive / Shotcut /
LosslessCut, exports the timeline again, and `vedit handoff diff <project> <file>` compares it with the
neutral timeline we handed off (handoff.json). Insights go to learning (events + the style profile),
the same way CapCut diffs do. `--apply-cuts` makes the editor's main-track cut the new main track of
edit.json; graphics, captions and sounds anchored to words follow it.
"""

from __future__ import annotations

from pathlib import Path
from statistics import median
from typing import Any

from ..project import Project
from ..timeline import Clip, Edit
from ..util import VeditError, read_json


def read_any(path: str | Path, *, fps: float | None = None) -> dict:
    """Any timeline file -> {"tracks": [{"name", "kind", "items": [{path, start, duration, src_in, ...}]}], "markers"}."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".fcpxml":
        from .fcpxml import read
        r = read(path)
        tracks = [{"name": "V1", "kind": "video", "items": [c for c in r["clips"] if c["tag"] != "gap"]}]
        lanes: dict[int, list] = {}
        for c in r["connected"]:
            lanes.setdefault(c["lane"], []).append(c)
        for lane in sorted(lanes, key=lambda x: (x < 0, abs(x))):
            tracks.append({"name": f"lane {lane}", "kind": "video" if lane > 0 else "audio", "items": lanes[lane]})
        return {"tracks": tracks, "markers": r["markers"], "transitions": len(r["transitions"])}
    if ext == ".mlt":
        from .mlt import read
        return read(path)
    if ext == ".llc":
        from ..llc import read as read_llc
        proj = read_llc(path)
        media = proj.get("mediaFileName") or ""
        t, items = 0.0, []
        for seg in proj["cutSegments"]:
            if seg.get("selected", True) is False or seg.get("end") is None:
                continue
            d = seg["end"] - seg["start"]
            items.append({"name": seg.get("name", ""), "path": str(path.parent / media) if media else "", "start": t,
                          "duration": d, "src_in": seg["start"]})
            t += d
        return {"tracks": [{"name": "V1", "kind": "video", "items": items}], "markers": []}
    from .otio import read
    return read(path, fps=fps)


def _same(a: str, b: str) -> bool:
    if not a or not b:
        return False
    try:
        return Path(a).resolve() == Path(b).resolve() or Path(a).name.lower() == Path(b).name.lower()
    except OSError:
        return Path(a).name.lower() == Path(b).name.lower()


def diff(handed: dict, current: dict) -> dict[str, Any]:
    """`handed` = handoff.json["handoff"], `current` = read_any(export)."""
    notes: list[str] = []
    out: dict[str, Any] = {"notes": notes}
    g_main = [i for i in handed["tracks"][0]["items"]]
    c_main = current["tracks"][0]["items"] if current["tracks"] else []
    gd, cd = sum(i["duration"] for i in g_main), sum(i["duration"] for i in c_main)
    if gd and abs(cd / gd - 1) > 0.02:
        out["main_duration_ratio"] = round(cd / gd, 3)
        notes.append(f"main track {'tightened' if cd < gd else 'loosened'} to {cd / gd:.0%} of the handed-off length")
    if len(c_main) != len(g_main):
        notes.append(f"main clips: {len(g_main)} -> {len(c_main)}")
    heads, tails, dropped = [], [], 0
    for g in g_main:
        g_out = g["src_in"] + g["duration"] * g.get("speed", 1.0)
        best = None
        for c in c_main:
            if not _same(g["path"], c["path"]):
                continue
            c_out = c["src_in"] + c["duration"] * c.get("speed", 1.0)
            ov = min(g_out, c_out) - max(g["src_in"], c["src_in"])
            if ov > 0 and (best is None or ov > best[0]):
                best = (ov, c["src_in"] - g["src_in"], g_out - c_out)
        if best is None:
            dropped += 1
        else:
            heads.append(best[1])
            tails.append(best[2])
    if dropped:
        notes.append(f"{dropped} main clip(s) removed")
    if heads and abs(median(heads)) > 0.04:
        out["head_trim_s"] = round(median(heads), 3)
        notes.append(f"clip starts moved by {median(heads):+.2f}s (median; + = later, the editor trims heads)")
    if tails and abs(median(tails)) > 0.04:
        out["tail_trim_s"] = round(median(tails), 3)
        notes.append(f"clip ends moved by {-median(tails):+.2f}s (median; - = earlier, the editor trims tails)")
    order_g = [g["src_in"] for g in g_main]
    order_c = [c["src_in"] for c in c_main]
    if len(order_g) == len(order_c) and sorted(range(len(order_c)), key=lambda i: order_c[i]) != \
            sorted(range(len(order_g)), key=lambda i: order_g[i]):
        notes.append("main clips re-ordered")

    def count(tracks, kind, skip_first=False) -> int:
        ts = [t for t in tracks if t["kind"] == kind]
        if skip_first and ts:
            ts = ts[1:]
        return sum(len(t["items"]) for t in ts)

    g_v, c_v = count(handed["tracks"], "video", True), count(current["tracks"], "video", True)
    if c_v < g_v:
        notes.append(f"{g_v - c_v} b-roll/graphic layer clip(s) removed (maybe too busy)")
    elif c_v > g_v:
        notes.append(f"{c_v - g_v} b-roll/graphic layer clip(s) added (wants more visuals)")
    g_a = sum(len(t["items"]) for t in handed["tracks"] if t["kind"] == "audio" and t["role"] != "dialogue")
    c_a_tracks = [t for t in current["tracks"] if t["kind"] == "audio"]
    c_a = sum(len(t["items"]) for t in c_a_tracks) - (len(c_main) if any(t["name"].lower().startswith("a1") for t in c_a_tracks)
                                                     else 0)
    if c_a < g_a:
        notes.append(f"{g_a - c_a} music/SFX clip(s) removed")
    music = [i for t in handed["tracks"] if t["role"] == "music" for i in t["items"]]
    if music:
        vols = [c.get("volume_db") for t in current["tracks"] if t["kind"] == "audio" for c in t["items"]
                if any(_same(c.get("path", ""), m["path"]) for m in music) and c.get("volume_db") is not None]
        import math
        g_db = median(20 * math.log10(max(m["volume"], 1e-4)) for m in music)
        if vols and abs(median(vols) - g_db) > 1.5:
            out["music_volume_ratio"] = round(10 ** ((median(vols) - g_db) / 20), 3)
            notes.append(f"music level changed by {median(vols) - g_db:+.1f} dB")
    g_m, c_m = len(handed.get("markers", [])), len(current.get("markers", []))
    if g_m and c_m < g_m:
        notes.append(f"{g_m - c_m} vedit marker(s) cleared (notes dealt with)")
    if not notes:
        notes.append("no meaningful changes detected")
    return out


def main_from_ranges(edit: Edit, ranges: list[dict]) -> tuple[Edit, list[str]]:
    """Replace the main track with ranges [{"path" | "source", "src_in", "src_out" | "duration", "speed"?, "name"?}].
    Labels, framing (fit, zoom, crop path, grade) and transitions carry over from the old clip that overlaps most."""
    by_path = {str(Path(s.path).resolve()).lower(): sid for sid, s in edit.sources.items()}
    by_name = {Path(s.path).name.lower(): sid for sid, s in edit.sources.items()}
    old = list(edit.main)
    new, skipped = [], []
    for n, r in enumerate(ranges, 1):
        sid = r.get("source")
        if not sid and r.get("path"):
            try:
                key = str(Path(r["path"]).resolve()).lower()
            except OSError:
                key = ""
            sid = by_path.get(key) or by_name.get(Path(r["path"]).name.lower())
        if not sid or sid not in edit.sources:
            skipped.append(r.get("name") or r.get("path") or f"#{n}")
            continue
        speed = float(r.get("speed", 1.0) or 1.0)
        a = float(r["src_in"])
        b = float(r["src_out"]) if r.get("src_out") is not None else a + float(r["duration"]) * speed
        if b - a < 1 / max(edit.canvas.fps, 1):
            continue
        best, ov = None, 0.0
        for c in old:
            if c.source == sid:
                o = min(b, c.src_out) - max(a, c.src_in)
                if o > ov:
                    best, ov = c, o
        base = best.model_dump() if best else {}
        for k in ("id", "source", "src_in", "src_out", "start", "speed"):
            base.pop(k, None)
        if best and best.crop:                       # keep the reframe path in clip-local time
            shift = a - best.src_in
            base["crop"] = [{**k.model_dump(), "t": max(0.0, k.t - shift)} for k in best.crop]
        if r.get("name") and not base.get("label"):
            base["label"] = r["name"]
        new.append(Clip(id=f"m{n:03d}", source=sid, src_in=round(a, 4), src_out=round(b, 4), speed=speed, **base))
    if not new:
        raise VeditError("None of the edited clips match a source of this project (relink, or check the export).")
    edit.main = new
    return edit.layout(), skipped


def run_diff(proj: Project, export: str | Path, *, target: str | None = None, learn_style: str | None = None,
             apply_cuts: bool = False) -> dict:
    meta = proj.meta().get("handoffs", {})
    target = target or (max(meta, key=lambda k: meta[k]["at"]) if meta else None)
    if not target:
        raise VeditError("No hand-off recorded for this project (run `vedit handoff <project> --to ...` first).")
    manifest = read_json(Path(meta[target]["dir"]) / "handoff.json")
    if not manifest:
        raise VeditError(f"handoff.json missing in {meta[target]['dir']}")
    handed = manifest["handoff"]
    current = read_any(export, fps=handed["fps"])
    insights = diff(handed, current)
    insights["target"] = target
    from .. import learn
    learn.event("editor_diff", {"target": target, "export": str(export), **insights}, project=str(proj.root))
    if learn_style:
        from .. import styles
        styles.learn(learn_style, insights)
        insights["learned_into"] = learn_style
    if apply_cuts:
        e = proj.edit()
        items = current["tracks"][0]["items"] if current["tracks"] else []
        ranges = [{"path": i["path"], "src_in": i["src_in"], "duration": i["duration"], "speed": i.get("speed", 1.0),
                   "name": i.get("name", "")} for i in items if i.get("enabled", True)]
        e, skipped = main_from_ranges(e, ranges)
        proj.save_edit(e)
        proj.log(f"main track taken from the {target} re-export ({len(e.main)} clips)")
        insights["applied"] = {"main_clips": len(e.main), "duration": round(e.duration, 3), "skipped": skipped}
    return insights
