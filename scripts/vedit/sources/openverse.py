"""Openverse (WordPress): CC-licensed and public-domain images and audio, no key needed."""

from __future__ import annotations

HINT = ""
API = "https://api.openverse.org/v1"


def available() -> bool:
    return True


def search(query: str, *, kind: str = "image", limit: int = 10, orientation: str | None = None) -> list[dict]:
    from . import _client
    if kind not in ("image", "audio"):
        return []
    params = {"q": query, "page_size": min(limit, 20), "mature": "false"}
    if kind == "image" and orientation:
        params["aspect_ratio"] = {"portrait": "tall", "landscape": "wide", "square": "square"}.get(orientation, "")
    with _client() as c:
        r = c.get(f"{API}/{'images' if kind == 'image' else 'audio'}/", params=params)
        r.raise_for_status()
        rows = r.json().get("results", [])
    out = []
    for x in rows:
        lic = x.get("license") or ""
        lic = "cc0" if lic == "cc0" else "pdm" if lic == "pdm" else f"cc-{lic}" if lic else "unknown"
        out.append({"provider": "openverse", "id": x["id"], "kind": kind, "title": x.get("title") or "",
                    "url": x.get("url"), "page": x.get("foreign_landing_url"), "thumb": x.get("thumbnail"),
                    "width": x.get("width"), "height": x.get("height"),
                    "duration": (x.get("duration") or 0) / 1000 if kind == "audio" else None,
                    "licence": f"{lic}-{x.get('license_version')}" if x.get("license_version") and lic != "pdm" else lic,
                    "author": x.get("creator"), "attribution": x.get("attribution"),
                    "via": x.get("source") or x.get("provider")})
    return out
