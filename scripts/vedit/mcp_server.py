"""MCP server over the vedit engine (stdio). Same commands as the CLI, exposed as typed tools.

Register in Claude Code:   claude mcp add --scope user vedit -- "<skill>/vedit.cmd" mcp
Claude Desktop config:     {"mcpServers": {"vedit": {"command": "<skill>/vedit.cmd", "args": ["mcp"]}}}
Name it `vedit`: the Artifact Studio calls this server as `host:vedit` (studio_* tools) when it is opened in
the Claude desktop app, so the owner's Studio edits reach edit.json directly.
"""

from __future__ import annotations

import contextlib
import io
import json

try:  # mcp 2.x renamed FastMCP to MCPServer; keep working on both
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # pragma: no cover - mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .cli import main as cli_main

server = _Server("video-editing-skill")


def _run(argv: list[str]) -> str:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_main(argv)
    text = out.getvalue().strip()
    if code != 0:
        return f"ERROR (exit {code}): {err.getvalue().strip() or text}"
    return text or "ok"


@server.tool()
def vedit(args: list[str]) -> str:
    """Run any vedit CLI command, e.g. ["capcut", "list"] or ["captions", "build", "D:/footage", "--style", "bold_box"]."""
    return _run(args)


@server.tool()
def doctor() -> str:
    """Check ffmpeg, Node, fonts, CapCut calibration and optional integrations; returns fixes for anything missing."""
    return _run(["doctor", "--json"])


@server.tool()
def project_init(footage: str, ratio: str = "9:16", name: str | None = None) -> str:
    """Create an edit project in <footage>/edit/ (ratio: 9:16, 16:9, 1:1, 4:5, ...)."""
    argv = ["project", "init", footage, "--ratio", ratio]
    if name:
        argv += ["--name", name]
    return _run(argv)


@server.tool()
def transcribe(project: str, engine: str, language: str | None = None) -> str:
    """Word-level transcription. engine: whisper (local, free) or scribe (ElevenLabs). Ask the user which, per project."""
    argv = ["transcribe", project, "--engine", engine]
    if language:
        argv += ["--language", language]
    return _run(argv)


@server.tool()
def pack(project: str) -> str:
    """Build takes_packed.md (the transcript view to plan cuts from). Returns its path; read that file next."""
    return _run(["pack", project])


@server.tool()
def plan_apply(project: str, keeps: list[dict]) -> str:
    """Set the main track from keep ranges: [{"source", "from": "P3"|sec, "to": "P9"|sec, "label", "zoom", "transition"}]."""
    from .project import find
    p = find(project)
    path = p.root / "keeps.json"
    path.write_text(json.dumps(keeps, ensure_ascii=False, indent=2), encoding="utf-8")
    return _run(["plan", "apply", project, str(path)])


@server.tool()
def captions_build(project: str, style: str | None = None) -> str:
    """Generate caption chunks from the transcript through the current cut."""
    return _run(["captions", "build", project] + (["--style", style] if style else []))


@server.tool()
def storyboard(project: str) -> str:
    """Write the approval storyboard (self-contained HTML). Show it to the user before rendering."""
    return _run(["storyboard", project])


@server.tool()
def mg_render(project: str, ids: list[str] | None = None, force: bool = False) -> str:
    """Render motion-graphics overlays defined in edit.json (alpha video)."""
    return _run(["mg", "render", project] + (["--id", *ids] if ids else []) + (["--force"] if force else []))


@server.tool()
def render(project: str, preview: bool = False) -> str:
    """Render final.mp4 (or a fast 540p preview) from edit.json."""
    return _run(["render", project] + (["--preview"] if preview else []))


@server.tool()
def qa(project: str) -> str:
    """Self-check the render; returns issues and frame-sheet paths to look at."""
    return _run(["qa", project])


@server.tool()
def capcut_build(project: str, pro: str, name: str | None = None, close_capcut: bool = False) -> str:
    """Write the edit as an editable CapCut project. pro: yes|no (may Pro resources be used?)."""
    argv = ["capcut", "build", project, "--pro", pro] + (["--name", name] if name else []) + (["--close"] if close_capcut else [])
    return _run(argv)


