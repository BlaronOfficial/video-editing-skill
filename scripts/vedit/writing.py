"""English writing pass: flag machine-sounding patterns in text Claude writes (titles, on-screen text, lower
thirds, post copy, voiceover scripts). Captions of real speech are never checked: they are what was said.

The pattern list follows blader/humanizer (MIT) and Wikipedia's "Signs of AI writing" (WikiProject AI
Cleanup); the wording and the checks here are our own. Strong patterns are worth fixing on their own; weak
ones only matter in clusters. Plus format checks for video text: on-screen length, title length, hashtags.
Pure Python, no models: `vedit text check "<text>"` or `vedit text check <project>`.
"""

from __future__ import annotations

import re
from pathlib import Path

AI_WORDS = ("delve", "tapestry", "testament", "pivotal", "realm", "intricate", "showcase", "showcasing", "foster",
            "fostering", "underscore", "underscores", "vibrant", "seamless", "seamlessly", "elevate", "unlock",
            "harness", "leverage", "embark", "game-changer", "game changer", "robust", "meticulous", "meticulously",
            "bustling", "ever-evolving", "ever-changing", "unleash", "transformative", "captivating", "groundbreaking",
            "beacon", "synergy", "holistic", "navigate the", "navigating the", "landscape", "dive into", "deep dive",
            "in today's fast-paced", "in today's digital", "treasure trove", "plethora", "myriad", "paramount",
            "nuanced", "multifaceted", "resonate", "resonates", "commendable", "enhance", "streamline", "empower")
SALES = ("nestled", "breathtaking", "stunning", "world-class", "must-see", "unparalleled", "cutting-edge",
         "state-of-the-art", "best-in-class", "second to none", "unrivaled", "unmatched", "awe-inspiring",
         "rich history", "rich heritage", "hidden gem")
RESIDUE = ("i hope this helps", "great question", "certainly!", "absolutely!", "feel free to", "let me know if",
           "happy to help", "as an ai", "i'd be happy", "here is a", "here's a revised", "sure!", "of course!")
LIMITS = ("as of my last", "as of my knowledge", "my training data", "i don't have access", "i cannot browse",
          "up to my knowledge cutoff")

