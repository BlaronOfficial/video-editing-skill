"""Pexels: free stock photos and videos (Pexels licence: free to use, no attribution required). Free key."""

from __future__ import annotations

from .. import config

HINT = "free key at pexels.com/api, then `vedit secret set pexels <key>`"


def available() -> bool:
    return bool(config.secret("pexels"))


def search(query: str, *, kind: str = "image", limit: int = 10, orientation: str | None = None) -> list[dict]:
    from . import _client
    if kind not in ("image", "video"):
        return []
    params = {"query": query, "per_page": min(limit, 30)}
    if orientation:
        params["orientation"] = orientation
    url = "https://api.pexels.com/v1/search" if kind == "image" else "https://api.pexels.com/videos/search"
    with _client() as c:
        r = c.get(url, params=params, headers={"Authorization": config.secret("pexels")})
        r.raise_for_status()
        body = r.json()
    out = []
    for x in body.get("photos" if kind == "image" else "videos", []):
        if kind == "image":
            dl, thumb, author = x["src"].get("original"), x["src"].get("medium"), x.get("photographer")
            dur = None
        else:
            files = sorted((f for f in x.get("video_files", []) if f.get("file_type") == "video/mp4"),
                           key=lambda f: -(f.get("width") or 0) * (f.get("height") or 0))
            best = next((f for f in files if (f.get("height") or 0) <= 2160), files[0] if files else {})
            dl, thumb, author, dur = best.get("link"), x.get("image"), (x.get("user") or {}).get("name"), x.get("duration")
        out.append({"provider": "pexels", "id": str(x["id"]), "kind": kind, "title": x.get("alt") or "",
                    "url": dl, "page": x.get("url"), "thumb": thumb, "width": x.get("width"), "height": x.get("height"),
                    "duration": dur, "licence": "pexels", "author": author,
                    "attribution": f"Photo/video by {author} on Pexels" if author else "Pexels", "via": "pexels"})
    return out
