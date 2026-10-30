"""Wikimedia Commons: photos, illustrations, maps, historical footage (CC / public domain), no key needed."""

from __future__ import annotations

import re

HINT = ""
API = "https://commons.wikimedia.org/w/api.php"


def available() -> bool:
    return True


def _plain(html: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def _code(short: str) -> str:
    s = (short or "").lower()
    if "public domain" in s or s in ("pd", "pdm"):
        return "pdm"
    if "cc0" in s or "cc-zero" in s:
        return "cc0"
    m = re.search(r"cc[ -]?(by(?:[ -](?:sa|nc|nd))*)[ -]?([\d.]+)?", s)
    if m:
        return "cc-" + m.group(1).replace(" ", "-") + (f"-{m.group(2)}" if m.group(2) else "")
    return s or "unknown"


def search(query: str, *, kind: str = "image", limit: int = 10, orientation: str | None = None) -> list[dict]:
    from . import _client
    if kind not in ("image", "video", "audio"):
        return []
    ft = {"image": "bitmap", "video": "video", "audio": "audio"}[kind]
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
              "gsrsearch": f"{query} filetype:{ft}", "gsrlimit": min(limit, 20), "prop": "imageinfo",
              "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 640}
    with _client() as c:
        r = c.get(API, params=params)
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages", {})
    out = []
    for pg in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        ii = (pg.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata") or {}
        val = lambda k: (meta.get(k) or {}).get("value")  # noqa: E731
        w, h = ii.get("width"), ii.get("height")
        if orientation and w and h:
            if (orientation == "portrait" and w > h) or (orientation == "landscape" and h > w):
                continue
        lic = _code(val("LicenseShortName") or "")
        author = _plain(val("Artist"))
        title = pg.get("title", "").removeprefix("File:")
        out.append({"provider": "wikimedia", "id": str(pg.get("pageid")), "kind": kind, "title": title,
                    "url": (ii.get("url") or "").split("?")[0], "page": ii.get("descriptionurl"),
                    "thumb": ii.get("thumburl"), "width": w, "height": h, "duration": None, "licence": lic,
                    "author": author,
                    "attribution": f'"{title}" by {author or "unknown"}, {val("LicenseShortName") or lic}, via Wikimedia Commons',
                    "via": "commons"})
    return out
