"""Assemble a piece's one-file page: <piece>/index.html from its src/ parts, the kit and its style.

Order (piece.json "build" replaces it; "scenes" replaces src/scenes.js with several files, one per era or agent):
    src/head.html, kit/core.js, style, src/scenes.js, src/bridges.js, kit/morph.js, kit/board.js,
    kit/score-head.js, src/score.js, kit/score-tail.js
Injected right after "use strict" (before the head's code): OVERLAY, LOOP_AUDIO, BEATS (beats.json), VOICE
(voice.json), ASSETS (assets/: the owner's screenshots and logos, embedded so the canvas stays readable).
Appended: vedit's adapter, so the page is an ordinary MG composition (window.__seek / __duration / __ready, the
format from __VEDIT_DATA__, sub-frame motion blur for styles on 1s, bundled fonts preloaded).
Checks: one <script>, `const STYLE` defined, no network URLs or data: URIs in the code, the script compiles (Node).
Adapted from animate's tools/build.mjs (MIT, (c) 2026 cth9191).
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path

from ..util import VeditError, read_json, which
from . import ANIM, style_dir

DEFAULT = ["src/head.html", "kit/core.js", "style", "src/scenes.js", "src/bridges.js", "kit/morph.js", "kit/board.js",
           "kit/score-head.js", "src/score.js", "kit/score-tail.js"]
MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif",
        "svg": "image/svg+xml"}
# bundled OFL families the kit's font stacks name (served at /__fonts/ by the renderer, Google Fonts in the Studio)
FONT_FAMILIES = ["Caveat Brush", "Permanent Marker", "Atma", "Galada", "Hind Siliguri", "Tiro Bangla"]
STUDIO_LIVE_MAX = 190_000            # bytes: a page this size plays live in the Studio (one database document, ~200 KB)

ADAPTER = r"""
// ---- vedit adapter (anim/build.py): the page as an MG composition for vedit's renderer and Studio
if (typeof HAND === 'undefined') window.HAND = '"Caveat Brush", "Atma", cursive';
window.__duration = TIMELINE.duration;
window.__fps = TIMELINE.fps;
window.__seek = (t) => {
  const d = window.__VEDIT_DATA__ || {}, n = Math.max(1, d.blur | 0);
  if (typeof window.renderFrame !== 'function') return;
  if (n <= 1 || !(typeof STYLE === 'object' && STYLE.ones)) { window.renderFrame(t); return; }
  // motion blur: n sub-frames across half the frame interval (a 180-degree shutter), averaged
  const cv = document.getElementById('c'), tmp = document.createElement('canvas'); tmp.width = cv.width; tmp.height = cv.height;
  const acc = new Float32Array(cv.width * cv.height * 4);
  for (let j = 0; j < n; j++) {
    window.renderFrame(t + (j / n) * 0.5 / TIMELINE.fps, tmp, true);
    const px = tmp.getContext('2d').getImageData(0, 0, tmp.width, tmp.height).data;
    for (let k = 0; k < px.length; k++) acc[k] += px[k];
  }
  const g = cv.getContext('2d'), img = g.createImageData(cv.width, cv.height);
  for (let k = 0; k < acc.length; k++) img.data[k] = acc[k] / n;
  g.putImageData(img, 0, 0);
};
window.__ready = Promise.all([
  window.ASSETS_READY || null,
  ...(document.fonts ? __FONTS__.flatMap((f) => ['400', '700'].map((w) => document.fonts.load(`${w} 40px "${f}"`, 'Aa অআক্ষ').catch(() => null))) : []),
]).then(() => { if (typeof window.renderFrame === 'function') window.renderFrame(0); });
"""

HEAD_EXTRA = """<link rel="stylesheet" href="/__mg/base.css">
<script>if (window.__VEDIT_RENDERING__) document.documentElement.classList.add('vedit-render');</script>
<style>
  .vedit-render body { display: block !important; }
  .vedit-render canvas { width: 100vw !important; height: 100vh !important; max-width: none !important; max-height: none !important;
    aspect-ratio: auto !important; object-fit: contain; cursor: default; }
  .vedit-render.vedit-overlay, .vedit-render.vedit-overlay body { background: transparent !important; }
