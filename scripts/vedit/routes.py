"""Route planner: ranked ways to make each thing an edit needs, given what is available right now.

Routes come from presets/routes.json, personal/routes.json and personal extensions. Ranking blends the
route's own scores with availability (capabilities.available), the owner's history (accepted/rejected,
worked/failed) and their cost. Claude still decides: the planner is a starting point, and the best
results often mix routes (a Claude-drawn layout + a web-AI texture + an earshot whoosh).
"""

from __future__ import annotations

import time

from . import capabilities, extensions
from .paths import personal_dir, presets_dir
from .util import VeditError, read_json, write_json

COST = {"free": 3, "subscription": 2, "paid": 1, "credits": 0}
LICENCE = {"own": 3, "cc": 2, "stock": 2, "ai-service": 1, "check": 1}


def load() -> dict[str, list[dict]]:
    data = {k: list(v) for k, v in (read_json(presets_dir() / "routes.json", default={}) or {}).items()
            if not k.startswith("_")}
    for source in (read_json(personal_dir() / "routes.json", default={}) or {}, extensions.routes()):
        for need, items in source.items():
            if need.startswith("_"):
                continue
            existing = {r["id"] for r in data.get(need, [])}
            data.setdefault(need, []).extend(dict(r, personal=True) for r in items if r["id"] not in existing)
    return data


def _stats() -> dict:
    return read_json(personal_dir() / "learning" / "routes.json", default={}) or {}


def plan(need: str, *, caps: dict | None = None) -> list[dict]:
    routes = load()
    if need not in routes:
        raise VeditError(f"Unknown need '{need}'. Known: {', '.join(sorted(routes))}")
    caps = caps or capabilities.collect()
    stats = _stats().get(need, {})
    outcomes = caps.get("outcomes", {})
    ranked = []
    for r in routes[need]:
        missing = [req for req in r.get("requires", []) if not capabilities.available(req, caps)]
        score = 2 * r.get("quality", 3) + r.get("speed", 3) + COST.get(r.get("cost", "free"), 1) \
            + LICENCE.get(r.get("licence", "check"), 1) + (1 if r.get("privacy") == "local" else 0)
        s = stats.get(r["id"], {})
        kept, rejected = s.get("kept", 0), s.get("rejected", 0)
        if kept + rejected >= 3:
            score += 4 * (kept / (kept + rejected) - 0.5)
        fails = sum(outcomes.get(req.split("|")[0], {}).get("fail", 0) for req in r.get("requires", []))
        score -= min(3, fails)
        from .analytics import route_bonus
        bonus, perf = route_bonus(need, r["id"])        # retention measured on published videos
        score += bonus
        ranked.append({**r, "available": not missing, "missing": missing, "score": round(score, 2),
                       "history": s or None, "performance": perf, "needs_ask": r.get("cost") in ("credits", "paid")})
    ranked.sort(key=lambda x: (not x["available"], -x["score"]))
    return ranked


def log(need: str, route: str, result: str, *, project: str | None = None, note: str = "") -> dict:
    """result: used | kept | rejected | failed. Feeds ranking and the learning profile."""
    if result not in ("used", "kept", "rejected", "failed"):
        raise VeditError("result must be used | kept | rejected | failed")
    path = personal_dir() / "learning" / "routes.json"
    data = read_json(path, default={}) or {}
    s = data.setdefault(need, {}).setdefault(route, {"used": 0, "kept": 0, "rejected": 0, "failed": 0})
    s[result] += 1
    s["last"] = time.strftime("%Y-%m-%d %H:%M")
    write_json(path, data)
    from . import learn
    learn.event("route", {"need": need, "route": route, "result": result, "note": note}, project=project)
    return s


# ------------------------------------------------------------------ CLI

def register_cli(sp) -> None:
    s = sp.add_parser("route", help="rank ways to make something (icon, image, music, 3d, ...) and log outcomes")
    s.add_argument("action", choices=["needs", "plan", "log"])
    s.add_argument("need", nargs="?")
    s.add_argument("route_id", nargs="?")
    s.add_argument("result", nargs="?", choices=["used", "kept", "rejected", "failed"])
    s.add_argument("--project"); s.add_argument("--note", default="")
    s.add_argument("--all", action="store_true", help="plan: include unavailable routes")
    s.set_defaults(fn=_cmd)


def _cmd(a) -> None:
    from .util import print_json
    if a.action == "needs":
        print_json({k: [r["id"] for r in v] for k, v in load().items()})
    elif a.action == "plan":
        rows = plan(a.need)
        if not a.all:
            rows = [r for r in rows if r["available"]] + [
                {"id": r["id"], "available": False, "missing": r["missing"]} for r in rows if not r["available"]]
        print_json(rows)
    else:
        print_json(log(a.need, a.route_id, a.result, project=a.project, note=a.note))
