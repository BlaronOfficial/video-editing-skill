"""Learning: every decision the owner makes teaches the next edit.

Sources
  studio    ops from the Studio (accept/reject suggestions, knob values, trims, word fixes, directions)
  route     which ways of making things were kept or rejected (routes.log)
  diff      what the owner changed after a hand-off (CapCut today; Resolve/NLE/LLC in phase 3)
  chat      plain-language rules ("captions bigger", "never use whooshes") via `vedit learn note`
  analytics YouTube retention/CTR per published edit (phase 5)

Storage (git-ignored): personal/learning/events.jsonl (append-only), personal/profile.json (aggregate,
rebuilt from events), personal/rules.md (rules Claude reads at intake). Scopes: global, style:<name>,
brand:<name>, format:<ratio>.
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .paths import personal_dir
from .util import read_json, write_json


def _dir() -> Path:
    path = personal_dir() / "learning"
    path.mkdir(parents=True, exist_ok=True)
    return path


def event(kind: str, data: dict[str, Any], *, project: str | None = None, scope: dict[str, str] | None = None) -> None:
    from . import config
    if kind == "studio" and not config.load().get("learning", {}).get("studio", True):
        return
    rec = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "project": project, "scope": scope or {}, **data}
    with open(_dir() / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def events(tail: int | None = None) -> list[dict]:
    path = _dir() / "events.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-tail:] if tail else rows


def note(rule: str, scope: str = "global") -> Path:
    """Add a plain-language rule. Claude reads personal/rules.md before every new project."""
    path = personal_dir() / "rules.md"
    head = "" if path.exists() else "# Editing rules learned from the owner\n\nApplied at intake. Scope in brackets.\n\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(head + f"- [{scope}] {rule.strip()}  _(added {time.strftime('%Y-%m-%d')})_\n")
    event("chat", {"rule": rule, "scope_name": scope})
    return path


def rules() -> str:
    path = personal_dir() / "rules.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def rebuild() -> dict:
    """Aggregate events into personal/profile.json (knob medians, acceptance per suggestion kind, favourites)."""
    knobs: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    kinds: dict[str, Counter] = defaultdict(Counter)
    templates: Counter = Counter()
    sfx: Counter = Counter()
    styles: Counter = Counter()
    directions: Counter = Counter()
    fixes = 0
    for ev in events():
        scope = ev.get("scope") or {}
        keys = ["global"] + [f"{k}:{v}" for k, v in scope.items() if v]
        if ev["kind"] != "studio":
            continue
        op = ev.get("op", {})
        name = op.get("op")
        if name == "knob":
            for k in keys:
                knobs[k][op.get("id")].append(op.get("value"))
        elif name in ("accept", "reject"):
            kind = ev.get("suggestion_kind", "other")
            kinds[kind]["accepted" if name == "accept" else "rejected"] += 1
            if name == "accept" and ev.get("template"):
                templates[ev["template"]] += 1
            if name == "accept" and ev.get("sfx_id"):
                sfx[ev["sfx_id"]] += 1
        elif name == "set" and op.get("path") == "captions.style":
            styles[op.get("value")] += 1
        elif name == "choose_direction":
            directions[ev.get("direction_title", op.get("id"))] += 1
        elif name == "caption_word":
            fixes += 1

    def median(vals: list) -> Any:
        nums = sorted(v for v in vals if isinstance(v, (int, float)))
        if nums:
            return nums[len(nums) // 2]
        return Counter(v for v in vals if v is not None).most_common(1)[0][0] if vals else None

    profile = {
        "rebuilt": time.strftime("%Y-%m-%d %H:%M"),
        "knobs": {scope: {k: median(v) for k, v in vals.items()} for scope, vals in knobs.items()},
        "suggestions": {k: {**c, "rate": round(c["accepted"] / max(1, c["accepted"] + c["rejected"]), 2)}
                        for k, c in kinds.items()},
        "favourite_templates": [t for t, _ in templates.most_common(8)],
        "favourite_sfx": [s for s, _ in sfx.most_common(12)],
        "caption_styles": [s for s, _ in styles.most_common(4)],
        "directions_chosen": [d for d, _ in directions.most_common(6)],
        "caption_word_fixes": fixes,
        "routes": read_json(_dir() / "routes.json", default={}) or {},
    }
    write_json(personal_dir() / "profile.json", profile)
    return profile


def profile(*, style: str | None = None, brand: str | None = None, ratio: str | None = None) -> dict:
    """Knob defaults for a new edit: global, overridden by style, brand and format, plus rules text."""
    prof = read_json(personal_dir() / "profile.json", default=None) or rebuild()
    merged: dict[str, Any] = dict(prof.get("knobs", {}).get("global", {}))
    for scope in (f"style:{style}" if style else None, f"brand:{brand}" if brand else None,
                  f"format:{ratio}" if ratio else None):
        if scope:
            merged.update(prof.get("knobs", {}).get(scope, {}))
    return {"knobs": merged, "suggestions": prof.get("suggestions", {}),
            "favourite_templates": prof.get("favourite_templates", []), "favourite_sfx": prof.get("favourite_sfx", []),
            "caption_styles": prof.get("caption_styles", []), "rules": rules()}


# ------------------------------------------------------------------ CLI

def register_cli(sp) -> None:
    s = sp.add_parser("learn", help="preferences learned from Studio decisions, edits and feedback")
    s.add_argument("action", choices=["note", "profile", "rebuild", "events", "rules"])
    s.add_argument("text", nargs="?")
    s.add_argument("--scope", default="global", help="global | style:<name> | brand:<name> | format:<ratio>")
    s.add_argument("--style"); s.add_argument("--brand"); s.add_argument("--ratio")
    s.add_argument("--tail", type=int, default=30)
    s.set_defaults(fn=_cmd)


def _cmd(a) -> None:
    from .util import VeditError, print_json
    if a.action == "note":
        if not a.text:
            raise VeditError('Give the rule: vedit learn note "captions one size bigger on 9:16"')
        print_json({"rules": str(note(a.text, a.scope))})
    elif a.action == "profile":
        print_json(profile(style=a.style, brand=a.brand, ratio=a.ratio))
    elif a.action == "rebuild":
        print_json(rebuild())
    elif a.action == "rules":
        print(rules() or "(no rules yet)")
    else:
        print_json(events(a.tail))
