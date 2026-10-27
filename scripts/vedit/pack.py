"""takes_packed.md: the compact transcript view Claude plans an edit from (instead of watching video).

Each source becomes numbered phrases (split on pauses/sentence ends) with timestamps, pauses, filler
markers, low-confidence words and likely-retake hints. A JSON index maps phrase ids to times so a plan
can say {"source": "a_roll", "from": "P3", "to": "P7"}.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

from .util import fmt_ts, read_json, write_json, write_text

HARD_FILLERS = {
    "um", "umm", "uh", "uhh", "erm", "er", "ah", "ahh", "hmm", "hm", "mm", "mhm",
    "উম", "উমম", "আ", "আঃ", "এ", "হুম", "ইয়ে",
}
SOFT_FILLERS = {"like", "basically", "actually", "literally", "so", "right", "okay", "মানে", "আসলে", "তো", "আচ্ছা"}
SOFT_PHRASES = ("you know", "i mean", "kind of", "sort of")

_norm_re = re.compile(r"[^\wঀ-৿']+", re.U)


def _norm(word: str) -> str:
    return _norm_re.sub("", word.lower())


def phrases_from_words(words: list[dict], *, pause: float = 0.45) -> list[dict]:
    phrases: list[dict] = []
    cur: list[int] = []
    for i, w in enumerate(words):
        if cur:
            prev = words[cur[-1]]
            if w["s"] - prev["e"] >= pause or prev["w"].endswith((".", "?", "!", "।")):
                phrases.append({"idx": cur})
                cur = []
        cur.append(i)
    if cur:
        phrases.append({"idx": cur})
    for n, ph in enumerate(phrases, 1):
        ws = [words[i] for i in ph["idx"]]
        ph.update({"id": f"P{n}", "s": ws[0]["s"], "e": ws[-1]["e"], "text": " ".join(w["w"] for w in ws)})
    return phrases


def _retake_hints(phrases: list[dict]) -> dict[str, str]:
    """Earlier phrase -> later phrase that probably redoes it (the later take is usually the keeper)."""
    hints: dict[str, str] = {}
    norm = [[_norm(t) for t in p["text"].split() if _norm(t)] for p in phrases]
    for i, a in enumerate(norm):
        if len(a) < 3:
            continue
        for j in range(i + 1, min(i + 5, len(norm))):
            b = norm[j]
            if len(b) < 3:
                continue
            same_start = a[:3] == b[:3]
            ratio = SequenceMatcher(None, " ".join(a[:8]), " ".join(b[:8])).ratio()
            if same_start or ratio > 0.72:
                hints[phrases[i]["id"]] = phrases[j]["id"]
                break
    return hints


def _render_word(w: dict) -> str:
    n = _norm(w["w"])
    text = w["w"]
    if n in HARD_FILLERS:
        return f"~{text}~"
    if n in SOFT_FILLERS:
        text = f"°{text}"
    if w.get("p") is not None and w["p"] < 0.45:
        text += "?"
    return text


def pack_transcript(transcript: dict, source_id: str) -> tuple[list[str], dict]:
    words = [w for w in transcript.get("words", []) if w.get("type", "word") == "word"]
    events = [w for w in transcript.get("words", []) if w.get("type") == "event"]
    phrases = phrases_from_words(words)
    hints = _retake_hints(phrases)
    lang = transcript.get("language") or "?"
    lines = [f"## {source_id}  ({fmt_ts(transcript.get('duration', 0), ms=False)}, {lang}, "
             f"{transcript.get('engine')} {transcript.get('model', '')})", ""]
    if not phrases:
        lines.append("(no speech detected)")
    prev_end = 0.0
    ev_i = 0
    for ph in phrases:
        gap = ph["s"] - prev_end
        if gap >= 0.6:
            lines.append(f"‖{gap:.1f}s‖")
        while ev_i < len(events) and events[ev_i]["s"] < ph["s"]:
            lines.append(f"  ({events[ev_i]['w']} @{events[ev_i]['s']:.1f})")
            ev_i += 1
        body = " ".join(_render_word(words[i]) for i in ph["idx"])
        tag = f"  ⟲ redone in {hints[ph['id']]}" if ph["id"] in hints else ""
        speaker = words[ph["idx"][0]].get("speaker")
        spk = f"{speaker}: " if speaker else ""
        lines.append(f"{ph['id']} [{ph['s']:.2f}–{ph['e']:.2f}] {spk}{body}{tag}")
        prev_end = ph["e"]
    tail = transcript.get("duration", 0) - prev_end
    if tail >= 0.6:
        lines.append(f"‖{tail:.1f}s‖ (end)")
    index = {ph["id"]: {"s": ph["s"], "e": ph["e"], "text": ph["text"]} for ph in phrases}
    return lines, index


def pack_project(transcripts: dict[str, Path], out_md: Path, out_index: Path, *, title: str = "") -> Path:
    header = [
        f"# Takes — {title}".rstrip(" —"),
        "",
        "Legend: P# [start–end s] phrase · ‖1.2s‖ pause · ~um~ filler (cut) · °so soft filler (judge) · "
        "word? low confidence · ⟲ likely retake (prefer the later take)",
        "Plan cuts by phrase id or time; `vedit plan apply` snaps boundaries to word edges.",
        "",
    ]
    body: list[str] = []
    index: dict[str, dict] = {}
    for sid, path in transcripts.items():
        data = read_json(path) or {}
        lines, idx = pack_transcript(data, sid)
        body += lines + [""]
        index[sid] = idx
    write_json(out_index, index)
    return write_text(out_md, "\n".join(header + body))
