"""Suggestion cards and creative directions: how Claude offers choices instead of making every call alone.

edit/suggestions.json
  {"items": [{"id", "kind", "title", "reason", "at": {"start", "end"} | null, "anchor": {...} | null,
              "options": [{"id", "label", "description", "ops": [<ops.py ops>], "preview": {...}}],
              "default": "<option id>", "status": "open|accepted|rejected", "chosen": "<option id>"}]}
  kind: hook | cut | broll | graphic | sfx | music | zoom | caption | transition | grade | text | vfx | voice | other

edit/directions.json   (plan mode opens with 2-3 of these)
  {"items": [{"id", "title", "treatment", "hook", "pacing", "look", "sound", "captions",
              "moodboard": [{"src", "credit", "url"}], "ops": [...]}], "chosen": "<id>" | null}

Accepting an option applies its ops (ops.py), so every card is a concrete, reversible edit.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .project import Project
from .util import VeditError, read_json, write_json

KINDS = ("hook", "cut", "broll", "graphic", "sfx", "music", "zoom", "caption", "transition", "grade", "text", "vfx",
         "voice", "other")


class _M(BaseModel):
    model_config = ConfigDict(extra="allow")


class Option(_M):
    id: str
    label: str
    description: str = ""
    ops: list[dict[str, Any]] = Field(default_factory=list)
    preview: dict[str, Any] = Field(default_factory=dict)


class Suggestion(_M):
    id: str
    kind: str = "other"
    title: str
    reason: str = ""
    at: Optional[dict[str, float]] = None
    anchor: Optional[dict[str, Any]] = None
    options: list[Option] = Field(default_factory=list)
    default: Optional[str] = None
    status: Literal["open", "accepted", "rejected"] = "open"
    chosen: Optional[str] = None


class Direction(_M):
    id: str
    title: str
    treatment: str = ""
    hook: str = ""
    pacing: str = ""
    look: str = ""
    sound: str = ""
    captions: str = ""
    moodboard: list[dict[str, Any]] = Field(default_factory=list)
    ops: list[dict[str, Any]] = Field(default_factory=list)


def _sug_path(p: Project):
    return p.root / "suggestions.json"


def _dir_path(p: Project):
    return p.root / "directions.json"


def load_suggestions(p: Project) -> dict:
    return read_json(_sug_path(p), default={"items": []}) or {"items": []}


def load_directions(p: Project) -> dict:
    return read_json(_dir_path(p), default={"items": [], "chosen": None}) or {"items": [], "chosen": None}


def save_suggestions(p: Project, data: dict) -> None:
    data["items"] = [Suggestion.model_validate(s).model_dump(mode="json", exclude_none=True) for s in data.get("items", [])]
    write_json(_sug_path(p), data)


def save_directions(p: Project, data: dict) -> None:
    data["items"] = [Direction.model_validate(x).model_dump(mode="json", exclude_none=True) for x in data.get("items", [])]
    write_json(_dir_path(p), data)


def add_suggestions(p: Project, items: list[dict], *, replace: bool = False) -> dict:
    data = {"items": []} if replace else load_suggestions(p)
    ids = {s["id"] for s in data["items"]}
    for raw in items:
        s = Suggestion.model_validate(raw)
        if s.kind not in KINDS:
            raise VeditError(f"Suggestion {s.id}: unknown kind '{s.kind}'. Kinds: {', '.join(KINDS)}")
        if not s.options:
            raise VeditError(f"Suggestion {s.id} needs at least one option (each option carries the ops it applies).")
        if s.id in ids:
            data["items"] = [x for x in data["items"] if x["id"] != s.id]
        data["items"].append(s.model_dump(mode="json", exclude_none=True))
        ids.add(s.id)
    save_suggestions(p, data)
    return data


def add_directions(p: Project, items: list[dict], *, replace: bool = True) -> dict:
    data = {"items": [], "chosen": None} if replace else load_directions(p)
    data["items"] += [Direction.model_validate(x).model_dump(mode="json", exclude_none=True) for x in items]
    save_directions(p, data)
    return data


def decide(p: Project, suggestion_id: str, option_id: str | None) -> dict:
    """Accept (option_id) or reject (None) one card, applying its ops to edit.json."""
    from .ops import apply_ops
    op = {"op": "accept", "suggestion": suggestion_id, "option": option_id} if option_id else \
        {"op": "reject", "suggestion": suggestion_id}
    sug = load_suggestions(p)
    edit, report = apply_ops(p.edit(), [op], suggestions=sug)
    if report["errors"]:
        raise VeditError(report["errors"][0]["error"])
    p.save_edit(edit)
    save_suggestions(p, sug)
    return report


# ------------------------------------------------------------------ CLI

def register_cli(sp) -> None:
    s = sp.add_parser("suggest", help="Studio suggestion cards (each option = concrete ops)")
    s.add_argument("action", choices=["list", "add", "accept", "reject", "clear"])
    s.add_argument("path"); s.add_argument("id", nargs="?"); s.add_argument("option", nargs="?")
    s.add_argument("--file", help="add: JSON file with a list of suggestions"); s.add_argument("--replace", action="store_true")
    s.add_argument("--status", choices=["open", "accepted", "rejected"])
    s.set_defaults(fn=_cmd_suggest)
    s = sp.add_parser("directions", help="creative directions offered at the start of plan mode")
    s.add_argument("action", choices=["list", "add", "choose"])
    s.add_argument("path"); s.add_argument("id", nargs="?"); s.add_argument("--file"); s.add_argument("--append", action="store_true")
    s.set_defaults(fn=_cmd_directions)


def _cmd_suggest(a) -> None:
    from .project import find
    from .util import print_json
    p = find(a.path)
    if a.action == "list":
        items = load_suggestions(p)["items"]
        if a.status:
            items = [s for s in items if s.get("status", "open") == a.status]
        print_json([{"id": s["id"], "kind": s["kind"], "title": s["title"], "status": s.get("status", "open"),
                     "options": [o["id"] for o in s["options"]], "chosen": s.get("chosen")} for s in items])
    elif a.action == "add":
        raw = read_json(a.file)
        data = add_suggestions(p, raw if isinstance(raw, list) else raw.get("items", []), replace=a.replace)
        print_json({"suggestions": len(data["items"])})
    elif a.action in ("accept", "reject"):
        print_json(decide(p, a.id, a.option if a.action == "accept" else None))
    else:
        save_suggestions(p, {"items": []})
        print_json({"suggestions": 0})


def _cmd_directions(a) -> None:
    from .ops import apply_ops
    from .project import find
    from .util import print_json
    p = find(a.path)
    if a.action == "list":
        print_json(load_directions(p))
    elif a.action == "add":
        raw = read_json(a.file)
        print_json(add_directions(p, raw if isinstance(raw, list) else raw.get("items", []), replace=not a.append))
    else:
        dirs = load_directions(p)
        edit, report = apply_ops(p.edit(), [{"op": "choose_direction", "id": a.id}], directions=dirs)
        if report["errors"]:
            raise VeditError(report["errors"][0]["error"])
        p.save_edit(edit)
        save_directions(p, dirs)
        p.log(f"direction chosen: {a.id}")
        print_json({"chosen": a.id, "applied": len(report["applied"])})
