"""Phase 4 checks: 3D templates, Blender, tracking, screen replacement, follow labels, tracked face blur,
person cut-outs (text behind the person, background blur, outline), depth (parallax, depth of field),
camera FX, plus the render fixes found on the way. Run from the skill root:

    scripts/.venv/Scripts/python.exe tests/test_phase4.py            # everything but Blender (~6 min)
    scripts/.venv/Scripts/python.exe tests/test_phase4.py --blender  # + Blender templates (~6 min more)

Needs the models the owner agreed to (modnet, depth_small; birefnet_lite optional). Every check measures
the result against ground truth (synthetic footage with known motion) or pixels, not just that a file
appeared.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ["VEDIT_PERSONAL_DIR"] = str(ROOT / "tests" / "out" / "personal_test")

import numpy as np  # noqa: E402

from vedit import mg, models  # noqa: E402
from vedit.media import ffmpeg, probe  # noqa: E402

OUT = ROOT / "tests" / "out" / "phase4"
LIZ = ROOT / "tests" / "footage" / "e2e" / "liz_epidemiologist.webm"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)


def ff(*args: str) -> None:
    p = subprocess.run([ffmpeg(), "-v", "error", "-y", *args], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-800:])


def vedit(*args: str) -> dict:
    p = subprocess.run([sys.executable, "-m", "vedit.cli", *args], capture_output=True, text=True, cwd=ROOT / "scripts",
                       env={**os.environ, "PYTHONUTF8": "1"})
    out = p.stdout.strip()
    if p.returncode:
        raise RuntimeError(f"vedit {' '.join(args)} failed: {p.stderr[-1500:]}")
    return json.loads(out[out.index("{"):]) if "{" in out else {}


def frame(path, t: float, w: int | None = None, gray: bool = False) -> np.ndarray:
    info = probe(path)
    W, H = (w, int(round(info.height * w / info.width / 2)) * 2) if w else (info.width, info.height)
    pix = "gray" if gray else "rgb24"
    p = subprocess.run([ffmpeg(), "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-vf", f"scale={W}:{H}",
                        "-f", "rawvideo", "-pix_fmt", pix, "-"], capture_output=True)
    a = np.frombuffer(p.stdout, np.uint8)
    return a.reshape(H, W) if gray else a.reshape(H, W, 3)


def rgba(path: Path) -> np.ndarray:
    import cv2
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_UNCHANGED)


def sharp(img: np.ndarray) -> float:
    import cv2
    g = img if img.ndim == 2 else cv2.cvtColor(img.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def sharp_in(img: np.ndarray, mask: np.ndarray) -> float:
    """Detail (Laplacian variance) measured only inside a mask (eroded, so the mask edge does not count)."""
    import cv2
    g = img if img.ndim == 2 else cv2.cvtColor(img.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    lap = cv2.Laplacian(g, cv2.CV_64F)
    m = cv2.erode(mask.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    return float(lap[m].var()) if m.any() else 0.0


def nframes(path) -> int:
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-count_frames", "-show_entries",
                        "stream=nb_read_frames", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return int(p.stdout.strip() or 0)


def at(rows, t):
    a = np.asarray(rows)
    return a[int(np.argmin(np.abs(a[:, 0] - t))), 1:]


# ------------------------------------------------------------------ 3D templates

def test_templates() -> None:
    d = OUT / "tpl"
    d.mkdir(parents=True, exist_ok=True)
    scr = OUT / "screen.png"
    ff("-f", "lavfi", "-i", "testsrc2=s=1280x720:d=1", "-frames:v", "1", str(scr))
    jobs = {
        "title_3d": ({"text": "MAKE IT POP", "subtitle": "3D titles"}, 1.8),
        "title_3d_bn": ({"text": "বাংলা থ্রিডি", "color": "#FFE14D"}, 1.8),
        "logo_3d": ({"text": "VEDIT", "tagline": "edit with Claude"}, 2.0),
        "product_spin": ({"image": scr.as_posix(), "title": "Test", "price": "$19"}, 2.2),
        "device_mockup": ({"screen": scr.as_posix(), "device": "phone"}, 2.0),
        "particles": ({"mode": "confetti", "burst_at": 0.2}, 1.0),
        "camera_flythrough": ({"words": ["IDEA", "EDIT"], "end_text": "POST"}, 3.0),
        "chart_3d": ({"title": "Views", "bars": [{"label": "A", "value": 10}, {"label": "B", "value": 40}], "unit": "k"}, 3.2),
        "globe": ({}, 3.5),
    }
    for name, (data, t) in jobs.items():
        tpl = name.replace("_bn", "")
        png = mg.still(mg.template_path(tpl), d / f"{name}.png", width=540, height=960, t=t, data={"duration": 5, **data})
        a = rgba(png)[..., 3] if rgba(png).shape[2] == 4 else None
        cov = float((a > 10).mean()) if a is not None else 0.0
        check(f"3D template {name}: renders with transparency", a is not None and 0.004 < cov < 0.9, f"coverage {cov:.3f}")
    outs = mg.render_html(mg.template_path("title_3d"), d / "title3d", width=540, height=960, fps=30, duration=1.5,
                          data={"text": "GO"}, formats=["webm"])
    i = probe(outs[0])
    check("3D template animates to an alpha WebM of the right length", abs(i.duration - 1.5) < 0.05 and i.has_alpha,
          f"{i.duration}s alpha={i.has_alpha}")
    from vedit.studio import app_files
    files = app_files()
    kit = (ROOT / "mg" / "lib" / "three-kit.js").read_text(encoding="utf-8")
    check("Studio publishes the 3D kit and templates (three.js from jsDelivr via the import map)",
          "mg/lib/three-kit.js" in files and "mg/templates/globe.html" in files and "https://" not in kit.split("import")[0])


# ------------------------------------------------------------------ tracking + compose

def make_project() -> tuple[Path, dict]:
    import p4_footage
    synth = OUT / "synth"
    truth = p4_footage.make(synth) if not (synth / "truth.json").exists() else json.loads((synth / "truth.json").read_text())
    foot = OUT / "foot"
    if foot.exists():
        shutil.rmtree(foot)
    foot.mkdir(parents=True)
    shutil.copy(synth / "plane.mp4", foot / "plane.mp4")
    shutil.copy(synth / "box.mp4", foot / "box.mp4")
    ff("-ss", "30", "-t", "10", "-i", str(LIZ), "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
       str(foot / "liz.mp4"))
    vedit("project", "init", str(foot), "--ratio", "16:9", "--name", "p4test")
    keeps = foot / "edit" / "keeps.json"
    keeps.write_text(json.dumps([{"source": "plane", "from": 0.0, "to": 3.9, "exact": True},
                                 {"source": "box", "from": 0.0, "to": 3.9, "exact": True},
                                 {"source": "liz", "from": 0.5, "to": 6.5, "exact": True}]))
    vedit("plan", "apply", str(foot), str(keeps))
    vedit("mode", str(foot), "auto")
    return foot, truth


def test_tracking(foot: Path, truth: dict) -> None:
    from vedit.vfx import planar, track
    synth = OUT / "synth"
    tb = truth["box"]
    mid = tb[60]
    for method in ("auto", "vit"):
        s = track.finish_box_samples(track.track_box(str(synth / "box.mp4"), None, at=mid[0], box=tuple(mid[1:]), t0=0.0,
                                                     t1=3.9, method=method, progress=False))
        errs, ious = [], []
        for row in s:
            g = at(tb, row[0])
            x, y, w, h = row[1:5]
            errs.append(np.hypot((x + w / 2) - (g[0] + g[2] / 2), (y + h / 2) - (g[1] + g[3] / 2)))
            ix = max(0, min(x + w, g[0] + g[2]) - max(x, g[0]))
            iy = max(0, min(y + h, g[1] + g[3]) - max(y, g[1]))
            ious.append(ix * iy / (w * h + g[2] * g[3] - ix * iy))
        lim = (5, 0.92) if method == "auto" else (12, 0.8)
        check(f"object tracking ({method}) follows a moving, growing patch forwards and backwards",
              np.mean(errs) < lim[0] and np.mean(ious) > lim[1], f"centre error {np.mean(errs):.1f}px, IoU {np.mean(ious):.3f}")
    tp = truth["plane"]
    mid = tp[45]
    s = planar.track_plane(str(synth / "plane.mp4"), None, at=mid[0], corners=np.asarray(mid[1:]).reshape(4, 2).tolist(),
                           t0=0.0, t1=3.9, progress=False)
    errs = [np.linalg.norm(np.asarray(r[1:9]).reshape(4, 2) - at(tp, r[0]).reshape(4, 2), axis=1).mean() for r in s]
    check("planar tracking: corners of a turning, jittering screen", np.mean(errs) < 1.5 and np.percentile(errs, 95) < 3,
          f"mean {np.mean(errs):.2f}px, p95 {np.percentile(errs, 95):.2f}px")
    f0 = frame(synth / "plane.mp4", 1.5)[..., ::-1].copy()
    cands = planar.suggest_quads(f0)
    gt = np.asarray(at(tp, 1.5)).reshape(4, 2)
    best = min((np.linalg.norm(np.asarray(c["corners"]) - gt, axis=1).mean() for c in cands), default=999)
    check("screen suggestion finds the screen's corners in a busy frame", best < 25, f"best candidate {best:.1f}px off")

    # edit: screen replacement, an attached label, tracked face blur
    P = str(foot)
    corners = ",".join(f"{v:.1f}" for v in at(tp, 1.5))
    mag = foot / "edit" / "assets" / "magenta.png"
    ff("-f", "lavfi", "-i", "color=c=0xff00ff:s=400x700", "-frames:v", "1", str(mag))
    r = vedit("vfx", "screen", P, "--clip", "m001", "--at", "1.5", "--corners", corners, "--media", str(mag))
    check("vfx screen: tracked on the clip, no lost frames", r["tracked"] and r["tracked"][0]["lost_frames"] == 0,
          json.dumps(r["tracked"]))
    g = at(tb, 2.0)
    r = vedit("vfx", "track", P, "--clip", "m002", "--box", ",".join(str(int(v)) for v in g), "--at", "2.0", "--id", "boxy")
    check("vfx track: saved with the edit", r["track"] == "boxy" and r["lost_frames"] == 0, f"{r['frames']} frames")
    sheet = vedit("vfx", "sheet", P, "--track", "boxy")
    check("vfx sheet: frames with the track drawn, for Claude's eyes", Path(sheet["sheet"]).exists())
    import cv2 as _cv
    ring = np.zeros((90, 90, 4), np.uint8)
    _cv.circle(ring, (45, 45), 38, (0, 255, 0, 255), 8)
    _cv.imwrite(str(foot / "edit" / "assets" / "ring.png"), ring)
    from vedit.project import find
    from vedit.timeline import Overlay
    p = find(foot)
    e = p.edit()
    e.overlays.append(Overlay(id="tag", start=3.9, duration=3.9, path=str(foot / "edit" / "assets" / "ring.png")))
    p.save_edit(e)
    r = vedit("vfx", "attach", P, "tag", "--track", "boxy")
    check("vfx attach: the label is on screen for the whole box clip", r["frames_on_screen"] >= 110, str(r["frames_on_screen"]))
    r = vedit("vfx", "faces", P, "--clip", "m003", "--blur")
    check("vfx faces: the speaker's face tracked over the clip and blurred", r["faces"] and r["faces"][0]["frames_seen"] > 150
          and r["redactions_added"] == 1, json.dumps(r["faces"][0]) if r["faces"] else "no face")

    r = vedit("render", P, "--preview")
    out = Path(r["output"])
    check("render: VFX edit keeps every frame (no stall)", nframes(out) == int(round(probe(out).duration * 30)) == 414,
          f"{nframes(out)} frames")
    # screen: the magenta insert covers the tracked quad, nothing outside it
    k = 960 / 1280 * (1920 / 1280) / 1.5          # preview px per source px (1280 source -> 1920 canvas -> 960 preview)
    fills, spill = [], []
    for t in (0.5, 1.5, 2.8, 3.6):
        img = frame(out, t).astype(int)
        mag_px = (img[..., 0] > 180) & (img[..., 1] < 100) & (img[..., 2] > 180)      # preview: CRF 30 smears chroma
        base = frame(foot / "plane.mp4", t, w=960).astype(int)                          # pink circles in the background
        mag_px_base = (base[..., 0] > 180) & (base[..., 1] < 100) & (base[..., 2] > 180)
        q = (np.asarray(at(tp, t)).reshape(4, 2) * k).astype(np.int32)
        inside = np.zeros(mag_px.shape, np.uint8)
        _cv.fillConvexPoly(inside, q, 1)
        core = _cv.erode(inside, np.ones((5, 5), np.uint8)).astype(bool)
        outer = ~_cv.dilate(inside, np.ones((7, 7), np.uint8)).astype(bool)
        fills.append(mag_px[core].mean())
        spill.append((mag_px & ~_cv.dilate(mag_px_base.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool))[outer].mean())
    check("screen replacement: the insert fills the moving screen and stays inside it", min(fills) > 0.95 and max(spill) < 0.01,
          f"fill {min(fills):.3f}, outside {max(spill):.4f}")
    # attached ring: centre of the green ring vs the box centre
    errs = []
    for T in (4.3, 5.0, 6.0, 7.2):
        img = frame(out, T).astype(int)
        base = frame(foot / "box.mp4", T - 3.9, w=960).astype(int)      # the same picture without the ring
        green = (img[..., 1] > 190) & (img[..., 0] < 90) & (img[..., 2] < 90)
        green &= ~_cv.dilate(((base[..., 1] > 150) & (base[..., 0] < 130) & (base[..., 2] < 130)).astype(np.uint8),
                             np.ones((5, 5), np.uint8)).astype(bool)
        ys, xs = np.nonzero(green)
        g = at(tb, T - 3.9)
        cx, cy = (g[0] + g[2] / 2) * 0.75, (g[1] + g[3] / 2) * 0.75
        errs.append(np.hypot(np.median(xs) - cx, np.median(ys) - cy) if len(xs) else 999)
    check("attached label follows the tracked box in the render", np.median(errs) < 8, "errors " + ", ".join(f"{e:.1f}" for e in errs))
    # faces: blurred and undetectable
    from vedit import faces
    src_f = frame(foot / "liz.mp4", 2.0)
    det = faces.detect(src_f[..., ::-1].copy())
    x, y, w, h, _ = det[0]
    sc = 960 / 1280
    seen = 0
    for T in (8.3, 9.5, 11.0, 12.5, 13.4):
        rf = frame(out, T)
        seen += bool(faces.detect(_cv.resize(rf[..., ::-1].copy(), (1280, 720))))
    rf = frame(out, 7.8 + 1.5)
    s0 = sharp(src_f[int(y):int(y + h), int(x):int(x + w)])
    s1 = sharp(_cv.resize(rf, (1280, 720))[int(y):int(y + h), int(x):int(x + w)])
    check("tracked face blur: the face loses detail and the detector no longer finds it", s1 < 0.3 * s0 and seen <= 1,
          f"detail {s0:.0f} -> {s1:.0f}, face found in {seen}/5 frames")


def test_subject(foot: Path) -> None:
    import cv2
    from vedit.project import find
    from vedit.timeline import MGSpec, Overlay
    P = str(foot)
    p = find(foot)
    e = p.edit()
    c = next(c for c in e.main if c.id == "m003")
    c.redact = []
    e.overlays = [o for o in e.overlays if o.id != "tag"]
    e.overlays.append(Overlay(id="behind", start=7.8, duration=6.0, layer=0,
                              mg=MGSpec(template="text_punch", data={"text": "BEHIND", "y": 0.38, "color": "#FFE14D"})))
    p.save_edit(e)
    vedit("vfx", "subject", P, "--clip", "m003", "--background", "blur:16", "--outline", "#ffffff:8", "--above", "1")
    vedit("mg", "render", P)
    r = vedit("render", P, "--preview")
    out = Path(r["output"])
    check("render with a person cut-out keeps every frame", nframes(out) == 414, str(nframes(out)))
    from vedit.vfx import matte
    T = 7.8 + 2.0
    src = frame(foot / "liz.mp4", 0.5 + 2.0)
    a = matte.modnet(src[..., ::-1].copy())
    m = cv2.resize(a, (960, 540)) > 0.5
    img = frame(out, T)
    plain = cv2.resize(src, (960, 540))
    yellow = (img[..., 0] > 200) & (img[..., 1] > 170) & (img[..., 2] < 110)
    inner = cv2.erode(m.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    outer = ~cv2.dilate(m.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    check("text behind the person: the title shows around her, never over her", yellow[outer].sum() > 2000 and
          yellow[inner].mean() < 0.01, f"title px outside {int(yellow[outer].sum())}, over the person {yellow[inner].mean():.4f}")
    bg = outer & ~yellow
    sb, sp = sharp_in(img, bg) / max(1e-6, sharp_in(plain, bg)), sharp_in(img, inner) / max(1e-6, sharp_in(plain, inner))
    check("background blurred, the person kept sharp", sb < 0.5 and sp > 0.6, f"background detail kept {sb:.2f}, person {sp:.2f}")
    mu = m.astype(np.uint8)
    ring = cv2.dilate(mu, np.ones((13, 13), np.uint8)).astype(bool) & ~cv2.dilate(mu, np.ones((5, 5), np.uint8)).astype(bool)
    bright, before = (img.min(axis=2) > 200)[ring].mean(), (plain.min(axis=2) > 200)[ring].mean()
    check("sticker outline drawn around the person", bright > 0.3 and bright > 2 * before,
          f"{bright:.2f} of the edge is white (was {before:.2f})")


def test_depth(foot: Path) -> None:
    import cv2
    from vedit import faces
    still = OUT / "still.jpg"
    ff("-ss", "4", "-i", str(foot / "liz.mp4"), "-frames:v", "1", str(still))
    r = vedit("vfx", "depth", str(still), "--out", str(OUT / "depth.png"))
    d = cv2.imdecode(np.fromfile(str(OUT / "depth.png"), np.uint8), cv2.IMREAD_UNCHANGED).astype(float) / 65535
    img = cv2.imread(str(still))
    x, y, w, h, _ = faces.detect(img)[0]
    face_d = float(np.median(d[int(y):int(y + h), int(x):int(x + w)]))
    wall_d = float(np.median(d[20:120, 20:300]))
    check("depth: the speaker is nearer than the wall behind her", face_d > wall_d + 0.2, f"face {face_d:.2f}, wall {wall_d:.2f}")
    r = vedit("vfx", "dof-image", str(still), "--out", str(OUT / "dof.png"))
    dof = cv2.imread(str(OUT / "dof.png"))
    fs = sharp(dof[int(y):int(y + h), int(x):int(x + w)]) / max(1, sharp(img[int(y):int(y + h), int(x):int(x + w)]))
    ws = sharp(dof[20:120, 20:300]) / max(1, sharp(img[20:120, 20:300]))
    check("depth of field (auto focus): face sharp, wall soft", fs > 0.7 and ws < 0.5, f"face kept {fs:.2f}, wall kept {ws:.2f}, focus {r['focus']}")
    r = vedit("vfx", "parallax", str(still), "--out", str(OUT / "parallax.mp4"), "--duration", "3", "--move", "dolly_in")
    f0, f1 = frame(OUT / "parallax.mp4", 0.0, w=480), frame(OUT / "parallax.mp4", 2.9, w=480)
    border = min(f1[:4].mean(), f1[-4:].mean(), f1[:, :4].mean(), f1[:, -4:].mean())
    check("3D photo: the camera moves into the still without revealing edges", np.abs(f0.astype(int) - f1.astype(int)).mean() > 8
          and border > 25 and r["frames"] == 90, f"change {np.abs(f0.astype(int) - f1.astype(int)).mean():.1f}, border {border:.0f}")
    for model in ("modnet", "birefnet"):
        if model == "birefnet" and not models.is_ready("birefnet_lite"):
            check("cut-out (birefnet): skipped, model not downloaded", True)
            continue
        r = vedit("vfx", "cutout", str(still), "--out", str(OUT / f"cut_{model}.png"), "--model", model)
        a = rgba(Path(r["output"]))[..., 3]
        check(f"still cut-out ({model}): the person kept, the room removed", 0.15 < r["coverage"] < 0.45 and
              a[int(y + h / 2), int(x + w / 2)] > 200 and a[40, 40] < 20, f"coverage {r['coverage']}")
    # depth of field on a clip, focus pulled from her to the wall
    P = str(foot)
    vedit("vfx", "subject", P, "--clip", "m003", "--clear")
    vedit("vfx", "dof", P, "--clip", "m003", "--blur", "12")
    from vedit.project import find
    p = find(foot)
    e = p.edit()
    e.overlays = [o for o in e.overlays if o.id != "behind"]
    p.save_edit(e)
    out = Path(vedit("render", P, "--preview")["output"])
    img = frame(out, 7.8 + 2.0)
    plain = cv2.resize(frame(foot / "liz.mp4", 2.5), (960, 540))
    fx, fy, fw, fh = (int(v * 0.75) for v in (x, y, w, h))
    check("clip depth of field: face sharp, wall soft, every frame kept", nframes(out) == 414 and
          sharp(img[fy:fy + fh, fx:fx + fw]) > 0.6 * sharp(plain[fy:fy + fh, fx:fx + fw]) and
          sharp(img[10:80, 10:220]) < 0.5 * sharp(plain[10:80, 10:220]), f"{nframes(out)} frames")


def test_camera(foot: Path) -> None:
    import cv2
    from vedit.project import find
    from vedit.timeline import EffectItem, Transition
    p = find(foot)
    e = p.edit()
    for c in e.main:
        c.dof = None
        c.screen = []
    m = {c.id: c for c in e.main}
    m["m002"].transition_in = Transition(type="whip_left", duration=0.4)
    e.effects = [EffectItem(id="mb", start=4.5, duration=1.0, render="motion_blur"),
                 EffectItem(id="hh", start=0.5, duration=3.0, render="handheld")]
    p.save_edit(e)
    out = Path(vedit("render", str(foot), "--preview")["output"])
    n = nframes(out)
    check("whip transition from a clip starting at source 0 keeps the timing (edge frame held)", n == 414 and
          abs(probe(out).duration - 13.8) < 0.04, f"{n} frames, {probe(out).duration}s")
    s_cut = sharp(frame(out, 3.9, gray=True))
    s_out = sharp(frame(out, 3.0, gray=True))
    check("whip: heavy directional blur across the cut", s_cut < 0.35 * s_out, f"detail {s_out:.0f} -> {s_cut:.0f} at the cut")
    s_mb, s_no = sharp(frame(out, 5.0, gray=True)), sharp(frame(out, 6.5, gray=True))
    check("motion blur effect softens its window only", s_mb < 0.8 * s_no, f"{s_no:.0f} -> {s_mb:.0f}")
    a, b = frame(out, 1.0, gray=True).astype(np.float32), frame(out, 1.4, gray=True).astype(np.float32)
    sh, _ = cv2.phaseCorrelate(a, b)
    check("handheld drift moves the frame", np.hypot(*sh) > 1.0, f"shift {np.hypot(*sh):.1f}px in 0.4 s")
    tags = {subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=color_space,color_range",
                            "-of", "csv=p=0", str(f)], capture_output=True, text=True).stdout.strip()
            for f in (foot / "edit" / "render" / "work").glob("seg_*.mp4")}
    check("every clip segment leaves with the same BT.709 tags (no mid-stream reconfigure)", tags == {"tv,bt709"}, str(tags))


def test_misc(foot: Path) -> None:
    from vedit.exports import flatten
    from vedit.project import find
    p = find(foot)
    e = p.edit()
    c = next(c for c in e.main if c.id == "m003")
    c.subject = {"background": "blur:12"}
    notes = [it.note for tr in flatten(e).tracks for it in tr.items if getattr(it, "note", "")]
    check("hand-offs note VFX that only the vedit render has", any("person cut-out" in n for n in notes),
          next((n for n in notes if "cut-out" in n), "")[:90])
    routes = json.loads((ROOT / "presets" / "routes.json").read_text(encoding="utf-8"))
    ids = {r["id"] for r in routes["vfx"]} | {r["id"] for r in routes["3d"]}
    check("route planner knows the native VFX and 3D routes", {"native_track", "native_planar", "native_matte", "native_depth",
                                                                "native_camera", "threejs", "blender"} <= ids)
    ck = vedit("vfx", "check")
    check("vfx check: VitTrack, models and Blender reported", ck["vit_tracker"] and ck["models"]["modnet"]["ready"]
          and "depth_small" in ck["models"], ck.get("blender", ""))


def test_blender() -> None:
    from vedit import blender
    d = OUT / "blender"
    d.mkdir(parents=True, exist_ok=True)
    svg = d / "logo.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">'
                   '<circle cx="100" cy="100" r="90" fill="#1f6feb"/>'
                   '<path d="M100 30 L120 80 L172 80 L130 112 L146 164 L100 132 L54 164 L70 112 L28 80 L80 80 Z" fill="#ffd84d"/></svg>')
    cut = d / "card.png"
    ff("-f", "lavfi", "-i", "testsrc2=s=600x800:d=1", "-frames:v", "1", str(cut))
    for tpl, data in (("title_3d", {"text": "VEDIT 3D"}), ("logo_3d", {"logo": str(svg)}),
                      ("product_turntable", {"image": str(cut)})):
        png = blender.still(tpl, d / f"{tpl}.png", data=data, width=360, height=640, t=1.5, duration=3.0)
        a = rgba(png)
        cov = float((a[..., 3] > 10).mean()) if a.shape[2] == 4 else 0
        check(f"Blender {tpl}: renders headless with a transparent background", 0.01 < cov < 0.8, f"coverage {cov:.3f}")
    try:
        blender.still("title_3d", d / "bn.png", data={"text": "বাংলা"}, width=200, height=200, t=1.0)
        ok = False
    except Exception as exc:
        ok = "Three.js" in str(exc)
    check("Blender title refuses Bangla (no shaping) and points to the Three.js template", ok)


def main() -> int:
    if OUT.exists():
        for sub in ("foot", "tpl", "blender"):
            shutil.rmtree(OUT / sub, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for m_ in ("modnet", "depth_small", "vittrack"):
        if not models.is_ready(m_):
            print(f"missing model {m_}: run `vedit models get {m_}` (asked first)")
            return 2
    test_templates()
    foot, truth = make_project()
    test_tracking(foot, truth)
    test_subject(foot)
    test_depth(foot)
    test_camera(foot)
    test_misc(foot)
    if "--blender" in sys.argv:
        test_blender()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
