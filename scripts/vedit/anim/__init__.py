"""Animated pieces: illustrated, procedurally drawn animation on one deterministic <canvas> page.

The drawing kit, the 7 styles, the templates and the story grammar are adapted from animate (MIT, (c) 2026
cth9191; anim/LICENSE-animate). vedit builds the page itself (`build`), renders it with its own renderer
(mg/renderer: system Chrome, GPU, workers), times it to its own voices (`voice`), checks it (`review`) and places
it in an edit as an insert, a whole short or a doodle overlay (`pieces.add`).

    anim/kit/        core (RNG, boiling lines, ink/paint/hatch, cameras, springs, Bangla-safe text), morph
                     (eras + shape-morph bridges), board (storyboard), score-head/-tail (synth + loudness)
    anim/styles/     cut-paper, crosshatch, riso, sketchbook, math, pixel, isometric (STYLE.md, kit.js, demo/)
    anim/templates/  piece (multi-format starter), beat-cut (hard cuts on the beat), style (a blank style kit)
    anim/grammar/    FORMATS, STORY, FRAME, craft, new-style, intake
    personal/anim/styles/<name>/   styles the owner made from references (survive `git pull`)
    <project>/edit/anim/<piece>/   piece.json, src/, assets/, voice/, audio/, index.html, renders/, review/
"""

from __future__ import annotations

import re
from pathlib import Path

from ..paths import SKILL_ROOT, personal_dir

ANIM = SKILL_ROOT / "anim"
FPS = 24
FORMATS = {"9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080), "16:9": (1920, 1080)}


def anim_dir() -> Path:
    return ANIM


def personal_styles_dir() -> Path:
    return personal_dir() / "anim" / "styles"


def format_for(width: int, height: int) -> str:
    """The piece format nearest to a canvas size (by aspect ratio)."""
    r = width / max(1, height)
    return min(FORMATS, key=lambda k: abs(FORMATS[k][0] / FORMATS[k][1] - r))


def _style_info(d: Path, origin: str) -> dict:
    md = (d / "STYLE.md").read_text(encoding="utf-8", errors="replace") if (d / "STYLE.md").exists() else ""
    first = next((l.strip() for l in md.splitlines()[1:] if l.strip() and not l.startswith(("#", "!["))), "")
    proven = re.search(r"(?im)^\*\*proven on[:\*]*\**\s*(.+)$|^#+\s*proven on\s*\n+(.+)$", md)
    sample = next((p for p in (d / "sample.jpg", d / "sample.png") if p.exists()), None)
    return {"name": d.name, "origin": origin, "path": str(d), "about": first[:240],
            "proven": (proven.group(1) or proven.group(2)).strip()[:200] if proven else "",
            "sample": str(sample) if sample else None, "demo": (d / "demo" / "piece.json").exists()}


def styles() -> list[dict]:
    """Shipped styles plus the owner's own (personal ones win on a name clash)."""
    out: dict[str, dict] = {}
    for root, origin in ((ANIM / "styles", "shipped"), (personal_styles_dir(), "personal")):
        if root.exists():
            for d in sorted(root.iterdir()):
                if (d / "kit.js").exists():
                    out[d.name] = _style_info(d, origin)
    return list(out.values())


def style_dir(name: str, piece_dir: Path | None = None) -> Path:
    """A style's folder: beside the piece (walking up), then personal/anim/styles, then the shipped ones."""
    if piece_dir is not None:
        for d in [piece_dir, *piece_dir.parents]:
            c = d / "styles" / name
            if (c / "kit.js").exists():
                return c
    for root in (personal_styles_dir(), ANIM / "styles"):
        c = root / name
        if (c / "kit.js").exists():
            return c
    from ..util import VeditError
    raise VeditError(f"Unknown animation style '{name}'. Styles: {', '.join(s['name'] for s in styles())}")
