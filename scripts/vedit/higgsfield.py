"""Higgsfield (optional): detect the integration, keep a credit ledger, import generated media.

Generation itself goes through Higgsfield's own skills/CLI (Claude Code) or its MCP connector, whose
flags change over time; Claude reads `higgsfield --help` at run time. This module only does the parts
that must be reliable: detection, the approval ledger, and importing outputs with provenance.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .assets import add_provenance, download
from .project import Project, add_source
from .util import read_json, which, write_json


def status() -> dict:
    cli = which("higgsfield")
    info: dict = {"cli": bool(cli), "cli_path": cli, "auth": None, "mcp": None}
    if cli:
        for args in (["auth", "status"], ["whoami"]):
            try:
                out = subprocess.run([cli, *args], capture_output=True, text=True, timeout=30)
                if out.returncode == 0:
                    info["auth"] = (out.stdout or out.stderr).strip()[:300]
                    break
            except Exception:
                continue
    claude = which("claude")
    if claude:
        try:
            out = subprocess.run([claude, "mcp", "list"], capture_output=True, text=True, timeout=60)
            info["mcp"] = "higgsfield" in (out.stdout or "").lower()
        except Exception:
            pass
    info["available"] = bool(info["cli"] or info["mcp"])
    info["setup"] = ("npm i -g @higgsfield/cli && higgsfield auth login && npx skills add higgsfield-ai/skills   "
                     "(or add the MCP: claude mcp add --transport http higgsfield https://mcp.higgsfield.ai/mcp)")
    return info


def _ledger(proj: Project) -> Path:
    return proj.sub("assets") / "higgsfield_ledger.json"


def propose(proj: Project, shots: list[dict]) -> dict:
    """Record a generation plan awaiting approval. shots: [{id, purpose, model, prompt, seconds, est_credits}]"""
    ledger = read_json(_ledger(proj), default={"plans": [], "generations": []})
    plan = {"id": f"plan_{int(time.time())}", "created": time.strftime("%Y-%m-%d %H:%M"), "status": "awaiting_approval",
            "shots": shots, "est_total": round(sum(float(s.get("est_credits") or 0) for s in shots), 1)}
    ledger["plans"].append(plan)
    write_json(_ledger(proj), ledger)
    return plan


def approve(proj: Project, plan_id: str) -> dict:
    ledger = read_json(_ledger(proj), default={"plans": [], "generations": []})
    for p in ledger["plans"]:
        if p["id"] == plan_id:
            p["status"] = "approved"
            p["approved"] = time.strftime("%Y-%m-%d %H:%M")
            write_json(_ledger(proj), ledger)
            return p
    raise KeyError(plan_id)


def import_output(proj: Project, src: str, *, shot_id: str, prompt: str = "", model: str = "", credits: float | None = None,
                  kind: str = "broll") -> dict:
    """Bring a generated file (local path or URL) into the project and register it as a source."""
    dest_dir = proj.sub("assets") / "higgsfield"
    path = download(src, dest_dir, name=f"{shot_id}{Path(src.split('?')[0]).suffix}") if src.startswith("http") else Path(src)
    sid = add_source(proj, path, origin=f"higgsfield:{model or 'unknown'}", sid=f"hf_{shot_id}")
    add_provenance(proj.root, path, source="higgsfield", url=src if src.startswith("http") else None,
                   license="Higgsfield plan terms", notes=f"{model}: {prompt[:200]}", credits=credits)
    ledger = read_json(_ledger(proj), default={"plans": [], "generations": []})
    ledger["generations"].append({"shot": shot_id, "file": str(path), "model": model, "credits": credits,
                                  "kind": kind, "at": time.strftime("%Y-%m-%d %H:%M")})
    write_json(_ledger(proj), ledger)
    return {"source_id": sid, "path": str(path)}


def spent(proj: Project) -> float:
    ledger = read_json(_ledger(proj), default={"generations": []})
    return round(sum(float(g.get("credits") or 0) for g in ledger.get("generations", [])), 1)
