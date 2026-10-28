"""Edit operations: the language the Studio, suggestion cards and the engine share.

Ops act on the JSON form of edit.json, so studio/js/ops.js can mirror them exactly for the live
preview. Each op is a dict with an "op" name:

  cut_words / restore_words {source, from, to}   remove / bring back words (from = first word start,
                                                 to = last word end); boundaries land mid-gap, word-safe
  cut_range / restore_range {source, from, to}   the same with exact source times
  trim {clip, src_in?, src_out?}   split {clip, at}   delete_clip {clip}   move_clip {clip, index}
  set {path, value}            "captions.style", "color.preset", "overlays[hook].transform.y" (null deletes)
  add {list, item}   remove {list, id}   update {list, id, fields}   enable {list, id, on}
  caption_word {key, text}     fix a misheard word ("" hides it, null restores); keys are "<source>@<start>"
  caption_emphasis {key, on}   caption_emoji {key, emoji}
  knob {id, value}             Studio tuning (presets/knobs.json), applied at bake time
  accept {suggestion, option}  reject {suggestion}   choose_direction {id}
  note {text, at?}   request {what, target?, text?}   approve {stage?}   -> handed to Claude / the workflow

apply_ops() never raises for a bad op: it reports it and continues, because one stale op from the
Studio must not lose the owner's other edits.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .timeline import Edit
from .util import VeditError

LISTS = ("main", "broll", "overlays", "texts", "audio", "effects", "custom_fx")
MIN_CLIP = 0.08
EPS = 0.02
PAD_IN, PAD_OUT = 0.06, 0.12
CLAUDE_OPS = ("note", "request")


class OpError(ValueError):
    pass


# ------------------------------------------------------------------ helpers

def _words_for(edit_json: dict, sid: str) -> list[tuple[float, float]]:
    src = edit_json.get("sources", {}).get(sid) or {}
    path = src.get("transcript")
    if not path:
        return []
    from .knobs import _words
    return list(_words(path))


def word_bounds(words: list[tuple[float, float]], first_s: float, last_e: float) -> tuple[float, float]:
    """Expand a word span to mid-gap boundaries so neighbouring words keep their attack and release."""
    prev = [w for w in words if w[1] <= first_s + 1e-3]
    nxt = [w for w in words if w[0] >= last_e - 1e-3]
    lo = (prev[-1][1] + first_s) / 2 if prev else max(0.0, first_s - PAD_IN)
    hi = (last_e + nxt[0][0]) / 2 if nxt else last_e + PAD_OUT
    if prev:      # keep 20 ms of the previous word's release when there is room, never cut inside the span
        lo = min(first_s, max(lo, prev[-1][1] + 0.02))
    if nxt:
        hi = max(last_e, min(hi, nxt[0][0] - 0.02))
    return round(lo, 3), round(max(hi, lo + 0.05), 3)


def _all_ids(d: dict) -> set[str]:
    return {it.get("id") for name in LISTS for it in d.get(name, []) if isinstance(it, dict)}


def _new_id(d: dict, base: str) -> str:
    ids = _all_ids(d)
    n = 2
    while f"{base}.{n}" in ids:
        n += 1
    return f"{base}.{n}"


def _find(d: dict, list_name: str, item_id: str) -> tuple[list, int]:
    if list_name not in LISTS:
        raise OpError(f"unknown list '{list_name}'")
    items = d.setdefault(list_name, [])
    for i, it in enumerate(items):
        if it.get("id") == item_id:
            return items, i
    raise OpError(f"no {list_name} item '{item_id}'")


def _clip(d: dict, clip_id: str) -> tuple[list, int]:
    for name in ("main", "broll"):
        for i, c in enumerate(d.get(name, [])):
            if c.get("id") == clip_id:
                return d[name], i
    raise OpError(f"no clip '{clip_id}'")


def _deep_merge(base: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if v is None:
            base.pop(k, None)
        elif isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


_SEG = re.compile(r"([A-Za-z_][\w]*)(?:\[([^\]]+)\])?")


def _walk_path(d: dict, path: str) -> tuple[Any, str]:
    """Return (container, final key) for a path like 'overlays[hook].transform.y'."""
    parts = path.split(".")
    node: Any = d
    for i, part in enumerate(parts):
        m = _SEG.fullmatch(part)
        if not m:
            raise OpError(f"bad path segment '{part}'")
        key, sel = m.group(1), m.group(2)
        last = i == len(parts) - 1
        if sel is not None:
            items = node.setdefault(key, [])
            match = next((it for it in items if str(it.get("id")) == sel), None)
            if match is None:
                raise OpError(f"no item '{sel}' in {key}")
            if last:
                raise OpError("path must end with a field, not a list item")
            node = match
        elif last:
            return node, key
        else:
            node = node.setdefault(key, {})
    raise OpError("empty path")


# ------------------------------------------------------------------ cut operations

def cut_range(d: dict, sid: str, lo: float, hi: float) -> None:
    out = []
    for c in d.get("main", []):
        if c["source"] != sid or c["src_out"] <= lo or c["src_in"] >= hi:
            out.append(c)
            continue
        left = (c["src_in"], min(c["src_out"], lo)) if c["src_in"] < lo else None
        right = (max(c["src_in"], hi), c["src_out"]) if c["src_out"] > hi else None
        if left and left[1] - left[0] >= MIN_CLIP:
            a = copy.deepcopy(c)
            a["src_out"] = round(left[1], 3)
            if right:
                a.pop("fade_out", None)
            out.append(a)
        if right and right[1] - right[0] >= MIN_CLIP:
            b = copy.deepcopy(c)
            b["src_in"] = round(right[0], 3)
            if left and left[1] - left[0] >= MIN_CLIP:
                b["id"] = _new_id({"main": out + d.get("main", []), "broll": d.get("broll", [])}, c["id"])
                b.pop("transition_in", None)
                b.pop("fade_in", None)
            out.append(b)
    d["main"] = out


def _subtract(lo: float, hi: float, covered: list[tuple[float, float]]) -> list[tuple[float, float]]:
    gaps, cur = [], lo
    for s, e in sorted(covered):
        if e <= cur or s >= hi:
            continue
        if s > cur:
            gaps.append((cur, min(s, hi)))
        cur = max(cur, e)
    if cur < hi:
        gaps.append((cur, hi))
    return [(round(a, 3), round(b, 3)) for a, b in gaps if b - a >= MIN_CLIP / 2]


def _mergeable(a: dict, b: dict) -> bool:
    keys = ("speed", "zoom", "transform", "crop", "fit", "volume", "mute", "color")
    return not b.get("transition_in") and all(a.get(k) == b.get(k) for k in keys)


def restore_range(d: dict, sid: str, lo: float, hi: float) -> None:
    main = d.setdefault("main", [])
    covered = [(c["src_in"], c["src_out"]) for c in main if c["source"] == sid]
    for g0, g1 in _subtract(lo, hi, covered):
        prev = next((c for c in main if c["source"] == sid and abs(c["src_out"] - g0) < EPS), None)
        nxt = next((c for c in main if c["source"] == sid and abs(c["src_in"] - g1) < EPS), None)
        if prev and nxt and main.index(nxt) == main.index(prev) + 1 and _mergeable(prev, nxt):
            prev["src_out"] = nxt["src_out"]
            main.remove(nxt)
        elif prev:
            prev["src_out"] = g1
        elif nxt:
            nxt["src_in"] = g0
        else:
            item = {"id": _new_id(d, f"r_{sid}"), "source": sid, "src_in": g0, "src_out": g1, "label": "restored"}
            before = [i for i, c in enumerate(main) if c["source"] == sid and c["src_out"] <= g0 + EPS]
            after = [i for i, c in enumerate(main) if c["source"] == sid and c["src_in"] >= g1 - EPS]
            pos = before[-1] + 1 if before else (after[0] if after else len(main))
            main.insert(pos, item)


# ------------------------------------------------------------------ dispatcher

def _apply(d: dict, op: dict, ctx: dict, report: dict, depth: int = 0) -> None:
    name = op.get("op")
    if depth > 3:
        raise OpError("nested accept too deep")
    if name in ("cut_words", "restore_words"):
        words = _words_for(d, op["source"])
        lo, hi = word_bounds(words, float(op["from"]), float(op["to"])) if words else (float(op["from"]), float(op["to"]))
        (cut_range if name == "cut_words" else restore_range)(d, op["source"], lo, hi)
        report["captions_dirty"] = True
    elif name in ("cut_range", "restore_range"):
        (cut_range if name == "cut_range" else restore_range)(d, op["source"], float(op["from"]), float(op["to"]))
        report["captions_dirty"] = True
    elif name == "trim":
        items, i = _clip(d, op["clip"])
        c = items[i]
        s = float(op.get("src_in", c["src_in"]))
        e = float(op.get("src_out", c["src_out"]))
        if e - s < MIN_CLIP:
            raise OpError("trim would leave the clip shorter than 0.08 s")
        c["src_in"], c["src_out"] = round(s, 3), round(e, 3)
        report["captions_dirty"] = True
    elif name == "split":
        items, i = _clip(d, op["clip"])
        c = items[i]
        at = float(op["at"])
        if not c["src_in"] + MIN_CLIP <= at <= c["src_out"] - MIN_CLIP:
            raise OpError("split point outside the clip")
        b = copy.deepcopy(c)
        b["id"] = _new_id(d, c["id"])
        b["src_in"] = round(at, 3)
        b.pop("transition_in", None)
        b.pop("fade_in", None)
        c["src_out"] = round(at, 3)
        c.pop("fade_out", None)
        items.insert(i + 1, b)
        report.setdefault("created", []).append(b["id"])
    elif name == "delete_clip":
        items, i = _clip(d, op["clip"])
        items.pop(i)
        report["captions_dirty"] = True
    elif name == "move_clip":
        items, i = _clip(d, op["clip"])
        c = items.pop(i)
        items.insert(max(0, min(len(items), int(op["index"]))), c)
        report["captions_dirty"] = True
    elif name == "set":
        node, key = _walk_path(d, op["path"])
        if op.get("value") is None:
            node.pop(key, None)
        else:
            node[key] = copy.deepcopy(op["value"])
        if op["path"].startswith(("captions", "main")):
            report["captions_dirty"] = True
    elif name == "add":
        lst = op["list"]
        if lst not in LISTS:
            raise OpError(f"unknown list '{lst}'")
        item = copy.deepcopy(op["item"])
        if not item.get("id") or item["id"] in _all_ids(d):
            item["id"] = _new_id(d, item.get("id") or (lst[:-1] if lst.endswith("s") else lst))
        d.setdefault(lst, []).append(item)
        report.setdefault("created", []).append(item["id"])
    elif name == "remove":
        items, i = _find(d, op["list"], op["id"])
        items.pop(i)
    elif name == "update":
        items, i = _find(d, op["list"], op["id"])
        _deep_merge(items[i], op.get("fields") or {})
    elif name == "enable":
        items, i = _find(d, op["list"], op["id"])
        items[i]["enabled"] = bool(op.get("on", True))
    elif name == "caption_word":
        fixes = d.setdefault("captions", {}).setdefault("word_fixes", {})
        if op.get("text") is None:
            fixes.pop(op["key"], None)
        else:
            fixes[op["key"]] = str(op["text"])
        report["captions_dirty"] = True
    elif name == "caption_emphasis":
        keys = d.setdefault("captions", {}).setdefault("emphasis_keys", [])
        if op.get("on", True) and op["key"] not in keys:
            keys.append(op["key"])
        elif not op.get("on", True) and op["key"] in keys:
            keys.remove(op["key"])
        report["captions_dirty"] = True
    elif name == "caption_emoji":
        emo = d.setdefault("captions", {}).setdefault("emoji_keys", {})
        if op.get("emoji"):
            emo[op["key"]] = op["emoji"]
        else:
            emo.pop(op["key"], None)
        report["captions_dirty"] = True
    elif name == "knob":
        from .knobs import definitions
        if op["id"] not in definitions():
            raise OpError(f"unknown knob '{op['id']}'")
        knobs = d.setdefault("knobs", {})
        if op.get("value") is None:
            knobs.pop(op["id"], None)
        else:
            knobs[op["id"]] = op["value"]
    elif name in ("accept", "reject"):
        sug = ctx.get("suggestions") or {"items": []}
        item = next((s for s in sug.get("items", []) if s.get("id") == op["suggestion"]), None)
        if item is None:
            raise OpError(f"no suggestion '{op['suggestion']}'")
        if name == "accept":
            option = next((o for o in item.get("options", []) if o.get("id") == op.get("option")), None)
            if option is None:
                raise OpError(f"suggestion '{item['id']}' has no option '{op.get('option')}'")
            for sub in option.get("ops", []):
                _apply(d, sub, ctx, report, depth + 1)
            item["status"], item["chosen"] = "accepted", option["id"]
        else:
            item["status"] = "rejected"
        report.setdefault("learn_context", []).append({"suggestion_kind": item.get("kind"),
                                                       "suggestion_title": item.get("title")})
        ctx["suggestions_dirty"] = True
    elif name == "choose_direction":
        dirs = ctx.get("directions") or {"items": []}
        item = next((x for x in dirs.get("items", []) if x.get("id") == op["id"]), None)
        if item is None:
            raise OpError(f"no direction '{op['id']}'")
        for sub in item.get("ops", []):
            _apply(d, sub, ctx, report, depth + 1)
        dirs["chosen"] = item["id"]
        report.setdefault("learn_context", []).append({"direction_title": item.get("title")})
        ctx["directions_dirty"] = True
    elif name in CLAUDE_OPS:
        report["pending"].append(op)
        return
    elif name == "approve":
        report.setdefault("workflow", []).append(op)
        return
    else:
        raise OpError(f"unknown op '{name}'")


def apply_ops(edit: Edit, ops: list[dict], *, suggestions: dict | None = None,
              directions: dict | None = None) -> tuple[Edit, dict]:
    """Apply ops in order. Returns (new edit, report). Bad ops are reported and skipped."""
    d = edit.model_dump(mode="json", exclude_none=True)
    ctx = {"suggestions": suggestions, "directions": directions}
    report: dict[str, Any] = {"applied": [], "pending": [], "errors": [], "captions_dirty": False}
    for op in ops:
        before = copy.deepcopy(d)
        try:
            _apply(d, op, ctx, report)
            if op.get("op") not in CLAUDE_OPS + ("approve",):
                Edit.model_validate(d)            # validate after each op so one bad op can be skipped
                report["applied"].append(op)
        except (OpError, KeyError, TypeError, ValueError) as exc:
            d = before
            report["errors"].append({"op": op, "error": str(exc) or exc.__class__.__name__})
    report["suggestions_dirty"] = bool(ctx.get("suggestions_dirty"))
    report["directions_dirty"] = bool(ctx.get("directions_dirty"))
    try:
        new = Edit.model_validate(d).layout()
    except Exception as exc:                       # should not happen: every op was validated
        raise VeditError(f"Edit became invalid after ops: {exc}") from exc
    return new, report
