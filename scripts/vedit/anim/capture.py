"""Screenshots of the owner's own product for an animated product reel (mg/renderer/capture.mjs): a page, one
element (a hero section, a pricing card, the logo), or the whole scrolling page, into <piece>/assets/.

A fresh headless profile: no cookies, no sign-ins, nothing typed. Only sites the owner owns or may show; ask
before capturing anything else. The build embeds assets/ into the page; draw them with drawAsset(...).
"""

from __future__ import annotations

import json

from ..paths import mg_dir
from ..util import VeditError, run
from .pieces import piece_dir


def capture(proj, name: str, url: str, out_name: str = "home.png", *, selector: str | None = None, full: bool = False,
            dark: bool = False, hide: str | None = None, width: int = 1280, height: int = 800, scale: float = 2.0,
            wait: int = 1500) -> dict:
    from ..assets import add_provenance
    from ..mg import _node
    if not url or not url.startswith(("http://", "https://")):
        raise VeditError("--url must be an http(s) address of the owner's own site")
    pd = piece_dir(proj, name)
    out = pd / "assets" / out_name
    cmd = [_node(), str(mg_dir() / "renderer" / "capture.mjs"), "--url", url, "--out", str(out), "--width", str(width),
           "--height", str(height), "--scale", str(scale), "--wait", str(wait)]
    if selector:
        cmd += ["--selector", selector]
    if full:
        cmd.append("--full")
    if dark:
        cmd.append("--dark")
    if hide:
        cmd += ["--hide", hide]
    proc = run(cmd, check=False, timeout=300)
    lines = [l for l in (proc.stdout or "").splitlines() if l.startswith("{")]
    if proc.returncode != 0 or not lines:
        raise VeditError("Capture failed: " + (proc.stderr or "").strip()[-400:])
    res = json.loads(lines[-1])
    add_provenance(proj.root, out, source="capture", url=url, license="the owner's own site (confirm)",
                   notes=f"screenshot for animated piece '{name}'" + (f" [{selector}]" if selector else ""))
    return {**res, "piece": name, "asset": out.name,
            "next": f"drawAsset('{out.name}', x, y, w, h, {{ fit: 'cover' }}) inside the style's own framing; rebuild"}
