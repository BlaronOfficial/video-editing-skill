"""Working modes and the approval gate.

  plan   (default) understand -> creative directions -> draft -> critique loop -> Studio -> iterate until
         approved. No final render, no hand-offs, no paid spend.
  step   the same Studio, gated stage by stage: cut -> captions -> graphics -> sound -> look -> final.
  auto   plan + execute without stopping; the Studio is published afterwards for review.
  execute is an action, not a mode: it needs plan_status=approved (or force on explicit request).

State lives in project.json under "workflow" so a later session (or the Claude app) continues correctly.
"""

from __future__ import annotations

import time

from . import config
from .project import Project
from .util import VeditError

MODES = ("plan", "step", "auto")
STAGES = ("cut", "captions", "graphics", "sound", "look", "final")
STATUSES = ("draft", "in_review", "changes_requested", "approved", "executed")


def state(proj: Project) -> dict:
    meta = proj.meta()
    wf = meta.get("workflow") or {}
    wf.setdefault("mode", config.load().get("mode", {}).get("default", "plan"))
    wf.setdefault("plan_status", "draft")
    wf.setdefault("stage", STAGES[0])
    wf.setdefault("approved_stages", [])
    wf.setdefault("history", [])
    return wf


def _save(proj: Project, wf: dict, note: str) -> dict:
    wf["history"] = (wf.get("history", []) + [{"at": time.strftime("%Y-%m-%d %H:%M"), "note": note}])[-50:]
    meta = proj.meta()
    meta["workflow"] = wf
    proj.save_meta(meta)
    return wf


def set_mode(proj: Project, mode: str) -> dict:
    if mode not in MODES:
        raise VeditError(f"Unknown mode '{mode}'. Use one of: {', '.join(MODES)}")
    wf = state(proj)
    wf["mode"] = mode
    return _save(proj, wf, f"mode -> {mode}")


def set_status(proj: Project, status: str, note: str = "") -> dict:
    if status not in STATUSES:
        raise VeditError(f"Unknown status '{status}'. Use one of: {', '.join(STATUSES)}")
    wf = state(proj)
    wf["plan_status"] = status
    if status == "approved":
        wf["approved_at"] = time.strftime("%Y-%m-%d %H:%M")
    return _save(proj, wf, f"status -> {status}" + (f": {note}" if note else ""))


def approve(proj: Project, stage: str | None = None) -> dict:
    """Approve the plan, or (step mode) one stage; approving 'final' approves the plan."""
    wf = state(proj)
    if stage:
        if stage not in STAGES:
            raise VeditError(f"Unknown stage '{stage}'. Stages: {', '.join(STAGES)}")
        if stage not in wf["approved_stages"]:
            wf["approved_stages"].append(stage)
        nxt = [s for s in STAGES if s not in wf["approved_stages"]]
        wf["stage"] = nxt[0] if nxt else "final"
        if stage == "final" or not nxt:
            wf["plan_status"] = "approved"
            wf["approved_at"] = time.strftime("%Y-%m-%d %H:%M")
        return _save(proj, wf, f"stage approved: {stage}")
    wf["plan_status"] = "approved"
    wf["approved_at"] = time.strftime("%Y-%m-%d %H:%M")
    wf["approved_stages"] = list(STAGES)
    return _save(proj, wf, "plan approved")


def require_execute(proj: Project, *, force: bool = False) -> dict:
    wf = state(proj)
    if force or wf["mode"] == "auto" or wf["plan_status"] in ("approved", "executed"):
        return wf
    raise VeditError(
        f"This project is in {wf['mode']} mode and the plan is '{wf['plan_status']}'. Get the owner's approval in the "
        f"Studio (or `vedit plan approve {proj.root}`), or pass --force only if the owner explicitly asked to render now.")


def mark_executed(proj: Project, note: str = "") -> dict:
    wf = state(proj)
    wf["plan_status"] = "executed"
    return _save(proj, wf, "executed" + (f": {note}" if note else ""))


# ------------------------------------------------------------------ CLI

