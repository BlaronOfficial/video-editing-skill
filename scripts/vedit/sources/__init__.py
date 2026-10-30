"""Free asset sources behind one search: Openverse (no key), Wikimedia Commons (no key), Pexels and Pixabay
(free keys). Every hit carries its licence, author and attribution text, and `get()` logs provenance.

The browser (Google Images, Pinterest, Behance, ...) and the owner's logged-in web AI tools are the other
half of sourcing; Claude drives those itself (references/sourcing.md, references/webai.md) and the files
come in through `vedit inbox pull`.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..util import VeditError

UA = "vedit/0.2 (video-editing-skill; https://github.com/BlaronOfficial/video-editing-skill)"
COMMERCIAL_OK = {"cc0", "pdm", "by", "by-sa", "pexels", "pixabay", "public domain", "cc-by", "cc-by-sa", "cc-zero"}


def _client(timeout: float = 25):
    import httpx
    return httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": UA})


def licence_flags(licence: str) -> dict:
    """commercial use / attribution / share-alike / no-derivatives flags from a licence code."""
    lic = (licence or "").lower().replace(" ", "-")
    nc = "nc" in lic.split("-") or "noncommercial" in lic
    nd = "nd" in lic.split("-")
    unknown = lic in ("", "unknown")
    return {"commercial": not nc and not unknown, "attribution": lic.startswith(("by", "cc-by")) or "-by" in lic,
            "share_alike": "sa" in lic.split("-"), "no_derivatives": nd, "unknown": unknown}


def providers() -> dict:
    from . import openverse, pexels, pixabay, wikimedia
    return {"openverse": openverse, "wikimedia": wikimedia, "pexels": pexels, "pixabay": pixabay}


def search(query: str, *, kind: str = "image", only: list[str] | None = None, limit: int = 10,
           commercial: bool = True, orientation: str | None = None) -> dict:
    """Search every available provider in parallel. kind: image | video | audio."""
    provs = {n: m for n, m in providers().items() if (not only or n in only) and m.available()}
    out, errors = [], {}

    def one(item):
        name, mod = item
        try:
            return name, mod.search(query, kind=kind, limit=limit, orientation=orientation)
        except Exception as exc:          # one provider down never sinks the search
            return name, exc

    with ThreadPoolExecutor(max_workers=4) as pool:
        for name, res in pool.map(one, provs.items()):
            if isinstance(res, Exception):
                errors[name] = str(res)[:200]
                continue
            for r in res:
                r["flags"] = licence_flags(r.get("licence", ""))
                if commercial and not r["flags"]["commercial"]:
                    continue
                out.append(r)
    skipped = [n for n, m in providers().items() if not m.available()]
    return {"query": query, "kind": kind, "results": out, "errors": errors,
            "unavailable": {n: providers()[n].HINT for n in skipped}}


def get(hit: dict, project_root: Path, *, register: bool = False, project=None) -> dict:
    """Download one search hit into edit/assets/<provider>/ with provenance (licence, author, attribution)."""
    from ..assets import add_provenance, download
    if not hit.get("url"):
        raise VeditError("this hit has no download url")
    dest = project_root / "assets" / hit["provider"]
    name = re.sub(r"[^\w.-]+", "_", f"{hit['provider']}_{hit['id']}")[:60]
    ext = Path(hit["url"].split("?")[0]).suffix[:5]
    out = download(hit["url"], dest, name=name + (ext or ""), user_agent=UA)   # Wikimedia refuses browser-like UAs
    rec = add_provenance(project_root, out, source=hit["provider"], url=hit.get("page") or hit["url"],
                         license=hit.get("licence"), notes=hit.get("attribution") or f"by {hit.get('author') or 'unknown'}")
    res = {"file": str(out), "provenance": rec, "flags": licence_flags(hit.get("licence", ""))}
    if register and project is not None:
        from ..project import add_source
        res["source_id"] = add_source(project, out, origin=f"{hit['provider']}:{hit.get('page') or hit['url']}")
    return res


def credits(project_root: Path) -> str:
    """Attribution lines for everything external in the project (for the video description)."""
    from ..util import read_json
    lines = []
    for r in read_json(project_root / "assets" / "provenance.json", default=[]) or []:
        flags = licence_flags(r.get("license", ""))
        if r.get("source") in ("camera", "synth") or not (flags["attribution"] or flags["unknown"]):
            continue
        note = r.get("notes") or ""
        lines.append(note if note.startswith('"') else f"{Path(r['file']).name}: {note} ({r.get('license')}) {r.get('url') or ''}".strip())
    return "\n".join(lines)


# ------------------------------------------------------------------ CLI

def cmd_sources(a) -> None:
    from ..paths import cache_dir
    from ..util import print_json, read_json, write_json
    last = cache_dir() / "sources_last.json"
    if a.action == "search":
        res = search(a.target, kind=a.kind, only=a.provider, limit=a.limit, commercial=not a.any_licence,
                     orientation=a.orientation)
        for i, r in enumerate(res["results"], start=1):
            r["n"] = i
        write_json(last, res)
        print_json(res)
        return
    from ..project import find
    p = find(a.target)
    if a.action == "credits":
        print(credits(p.root))
        return
    hits = (read_json(last) or {}).get("results", [])
    picked = [h for h in hits if h.get("n") in set(a.pick or [])]
    if not picked:
        raise VeditError("pick hits by number from the last `vedit sources search`: --pick 1 3")
    print_json([get(h, p.root, register=a.register, project=p) for h in picked])


def register_cli(sp) -> None:
    s = sp.add_parser("sources", help="free assets: Openverse, Wikimedia Commons, Pexels, Pixabay (licence-flagged)")
    s.add_argument("action", choices=["search", "get", "credits"])
    s.add_argument("target", help="search words, or the project for get/credits")
    s.add_argument("--kind", default="image", choices=["image", "video", "audio"])
    s.add_argument("--provider", nargs="*", choices=["openverse", "wikimedia", "pexels", "pixabay"])
    s.add_argument("--limit", type=int, default=8); s.add_argument("--orientation", choices=["portrait", "landscape", "square"])
    s.add_argument("--any-licence", action="store_true", help="include non-commercial results (flagged)")
    s.add_argument("--pick", type=int, nargs="*"); s.add_argument("--register", action="store_true")
    s.set_defaults(fn=cmd_sources)