</style>
"""


def _resolve(part: str, piece_dir: Path, style: str) -> Path:
    if part == "style":
        return style_dir(style, piece_dir) / "kit.js"
    if part.startswith("kit/"):
        return ANIM / "kit" / part[4:]
    m = re.match(r"^styles/([^/]+)/(.+)$", part)
    if m and not (piece_dir / part).exists():
        return style_dir(m.group(1), piece_dir) / m.group(2)
    return piece_dir / part


def _compile_check(script: str) -> str | None:
    node = which("node")
    if not node:
        return None
    js = ("const vm=require('vm');let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',d=>s+=d)"
          ".on('end',()=>{try{new vm.Script(s,{filename:'index.html'});}catch(e){console.error(e.message);process.exit(1);}});")
    p = subprocess.run([node, "-e", js], input=script, capture_output=True, text=True, encoding="utf-8", timeout=120)
    return (p.stderr or "syntax error").strip() if p.returncode else None


def build(piece_dir: str | Path) -> dict:
    """Build <piece>/index.html. Returns {path, bytes, lines, style, parts, extras, studio_live}."""
    root = Path(piece_dir)
    meta = read_json(root / "piece.json", default={}) or {}
    style = meta.get("style") or "cut-paper"
    parts = meta.get("build") or ([q for p in DEFAULT for q in (meta["scenes"] if p == "src/scenes.js" else [p])]
                                  if meta.get("scenes") else DEFAULT)
    out = ""
    for p in parts:
        f = _resolve(p, root, style)
        if not f.exists():
            raise VeditError(f"missing part: {p} ({f})")
        out += f.read_text(encoding="utf-8").rstrip() + "\n"
    m = re.search(r"<script>([\s\S]*)</script>", out)
    if not m:
        raise VeditError("no <script> block found (the head must open it and kit/score-tail.js closes it)")
    if not re.search(r"\bconst STYLE\s*=", m.group(1)):
        raise VeditError("no STYLE hooks: the style kit must define `const STYLE = { ... }`")
    bad = [(i + 1, l.strip()[:80]) for i, l in enumerate(out.splitlines()) if re.search(r"data:[a-z]+/|https?://", l, re.I)]
    if bad:
        raise VeditError("forbidden in the code (a data: URI or a web URL; assets go in assets/): "
                         + " | ".join(f"{n}: {l}" for n, l in bad[:5]))
    # pages copied from upstream animate read the format from the URL only
    out = out.replace("const FORMAT = new URLSearchParams(location.search).get('format') || '9:16';",
                      "const FORMAT = (window.__VEDIT_DATA__ && window.__VEDIT_DATA__.format) || "
                      "new URLSearchParams(location.search).get('format') || '9:16';")

    inject = [f"const OVERLAY = {json.dumps(bool(meta.get('overlay')))};",
              f"const LOOP_AUDIO = {json.dumps(bool(meta.get('loop')))};"]
    extras = []
    if (root / "beats.json").exists():
        inject.append("// ---- beats.json (vedit anim beats): the supplied track's tempo, beats, bars and hits\n"
                      f"const BEATS = {json.dumps(read_json(root / 'beats.json'), ensure_ascii=False)};")
        extras.append("beats.json")
    if (root / "voice.json").exists():
        v = read_json(root / "voice.json")
        inject.append("// ---- voice.json (vedit anim voice): the voice-over's lines and word times\n"
                      f"const VOICE = {json.dumps(v, ensure_ascii=False)};")
        extras.append("voice.json")
    assets = sorted(f for f in (root / "assets").glob("*") if f.suffix.lower().lstrip(".") in MIME) \
        if (root / "assets").exists() else []
    asset_bytes = 0
    if assets:
        src = {}
        for f in assets:
            b = f.read_bytes()
            asset_bytes += len(b)
            src[f.name] = f"data:{MIME[f.suffix.lower().lstrip('.')]};base64," + base64.b64encode(b).decode("ascii")
        inject.append(f"// ---- assets/ (embedded by vedit anim build): {', '.join(f.name for f in assets)}\n"
                      "const ASSETS = {};\nwindow.ASSETS_READY = Promise.all(Object.entries("
                      f"{json.dumps(src)}).map(([k, u]) => {{ const i = new Image(); i.src = u; ASSETS[k] = i; return i.decode(); }}));")
        extras.append(f"{len(assets)} asset(s), {asset_bytes / 1e6:.1f} MB")
    at = out.find('"use strict";')
    at = at + len('"use strict";') if at >= 0 else out.find("<script>") + len("<script>")
    out = out[:at] + "\n" + "\n".join(inject) + out[at:]
    end = out.rfind("</script>")
    tail = ""
    if assets:   # hold renderFrame until the assets are decoded (every tool waits for it)
        tail += ("// ---- hold renderFrame until the assets are decoded\n{ const rf = window.renderFrame; "
                 "window.renderFrame = undefined; window.ASSETS_READY.then(() => { window.renderFrame = rf; }); }\n")
    tail += ADAPTER.replace("__FONTS__", json.dumps(FONT_FAMILIES))
    out = out[:end] + tail + out[end:]
    head_extra = HEAD_EXTRA if not meta.get("overlay") else HEAD_EXTRA.replace(
        "document.documentElement.classList.add('vedit-render');",
        "document.documentElement.classList.add('vedit-render', 'vedit-overlay');")
    out = re.sub(r"</head>", lambda _: head_extra + "</head>", out, count=1)
    script = re.search(r"<script>([\s\S]*)</script>", out[out.find("<body"):] if "<body" in out else out)
    err = _compile_check(script.group(1)) if script else "no script"
    if err:
        raise VeditError(f"syntax error in the built page: {err}")
    path = root / "index.html"
    path.write_text(out, encoding="utf-8")
    size = len(out.encode("utf-8"))
    res = {"path": str(path), "bytes": size, "lines": out.count("\n"), "style": style, "parts": len(parts),
           "extras": extras, "studio_live": size <= STUDIO_LIVE_MAX}
    if asset_bytes > 12e6:
        res["warning"] = f"{asset_bytes / 1e6:.1f} MB of assets: resize screenshots to the size they are shown at"
    return res
