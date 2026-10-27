"""Long-to-shorts: rank self-contained 20-60 s windows from a long transcript, then cut the chosen ones.

The script does the mechanical scoring (sentence-aligned, dense speech, energy, hook-ish openings,
no retakes); Claude reads the top candidates and judges which actually stand alone and would hook.
"""

from __future__ import annotations

import re

from .audio import energy_curve
from .captions import transcript_words
from .pack import _retake_hints, phrases_from_words
from .project import Project, RATIOS
from .timeline import Canvas, Edit, Source

HOOK_WORDS = re.compile(r"\b(you|your|how|why|what|stop|never|secret|mistake|best|worst|\d+)\b|[?]|কেন|কিভাবে|ভুল|সেরা|গোপন", re.I)


def candidates(source_id: str, transcript_path: str, media_path: str, *, min_len: float = 20, max_len: float = 60,
               top: int = 12) -> list[dict]:
    words = transcript_words(transcript_path)
    phrases = phrases_from_words(words)
    retakes = set(_retake_hints(phrases))
    energy = dict(energy_curve(media_path, step=1.0))
    out = []
    for i in range(len(phrases)):
        dur = 0.0
        for j in range(i, len(phrases)):
            dur = phrases[j]["e"] - phrases[i]["s"]
            if dur > max_len:
                break
            if dur < min_len:
                continue
            window = phrases[i:j + 1]
            text = " ".join(p["text"] for p in window)
            n_words = len(text.split())
            density = n_words / dur
            ends_clean = window[-1]["text"].rstrip().endswith((".", "!", "?", "।"))
            hook = 1.0 if HOOK_WORDS.search(window[0]["text"]) else 0.0
            retake_pen = sum(1 for p in window if p["id"] in retakes)
            e = [energy.get(float(int(t)), -60) for t in range(int(window[0]["s"]), int(window[-1]["e"]) + 1)]
            loud = (sum(e) / len(e) + 60) / 60 if e else 0
            score = 1.6 * hook + 1.0 * ends_clean + 0.6 * min(density / 3.0, 1.2) + 0.8 * loud - 0.7 * retake_pen
            out.append({"source": source_id, "from": window[0]["id"], "to": window[-1]["id"], "start": round(window[0]["s"], 2),
                        "end": round(window[-1]["e"], 2), "duration": round(dur, 1), "score": round(score, 3),
                        "opening": window[0]["text"][:120], "preview": text[:400]})
    out.sort(key=lambda c: -c["score"])
    picked: list[dict] = []
    for c in out:   # non-overlapping best windows
        if all(c["end"] <= p["start"] or c["start"] >= p["end"] for p in picked):
            picked.append(c)
        if len(picked) >= top:
            break
    return picked


def make_short(parent: Project, name: str, keeps: list[dict], *, ratio: str = "9:16") -> Project:
    """New sub-project edit/shorts/<name>/ sharing the parent's sources and transcripts."""
    from .cuts import apply_keeps
    src_edit = parent.edit()
    root = parent.root / "shorts" / name
    for sub in ("render", "qa", "mg", "assets", "storyboard", "capcut"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    w, h = RATIOS[ratio]
    edit = Edit(name=name, canvas=Canvas(width=w, height=h, fps=src_edit.canvas.fps),
                sources={k: Source(**v.model_dump()) for k, v in src_edit.sources.items()},
                captions=src_edit.captions.model_copy(update={"chunks": []}), color=src_edit.color, style=src_edit.style,
                brand=src_edit.brand)
    edit = apply_keeps(edit, keeps, index_path=str(parent.root / "takes_index.json"))
    proj = Project(root)
    proj.save_edit(edit)
    proj.save_meta({"name": name, "parent": str(parent.root), "ratio": ratio, "decisions": []})
    return proj