PATTERNS: list[tuple[str, str, str, str]] = [
    # (id, strength, regex, what to do)
    ("not_x_but_y", "strong",
     r"\b(?:it'?s|this is|that'?s|isn'?t|is not|was not|wasn'?t)\s+(?:not\s+)?(?:just|only|merely|simply|about)\b[^.!?\n]{0,60}?[,;:—–-]\s*(?:it'?s|but|this is|that'?s)\b|\bnot (?:just|only|merely) [^.!?\n]{1,50}?,? but\b",
     "state the claim directly; drop the contrast nobody raised"),
    ("staged_runup", "strong",
     r"\b(?:here'?s the (?:thing|kicker|truth|secret|catch)|the truth is|let'?s be honest|let me be clear|"
     r"here'?s why|the real (?:secret|answer|question) is|but here'?s|spoiler:|plot twist)\b",
     "say the point without announcing it"),
    ("arguing_with_no_one", "strong",
     r"\b(?:you might (?:think|be thinking)|contrary to popular belief|some (?:people )?(?:say|think)|"
     r"many believe|it'?s easy to think)\b",
     "drop the imagined objection"),
    ("inflated_significance", "strong",
     r"\b(?:plays? an? (?:crucial|pivotal|vital|key|significant|important) role|stands? as an?|marks? an? "
     r"(?:significant|pivotal|major|new) (?:milestone|moment|shift|turning point)|setting the stage|a testament to|"
     r"enduring legacy|shaping the future|cannot be overstated|more than (?:just )?an?)\b",
     "say what it does, plainly"),
    ("ing_rider", "strong",
     r",\s*(?:highlighting|underscoring|emphasizing|emphasising|showcasing|symbolizing|symbolising|reflecting|"
     r"ensuring|contributing to|fostering|cementing|solidifying|demonstrating)\b",
     "cut the trailing -ing phrase or make it its own sentence with a real claim"),
    ("borrowed_authority", "strong",
     r"\b(?:experts? (?:say|agree|believe|suggest)|studies (?:show|suggest)|research (?:shows|suggests)|"
     r"industry (?:leaders|experts)|according to many)\b",
     "name the source or drop the appeal"),
    ("copula_avoidance", "strong", r"\b(?:serves? as|stands? as|functions? as|acts? as an?|boasts? an?)\b",
     "use is / has"),
    ("writing_about_text", "strong",
     r"\b(?:in this (?:video|article|post|section|guide),? (?:we|i|you)|this (?:video|post|article|section) "
     r"(?:will|explores|covers|dives)|below,? you'?ll find|without further ado)\b",
     "start with the subject, not the document"),
    ("vague_connection", "weak", r"\b(?:associated with|linked to|in relation to|connected to)\b",
     "name the actual relationship"),
    ("stacked_qualifiers", "weak",
     r"\b(?:may|might|could) (?:potentially|possibly|perhaps)\b|\b(?:somewhat|arguably|relatively) (?:quite|rather|fairly)\b",
     "commit to the claim or cut it"),
    ("curly_quotes", "weak", r"[“”‘’]", "use straight quotes"),
]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def check(text: str, *, kind: str = "general") -> dict:
    """Findings for one text. kind: general | title | onscreen | post | script (adds format checks)."""
    findings: list[dict] = []
    low = text.lower()

    def add(pid: str, strength: str, excerpt: str, fix: str) -> None:
        findings.append({"pattern": pid, "strength": strength, "excerpt": excerpt.strip()[:90], "fix": fix})

    for pid, strength, rx, fix in PATTERNS:
        for m in re.finditer(rx, text, re.I):
            a = max(0, m.start() - 25)
            add(pid, strength, text[a:m.end() + 25], fix)
    for w in AI_WORDS:
        for m in re.finditer(r"\b" + re.escape(w) + r"\b", low):
            add("ai_vocabulary", "strong", text[max(0, m.start() - 20):m.end() + 20], f"replace '{w}' with a plain word")
    for w in SALES:
        if w in low:
            add("sales_language", "strong", w, "describe it; let the viewer decide it is stunning")
    for w in RESIDUE:
        if w in low:
            add("chatbot_residue", "strong", w, "delete it")
    for w in LIMITS:
        if w in low:
            add("knowledge_disclaimer", "strong", w, "check the fact or leave it out; never guess around a gap")

    words = re.findall(r"[A-Za-z][\w'-]*", text)
    n = max(1, len(words))
    sents = _sentences(text)
    dashes = len(re.findall(r"[—–]| - ", text))
    if dashes and dashes / n * 100 > 1.0 and dashes >= 2:
        add("dash_overuse", "strong", f"{dashes} dashes in {n} words", "use commas, periods or parentheses")
    triads = sum(1 for s in sents if re.search(r"\b\w+(?: \w+)?, \w+(?: \w+)?,? and \w+", s))
    if len(sents) >= 3 and triads / len(sents) > 0.34:
        add("forced_triads", "weak", f"{triads} of {len(sents)} sentences list three things", "list what is really there")
    openers = [s.split()[0].lower() for s in sents if s.split()]
    for i in range(len(openers) - 2):
        if openers[i] == openers[i + 1] == openers[i + 2]:
            add("repeated_openings", "weak", " / ".join(sents[i:i + 3])[:90], "vary the sentence openings")
            break
    hyph = len(re.findall(r"\b\w+-\w+\b", text))
    if hyph / n * 100 > 4 and hyph >= 3:
        add("hyphen_pairs", "weak", f"{hyph} hyphenated pairs", "unhyphenate where the meaning is clear")
    passive = len(re.findall(r"\b(?:is|are|was|were|been|being|be)\s+\w+ed\b", low))
    if len(sents) >= 3 and passive / len(sents) > 0.5:
        add("passive_voice", "weak", f"{passive} passive verbs", "say who does what")
    if text.count("**") >= 6:
        add("bold_decoration", "strong", f"{text.count('**') // 2} bold spans", "bold only what must be found")
    for line in text.splitlines():
        if line.startswith("#") and re.search(r"[\U0001F300-\U0001FAFF]", line):
            add("decorative_heading", "strong", line, "no emojis in headings")
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    for i, para in enumerate(paras[1:], start=1):
        if len(para.split()) <= 5 and len(paras[i - 1].split()) > 25 and para.endswith("."):
            add("dramatic_closer", "weak", para, "fold it into the paragraph before or cut it")

    # video text formats
    if kind == "title" and len(text) > 70:
        add("title_length", "strong", f"{len(text)} characters", "keep titles under ~70 characters (cut on mobile)")
    if kind == "onscreen":
        for line in text.splitlines():
            if len(line.split()) > 7:
                add("onscreen_length", "strong", line, "on-screen text: 7 words a line at most, it is read in a glance")
    if kind == "post":
        tags = re.findall(r"#\w+", text)
        if len(tags) > 5:
            add("hashtags", "weak", f"{len(tags)} hashtags", "3-5 specific hashtags read better than a wall")

    strong = [f for f in findings if f["strength"] == "strong"]
    weak_kinds = {f["pattern"] for f in findings if f["strength"] == "weak"}
    verdict = "clean" if not strong and len(weak_kinds) < 3 else "fix"
    return {"verdict": verdict, "strong": len(strong), "weak": len(findings) - len(strong), "findings": findings,
            "words": len(words)}


