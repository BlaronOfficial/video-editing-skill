"""Phase 6 checks: the beat map, animated pieces (adapted from animate, MIT), Bangla in every style, pieces timed to
vedit's voices, pieces in edits (insert, short, doodles over footage), the measured QA checks, and music made in
code. Run from the skill root:

    scripts/.venv/Scripts/python.exe tests/test_phase6.py

Needs Chrome or Edge (the renderer), Node, the fonts (`vedit setup fonts`), the voice tools and kokoro_multi
(+ the network for Edge Bangla). Every check measures: beat grids against planted clicks, frames hashed twice,
text positions from the page itself, speech onsets in the audio, pixels in renders, loudness in the mix.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["VEDIT_PERSONAL_DIR"] = str(ROOT / "tests" / "out" / "personal_test")

import numpy as np  # noqa: E402

from vedit.media import ffmpeg, measure_loudness, probe  # noqa: E402

OUT = ROOT / "tests" / "out" / "phase6"
results: list[tuple[str, bool, str]] = []
HALF_FRAME_24 = 0.5 / 24
STYLES = ["cut-paper", "crosshatch", "riso", "sketchbook", "math", "pixel", "isometric"]


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)


def vedit(*args: str, env: dict | None = None) -> dict:
    p = subprocess.run([sys.executable, "-m", "vedit.cli", *args], capture_output=True, text=True, cwd=ROOT / "scripts",
                       env={**os.environ, "PYTHONUTF8": "1", **(env or {})}, encoding="utf-8")
    out = p.stdout.strip()
    if p.returncode:
        raise RuntimeError(f"vedit {' '.join(args)} failed: {p.stderr[-1500:]}")
    starts = [i for i in (out.find("{"), out.find("[")) if i >= 0]
    return json.loads(out[min(starts):]) if starts else {}


def ff(*args: str) -> None:
    subprocess.run([ffmpeg(), "-v", "error", "-y", *args], check=True)


def frame(path, t: float, w: int = 540) -> np.ndarray:
    info = probe(path)
    W, H = info.display_size
    h = round(w * H / W / 2) * 2
    raw = subprocess.run([ffmpeg(), "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                          "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3)


def wav_mono(path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        x = np.frombuffer(w.readframes(n), np.int16).astype(np.float32) / 32768
    return (x.reshape(-1, ch).mean(axis=1) if ch > 1 else x), sr


# ------------------------------------------------------------------ synthetic music

SR = 44100


def _write(path: Path, y: np.ndarray) -> None:
    y = np.clip(y / (np.max(np.abs(y)) + 1e-9) * 0.8, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((y * 32767).astype(np.int16).tobytes())


def _place(y, t, snd, g=1.0):
    i = int(round(t * SR))
    if i < len(y):
        n = min(len(snd), len(y) - i)
        y[i:i + n] += g * snd[:n]


def _click(rng):
    n = int(0.03 * SR)
    return rng.normal(0, 1, n) * np.exp(-np.arange(n) / (0.004 * SR))


def _kick():
    n = int(0.35 * SR); t = np.arange(n) / SR
    return np.sin(2 * np.pi * np.cumsum(50 + 70 * np.exp(-t * 30)) / SR) * np.exp(-t * 9)


def _snare(rng):
    n = int(0.2 * SR); t = np.arange(n) / SR
    return (0.7 * rng.normal(0, 1, n) + 0.5 * np.sin(2 * np.pi * 185 * t)) * np.exp(-t * 22)


def _hat(rng):
    n = int(0.05 * SR); x = np.diff(rng.normal(0, 1, n), prepend=0)
    return x * np.exp(-np.arange(n) / (0.008 * SR))


def make_track(path: Path, kind: str, bpm: float, dur: float = 60.0, off: float = 0.37, drop=None, hit=None) -> np.ndarray:
    rng = np.random.default_rng(int(bpm * 10))
    y = np.zeros(int(dur * SR)); per = 60 / bpm
    beats = np.arange(off, dur - 0.05, per)
    c, kk, sn, hh = _click(rng), _kick(), _snare(rng), _hat(rng)
    t = np.arange(len(y)) / SR
    if kind == "drums":
        y += sum(np.sin(2 * np.pi * f * t) * 0.1 for f in (220, 277.2, 329.6)) * (0.8 + 0.2 * np.sin(2 * np.pi * 0.25 * t))
    for k, b in enumerate(beats):
        if drop and drop[0] <= b < drop[1]:
            continue
        if kind == "click":
            _place(y, b, c)
        elif kind == "accent":
            _place(y, b, c)
            if k % 4 == 1:
                _place(y, b, kk, 1.4)
        else:
            _place(y, b, kk if k % 2 == 0 else sn)
            _place(y, b, hh, 0.3)
            _place(y, b + per / 2, hh, 0.25)
    if drop:
        y[int(drop[0] * SR):int(drop[1] * SR)] *= 0.0
    if hit is not None:
        _place(y, hit, _kick(), 6.0)
        _place(y, hit, _snare(rng), 5.0)
    _write(path, y)
    return beats


# ------------------------------------------------------------------ 1. the beat map

def test_beats() -> None:
    from vedit import audio
    d = OUT / "beats"
    d.mkdir(parents=True, exist_ok=True)
    worst, rows = 0.0, []
    for bpm in (87, 100, 120, 128, 140, 174):
        truth = make_track(d / f"click_{bpm}.wav", "click", bpm)
        r = audio.beats(d / f"click_{bpm}.wav")
        det = np.array(r["beats"])
        err = max(abs(det[np.argmin(np.abs(det - b))] - b) for b in truth)
        worst = max(worst, err)
        rows.append(f"{bpm}:{r['bpm']}")
        if abs(r["bpm"] - bpm) > 0.05:
            worst = 9.9
    check("beat map: click tracks at 87-174 BPM, 60 s each: the grid stays within half a frame to the end",
          worst <= HALF_FRAME_24, f"worst {worst * 1000:.1f} ms; {' '.join(rows)}")
    worst, rows = 0.0, []
    for bpm in (87, 100, 120, 128, 140):
        truth = make_track(d / f"drums_{bpm}.wav", "drums", bpm)
        r = audio.beats(d / f"drums_{bpm}.wav")
        det = np.array(r["beats"])
        err = max(abs(truth[np.argmin(np.abs(truth - b))] - b) for b in det)
        worst = max(worst, err if abs(r["bpm"] - bpm) < 0.1 else 9.9)
        rows.append(f"{bpm}:{r['bpm']}")
    check("beat map: drum loops over a pad (kick, snare, off-beat hi-hats) get their tempo and stay on the beat",
          worst <= HALF_FRAME_24, f"worst {worst * 1000:.1f} ms; {' '.join(rows)}")
    truth = make_track(d / "accent.wav", "accent", 120, 30.0)
    r = audio.beats(d / "accent.wav")
    want = truth[1::4]
    right = np.mean([np.min(np.abs(np.array(r["downbeats"]) - w)) < 0.03 for w in want])
    check("beat map: bars start where the kick is (downbeats)", right == 1.0, f"{right:.0%}")
    make_track(d / "arc.wav", "drums", 120, 40.0, drop=(20.0, 21.5), hit=21.5)
    r = audio.beats(d / "arc.wav")
    q = r.get("quiet") or []
    check("beat map: a planted drop and the big hit after it are found",
          any(a <= 20.3 and b >= 21.2 for a, b in q) and abs(r["loudest"]["t"] - 21.5) <= 0.15
          and any(abs(h - 21.5) < 0.06 for h in r["hits"]), f"quiet {q}, loudest {r['loudest']}, hits {r['hits'][:6]}")
    real = ROOT / "tests" / "footage" / "music_test.mp3"
    if real.exists():
        r = audio.beats(real)
        check("beat map: a real music clip gets a steady grid with onsets on most beats",
              r["bpm"] and 60 <= r["bpm"] <= 200 and r["confidence"] >= 0.6,
              f"{r['bpm']} BPM, confidence {r['confidence']}, other tempos {r['other_tempos']}")


def test_snap() -> None:
    from vedit.beatsync import measure
    from vedit.project import find
    from vedit.timeline import AudioClip, Clip, Source
    d = OUT / "snap"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    for name in ("synthetic_a.mp4", "synthetic_b.mp4"):
        shutil.copy(ROOT / "tests" / "footage" / name, d / name)
    make_track(d / "music.wav", "drums", 120, 20.0, off=0.0)
    vedit("project", "init", str(d), "--ratio", "16:9", "--name", "p6snap")
    p = find(d)
    e = p.edit()
    a_id, b_id = next(iter(e.sources)), list(e.sources)[1]
    e.main = [Clip(id="c1", source=a_id, src_in=0.0, src_out=2.32), Clip(id="c2", source=b_id, src_in=0.0, src_out=2.21),
              Clip(id="c3", source=a_id, src_in=3.0, src_out=5.17), Clip(id="c4", source=b_id, src_in=3.0, src_out=6.0)]
    pm = probe(d / "music.wav")
    e.sources["music"] = Source(id="music", path=str((d / "music.wav").resolve()), kind="audio", duration=pm.duration)
    e.audio.append(AudioClip(id="music", source="music", start=0.0, role="music", sync="beats"))
    p.save_edit(e.layout())
    before = measure(p.edit(), p.edit().audio[0])
    dry = vedit("beats", "snap", str(d), "--music", "music", "--grid", "beats", "--tolerance", "0.25")
    vedit("beats", "snap", str(d), "--music", "music", "--grid", "beats", "--tolerance", "0.25", "--apply")
    after = measure(p.edit(), p.edit().audio[0])
    check("beats snap: off-beat montage cuts move onto the music's beats (a dry run first, then --apply)",
          before["on_grid"] < before["cuts"] and after["on_grid"] == after["cuts"] and dry["moved"] >= 2 and not dry["applied"],
          f"before {before['on_grid']}/{before['cuts']}, after {after['on_grid']}/{after['cuts']}, moved {dry['moved']}")


# ------------------------------------------------------------------ 2. styles through vedit's renderer

def anim_project() -> Path:
    d = OUT / "anim_proj"
    if (d / "edit" / "edit.json").exists():
        return d
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    shutil.copy(ROOT / "tests" / "footage" / "synthetic_b.mp4", d / "clip.mp4")
    vedit("project", "init", str(d), "--ratio", "9:16", "--name", "p6anim")
    return d


def stems_sum(audio: dict) -> float:
    mix, _ = wav_mono(audio["mix"])
    mus, _ = wav_mono(audio["music"])
    sfx, _ = wav_mono(audio["sfx"])
    n = min(len(mix), len(mus), len(sfx))
    res = mix[:n] - (mus[:n] + sfx[:n])
    return float(np.sqrt((res ** 2).mean()) / (np.sqrt((mix[:n] ** 2).mean()) + 1e-9))


def test_styles() -> dict:
    d = anim_project()
    out = {}
    det_all, errs, sums, durs = [], [], [], []
    t0 = time.time()
    styles = [s for s in os.environ.get("P6_STYLES", ",".join(STYLES)).split(",") if s in STYLES]   # a subset per run
    for s in styles:
        name = f"demo_{s.replace('-', '_')}"
        shutil.rmtree(d / "edit" / "anim" / name, ignore_errors=True)
        vedit("anim", "new", str(d), name, "--style", s)
        tl = vedit("anim", "tile", str(d), name, "--frames", "0,25,72,121")
        det_all.append(tl["deterministic"] is True)
        r = vedit("anim", "render", str(d), name)
        info = probe(r["video"])
        durs.append(abs(info.duration - r["duration"]) < 0.1)
        sums.append(stems_sum(r["audio"]))
        if r.get("page_log") or tl.get("page_log"):
            errs.append(f"{s}: {(r.get('page_log') or tl.get('page_log'))[:2]}")
        out[s] = r
    check(f"style demos ({', '.join(styles)}) build and render through vedit's renderer, frame-identical when rendered twice",
          all(det_all) and all(durs) and not errs,
          f"{sum(det_all)}/{len(styles)} deterministic, {time.time() - t0:.0f} s, {errs[:2]}")
    check("each piece's score stems sum back to its mix", max(sums) < 0.25, f"worst residual {max(sums):.3f}")
    gpu = next(iter(out.values())).get("gpu") or {}
    check("WebGL runs on the GPU in the renderer (and reports it)", gpu.get("ok") is True, gpu.get("renderer", ""))
    return out


def test_example() -> None:
    d = anim_project()
    ex = d / "edit" / "anim" / "history"
    shutil.rmtree(ex, ignore_errors=True)
    shutil.copytree(ROOT / "anim" / "examples" / "history-of-ai", ex)
    t1 = time.time()
    r = vedit("anim", "render", str(d), "history")
    tl = vedit("anim", "tile", str(d), "history", "--frames", "100,600,1200")
    check("the 60 s history-of-AI example (15 eras, 13 morphs) renders through vedit",
          abs(probe(r["video"]).duration - 60.0) < 0.1 and tl["deterministic"] is True and not r.get("page_log"),
          f"{time.time() - t1:.0f} s render+tile, gpu {r.get('gpu', {}).get('ok')}")


def test_formats() -> None:
    d = anim_project()
    # one piece, two shapes
    shutil.rmtree(d / "edit" / "anim" / "multi", ignore_errors=True)
    vedit("anim", "new", str(d), "multi", "--from", "piece", "--formats", "9:16,16:9")
    a = vedit("anim", "render", str(d), "multi")
    b = vedit("anim", "render", str(d), "multi", "--format", "16:9")
    sa, sb = probe(a["video"]).display_size, probe(b["video"]).display_size
    check("one piece renders 9:16 and 16:9, laid out for each (not cropped)", tuple(sa) == (1080, 1920) and tuple(sb) == (1920, 1080),
          f"{sa} / {sb}")
    st = vedit("anim", "board", str(d), "multi", "--panels", "--cards")
    from vedit.project import find
    from vedit.suggest import load_suggestions
    cards = [s for s in load_suggestions(find(d))["items"] if s["id"].startswith("board_multi_")]
    check("storyboard: the piece draws its own board, one panel image and one Studio card per beat",
          Path(st["image"]).exists() and all(Path(p["image"]).exists() for p in st["panels"]) and len(cards) == len(st["panels"]),
          f"{len(st['panels'])} panels, {len(cards)} cards")


# ------------------------------------------------------------------ 3. Bangla in every style

BN_SCENES = r"""
// ---- test: Bangla in this style (a typed line, a hand caption, the style's own text where it has one)
const BN_TYPE = 'বাংলা লেখা: ক্ষমা, স্ত্রী, রাষ্ট্র';
const BN_HAND = 'গল্পটা এখানে শুরু';
ERA_LIST.forEach((e) => { const f = e[2]; e[2] = () => {
  f();
  if (typeof pixCaption === 'function') pixCaption('বাংলা ভাষা', { at: 0.1 });
  if (DEFER) DEFER.push(() => {
    ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1;
    ctx.fillStyle = 'rgba(255,255,255,0.88)'; ctx.fillRect(70, 1130, 900, 300);
    monoText(BN_TYPE, 100, 1200, 44, '#1d1d1d', { count: 99, key: 'bnt' });
    ctx.font = `400 64px ${typeof HAND !== 'undefined' ? HAND : 'cursive'}`; ctx.fillStyle = '#1d1d1d'; ctx.textAlign = 'center';
    ctx.fillText(BN_HAND, 520, 1300);
    if (typeof handLetter === 'function') handLetter('খাতার পাতা', 520, 1395, 54, { reveal: 1 });
    else if (typeof mText === 'function') mText([{ s: 'গণিতের ভাষা', c: '#1d1d1d' }], 520, 1395, 50);
    ctx.restore();
  });
}; });
"""


def test_bangla() -> None:
    from vedit import checks
    from vedit.anim.pieces import _page, _renderer, piece_dir
    from vedit.project import find
    d = anim_project()
    p = find(d)
    probs, cut, drawn = [], [], {}
    crops = OUT / "bangla"
    crops.mkdir(parents=True, exist_ok=True)
    for s in STYLES:
        name = f"bn_{s.replace('-', '_')}"
        shutil.rmtree(d / "edit" / "anim" / name, ignore_errors=True)
        vedit("anim", "new", str(d), name, "--style", s)
        pd = piece_dir(p, name)
        sc = pd / "src" / "scenes.js"
        sc.write_text(sc.read_text(encoding="utf-8") + BN_SCENES, encoding="utf-8")
        from vedit.anim.build import build
        build(pd)
        args, _ = _page(pd, None)
        r = _renderer([*args, "--probe-text", str(pd / "probe.json"), "--probe-every", "12",
                       "--stills", "1.2", "--still-dir", str(crops / name)], timeout=900)
        if r.get("page_log"):
            probs.append(f"{s}: {r['page_log'][:2]}")
        pr = json.loads((pd / "probe.json").read_text(encoding="utf-8"))
        tl = pr.get("timeline") or {}
        skip = [(m - 0.6, m + 0.6) for m in tl.get("morphs", [])]
        bad = [i for i in checks.text_issues(pr, skip=skip, safe={"top": 0, "bottom": 0, "right": 0, "left": 0})
               if i["kind"] == "text_cut" and any("ঀ" <= ch <= "৿" for ch in i["text"])]
        cut += [f"{s}: {b['text']}" for b in bad]
        items = [it["s"] for smp in pr["samples"] for it in smp["items"]]
        drawn[s] = any("গল্পটা" in t for t in items) and any("ক্ষ" in t for t in items)
        # glyph by glyph, left to right: the typed line (and sketchbook's lettering) draw their clusters in order,
        # each to the right of the last, none on top of another
        last = pr["samples"][-1]["items"]
        for lo, hi, what in ((1140, 1215, "typed line"), (1335, 1412, "lettering")):
            row = []
            for it in last:
                if lo <= it["y0"] <= hi and any("ঀ" <= ch <= "৿" for ch in it["s"]) and len(it["s"]) <= 6:
                    if row and row[-1]["s"] == it["s"] and abs(row[-1]["x0"] - it["x0"]) < 2:
                        continue                                  # the same glyph's pen stroke over its fill
                    row.append(it)
            if len(row) >= 4:
                bad_order = [i for i in range(1, len(row)) if row[i]["x0"] < row[i - 1]["x1"] - 3]
                if bad_order:
                    cut.append(f"{s} {what}: glyph {bad_order[0]} overlaps the one before")
        from PIL import Image
        im = Image.open(next((crops / name).glob("*.png")))
        im.crop((60, 1120, 980, 1440)).save(crops / f"{name}.png")
    check("Bangla in all 7 styles: drawn whole (conjuncts kept as one cluster), nothing cut off, no page errors",
          all(drawn.values()) and not cut and not probs, f"drawn {sum(drawn.values())}/7, cut {cut[:2]}, errors {probs[:2]}")
    # Chrome's own segmentation: a conjunct and its vowel sign stay in one cluster
    page = OUT / "bangla" / "seg.html"
    page.write_text("<!doctype html><meta charset=utf-8><body><canvas id=c></canvas><script>"
                    + (ROOT / "anim" / "kit" / "core.js").read_text(encoding="utf-8").replace("const LX = (f) => f * W, LY = (f) => f * H, UNIT = Math.min(W, H) / 1080, PORTRAIT = H > W * 1.2, WIDE = W > H * 1.2;", "")
                    .replace("const MONO =", "const W = 16, H = 16, FPS = 24;\nconst MONO =")
                    + "\nwindow.TIMELINE = { a: graphemes('ক্ষমা'), b: graphemes('রাষ্ট্র'), c: graphemes('স্ত্রী') };</script>",
                    encoding="utf-8")
    seg = _renderer(["--input", str(page), "--info", "--width", "16", "--height", "16"], timeout=300)["timeline"]
    marks = set(chr(c) for c in range(0x09BE, 0x09CE)) | {"্", "ঁ", "ং", "ঃ"}
    ok = all(not g[0] in marks for k in ("a", "b", "c") for g in seg[k]) and seg["a"][0] == "ক্ষ"
    check("Chrome keeps Bangla conjuncts and vowel signs inside one glyph cluster (what per-letter effects step by)",
          ok, json.dumps(seg, ensure_ascii=False))


# ------------------------------------------------------------------ 4. voices drive the picture

def speech_onsets(wav: Path, lines: list[dict]) -> list[float]:
    """For each line: |line start - the speech onset found in the audio near it|."""
    x, sr = wav_mono(wav)
    win = int(0.005 * sr)
    env = np.sqrt(np.convolve(x ** 2, np.ones(win) / win, mode="same"))
    thr = 0.02 * env.max()
    errs = []
    for ln in lines:
        a, b = int(max(0, ln["t0"] - 0.35) * sr), int((ln["t0"] + 0.35) * sr)
        idx = np.where(env[a:b] > thr)[0]
        errs.append(abs((a + idx[0]) / sr - ln["t0"]) if len(idx) else 9.9)
    return errs


def test_voice() -> None:
    from vedit.anim.pieces import info
    from vedit.project import find
    d = anim_project()
    p = find(d)
    shutil.rmtree(d / "edit" / "anim" / "vo_en", ignore_errors=True)
    vedit("anim", "new", str(d), "vo_en", "--from", "piece")
    pd = d / "edit" / "anim" / "vo_en"
    script = {"lead": 0.8, "tail": 1.2, "lines": [
        {"id": "open", "text": "In nineteen fifty, a question was written down.", "after": 0.5},
        {"id": "turn", "text": "Can machines think?", "after": 0.9},
        {"id": "end", "text": "Seventy years later, the machines answered.", "after": 0.4}]}
    (pd / "voice").mkdir(exist_ok=True)
    (pd / "voice" / "script.json").write_text(json.dumps(script), encoding="utf-8")
    v = vedit("anim", "voice", str(d), "vo_en", "--voice", "kokoro:af_heart")
    vj = json.loads((pd / "voice.json").read_text(encoding="utf-8"))
    errs = speech_onsets(pd / "voice" / "voice.wav", vj["lines"])
    inf = info(p, "vo_en")
    T = inf["timeline"]
    check("anim voice (Kokoro, English): each line starts where its speech starts; the piece's clock is the voice",
          max(errs) <= 0.05 and abs(inf["duration"] - vj["duration"]) < 0.05 and len(T["narration"]) == 3,
          f"onset errors {[round(e * 1000) for e in errs]} ms, duration {inf['duration']} vs voice {vj['duration']}")
    script["lines"][0]["text"] = "In nineteen fifty, in a quiet office in Manchester, a question was written down."
    (pd / "voice" / "script.json").write_text(json.dumps(script), encoding="utf-8")
    vedit("anim", "voice", str(d), "vo_en", "--voice", "kokoro:af_heart")
    vj2 = json.loads((pd / "voice.json").read_text(encoding="utf-8"))
    T2 = info(p, "vo_en")["timeline"]
    moved = vj2["lines"][1]["t0"] - vj["lines"][1]["t0"]
    check("a re-take re-times the picture: later lines (and the scenes cued on them) move with the voice",
          moved > 0.8 and abs(T2["narration"][1]["t0"] - vj2["lines"][1]["t0"]) < 1e-3, f"line 2 moved {moved:+.2f} s")
    # the cue helpers, run in Node on the kit itself
    node = (f"const fs=require('fs');const vm=require('vm');const VOICE={json.dumps(vj2)};"
            "const ctx={VOICE,console,Intl};vm.createContext(ctx);"
            f"vm.runInContext('const W=16,H=16,FPS=24;'+fs.readFileSync({json.dumps(str(ROOT / 'anim' / 'kit' / 'core.js'))},'utf8')"
            "+';globalThis.__r=[VW(\"turn\",\"machines\",1),VL(\"end\").t0];',ctx);console.log(JSON.stringify(ctx.__r));")
    pr = subprocess.run(["node", "-e", node], capture_output=True, text=True, encoding="utf-8")
    vw = json.loads(pr.stdout or "[0,0]")
    want = next(w["t0"] for w in vj2["lines"][1]["words"] if w["w"].lower().strip("?") == "machines")
    check("VW / VL cue on the spoken words", abs(vw[0] - want) < 1e-6 and abs(vw[1] - vj2["lines"][2]["t0"]) < 1e-6,
          f"VW {vw[0]} vs {want}")
    shutil.rmtree(d / "edit" / "anim" / "vo_bn", ignore_errors=True)
    vedit("anim", "new", str(d), "vo_bn", "--from", "piece")
    pb = d / "edit" / "anim" / "vo_bn"
    (pb / "voice").mkdir(exist_ok=True)
    (pb / "voice" / "script.json").write_text(json.dumps({"lead": 0.8, "tail": 1.2, "lines": [
        {"id": "a", "text": "উনিশশো পঞ্চাশ সালে একটা প্রশ্ন লেখা হয়েছিল।", "after": 0.6},
        {"id": "b", "text": "যন্ত্র কি ভাবতে পারে?", "after": 0.6}]}, ensure_ascii=False), encoding="utf-8")
    vb = vedit("anim", "voice", str(d), "vo_bn", "--voice", "edge:bn-BD-NabanitaNeural")
    vjb = json.loads((pb / "voice.json").read_text(encoding="utf-8"))
    eb = speech_onsets(pb / "voice" / "voice.wav", vjb["lines"])
    check("anim voice (Edge, Bangla): lines on the speech, words timed by the service",
          max(eb) <= 0.05 and all(l["words"] for l in vjb["lines"]), f"onset errors {[round(e * 1000) for e in eb]} ms, {vb['words']} words")


# ------------------------------------------------------------------ 5. pieces in edits

def test_in_edit() -> None:
    from vedit import studio
    from vedit.project import find
    d = OUT / "insert"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    ff("-ss", "30", "-t", "14", "-i", str(ROOT / "tests" / "footage" / "e2e" / "liz_epidemiologist.webm"), "-vf",
       "scale=-2:1920,crop=1080:1920,setsar=1", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
       str(d / "liz.mp4"))
    vedit("project", "init", str(d), "--ratio", "9:16", "--name", "p6ins")
    keeps = d / "edit" / "keeps.json"
    keeps.write_text(json.dumps([{"source": "liz", "from": 0.0, "to": 13.5, "exact": True}]))
    vedit("plan", "apply", str(d), str(keeps))
    vedit("mode", str(d), "auto")
    vedit("anim", "new", str(d), "ins", "--style", "cut-paper")
    a = vedit("anim", "add", str(d), "ins", "--as", "insert", "--at", "3.0")
    e = find(d).edit()
    music = next(x for x in e.audio if x.id == "anim_ins_music")
    check("anim add --as insert: the piece over the footage, its score under the speaker (ducked, -12 dB)",
          any(o.id == "anim_ins" for o in e.overlays) and music.ducks and abs(music.volume - 10 ** (-12 / 20)) < 1e-3,
          f"{a['duration']} s at {a['start']} s, studio {a['studio']}")
    out = Path(vedit("render", str(d), "--preview")["output"])
    src = frame(d / "liz.mp4", 6.0).astype(int)
    got = frame(out, 6.0).astype(int)
    keep = frame(out, 1.0).astype(int)
    q = vedit("qa", str(d), "--render", str(out), "--no-ears")
    check("the insert renders (the piece on screen at 6 s, the footage before it) and QA finds no errors",
          np.abs(got - src).mean() > 25 and np.abs(keep - frame(d / "liz.mp4", 1.0).astype(int)).mean() < 12 and q["errors"] == 0,
          f"diff at 6 s {np.abs(got - src).mean():.1f}, errors {q['errors']}, issues {[i['kind'] for i in q['issues']][:6]}")
    studio.write_documents(find(d))
    docs = d / "edit" / "studio" / "docs"
    comp = [f for f in docs.glob("*.json") if "anim_ins" in f.read_text(encoding="utf-8")[:4000] and "comp_" in f.name] \
        if docs.exists() else []
    size = max((f.stat().st_size for f in comp), default=0)
    check("the Studio bundle carries the piece as a live page (one database document)", bool(comp) and size < 256 * 1024,
          f"{len(comp)} doc(s), {size / 1024:.0f} KiB")
    # a doodle overlay over footage (transparent paper)
    vedit("anim", "new", str(d), "doodle", "--overlay", "--style", "crosshatch")
    pd = d / "edit" / "anim" / "doodle"
    (pd / "src" / "scenes.js").write_text(
        "function sceneNight() { ink(ellipsePts(540, 820, 300, 190, 0, 72), { closed: true, w: 12, color: '#e0281e', key: 'ring', frac: ev(0.2, 0.8) }); }\n"
        "function sceneMorning() { ink([[220, 1300], [520, 1050]], { w: 12, color: '#e0281e', key: 'arrow', frac: ev(E0, 0.4) });"
        " ink(ellipsePts(540, 820, 300, 190, 0, 72), { closed: true, w: 12, color: '#e0281e', key: 'ring' }); }\n", encoding="utf-8")
    vedit("anim", "add", str(d), "doodle", "--as", "overlay", "--at", "9.0")
    vedit("mg", "render", str(d))
    out = Path(vedit("render", str(d), "--preview")["output"])
    img = frame(out, 9.0 + 6.0, 1080).astype(int)
    srcf = frame(d / "liz.mp4", 9.0 + 6.0, 1080).astype(int)
    ring = img[820 - 6:820 + 6, 240 - 30:240 + 30]
    red = ((ring[..., 0] > 150) & (ring[..., 1] < 110)).mean()
    away = np.abs(img[1600:1800, 100:400] - srcf[1600:1800, 100:400]).mean()
    check("doodles over footage: the ink ring is drawn and the footage shows through everywhere else",
          red > 0.1 and away < 12, f"red ink {red:.2f}, background diff {away:.1f}")
    # a whole animated short: the piece is the picture, its voice and score under it
    f = OUT / "short"
    shutil.rmtree(f, ignore_errors=True)
    f.mkdir(parents=True)
    ff("-f", "lavfi", "-i", "color=c=0x223344:s=1080x1920:d=1", "-frames:v", "1", str(f / "cover.png"))
    vedit("project", "init", str(f), "--ratio", "9:16", "--name", "p6short")
    e = find(f).edit()
    e.main = []
    find(f).save_edit(e)
    vedit("anim", "new", str(f), "story", "--from", "piece")
    sd = f / "edit" / "anim" / "story"
    (sd / "voice").mkdir(exist_ok=True)
    (sd / "voice" / "script.json").write_text(json.dumps({"lead": 0.6, "tail": 1.0, "lines": [
        {"id": "a", "text": "Every night, the spark waits for the moon.", "after": 0.6},
        {"id": "b", "text": "And every morning, the garden grows.", "after": 0.4}]}), encoding="utf-8")
    vedit("anim", "voice", str(f), "story", "--voice", "kokoro:am_michael")
    s = vedit("anim", "add", str(f), "story", "--as", "short")
    vedit("captions", "build", str(f), "--style", "karaoke_pop")
    vedit("mode", str(f), "auto")
    e = find(f).edit()
    out = Path(vedit("render", str(f), "--preview")["output"])
    lm = measure_loudness(out)
    check("anim add --as short: the piece is the picture, the voice and score under it, captions from the voice",
          abs(probe(out).duration - s["duration"]) < 0.3 and len(e.captions.chunks) >= 3 and lm["lufs"] > -20 and s["vo"],
          f"{probe(out).duration:.2f} s vs piece {s['duration']} s, {len(e.captions.chunks)} captions, {lm['lufs']:.1f} LUFS")


# ------------------------------------------------------------------ 6. measured QA

def test_qa() -> None:
    from vedit.project import find
    from vedit.timeline import AudioClip, Clip, Marker, MGSpec, Overlay, Source
    d = OUT / "qa"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    ff("-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=1", "-frames:v", "1", str(d / "card.png"))
    shutil.copy(ROOT / "tests" / "footage" / "synthetic_a.mp4", d / "move.mp4")
    make_track(d / "music.wav", "drums", 120, 30.0, off=0.0)
    vedit("project", "init", str(d), "--ratio", "9:16", "--name", "p6qa")
    p = find(d)
    e = p.edit()
    card = next(k for k, v in e.sources.items() if v.kind == "image")
    mv = next(k for k, v in e.sources.items() if v.kind == "video")
    # 0-7.5 s: one still card with nothing happening (a static stretch); then moving clips cut off the beat
    e.main = [Clip(id="still", source=card, src_in=0.0, src_out=7.5), Clip(id="m1", source=mv, src_in=0.0, src_out=2.31),
              Clip(id="m2", source=mv, src_in=4.0, src_out=6.27), Clip(id="m3", source=mv, src_in=7.0, src_out=11.0)]
    e.sources["music"] = Source(id="music", path=str((d / "music.wav").resolve()), kind="audio", duration=30.0)
    e.audio.append(AudioClip(id="music", source="music", start=0.0, role="music", sync="beats", duck=False))
    # a label hanging off the frame for 2 s
    (d / "edit" / "custom").mkdir(exist_ok=True)
    (d / "edit" / "custom" / "label.html").write_text(
        "<!doctype html><html><head><meta charset=utf-8><style>html,body{margin:0;width:1080px;height:1920px;background:transparent}"
        ".l{position:absolute;left:-160px;top:700px;font:700 90px Poppins,sans-serif;color:#fff;background:#000;padding:10px}</style>"
        "</head><body data-duration=2><div class=l>CUT OFF LABEL</div></body></html>", encoding="utf-8")
    e.overlays.append(Overlay(id="label", start=8.0, duration=2.0, mg=MGSpec(engine="html", file="custom/label.html")))
    e.markers.append(Marker(id="payoff", t=11.5, name="payoff", note="the payoff"))
    p.save_edit(e.layout())
    vedit("voice", "vo", str(d), "--voice", "kokoro:af_heart", "--text",
          "This sentence is packed with far too many quick little words for anybody to follow comfortably.",
          "--place", "audio", "--at", "8.2", "--speed", "1.9", "--name", "fast")
    vedit("mode", str(d), "auto")
    vedit("mg", "render", str(d))
    out = Path(vedit("render", str(d), "--preview")["output"])
    q = vedit("qa", str(d), "--render", str(out), "--no-ears")
    kinds = {i["kind"] for i in q["issues"]}
    want = {"text_cut", "static", "pace", "beat_grid", "sound_arc"}
    check("measured QA flags planted problems: cut-off text, a 7.5 s still stretch, a 4+ words/s VO, off-beat cuts, "
          "a payoff with no silence", want <= kinds, f"found {sorted(kinds & want)}, missing {sorted(want - kinds)}")
    # a clean edit: real footage, cuts, no plants
    c = OUT / "insert"
    q2 = vedit("qa", str(c), "--render", str(c / "edit" / "render" / "preview.mp4"), "--no-ears")
    bad = [i for i in q2["issues"] if i["kind"] in want | {"text_ui", "text_overlap"}]
    check("a clean edit gets none of the measured flags", not bad, str([(i["kind"], i["msg"][:60]) for i in bad][:3]))


# ------------------------------------------------------------------ 7. music made in code

def test_score() -> None:
    from vedit import checks
    from vedit.project import find
    from vedit.timeline import Clip, Marker
    d = OUT / "score"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    ff("-f", "lavfi", "-i", "testsrc2=s=1920x1080:d=1", "-frames:v", "1", str(d / "card.png"))
    vedit("project", "init", str(d), "--ratio", "16:9", "--name", "p6score")
    p = find(d)
    e = p.edit()
    card = next(k for k, v in e.sources.items() if v.kind == "image")
    e.main = [Clip(id="a", source=card, src_in=0.0, src_out=15.0), Clip(id="b", source=card, src_in=0.0, src_out=15.0),
              Clip(id="c", source=card, src_in=0.0, src_out=15.0)]
    e.markers.append(Marker(id="payoff", t=30.0, name="payoff"))
    e.markers.append(Marker(id="ch2", t=15.0, name="part two", kind="chapter"))
    p.save_edit(e.layout())
    t0 = time.time()
    s = vedit("score", "compose", str(d), "--mood", "warm")
    secs = time.time() - t0
    po = checks.payoff(s["score"], window=(30.0, 30.5))
    check("score compose: a 45 s bed shaped by the edit (silence before the payoff marker, the loudest hit on it)",
          po.get("silence_ok") and po.get("in_window") and s["level_db"] == 0.0,
          f"{s['bpm']:.0f} BPM {s['key']} {s['mode']}, {s['events']} events, {secs:.0f} s, payoff {po}")
    vedit("mode", str(d), "auto")
    out = Path(vedit("render", str(d), "--preview")["output"])
    lm = measure_loudness(out)
    q = vedit("qa", str(d), "--render", str(out), "--no-ears")
    check("the score in the render: -14 LUFS after the mix, and QA hears the payoff", abs(lm["lufs"] + 14) <= 1.5
          and not [i for i in q["issues"] if i["kind"] == "sound_arc"], f"{lm['lufs']:.1f} LUFS")
    moods = vedit("score", "moods")
    check("seven moods ship", len(moods) >= 7, ", ".join(moods))


# ------------------------------------------------------------------ 8. wiring

def test_wiring() -> None:
    from vedit import routes
    plan = routes.plan("animation")
    ids = [r["id"] for r in plan]
    check("route planner: animation is a need, the shipped styles rank first", ids and ids[0] == "anim_styles", str(ids[:4]))
    sk = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    desc = next(l for l in sk.splitlines() if l.startswith("description:"))[len("description:"):].strip()
    check("SKILL.md description stays within 1024 characters and mentions animation",
          len(desc) <= 1024 and "anim" in desc.lower(), f"{len(desc)} chars")
    lic = (ROOT / "anim" / "LICENSE-animate").read_text(encoding="utf-8")
    att = (ROOT / "ATTRIBUTIONS.md").read_text(encoding="utf-8")
    check("animate's MIT notice ships with the adapted code and is credited", "cth9191" in lic and "animate" in att.lower())


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    for name, fn in (("beats", test_beats), ("snap", test_snap), ("styles", test_styles), ("example", test_example),
                     ("formats", test_formats), ("bangla", test_bangla), ("voice", test_voice), ("edit", test_in_edit),
                     ("qa", test_qa), ("score", test_score), ("wiring", test_wiring)):
        if only and name not in only:
            continue
        try:
            fn()
        except Exception as exc:          # a crashed section is a failed check, and the run goes on
            import traceback
            traceback.print_exc()
            check(f"{name}: ran without crashing", False, str(exc)[-300:])
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