@server.tool()
def capcut_diff(project: str, learn_into_style: str | None = None) -> str:
    """Compare the user's CapCut edits with the generated project; optionally learn them into a style."""
    return _run(["capcut", "diff", project] + (["--learn", learn_into_style] if learn_into_style else []))


# ------------------------------------------------------------------ director + Studio live link

@server.tool()
def capabilities(refresh: bool = False) -> str:
    """What this machine and session can use (engine probe + what Claude recorded about connectors and web AIs)."""
    return _run(["capabilities", "show"] + (["--refresh"] if refresh else []))


@server.tool()
def route_plan(need: str) -> str:
    """Ranked ways to make something (icon, image, scene_clip, motion_graphic, 3d, vfx, music, sfx, voiceover, ...)."""
    return _run(["route", "plan", need])


@server.tool()
def workflow(project: str, action: str = "status", stage: str | None = None) -> str:
    """Plan status / approvals. action: status | approve | request-changes | in-review. stage for step mode."""
    return _run(["workflow", action, project] + (["--stage", stage] if stage else []))


def _studio_docs(project: str, names: tuple[str, ...]) -> dict:
    from . import studio
    from .project import find
    docs = studio.documents(find(project))
    return {k: v for k, v in docs.items() if k in names}


@server.tool()
def studio_apply(project: str, ops: list[dict]) -> str:
    """Apply Studio ops (see scripts/vedit/ops.py) to edit.json. Returns the report and the refreshed documents
    (meta, edit, suggestions, directions) for the page to write back to its database."""
    import tempfile
    from pathlib import Path
    from . import studio
    from .project import find
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "ops.json"
        f.write_text(json.dumps([{"seq": i, "op": op} for i, op in enumerate(ops)], ensure_ascii=False), encoding="utf-8")
        report = studio.apply(find(project), f)
    report["docs"] = _studio_docs(project, ("meta", "edit", "suggestions", "directions"))
    return json.dumps(report, ensure_ascii=False, default=str)


@server.tool()
def studio_state(project: str) -> str:
    """Current revision, workflow and documents of a project, for the Studio's live link."""
    from . import studio
    from .project import find
    p = find(project)
    return json.dumps({"status": studio.status(p), "docs": _studio_docs(project, ("meta", "edit"))},
                      ensure_ascii=False, default=str)


@server.tool()
def proxy_build(project: str, sources: list[str] | None = None) -> str:
    """Build Studio previews (proxies, peaks, sprites) and list files that still need uploading."""
    return _run(["studio", "build", project] + (["--only", *sources] if sources else []))


@server.tool()
def studio_file(project: str, name: str) -> str:
    """Base64 of one file from the project's Studio bundle (so the page can upload a new preview itself).
    Only files inside <project>/edit/studio/ are served, up to 20 MiB."""
    import base64
    from .project import find
    p = find(project)
    root = (p.root / "studio").resolve()
    f = (root / name).resolve()
    if root not in f.parents or not f.is_file():
        return "ERROR: not a Studio bundle file"
    if f.stat().st_size > 20 * 1024 * 1024:
        return "ERROR: file over 20 MiB"
    return base64.b64encode(f.read_bytes()).decode("ascii")


@server.tool()
def sfx_preview(sound_id: str, duration: float | None = None, pitch: str | None = None) -> str:
    """Render a sound-effect preview for the Studio (earshot bank arrives in phase 2; until then the vedit synth)."""
    import tempfile
    from pathlib import Path
    out = Path(tempfile.gettempdir()) / f"vedit_sfx_{sound_id.replace('/', '_')}.wav"
    argv = ["sfx", sound_id.split("/")[0], "--out", str(out)] + (["--duration", str(duration)] if duration else [])
    res = _run(argv)
    if res.startswith("ERROR"):
        return res
    import base64
    return base64.b64encode(out.read_bytes()).decode("ascii")


def main() -> None:
    server.run()
