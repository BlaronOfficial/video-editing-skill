"""`vedit update`: pull the latest skill from GitHub without touching personal/, then migrate and re-sync deps."""

from __future__ import annotations

from . import config
from .paths import SKILL_ROOT, mg_dir
from .util import VeditError, run, which

# Setup, updates and the launchers install from these as shipped (`npm ci`, uv `--frozen`), but npm or uv run by
# hand, or an older vedit, can rewrite them. Nobody edits a lockfile on purpose, so an update puts them back.
LOCKFILES = ("scripts/uv.lock", "mg/renderer/package-lock.json")


def update(*, check_only: bool = False) -> dict:
    if not (SKILL_ROOT / ".git").exists():
        raise VeditError("This copy was not installed with `git clone`, so it cannot self-update. Re-install with git.")
    git = which("git")
    if not git:
        raise VeditError("git is not installed.")
    status = [l for l in run([git, "status", "--porcelain", "--untracked-files=no"], cwd=SKILL_ROOT).stdout.splitlines()
              if l.strip()]
    edited = [l for l in status if l[3:] not in LOCKFILES]
    if edited:
        raise VeditError("Tracked skill files were modified locally, so a pull could conflict:\n" + "\n".join(edited) +
                         "\nPersonal data belongs in personal/ (git-ignored). Move edits there, or run "
                         "`git stash` / `git checkout -- <file>` and retry.")
    restored = {}
    if status and not check_only:
        run([git, "checkout", "HEAD", "--", *(l[3:] for l in status)], cwd=SKILL_ROOT)
        restored = {"restored": [l[3:] for l in status]}
    run([git, "fetch", "--quiet"], cwd=SKILL_ROOT, timeout=300)
    behind = run([git, "rev-list", "--count", "HEAD..@{u}"], cwd=SKILL_ROOT, check=False).stdout.strip() or "0"
    log = run([git, "log", "--oneline", "HEAD..@{u}"], cwd=SKILL_ROOT, check=False).stdout.strip()
    if check_only or behind == "0":
        return {"behind": int(behind), "changes": log.splitlines(), "updated": False, **restored}
    before = run([git, "rev-parse", "HEAD"], cwd=SKILL_ROOT).stdout.strip()
    run([git, "pull", "--ff-only", "--quiet"], cwd=SKILL_ROOT, timeout=300)
    changed = run([git, "diff", "--name-only", before, "HEAD"], cwd=SKILL_ROOT).stdout.split()
    steps = []
    if any(p.startswith("scripts/") for p in changed) and which("uv"):
        run(["uv", "sync", "--frozen", "--project", str(SKILL_ROOT / "scripts")], timeout=1800)
        steps.append("python deps synced")
    if any(p.startswith("mg/renderer/package") for p in changed) and (npm := which("npm")):   # npm.cmd on Windows
        run([npm, "ci", "--no-audit", "--no-fund"], cwd=mg_dir() / "renderer", timeout=1800)
        steps.append("renderer deps installed")
    config.save_user_values({})   # runs migrate() and stamps the current schema version
    steps.append("personal config migrated")
    return {"behind": int(behind), "changes": log.splitlines(), "updated": True, "steps": steps, **restored}
