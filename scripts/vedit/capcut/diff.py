"""Learn-from-edits: compare the CapCut project we generated with what the user changed in CapCut."""

from __future__ import annotations

import json
from statistics import median
from typing import Any


def _texts(content: dict) -> list[dict]:
    mats = {m["id"]: m for m in content.get("materials", {}).get("texts", [])}
    out = []
    for track in content.get("tracks", []):
        if track.get("type") != "text":
            continue
        for seg in track.get("segments", []):
            mat = mats.get(seg.get("material_id"), {})
            text, size, color = "", None, None
            try:
                body = json.loads(mat.get("content") or "{}")
                text = body.get("text", "")
                styles = body.get("styles") or [{}]
                size = styles[0].get("size")
                color = (((styles[0].get("fill") or {}).get("content") or {}).get("solid") or {}).get("color")
            except (ValueError, TypeError):
                text = mat.get("content", "")
            tr = seg.get("target_timerange", {})
            clip = seg.get("clip") or {}
            out.append({"text": text, "size": size, "color": color, "start": tr.get("start", 0) / 1e6,
                        "dur": tr.get("duration", 0) / 1e6, "y": (clip.get("transform") or {}).get("y", 0.0),
                        "scale": (clip.get("scale") or {}).get("x", 1.0), "track": track.get("name", "")})
    return out


def _video_segments(content: dict, index: int = 0) -> list[dict]:
    vids = [t for t in content.get("tracks", []) if t.get("type") == "video"]
    if len(vids) <= index:
        return []
    return [{"start": s["target_timerange"]["start"] / 1e6, "dur": s["target_timerange"]["duration"] / 1e6,
             "src_start": (s.get("source_timerange") or {}).get("start", 0) / 1e6} for s in vids[index].get("segments", [])]


def _audio_volumes(content: dict) -> list[float]:
    return [s.get("volume", 1.0) for t in content.get("tracks", []) if t.get("type") == "audio" for s in t.get("segments", [])]


def _names(content: dict, key: str) -> list[str]:
    return [m.get("name", "") for m in content.get("materials", {}).get(key, [])]


def diff(generated: dict, current: dict) -> dict[str, Any]:
    g_txt, c_txt = _texts(generated), _texts(current)
    insights: dict[str, Any] = {"notes": []}
    notes = insights["notes"]
    g_caps = [t for t in g_txt if t["track"] == "captions"] or g_txt
    c_caps = [t for t in c_txt if t["track"] == "captions"] or c_txt
    g_sizes = [t["size"] * t["scale"] for t in g_caps if t["size"]]
    c_sizes = [t["size"] * t["scale"] for t in c_caps if t["size"]]
    if g_sizes and c_sizes:
        ratio = median(c_sizes) / median(g_sizes)
        if abs(ratio - 1) > 0.05:
            insights["caption_size_ratio"] = round(ratio, 3)
            notes.append(f"captions resized to {ratio:.0%} of the generated size")
    if g_caps and c_caps:
        dy = median(t["y"] for t in c_caps) - median(t["y"] for t in g_caps)
        if abs(dy) > 0.03:
            insights["caption_y_delta"] = round(dy, 3)
            notes.append(f"captions moved {'up' if dy > 0 else 'down'} by {abs(dy):.2f} half-canvas")
    edited = sum(1 for a, b in zip(g_caps, c_caps) if a["text"] != b["text"])
    if edited:
        notes.append(f"{edited} caption text(s) corrected (check transcription accuracy / spelling of names)")
    if len(c_caps) < len(g_caps) * 0.8:
        notes.append(f"{len(g_caps) - len(c_caps)} caption segments deleted")
    g_colors = {t["color"] and tuple(round(x, 2) for x in t["color"]) for t in g_caps}
    c_colors = {t["color"] and tuple(round(x, 2) for x in t["color"]) for t in c_caps}
    if c_colors - g_colors:
        notes.append("caption colours changed")

    g_main, c_main = _video_segments(generated, 0), _video_segments(current, 0)
    if g_main and c_main:
        gd, cd = sum(s["dur"] for s in g_main), sum(s["dur"] for s in c_main)
        if gd and abs(cd / gd - 1) > 0.02:
            insights["main_duration_ratio"] = round(cd / gd, 3)
            notes.append(f"main track {'tightened' if cd < gd else 'loosened'} to {cd / gd:.0%} of the generated length")
        if len(c_main) != len(g_main):
            notes.append(f"main clips: {len(g_main)} -> {len(c_main)}")
    g_overlay = sum(len(_video_segments(generated, i)) for i in range(1, 8))
    c_overlay = sum(len(_video_segments(current, i)) for i in range(1, 8))
    if c_overlay < g_overlay:
        notes.append(f"{g_overlay - c_overlay} b-roll/graphic layer(s) removed (maybe too busy)")
    elif c_overlay > g_overlay:
        notes.append(f"{c_overlay - g_overlay} b-roll/graphic layer(s) added (wants more visuals)")
    gv, cv = _audio_volumes(generated), _audio_volumes(current)
    if gv and cv and median(gv) > 0:
        r = median(cv) / median(gv)
        if abs(r - 1) > 0.1:
            insights["music_volume_ratio"] = round(r, 3)
            notes.append(f"audio clip volume changed to {r:.0%}")
    for key, label in (("effects", "effects"), ("video_effects", "effects"), ("filters", "filters")):
        added = sorted(set(_names(current, key)) - set(_names(generated, key)))
        if added:
            notes.append(f"{label} added in CapCut: {', '.join(added[:6])}")
    if not notes:
        notes.append("no meaningful changes detected")
    return insights
