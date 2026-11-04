"""Performance learning: how the published video actually did, mapped back onto the edit that made it.

    vedit publish link <p> --url https://youtu.be/<id>        which upload is this edit
    vedit analytics auth --client-secret client.json           owner's own Google OAuth client (they sign in)
    vedit analytics pull <p>                                    YouTube Analytics API: metrics + retention curve
    vedit analytics import <p> --csv retention.csv              or a retention export from YouTube Studio
    vedit analytics report <p>                                  drops / rewatches with what was on screen, chart
    vedit analytics learn <p>                                   into the learning profile and route ranking

The curve is audience retention against the video's length. Because the edit knows every cut, word, graphic,
b-roll shot and sound, each drop or rewatch gets its context ("lost 9 points at 0:12-0:15 during a 0.9 s
pause"), and each kind of element gets a measured lift that the route planner uses next time.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import re
import secrets as _secrets
import time
from pathlib import Path
from typing import Any

import numpy as np

from . import config
from .paths import personal_dir
from .util import VeditError, read_json, write_json

SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly", "https://www.googleapis.com/auth/youtube.readonly"]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
DATA_API = "https://www.googleapis.com/youtube/v3/videos"
SECRET = "youtube_oauth"


# ------------------------------------------------------------------ linking

def video_id(url: str) -> str:
    u = url.strip()
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})", u)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", u):
        return u
    raise VeditError(f"Not a YouTube link or video id: {url}")


def link(proj, url: str, *, platform: str = "youtube", published: str | None = None) -> dict:
    vid = video_id(url) if platform == "youtube" else url
    meta = proj.meta()
    pubs = [p for p in meta.get("published", []) if p.get("video") != vid]
    rec = {"platform": platform, "video": vid, "url": url, "published": published,
           "linked": time.strftime("%Y-%m-%d %H:%M"), "duration_at_link": round(proj.edit().duration, 3)}
    meta["published"] = pubs + [rec]
    proj.save_meta(meta)
    from . import learn
    learn.event("publish", {"platform": platform, "video": vid}, project=proj.edit().name)
    return rec


def _linked(proj, video: str | None) -> dict:
    pubs = proj.meta().get("published", [])
    if video:
        vid = video_id(video)
        return next((p for p in pubs if p["video"] == vid), {"platform": "youtube", "video": vid})
    if not pubs:
        raise VeditError("No published video linked. `vedit publish link <project> --url <youtube link>` first.")
    return pubs[-1]


# ------------------------------------------------------------------ OAuth (the owner signs in, never Claude)

def _client(path: str | None) -> dict:
    stored = json.loads(config.secret(SECRET) or "{}")
    if path:
        data = read_json(path)
        if not data:
            raise VeditError(f"Could not read the OAuth client file {path}")
        c = data.get("installed") or data.get("web") or data
        stored.update({"client_id": c["client_id"], "client_secret": c.get("client_secret", "")})
    if not stored.get("client_id"):
        raise VeditError("No OAuth client yet. The owner creates one (Google Cloud console -> APIs: YouTube Analytics "
                         "API + YouTube Data API v3 -> Credentials -> OAuth client ID, type Desktop app), downloads the "
                         "JSON, then: vedit analytics auth --client-secret <file>.json")
    return stored


def auth_url(client: dict, redirect: str, state: str, verifier: str) -> str:
    from urllib.parse import urlencode
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return AUTH_URL + "?" + urlencode({
        "client_id": client["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": " ".join(SCOPES),
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "access_type": "offline",
        "prompt": "consent"})


def auth(client_secret: str | None = None, *, open_browser: bool = True, timeout: int = 300, transport=None,
         on_url=None) -> dict:
    """Installed-app OAuth with PKCE on a loopback port. The owner signs in and consents in their own browser;
    vedit only receives the code on 127.0.0.1 and keeps the refresh token in personal/secrets.json."""
    import http.server
    import threading
    import webbrowser
    from urllib.parse import parse_qs, urlparse
    import httpx
    client = _client(client_secret)
    got: dict[str, str] = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                               # noqa: N802
            q = parse_qs(urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<p>vedit got the permission. You can close this tab.</p>".encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_address[1]}"
    state, verifier = _secrets.token_urlsafe(16), _secrets.token_urlsafe(64)
    url = auth_url(client, redirect, state, verifier)
    print(f"Open this link and sign in as the channel owner:\n{url}", flush=True)
    if on_url:                                          # tests play the browser
        on_url(url)
    if open_browser:
        webbrowser.open(url)
    th = threading.Thread(target=srv.handle_request, daemon=True)
    th.start()
    th.join(timeout)
    srv.server_close()
    if not got.get("code"):
        raise VeditError("No permission came back (timed out or declined).")
    if got.get("state") != state:
        raise VeditError("OAuth state mismatch: ignored the reply.")
    with httpx.Client(transport=transport, timeout=60) as h:
        r = h.post(TOKEN_URL, data={"code": got["code"], "client_id": client["client_id"],
                                    "client_secret": client.get("client_secret", ""), "redirect_uri": redirect,
                                    "grant_type": "authorization_code", "code_verifier": verifier})
    if r.status_code >= 400:
        raise VeditError(f"Token exchange failed {r.status_code}: {r.text[:300]}")
    tok = r.json()
    if not tok.get("refresh_token"):
        raise VeditError("Google returned no refresh token; run auth again (it asks for consent each time).")
    config.set_secret(SECRET, json.dumps({**client, "refresh_token": tok["refresh_token"], "scopes": SCOPES}))
    return {"ok": True, "scopes": SCOPES, "stored": "personal/secrets.json"}


def _token(transport=None) -> str:
    import httpx
    c = json.loads(config.secret(SECRET) or "{}")
    if not c.get("refresh_token"):
        raise VeditError("Not connected to YouTube Analytics: `vedit analytics auth --client-secret <file>` "
                         "(or export the retention CSV from YouTube Studio and `vedit analytics import`).")
    with httpx.Client(transport=transport, timeout=60) as h:
        r = h.post(TOKEN_URL, data={"client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
                                    "refresh_token": c["refresh_token"], "grant_type": "refresh_token"})
    if r.status_code >= 400:
        raise VeditError(f"Could not refresh the YouTube token ({r.status_code}): run `vedit analytics auth` again.")
    return r.json()["access_token"]


def iso_duration(s: str) -> float:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", s or "")
    if not m:
        return 0.0
    d, h, mi, se = (float(x) if x else 0.0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def pull(proj, *, video: str | None = None, transport=None) -> dict:
    import httpx
    pub = _linked(proj, video)
    vid = pub["video"]
    token = _token(transport)
    hdr = {"Authorization": f"Bearer {token}"}
    with httpx.Client(transport=transport, timeout=60, headers=hdr) as h:
        r = h.get(DATA_API, params={"part": "contentDetails,snippet,statistics", "id": vid})
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            raise VeditError(f"YouTube has no video {vid} on this account (or it is private to another channel).")
        it = items[0]
        start = (it["snippet"].get("publishedAt") or "2005-01-01")[:10]
        end = time.strftime("%Y-%m-%d")
        base = {"ids": "channel==MINE", "startDate": start, "endDate": end, "filters": f"video=={vid}"}
        m = h.get(ANALYTICS, params={**base, "metrics": "views,estimatedMinutesWatched,averageViewDuration,"
                                                         "averageViewPercentage,likes,shares,subscribersGained"})
        m.raise_for_status()
        ret = h.get(ANALYTICS, params={**base, "dimensions": "elapsedVideoTimeRatio",
                                       "metrics": "audienceWatchRatio,relativeRetentionPerformance"})
        ret.raise_for_status()
    mj, rj = m.json(), ret.json()
    metrics = dict(zip([c["name"] for c in mj.get("columnHeaders", [])], (mj.get("rows") or [[]])[0]))
    rows = sorted((float(a), float(b), float(c)) for a, b, c in rj.get("rows", []))
    data = {"platform": "youtube", "video": vid, "title": it["snippet"].get("title"),
            "duration": iso_duration(it["contentDetails"].get("duration", "")), "metrics": metrics,
            "retention": [list(r) for r in rows], "source": "api", "pulled": time.strftime("%Y-%m-%d %H:%M")}
    return _save(proj, data)


def _save(proj, data: dict) -> dict:
    d = proj.root / "analytics"
    d.mkdir(parents=True, exist_ok=True)
    write_json(d / f"{data['video']}.json", data)
    return {"video": data["video"], "points": len(data["retention"]), "duration": data.get("duration"),
            "metrics": data.get("metrics", {}), "file": str(d / f"{data['video']}.json")}


# ------------------------------------------------------------------ CSV from YouTube Studio

def _num(v: str) -> float | None:
    v = (v or "").strip().replace(",", "")
    if not v or v.lower() in ("total", "totals"):
        return None
    if re.fullmatch(r"\d+:\d{1,2}(:\d{1,2})?(\.\d+)?", v):
        parts = [float(p) for p in v.split(":")]
        return sum(p * 60 ** (len(parts) - 1 - i) for i, p in enumerate(parts))
    try:
        return float(v.rstrip("%"))
    except ValueError:
        return None


def parse_csv(path: str | Path, *, duration: float | None = None) -> list[list[float]]:
    """Rows [ratio 0..1, watch ratio (0..1, rewatches can exceed 1), relative or None] from a retention export.
    Accepts video position as %, ratio or time (s / m:ss), retention as % or ratio."""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    rows = list(csv.reader(text.splitlines()))
    head = next((i for i, r in enumerate(rows) if any(re.search(r"position|elapsed|time", c, re.I) for c in r)), None)
    if head is None:
        raise VeditError("No 'video position' column in the CSV (export the audience retention report).")
    cols = [c.strip().lower() for c in rows[head]]
    xi = next(i for i, c in enumerate(cols) if re.search(r"position|elapsed|time", c))
    yi = next((i for i, c in enumerate(cols) if re.search(r"retention|watch ratio|audience", c) and "relative" not in c), None)
    ri = next((i for i, c in enumerate(cols) if "relative" in c), None)
    if yi is None:
        raise VeditError("No audience retention column in the CSV.")
    pts = []
    for r in rows[head + 1:]:
        if len(r) <= max(xi, yi):
            continue
        x, y = _num(r[xi]), _num(r[yi])
        if x is None or y is None:
            continue
        rel = _num(r[ri]) if ri is not None and ri < len(r) else None
        pts.append([x, y, rel, r[xi]])
    if len(pts) < 5:
        raise VeditError("Too few retention points in the CSV.")
    xs = np.asarray([p[0] for p in pts])
    as_time = ":" in str(pts[1][3]) or "sec" in cols[xi] or ("time" in cols[xi] and "%" not in cols[xi] and xs.max() > 100)
    if as_time:
        if not duration:
            raise VeditError("The CSV gives positions in seconds: pass the video length (--duration) or link the video.")
        ratio = xs / duration
    else:
        ratio = xs / 100.0 if xs.max() > 1.5 else xs
    ys = np.asarray([p[1] for p in pts])
    watch = ys / 100.0 if ys.max() > 2.5 else ys
    out = []
    for k, p in enumerate(pts):
        rel = p[2]
        if rel is not None and rel > 2.5:
            rel = rel / 100.0
        out.append([round(float(ratio[k]), 4), round(float(watch[k]), 4), rel])
    return sorted(out)


def import_csv(proj, path: str | Path, *, video: str | None = None, duration: float | None = None) -> dict:
    pub = _linked(proj, video) if (video or proj.meta().get("published")) else {"platform": "youtube", "video": "local"}
    dur = duration or pub.get("duration_at_link") or proj.edit().duration
    rows = parse_csv(path, duration=dur)
    data = {"platform": pub.get("platform", "youtube"), "video": pub["video"], "title": None, "duration": dur,
            "metrics": {}, "retention": rows, "source": f"csv:{Path(path).name}", "pulled": time.strftime("%Y-%m-%d %H:%M")}
    return _save(proj, data)


# ------------------------------------------------------------------ report

def _series(data: dict, D: float) -> tuple[np.ndarray, np.ndarray]:
    pts = np.asarray([[r[0], r[1]] for r in data["retention"]], dtype=float)
    t = np.clip(pts[:, 0], 0, 1) * D
    return t, pts[:, 1] * 100.0          # percent of viewers still watching


def _at(t: np.ndarray, r: np.ndarray, x: float) -> float:
    return float(np.interp(x, t, r))


def _slope(t: np.ndarray, r: np.ndarray, a: float, b: float) -> float:
    """Average change in retention (points per second) over [a, b]."""
    if b - a < 1e-6:
        return 0.0
    return (_at(t, r, b) - _at(t, r, a)) / (b - a)


def _context(edit, chunks, a: float, b: float) -> dict:
    ctx: dict[str, Any] = {}
    clips = [c for c in edit.main if c.start is not None and c.start < b and c.end > a]
    ctx["clips"] = [{"id": c.id, "label": c.label} for c in clips]
    ctx["cuts"] = [round(c.start, 2) for c in edit.main[1:] if c.start is not None and a - 0.4 <= c.start <= b + 0.4]
    words = [w for ch in chunks for w in ch.words if w.s < b and w.e > a]
    ctx["words"] = " ".join(w.w for w in words)[:160]
    gaps = []
    allw = sorted((w for ch in chunks for w in ch.words), key=lambda w: w.s)
    for w0, w1 in zip(allw, allw[1:]):
        if w1.s - w0.e >= 0.7 and w0.e < b and w1.s > a:
            gaps.append(round(w1.s - w0.e, 2))
    ctx["pause"] = max(gaps) if gaps else 0.0
    # graphics that run most of the video (progress bars, frames, watermarks) are not a moment's context
    D = max(edit.duration, 1e-6)
    ctx["graphics"] = [o.mg.template if o.mg and o.mg.template else (o.label or o.id) for o in edit.overlays
                       if o.enabled and o.start < b and o.start + o.duration > a and o.duration < 0.6 * D]
    ctx["broll"] = [c.label or c.id for c in edit.broll if c.start is not None and c.start < b and c.end > a]
    ctx["sounds"] = [x.label or x.id for x in edit.audio if x.enabled and x.role == "sfx" and a - 0.3 <= x.start <= b]
    return ctx


def _describe(kind: str, a: float, b: float, size: float, ctx: dict) -> str:
    def tc(x: float) -> str:
        return f"{int(x // 60)}:{x % 60:04.1f}"
    bits = []
    if ctx.get("pause"):
        bits.append(f"a {ctx['pause']:.1f} s pause")
    if ctx.get("words"):
        bits.append(f"while saying \"{ctx['words'][:70]}\"")
    if ctx.get("graphics"):
        bits.append("graphic: " + ", ".join(ctx["graphics"][:2]))
    if ctx.get("broll"):
        bits.append("b-roll: " + ", ".join(ctx["broll"][:2]))
    if ctx.get("cuts"):
        bits.append(f"cut at {', '.join(tc(c) for c in ctx['cuts'][:2])}")
    verb = "Lost" if kind == "drop" else "Rewatched"
    amount = f"{abs(size):.0f} points" if kind == "drop" else f"+{size:.0f} points"
    return f"{verb} {amount} at {tc(a)}-{tc(b)}" + (f" ({'; '.join(bits)})" if bits else "")


def _element_route(edit, kind: str, item) -> tuple[str, str] | None:
    """Which route (presets/routes.json) made this element, as far as the edit can tell."""
    if kind == "overlay":
        mg = item.mg
        if not mg:
            return None
        if mg.engine == "blender":
            return ("3d", "blender")
        if mg.template:
            from .mg import templates
            t = templates().get(mg.template, {})
            return ("3d", "threejs") if t.get("engine") == "three" else ("motion_graphic", "template")
        return ("motion_graphic", "custom_html")
    if kind == "broll":
        o = (edit.sources[item.source].origin or "").lower()
        for key, route in (("higgsfield", ("scene_clip", "higgsfield_video")), ("webai", ("scene_clip", "webai_video")),
                           ("pexels", ("scene_clip", "stock_video")), ("pixabay", ("scene_clip", "stock_video")),
                           ("openverse", ("image", "openverse")), ("wikimedia", ("image", "openverse")),
                           ("parallax", ("vfx", "native_depth")), ("library", ("scene_clip", "own_footage")),
                           ("camera", ("scene_clip", "own_footage"))):
            if o.startswith(key):
                return route
        return None
    if kind == "sfx":
        return ("sfx", "earshot_kit") if getattr(item, "sfx", None) else ("sfx", "own_library")
    return None


def report(proj, *, video: str | None = None, chart: bool = True) -> dict:
    from .captions import build_chunks
    pub = _linked(proj, video) if (video or proj.meta().get("published")) else {"video": "local"}
    data = read_json(proj.root / "analytics" / f"{pub['video']}.json")
    if not data:
        raise VeditError("No analytics yet: `vedit analytics pull <project>` or `vedit analytics import <project> --csv ...`.")
    edit = proj.edit()
    D = float(data.get("duration") or edit.duration)
    t, r = _series(data, D)
    if len(t) < 5:
        raise VeditError("Too few retention points to read.")
    chunks = edit.captions.chunks or build_chunks(edit)
    slopes = np.diff(r) / np.maximum(np.diff(t), 1e-6)
    mid = slopes[(t[:-1] > D * 0.1) & (t[:-1] < D * 0.9)]
    base = float(np.median(mid)) if len(mid) else float(np.median(slopes))
    # drops: steeper than 2.5x the typical slope and at least 1 point/s; rewatches: rising
    events: list[dict] = []
    k = 0
    while k < len(slopes):
        s = slopes[k]
        kind = "drop" if (s < min(-1.0, 2.5 * base) and t[k] >= 0.5) else "rewatch" if s > 0.6 else None
        if not kind:
            k += 1
            continue
        j = k
        while j + 1 < len(slopes) and ((slopes[j + 1] < min(-1.0, 2.5 * base)) if kind == "drop" else slopes[j + 1] > 0.6):
            j += 1
        a, b = float(t[k]), float(t[j + 1])
        size = float(r[j + 1] - r[k])
        if abs(size) >= 1.5:
            ctx = _context(edit, chunks, a, b)
            events.append({"kind": kind, "start": round(a, 2), "end": round(b, 2), "points": round(size, 1),
                           "context": ctx, "text": _describe(kind, a, b, size, ctx)})
        k = j + 1
    drops = sorted([e for e in events if e["kind"] == "drop"], key=lambda e: e["points"])[:6]
    rewatches = sorted([e for e in events if e["kind"] == "rewatch"], key=lambda e: -e["points"])[:4]
    # element lifts: how retention moved during each element compared with the video's typical slope
    lifts = []
    for kind, items in (("overlay", edit.overlays), ("broll", [c for c in edit.broll if c.start is not None]),
                        ("sfx", [x for x in edit.audio if x.role == "sfx"])):
        for it in items:
            a = it.start
            b = it.start + (it.duration if kind == "overlay" else (it.end - it.start) if kind == "broll" else 1.0)
            if a < 2.0 or b - a < 0.6 or b > D or b - a > 0.5 * D:
                continue
            lift = _slope(t, r, a, b) - base
            route = _element_route(edit, kind, it)
            name = (it.mg.template if kind == "overlay" and it.mg and it.mg.template else getattr(it, "label", "") or it.id)
            lifts.append({"kind": kind, "id": it.id, "name": name, "route": list(route) if route else None,
                          "lift": round(lift, 2), "window": [round(a, 2), round(b, 2)]})
    metrics = data.get("metrics", {})
    summary = {"video": pub["video"], "duration": round(D, 2), "edit_duration": round(edit.duration, 2),
               "same_cut": abs(D - edit.duration) <= 1.5, "start": round(_at(t, r, 0.0), 1),
               "at_3s": round(_at(t, r, min(3.0, D)), 1), "at_5s": round(_at(t, r, min(5.0, D)), 1),
               "at_30s": round(_at(t, r, min(30.0, D)), 1) if D >= 30 else None, "end": round(float(r[-1]), 1),
               "average": round(float(np.trapezoid(r, t) / max(D, 1e-6)), 1),
               "typical_slope": round(base, 2), "views": metrics.get("views"),
               "average_view_percentage": metrics.get("averageViewPercentage")}
    insights = []
    if not summary["same_cut"]:
        insights.append(f"The published video is {D:.1f} s and this edit is {edit.duration:.1f} s: it may not be this "
                        "cut. Times below follow the published length.")
    insights.append(f"Hook: {summary['at_3s']:.0f}% still watching at 3 s, {summary['at_5s']:.0f}% at 5 s; "
                    f"{summary['end']:.0f}% reach the end (average {summary['average']:.0f}%).")
    insights += [e["text"] for e in drops[:3]] + [e["text"] for e in rewatches[:2]]
    best = sorted([x for x in lifts if x["lift"] > 0.3], key=lambda x: -x["lift"])[:2]
    worst = sorted([x for x in lifts if x["lift"] < -0.3], key=lambda x: x["lift"])[:2]
    for x in best:
        insights.append(f"{x['kind']} '{x['name']}' held viewers better than the rest (+{x['lift']:.1f} points/s).")
    for x in worst:
        insights.append(f"{x['kind']} '{x['name']}' lost viewers faster than the rest ({x['lift']:.1f} points/s).")
    out = {"summary": summary, "drops": drops, "rewatches": rewatches, "lifts": lifts, "insights": insights,
           "source": data.get("source")}
    if chart:
        out["chart"] = str(_chart(proj, edit, t, r, D, drops, rewatches, pub["video"]))
    write_json(proj.root / "analytics" / f"{pub['video']}_report.json", out)
    return out


def _chart(proj, edit, t, r, D, drops, rewatches, vid) -> Path:
    from PIL import Image, ImageDraw
    W, H, L, R_, T, B = 1400, 460, 60, 20, 30, 70
    im = Image.new("RGB", (W, H), (18, 20, 26))
    d = ImageDraw.Draw(im)
    ymax = max(100.0, float(r.max()) * 1.05)
    X = lambda s: L + (W - L - R_) * s / max(D, 1e-6)
    Y = lambda v: T + (H - T - B) * (1 - v / ymax)
    for i, c in enumerate(edit.main):                                # clips as bands
        if c.start is None or c.start > D:
            continue
        d.rectangle([X(c.start), T, X(min(D, c.end)), H - B], fill=(28, 32, 42) if i % 2 else (34, 38, 50))
    for e in drops:
        d.rectangle([X(e["start"]), T, X(e["end"]), H - B], fill=(90, 30, 36))
    for e in rewatches:
        d.rectangle([X(e["start"]), T, X(e["end"]), H - B], fill=(30, 80, 50))
    for v in range(0, int(ymax) + 1, 20):
        d.line([L, Y(v), W - R_, Y(v)], fill=(55, 60, 72))
        d.text((8, Y(v) - 6), f"{v}%", fill=(170, 175, 185))
    for o in edit.overlays:                                          # graphics as ticks
        if o.enabled and o.start < D:
            d.polygon([(X(o.start), H - B + 4), (X(o.start) - 5, H - B + 14), (X(o.start) + 5, H - B + 14)], fill=(242, 181, 68))
    pts = [(X(a), Y(b)) for a, b in zip(t, r)]
    d.line(pts, fill=(120, 190, 255), width=3)
    for s in range(0, int(D) + 1, max(1, int(D // 12) or 1)):
        d.text((X(s) - 8, H - B + 22), f"{s}s", fill=(170, 175, 185))
    d.text((L, 8), f"Audience retention vs the edit ({vid}); red = drops, green = rewatches, ticks = graphics",
           fill=(220, 222, 228))
    out = proj.root / "analytics" / f"{vid}_retention.png"
    im.save(out)
    return out


# ------------------------------------------------------------------ learning

def learn_from(proj, *, video: str | None = None) -> dict:
    from . import learn
    rep = report(proj, video=video, chart=False)
    edit = proj.edit()
    s = rep["summary"]
    learn.event("performance", {"video": s["video"], "duration": s["duration"], "at_3s": s["at_3s"], "at_5s": s["at_5s"],
                                "average": s["average"], "end": s["end"], "drops": [
                                    {"points": e["points"], "pause": e["context"].get("pause"),
                                     "graphics": bool(e["context"].get("graphics")), "broll": bool(e["context"].get("broll")),
                                     "cut": bool(e["context"].get("cuts"))} for e in rep["drops"]],
                                "lifts": [{k: x[k] for k in ("kind", "name", "route", "lift")} for x in rep["lifts"]]},
                project=edit.name, scope={"style": edit.style or "", "brand": edit.brand or ""})
    path = personal_dir() / "learning" / "performance.json"
    perf = read_json(path, default={}) or {}
    n = 0
    for x in rep["lifts"]:
        if not x["route"]:
            continue
        need, route = x["route"]
        cell = perf.setdefault(need, {}).setdefault(route, {"n": 0, "lift_sum": 0.0})
        cell["n"] += 1
        cell["lift_sum"] = round(cell["lift_sum"] + x["lift"], 3)
        n += 1
    write_json(path, perf)
    prof = learn.rebuild()
    return {"learned_from": s["video"], "elements": n, "profile_performance": prof.get("performance")}


def route_bonus(need: str, route: str) -> tuple[float, dict | None]:
    """Score bonus for the route planner from measured retention lifts (needs 2+ observations)."""
    perf = (read_json(personal_dir() / "learning" / "performance.json", default={}) or {}).get(need, {}).get(route)
    if not perf or perf.get("n", 0) < 2:
        return 0.0, perf
    avg = perf["lift_sum"] / perf["n"]
    return max(-2.0, min(2.0, 2.0 * avg)), {**perf, "avg_lift": round(avg, 2)}


# ------------------------------------------------------------------ CLI

def register_cli(sp) -> None:
    s = sp.add_parser("publish", help="link a published video to its project (for performance learning)")
    s.add_argument("action", choices=["link", "list"]); s.add_argument("path")
    s.add_argument("--url"); s.add_argument("--platform", default="youtube"); s.add_argument("--published")
    s.set_defaults(fn=_cmd_publish)
    s = sp.add_parser("analytics", help="YouTube retention and metrics mapped onto the edit; learn from them")
    s.add_argument("action", choices=["auth", "pull", "import", "report", "learn"]); s.add_argument("path", nargs="?")
    s.add_argument("--client-secret"); s.add_argument("--no-browser", action="store_true")
    s.add_argument("--video"); s.add_argument("--csv"); s.add_argument("--duration", type=float)
    s.set_defaults(fn=_cmd_analytics)


def _cmd_publish(a) -> None:
    from .project import find
    from .util import print_json
    p = find(a.path)
    if a.action == "list":
        print_json(p.meta().get("published", []))
        return
    if not a.url:
        raise VeditError("vedit publish link <project> --url <youtube link>")
    print_json(link(p, a.url, platform=a.platform, published=a.published))


def _cmd_analytics(a) -> None:
    from .project import find
    from .util import print_json
    if a.action == "auth":
        print_json(auth(a.client_secret, open_browser=not a.no_browser))
        return
    if not a.path:
        raise VeditError(f"vedit analytics {a.action} <project>")
    p = find(a.path)
    if a.action == "pull":
        print_json(pull(p, video=a.video))
    elif a.action == "import":
        if not a.csv:
            raise VeditError("vedit analytics import <project> --csv <retention export>")
        print_json(import_csv(p, a.csv, video=a.video, duration=a.duration))
    elif a.action == "report":
        print_json(report(p, video=a.video))
    else:
        print_json(learn_from(p, video=a.video))
