"""Pixabay: free photos, illustrations, vectors and videos (Pixabay content licence). Free key."""

from __future__ import annotations

from .. import config

HINT = "free key at pixabay.com/api/docs, then `vedit secret set pixabay <key>`"


def available() -> bool:
    return bool(config.secret("pixabay"))


def search(query: str, *, kind: str = "image", limit: int = 10, orientation: str | None = None) -> list[dict]:
    from . import _client
    if kind not in ("image", "video"):
        return []
    params = {"key": config.secret("pixabay"), "q": query[:100], "per_page": max(3, min(limit, 50)), "safesearch": "true"}
    if kind == "image" and orientation in ("vertical", "portrait", "horizontal", "landscape"):
        params["orientation"] = "vertical" if orientation in ("vertical", "portrait") else "horizontal"
    url = "https://pixabay.com/api/" if kind == "image" else "https://pixabay.com/api/videos/"
    with _client() as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        hits = r.json().get("hits", [])
    out = []
    for x in hits:
        if kind == "image":
            dl, thumb, w, h, dur = x.get("largeImageURL"), x.get("previewURL"), x.get("imageWidth"), x.get("imageHeight"), None
        else:
            v = x.get("videos", {})
            best = v.get("large") if (v.get("large") or {}).get("url") else v.get("medium") or {}
            dl, thumb, w, h, dur = best.get("url"), best.get("thumbnail"), best.get("width"), best.get("height"), x.get("duration")
        out.append({"provider": "pixabay", "id": str(x["id"]), "kind": kind, "title": x.get("tags", ""), "url": dl,
                    "page": x.get("pageURL"), "thumb": thumb, "width": w, "height": h, "duration": dur,
                    "licence": "pixabay", "author": x.get("user"),
                    "attribution": f"by {x.get('user')} on Pixabay", "via": "pixabay"})
    return out
