"""Personal extensions: code Claude writes for this owner that must survive `git pull`.

`personal/extensions/*.py` modules are imported at CLI start. A module may define any of:
    register_cli(sp)      add `vedit <command>` sub-commands
    ROUTES                {need: [route, ...]} merged into the route planner
    ADDONS                [{"id", "name", "kind", "cost", "used_for", "check": callable}] shown by doctor
Third-party tools installed with `vedit tools add` live in isolated venvs; their adapters live here.
A broken extension is reported, never fatal: the core must keep working.
"""

from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from .paths import personal_dir


def ext_dir() -> Path:
    path = personal_dir() / "extensions"
    path.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache(maxsize=1)
def load() -> tuple[list[ModuleType], list[str]]:
    mods: list[ModuleType] = []
    errors: list[str] = []
    for f in sorted(ext_dir().glob("*.py")):
        if f.name.startswith("_"):
            continue
        name = f"vedit_personal_ext_{f.stem}"
        try:
            spec = importlib.util.spec_from_file_location(name, f)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            mods.append(mod)
        except Exception as exc:
            errors.append(f"{f.name}: {exc}")
    return mods, errors


def register_cli(sp) -> None:
    mods, _ = load()
    for mod in mods:
        if hasattr(mod, "register_cli"):
            try:
                mod.register_cli(sp)
            except Exception as exc:
                print(f"warning: extension {mod.__name__} could not register commands: {exc}", file=sys.stderr)


def routes() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for mod in load()[0]:
        for need, items in (getattr(mod, "ROUTES", None) or {}).items():
            out.setdefault(need, []).extend(items)
    return out


def addon_rows() -> list[dict]:
    rows: list[dict] = []
    mods, errors = load()
    for mod in mods:
        for a in getattr(mod, "ADDONS", None) or []:
            try:
                ok, detail = a["check"]() if callable(a.get("check")) else (True, "")
            except Exception as exc:
                ok, detail = False, f"check failed: {exc}"
            rows.append({"id": a.get("id"), "name": a.get("name", a.get("id")), "ok": ok, "detail": detail,
                         "kind": a.get("kind", "tool"), "cost": a.get("cost", "free"), "used_for": a.get("used_for", ""),
                         "licence": a.get("licence", ""), "size_mb": a.get("size_mb"), "enabled": True,
                         "install": a.get("install", ""), "personal": True})
    for err in errors:
        rows.append({"id": "extension_error", "name": "personal extension", "ok": False, "detail": err, "kind": "tool",
                     "cost": "free", "used_for": "", "licence": "", "size_mb": None, "enabled": True, "install": "",
                     "personal": True})
    return rows
