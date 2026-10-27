"""Turn keep-ranges into main-track clips with word-safe boundaries.

A plan item: {"source": "a_roll", "from": "P3" | 12.4, "to": "P7" | 31.0, "label": "hook",
              "zoom": {...}, "speed": 1.0, "exact": false}
Snapping puts a cut-in a little before the first kept word and a cut-out a little after the last one,
never inside a neighbouring word, so consonants are not clipped.
"""

from __future__ import annotations

from typing import Any

from .captions import transcript_words
from .pack import HARD_FILLERS, _norm
from .timeline import Clip, Edit, Transition, Zoom
from .util import VeditError, read_json

PAD_IN = 0.06
PAD_OUT = 0.12


def snap_range(words: list[dict], start: float, end: float, *, pad_in: float = PAD_IN, pad_out: float = PAD_OUT,
               duration: float | None = None) -> tuple[float, float]:
    inside = [w for w in words if w["s"] >= start - 0.15 and w["e"] <= end + 0.15]
    if not inside:
        return start, end
    first, last = inside[0], inside[-1]
    prev_words = [w for w in words if w["e"] <= first["s"]]
    next_words = [w for w in words if w["s"] >= last["e"]]
    cut_in = first["s"] - pad_in
    if prev_words:
        cut_in = max(cut_in, prev_words[-1]["e"] + 0.02)
    cut_out = last["e"] + pad_out
    if next_words:
        cut_out = min(cut_out, next_words[0]["s"] - 0.02)
    cut_in = max(0.0, cut_in)
    if duration:
        cut_out = min(duration, cut_out)
    return round(cut_in, 3), round(max(cut_out, cut_in + 0.1), 3)


def _resolve(ref: Any, index: dict, source: str, which: str) -> float:
    if isinstance(ref, (int, float)):
        return float(ref)
    if isinstance(ref, str) and ref.upper().startswith("P"):
        phrase = index.get(source, {}).get(ref.upper())
        if not phrase:
            raise VeditError(f"Phrase {ref} not found for source {source} (see takes_index.json)")
        return phrase["s"] if which == "from" else phrase["e"]
    return float(ref)


def apply_keeps(edit: Edit, keeps: list[dict], *, index_path: str | None = None, replace: bool = True) -> Edit:
    index = read_json(index_path, default={}) if index_path else {}
    clips: list[Clip] = [] if replace else list(edit.main)
    for n, item in enumerate(keeps, len(clips) + 1):
        sid = item["source"]
        if sid not in edit.sources:
            raise VeditError(f"Unknown source '{sid}'")
        src = edit.sources[sid]
        start = _resolve(item.get("from", item.get("start")), index, sid, "from")
        end = _resolve(item.get("to", item.get("end")), index, sid, "to")
        if not item.get("exact") and src.transcript:
            start, end = snap_range(transcript_words(src.transcript), start, end, duration=src.duration or None)
        clip = Clip(id=item.get("id") or f"m{n:03d}", source=sid, src_in=start, src_out=end,
                    speed=item.get("speed", 1.0), label=item.get("label", ""))
        if item.get("zoom"):
            clip.zoom = Zoom(**item["zoom"]) if isinstance(item["zoom"], dict) else Zoom(end_scale=float(item["zoom"]))
        if item.get("transition"):
            tr = item["transition"]
            clip.transition_in = Transition(**tr) if isinstance(tr, dict) else Transition(type=str(tr))
        for key in ("volume", "fit", "color", "capcut_filter", "mute"):
            if key in item:
                setattr(clip, key, item[key])
        clips.append(clip)
    edit.main = clips
    return edit.layout()


def auto_keeps(source_id: str, transcript_path: str, *, max_pause: float = 0.30, drop_fillers: bool = True,
               min_keep: float = 0.4) -> list[dict]:
    """Rough cut: keep speech, drop long pauses and hard fillers. Claude then removes retakes/tangents."""
    words = transcript_words(transcript_path)
    if drop_fillers:
        words = [w for w in words if _norm(w["w"]) not in HARD_FILLERS]
    keeps: list[dict] = []
    cur_s = cur_e = None
    for w in words:
        if cur_s is None:
            cur_s, cur_e = w["s"], w["e"]
        elif w["s"] - cur_e > max_pause:
            if cur_e - cur_s >= min_keep:
                keeps.append({"source": source_id, "from": cur_s, "to": cur_e})
            cur_s, cur_e = w["s"], w["e"]
        else:
            cur_e = w["e"]
    if cur_s is not None and cur_e - cur_s >= min_keep:
        keeps.append({"source": source_id, "from": cur_s, "to": cur_e})
    return keeps


def removed_summary(edit: Edit) -> dict:
    """How much was cut per source (for the storyboard and the user's sanity)."""
    out: dict[str, dict] = {}
    for sid, src in edit.sources.items():
        if src.kind != "video" and src.kind != "audio":
            continue
        kept = sum(c.src_out - c.src_in for c in edit.main if c.source == sid)
        if kept or any(c.source == sid for c in edit.main):
            out[sid] = {"source_s": round(src.duration, 2), "kept_s": round(kept, 2),
                        "removed_pct": round(100 * (1 - kept / src.duration), 1) if src.duration else None}
    return out