def register_cli(sp) -> None:
    s = sp.add_parser("handoffs", help="which hand-offs Execute writes for this project (picked at intake)")
    s.add_argument("path"); s.add_argument("targets", nargs="*", help="resolve premiere fcp kdenlive shotcut otio edl nle llc capcut | none")
    s.set_defaults(fn=_cmd_handoffs)
    s = sp.add_parser("mode", help="show or set the project's working mode (plan | step | auto)")
    s.add_argument("path"); s.add_argument("mode", nargs="?", choices=MODES)
    s.set_defaults(fn=_cmd_mode)
    s = sp.add_parser("workflow", help="plan status, approvals and stages")
    s.add_argument("action", choices=["status", "approve", "request-changes", "in-review", "reset"])
    s.add_argument("path"); s.add_argument("--stage", choices=STAGES); s.add_argument("--note", default="")
    s.set_defaults(fn=_cmd_workflow)
    s = sp.add_parser("execute", help="render an approved plan: graphics, custom FX, final render, QA")
    s.add_argument("path"); s.add_argument("--force", action="store_true"); s.add_argument("--no-qa", action="store_true")
    s.set_defaults(fn=_cmd_execute)


def _cmd_mode(a) -> None:
    from .project import find
    from .util import print_json
    p = find(a.path)
    print_json(set_mode(p, a.mode) if a.mode else state(p))


def _cmd_handoffs(a) -> None:
    from .project import find
    from .util import print_json
    p = find(a.path)
    if a.targets:
        wf = state(p)
        wf["handoffs"] = [] if a.targets == ["none"] else a.targets
        _save(p, wf, f"hand-offs -> {', '.join(a.targets)}")
    print_json({"handoffs": chosen_handoffs(p)})


def _cmd_workflow(a) -> None:
    from .project import find
    from .util import print_json
    p = find(a.path)
    if a.action == "status":
        print_json(state(p))
    elif a.action == "approve":
        print_json(approve(p, a.stage))
    elif a.action == "request-changes":
        print_json(set_status(p, "changes_requested", a.note))
    elif a.action == "in-review":
        print_json(set_status(p, "in_review", a.note))
    else:
        wf = state(p)
        wf.update(plan_status="draft", stage=STAGES[0], approved_stages=[])
        print_json(_save(p, wf, "reset"))


def _cmd_execute(a) -> None:
    """The deterministic half of Execute. Hand-offs, thumbnails and post copy stay Claude-driven."""
    from . import custom, mg
    from .project import find
    from .qa import check
    from .render import render
    from .util import print_json
    p = find(a.path)
    require_execute(p, force=a.force)
    e = p.edit()
    alpha = config.load()["capcut"]["alpha_overlays"]
    rendered = mg.render_all(e, p.sub("mg"), capcut_alpha=alpha)
    fx = custom.prepare(e, p)
    p.save_edit(e)
    t0 = time.time()
    res = render(e, p.sub("render") / f"{e.name}.mp4", work_dir=p.sub("render") / "work", project_root=p.root)
    res["seconds"] = round(time.time() - t0, 1)
    out = {"graphics": rendered, "custom_fx": fx, "render": res}
    if not a.no_qa:
        target = e.output.audio.target_lufs or config.load()["render"]["target_lufs"]
        out["qa"] = check(e, res["output"], p.sub("qa"), target_lufs=target)
    out["handoffs"] = run_handoffs(p)
    mark_executed(p, res["output"])
    p.log(f"executed -> {res['output']}")
    print_json(out)


def chosen_handoffs(proj: Project) -> list[str]:
    """Hand-offs picked at intake (project.json workflow.handoffs) or in config (outputs.handoffs as a list)."""
    wf = state(proj)
    picked = wf.get("handoffs")
    if picked is None:
        cfg = config.load().get("outputs", {}).get("handoffs", "ask")
        picked = cfg if isinstance(cfg, list) else []
    return [x for x in picked if x and x != "none"]


def run_handoffs(proj: Project) -> dict:
    """Execute's hand-off step. CapCut and Resolve Studio live import stay Claude-driven (they touch the owner's
    apps); files are written here."""
    from .exports.package import TARGETS, build
    done: dict = {}
    for target in chosen_handoffs(proj):
        t = {"nle": "nle", "premiere": "premiere", "fcp": "fcp", "resolve": "resolve", "kdenlive": "kdenlive",
             "shotcut": "shotcut", "otio": "otio", "edl": "edl"}.get(target)
        try:
            if t in TARGETS:
                r = build(proj, t)
                done[target] = {"dir": r["dir"], "warnings": r["warnings"]}
            elif target in ("llc", "losslesscut"):
                from .llc import from_edit
                done[target] = from_edit(proj.edit(), proj.sub("handoff") / "losslesscut", footage_dir=proj.footage_dir)
            else:
                done[target] = {"todo": f"run by Claude: {'vedit capcut build' if target == 'capcut' else target}"}
        except Exception as exc:             # one failing hand-off must not lose the render
            done[target] = {"error": str(exc)}
    return done