def project_texts(p) -> list[dict]:
    """Text Claude wrote for a project: text items, graphics data, post copy and scripts (not captions)."""
    e = p.edit()
    out = []
    for t in e.texts:
        out.append({"where": f"text {t.id}", "kind": "onscreen", "text": t.text})
    for o in e.overlays:
        if o.mg:
            for k, v in o.mg.data.items():
                if isinstance(v, str) and len(v.split()) >= 2 and not re.match(r"^(#|https?:|\d)", v):
                    out.append({"where": f"graphic {o.id}.{k}", "kind": "onscreen", "text": v})
                elif isinstance(v, list):
                    for i, item in enumerate(v):
                        if isinstance(item, str) and len(item.split()) >= 2:
                            out.append({"where": f"graphic {o.id}.{k}[{i}]", "kind": "onscreen", "text": item})
    for folder, kind in (("post", "post"), ("scripts", "script")):
        for f in sorted((p.root / folder).glob("*.md")) + sorted((p.root / folder).glob("*.txt")):
            out.append({"where": f"{folder}/{f.name}", "kind": kind, "text": f.read_text(encoding="utf-8")})
    return out


def check_project(p) -> dict:
    items = []
    for t in project_texts(p):
        r = check(t["text"], kind=t["kind"])
        if r["findings"]:
            items.append({"where": t["where"], "verdict": r["verdict"], "findings": r["findings"]})
    return {"checked": len(project_texts(p)), "to_fix": sum(1 for i in items if i["verdict"] == "fix"), "items": items}


def cmd_text(a) -> None:
    from .util import print_json
    target = a.target
    if a.file or (Path(target).exists() and Path(target).is_file() and not target.endswith(".json")):
        print_json(check(Path(target).read_text(encoding="utf-8"), kind=a.kind))
        return
    if Path(target).exists():
        from .project import find
        print_json(check_project(find(target)))
        return
    print_json(check(target, kind=a.kind))


def register_cli(sp) -> None:
    s = sp.add_parser("text", help="English writing pass: machine-sounding patterns in titles, on-screen text, posts")
    s.add_argument("action", choices=["check"]); s.add_argument("target", help="text, a text file, or a project")
    s.add_argument("--kind", default="general", choices=["general", "title", "onscreen", "post", "script"])
    s.add_argument("--file", action="store_true"); s.set_defaults(fn=cmd_text)
