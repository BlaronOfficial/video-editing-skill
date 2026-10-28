"""Studio knobs, applied non-destructively at bake time.

edit.json keeps the editorial decisions exactly as Claude (and the owner) made them; `edit.knobs` holds
tuning values (pace, zoom strength, levels, caption size, look...). `bake(edit)` returns the effective
edit that every output uses: render, CapCut, NLE exports, QA, and (mirrored in studio/js/bake.js) the
Studio's live preview. Changing a knob therefore never destroys the cut, and the two sides agree.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .paths import presets_dir
from .timeline import Clip, Edit, Transition
from .util import read_json

PAUSE_NATURAL = 1.2      # pace 0: keep pauses up to this long
PAUSE_TIGHT = 0.18       # pace 1: cut pauses longer than this
PAD_IN, PAD_OUT = 0.06, 0.12
MIN_PIECE = 0.12


@lru_cache(maxsize=1)
def definitions() -> dict[str, dict]:
    defs = {k: v for k, v in (read_json(presets_dir() / "knobs.json", default={}) or {}).items() if not k.startswith("_")}
    from .captions import list_presets
    for d in defs.values():
        if d.get("options") == "@caption_presets":
            d["options"] = sorted(list_presets())
    return defs


def max_pause(pace: float) -> float:
    pace = min(1.0, max(0.0, float(pace)))
    return round(PAUSE_NATURAL + (PAUSE_TIGHT - PAUSE_NATURAL) * pace, 3)


@lru_cache(maxsize=32)
def _words(path: str) -> tuple[tuple[float, float], ...]:
    from .captions import transcript_words
    return tuple((w["s"], w["e"]) for w in transcript_words(path))


def _pace_split(edit: Edit, limit: float) -> list[Clip]:
    """Split each main clip at internal pauses longer than `limit`, keeping word-safe pads."""
    out: list[Clip] = []
    for clip in edit.main:
        src = edit.sources[clip.source]
        if not src.transcript or clip.speed != 1.0:
            out.append(clip)
            continue
        words = [w for w in _words(src.transcript) if clip.src_in <= (w[0] + w[1]) / 2 <= clip.src_out]
        pieces: list[tuple[float, float]] = []
        start = clip.src_in
        for a, b in zip(words, words[1:]):
            gap = b[0] - a[1]
            if gap > limit:
                end = min(a[1] + PAD_OUT, a[1] + gap / 2)
                pieces.append((start, end))
                start = max(b[0] - PAD_IN, b[0] - gap / 2)
        pieces.append((start, clip.src_out))
        pieces = [(s, e) for s, e in pieces if e - s >= MIN_PIECE]
        if len(pieces) <= 1:
            out.append(clip)
            continue
        for n, (s, e) in enumerate(pieces):
            piece = clip.model_copy(deep=True)
            piece.id = clip.id if n == 0 else f"{clip.id}.p{n}"
            piece.src_in, piece.src_out = round(s, 3), round(e, 3)
            if n:
                piece.transition_in = None
                piece.fade_in = 0.0
            if n < len(pieces) - 1:
                piece.fade_out = 0.0
            out.append(piece)
    return out


def bake(edit: Edit) -> Edit:
    """The effective edit: knobs applied, anchors resolved, captions rebuilt for the baked timing."""
    k: dict[str, Any] = edit.knobs or {}
    e = edit.model_copy(deep=True)
    if k.get("pace") is not None:
        e.main = _pace_split(e, max_pause(k["pace"]))
    tr = k.get("transitions")
    if tr and tr != "keep":
        for n, clip in enumerate(e.main):
            clip.transition_in = None if tr == "none" or n == 0 else Transition(type=tr, duration=0.25)
    e.layout()
    z = k.get("zoom_strength")
    if z is not None:
        for clip in [*e.main, *e.broll]:
            if clip.zoom:
                clip.zoom.start_scale = round(1 + (clip.zoom.start_scale - 1) * z, 4)
                clip.zoom.end_scale = round(1 + (clip.zoom.end_scale - 1) * z, 4)
    if k.get("voice_level") is not None:
        for clip in e.main:
            clip.volume = round(clip.volume * k["voice_level"], 4)
    for knob, roles in (("music_level", ("music", "ambience")), ("sfx_level", ("sfx",))):
        if k.get(knob) is not None:
            for a in e.audio:
                if a.role in roles:
                    a.volume = round(a.volume * k[knob], 4)
    if k.get("duck_db") is not None:
        e.output.audio.duck_db = float(k["duck_db"])
    if k.get("grade_preset") is not None:
        e.color.preset = None if k["grade_preset"] == "none" else k["grade_preset"]
    if k.get("grade_intensity") is not None:
        e.color.intensity = float(k["grade_intensity"])
    if k.get("graphics_on") is False:
        e.overlays = []
        e.texts = []
    cap = e.captions
    if k.get("captions_on") is not None:
        cap.enabled = bool(k["captions_on"])
    if k.get("caption_style"):
        cap.style = k["caption_style"]
    if k.get("caption_size") is not None:
        cap.overrides = {**cap.overrides, "size_scale": float(k["caption_size"]) * float(cap.overrides.get("size_scale", 1.0))}
    if k.get("caption_y") is not None:
        cap.overrides = {**cap.overrides, "y": float(k["caption_y"]), "y_landscape": float(k["caption_y"])}
    if k.get("caption_words") is not None:
        cap.max_words = int(k["caption_words"])
    stored = edit.captions.chunks
    legacy = bool(stored) and not any(w.k for c in stored for w in c.words)      # v1 chunks, hand-tuned
    retime = any(k.get(x) is not None for x in ("pace", "caption_words", "caption_style"))
    if cap.enabled and cap.from_words and any(s.transcript for s in e.sources.values()) and \
            (not stored or not legacy or retime):
        from .captions import build_chunks
        by_key = {c.words[0].k: c for c in edit.captions.chunks if c.words and c.words[0].k}
        cap.chunks = build_chunks(e)
        for c in cap.chunks:                 # keep per-chunk placement Claude set by hand
            old = by_key.get(c.words[0].k) if c.words else None
            if old is not None and old.y is not None:
                c.y = old.y
    return e


# ------------------------------------------------------------------ CLI

def register_cli(sp) -> None:
    s = sp.add_parser("knobs", help="Studio tuning knobs (applied at bake time) and the baked timeline")
    s.add_argument("action", choices=["list", "get", "set", "unset", "bake"])
    s.add_argument("path", nargs="?"); s.add_argument("knob", nargs="?"); s.add_argument("value", nargs="?")
    s.set_defaults(fn=_cmd)


def _cmd(a) -> None:
    import json
    from .project import find
    from .util import VeditError, print_json
    if a.action == "list":
        print_json(definitions())
        return
    if not a.path:
        raise VeditError("Give the project path.")
    p = find(a.path)
    e = p.edit()
    if a.action == "get":
        print_json(e.knobs)
    elif a.action in ("set", "unset"):
        if a.knob not in definitions():
            raise VeditError(f"Unknown knob '{a.knob}'. Known: {', '.join(definitions())}")
        if a.action == "unset":
            e.knobs.pop(a.knob, None)
        else:
            try:
                e.knobs[a.knob] = json.loads(a.value)
            except (TypeError, json.JSONDecodeError):
                e.knobs[a.knob] = a.value
        p.save_edit(e)
        from . import learn
        learn.event("studio", {"op": {"op": "knob", "id": a.knob, "value": e.knobs.get(a.knob)}, "via": "cli"},
                    project=e.name, scope={"style": e.style or "", "brand": e.brand or "", "format": e.canvas.ratio})
        print_json(e.knobs)
    else:
        b = bake(e)
        print_json({"duration": round(b.duration, 3), "main": [{"id": c.id, "start": round(c.start or 0, 3),
                    "dur": round(c.duration, 3), "src": [c.src_in, c.src_out]} for c in b.main],
                    "captions": len(b.captions.chunks), "knobs": e.knobs})
