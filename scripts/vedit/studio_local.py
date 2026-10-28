"""Local Studio server: the same Studio app on http://127.0.0.1, for development, headless tests and as a
fallback where Claude Artifacts are unavailable. Nothing leaves the machine.

  GET  /                        studio/index.html (and the app's js/css)
  GET  /mg/templates/*, /mg/lib/*   shipped templates + runtime (same layout as the published artifact)
  GET  /local/api/project       {pid, docs}: every database document, media pointing at /local/file/...
  GET  /local/file/<rel>        files of the project's Studio bundle (HTTP Range for video seeking)
  POST /local/api/apply         {"ops": [...]} -> studio.apply, returns report + refreshed docs
  POST /local/api/send          {"text": ...}  -> appended to edit/studio/messages.jsonl for Claude
Binds to 127.0.0.1 only and serves nothing outside the skill's app folders and the project's bundle.
"""

from __future__ import annotations

import json
import mimetypes
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .paths import SKILL_ROOT, mg_dir
from .project import Project

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/json", ".json")


def local_documents(p: Project) -> dict:
    """documents() with media URLs rewritten to /local/file/<path relative to the bundle>."""
    from . import studio
    docs = studio.documents(p)
    local = json.loads((p.root / "studio" / "media.local.json").read_text(encoding="utf-8")) \
        if (p.root / "studio" / "media.local.json").exists() else {}
    bundle = (p.root / "studio").resolve()

    def rel(f: str) -> str:
        return "/local/file/" + Path(f).resolve().relative_to(bundle).as_posix()

    media = {"sources": {}, "overlays": {}}
    for sid, m in (local.get("sources") or {}).items():
        out = {k: v for k, v in m.items() if k not in ("proxy", "sprites", "audio", "still", "peaks")}
        out["proxy"] = [{"url": rel(c["file"]), "start": c["start"], "duration": c["duration"]} for c in m.get("proxy", [])]
        out["sprites"] = [{**{k: v for k, v in s.items() if k != "file"}, "url": rel(s["file"])} for s in m.get("sprites", [])]
        for k in ("audio", "still", "peaks"):
            if m.get(k):
                out[k] = rel(m[k]["file"])
        media["sources"][sid] = out
    for oid, o in (local.get("overlays") or {}).items():
        try:
            media["overlays"][oid] = rel(o["file"])
        except ValueError:
            media["overlays"][oid] = "/local/abs/" + str(Path(o["file"]).resolve()).replace("\\", "/")
    docs["media"] = media
    return docs


def serve(p: Project, *, port: int = 8765, open_browser: bool = True) -> None:
    from . import studio
    bundle = (p.root / "studio").resolve()
    app = (SKILL_ROOT / "studio").resolve()
    mg = mg_dir().resolve()
    allowed_abs = {Path(o["file"]).resolve() for o in (json.loads((bundle / "media.local.json").read_text(encoding="utf-8"))
                   .get("overlays", {}) or {}).values()} if (bundle / "media.local.json").exists() else set()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _send_json(self, data, code: int = 200) -> None:
            body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, f: Path) -> None:
            if not f.is_file():
                self.send_error(404)
                return
            size = f.stat().st_size
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            rng = self.headers.get("Range")
            start, end = 0, size - 1
            if rng and rng.startswith("bytes="):
                a, _, b = rng[6:].partition("-")
                start = int(a) if a else max(0, size - int(b))
                end = int(b) if a and b else size - 1
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            with open(f, "rb") as fh:
                fh.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = fh.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (ConnectionResetError, BrokenPipeError):
                        return
                    remaining -= len(chunk)

        def _inside(self, root: Path, rel: str) -> Path | None:
            f = (root / unquote(rel)).resolve()
            return f if (f == root or root in f.parents) else None

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                # The Artifact tool wraps the page in a document skeleton at publish time; do the same here.
                body = ("<!doctype html><html><head><meta charset=utf-8><meta name=viewport content=\"width=device-width,"
                        "initial-scale=1,viewport-fit=cover\"><style>:root{padding-top:env(safe-area-inset-top,0px);"
                        "padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}img{max-width:100%}"
                        "[hidden]{display:none!important}</style></head><body>"
                        + (app / "index.html").read_text(encoding="utf-8") + "</body></html>").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/local/api/project":
                return self._send_json({"pid": studio.project_id(p), "local": True, "docs": local_documents(p)})
            if path.startswith("/local/file/"):
                f = self._inside(bundle, path[len("/local/file/"):])
                return self._send_file(f) if f else self.send_error(403)
            if path.startswith("/local/abs/"):
                f = Path(unquote(path[len("/local/abs/"):])).resolve()
                return self._send_file(f) if f in allowed_abs else self.send_error(403)
            if path == "/mg/lib/base.css":
                return self._send_file(studio.studio_base_css())
            if path.startswith("/mg/"):
                f = self._inside(mg, path[len("/mg/"):])
                return self._send_file(f) if f else self.send_error(403)
            f = self._inside(app, path.lstrip("/"))
            return self._send_file(f) if f else self.send_error(403)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            if path == "/local/api/apply":
                with tempfile.TemporaryDirectory() as tmp:
                    f = Path(tmp) / "ops.json"
                    f.write_text(json.dumps([{"seq": i, "op": op} for i, op in enumerate(body.get("ops", []))],
                                            ensure_ascii=False), encoding="utf-8")
                    report = studio.apply(p, f)
                docs = local_documents(p)
                report["docs"] = {k: docs[k] for k in ("meta", "edit", "suggestions", "directions") if k in docs}
                return self._send_json(report)
            if path == "/local/api/send":
                msg = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), **body}
                with open(bundle / "messages.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(msg, ensure_ascii=False) + "\n")
                p.log(f"studio message: {str(body.get('text', ''))[:200]}")
                return self._send_json({"ok": True})
            self.send_error(404)

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/?local=1"
    print(json.dumps({"studio": url, "project": str(p.root)}), flush=True)
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def register_cli(sp) -> None:
    s = sp.add_parser("studio-local", help="serve the Studio on 127.0.0.1 (dev, tests, no-Artifact fallback)")
    s.add_argument("path"); s.add_argument("--port", type=int, default=8765); s.add_argument("--no-open", action="store_true")
    s.set_defaults(fn=lambda a: serve(__import__("vedit.project", fromlist=["find"]).find(a.path), port=a.port,
                                      open_browser=not a.no_open))
