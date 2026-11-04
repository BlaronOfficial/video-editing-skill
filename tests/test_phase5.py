"""Phase 5 checks: voices (offline, Edge, Bangla, cloning), voiceover in edits (faceless and over footage),
environments (MCP registration, launcher, shared-folder venvs), performance learning (CSV, API, report,
learn, route ranking). Run from the skill root:

    scripts/.venv/Scripts/python.exe tests/test_phase5.py

Needs the voice tools (`vedit setup voice`, `vedit setup openvoice`), the models kokoro_multi, bn_coqui,
bn_mimic3, pocket_tts, openvoice_v2, and the network for Edge. Every check measures the result: speech is
re-transcribed, clones are scored with a speaker-embedding model, captions are found in rendered pixels,
retention drops are planted at known times.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["VEDIT_PERSONAL_DIR"] = str(ROOT / "tests" / "out" / "personal_test")

import numpy as np  # noqa: E402

from vedit import models  # noqa: E402
from vedit.media import ffmpeg, measure_loudness, probe  # noqa: E402

OUT = ROOT / "tests" / "out" / "phase5"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)


def vedit(*args: str, env: dict | None = None) -> dict:
    p = subprocess.run([sys.executable, "-m", "vedit.cli", *args], capture_output=True, text=True, cwd=ROOT / "scripts",
                       env={**os.environ, "PYTHONUTF8": "1", **(env or {})}, encoding="utf-8")
    out = p.stdout.strip()
    if p.returncode:
        raise RuntimeError(f"vedit {' '.join(args)} failed: {p.stderr[-1200:]}")
    starts = [i for i in (out.find("{"), out.find("[")) if i >= 0]
    return json.loads(out[min(starts):]) if starts else {}


def heard(wav, language: str) -> list[str]:
    from vedit.transcribe import whisper
    from vedit.voice.text import norm
    return [norm(w["w"]) for w in whisper(Path(wav), language=language,
                                          model="base.en" if language == "en" else "large-v3-turbo")["words"]]


def wer(ref: list[str], hyp: list[str]) -> float:
    d = np.zeros((len(ref) + 1, len(hyp) + 1), int)
    d[:, 0], d[0, :] = range(len(ref) + 1), range(len(hyp) + 1)
    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]))
    return d[-1, -1] / max(1, len(ref))


def cer_bn(ref: str, wav) -> float:
    """Character error rate on Bangla letters only (Whisper splits and spells Bangla words its own way, so word
    error rate is unfair here)."""
    import re
    from vedit.transcribe import whisper
    letters = lambda t: re.sub(r"[^ঀ-৿]", "", t.replace("।", ""))
    hyp = letters("".join(w["w"] for w in whisper(Path(wav), language="bn", model="large-v3-turbo")["words"]))
    return wer(list(letters(ref)), list(hyp))


def frame(path, t: float, w: int = 540) -> np.ndarray:
    info = probe(path)
    h = int(round(info.height * w / info.width / 2)) * 2
    p = subprocess.run([ffmpeg(), "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-vf", f"scale={w}:{h}",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    return np.frombuffer(p.stdout, np.uint8).reshape(h, w, 3)


# ------------------------------------------------------------------ voices

def test_voices() -> dict:
    from vedit.voice import engine, text as T
    d = OUT / "voices"
    d.mkdir(parents=True, exist_ok=True)
    rows = engine.list_voices()
    backends = {r["backend"] for r in rows}
    check("voice list: every backend with a licence and a commercial flag",
          {"kokoro", "bn_coqui", "bn_mimic3", "edge"} <= backends and all(r["licence"] and r["commercial"] for r in rows),
          f"{len(rows)} voices")
    check("Bangla numbers spelled for offline voices",
          T.bn_spell_numbers("২০২৬ সালে 3.5 গুণ, 40%") == "দুই হাজার ছাব্বিশ সালে তিন দশমিক পাঁচ গুণ, চল্লিশ শতাংশ"
          and T.bn_number(100000) == "এক লাখ" and T.bn_number(350) == "তিনশো পঞ্চাশ")
    split = T.sentences("One. Two!\n\nThree? Four.")
    check("sentence split: pauses between sentences and paragraphs", [p for _, p in split] == [0.28, 0.6, 0.28, 0.0],
          str(split))

    en = "Most creators lose viewers in the first three seconds. Here is how to fix that, step by step."
    r = engine.say(en, d / "kokoro.wav", "kokoro:af_heart")
    words = json.loads(Path(r["transcript"]).read_text(encoding="utf-8"))["words"]
    mono = all(a["s"] <= b["s"] for a, b in zip(words, words[1:])) and all(w["e"] <= r["duration"] for w in words)
    w_ = wer([T.norm(x) for x in T.words(en)], heard(r["audio"], "en"))
    check("Kokoro English: intelligible (re-transcribed) with Whisper-aligned word times",
          w_ <= 0.12 and r["alignment"]["method"] == "whisper" and r["alignment"]["matched"] >= 0.85 and mono
          and len(words) == len(T.words(en)), f"WER {w_:.2f}, matched {r['alignment']['matched']}, {r['seconds']} s")
    r2 = engine.say("Meet Nahid Hasan from Blaron Studio.", d / "names.wav", "kokoro:am_michael", align="proportional")
    check("Kokoro speaks names missing from its dictionary (espeak inside sherpa-onnx 1.13.8)", r2["duration"] > 2.0,
          f"{r2['duration']} s")
    es = engine.say("Hola a todos, hoy vamos a editar un video.", d / "es.wav", "kokoro:ef_dora", align="proportional")
    w_es = wer([T.norm(x) for x in T.words("Hola a todos, hoy vamos a editar un video.")], heard(es["audio"], "es"))
    check("Kokoro Spanish voice speaks Spanish", w_es <= 0.4, f"WER {w_es:.2f}")

    bn = "ভিডিওর প্রথম তিন সেকেন্ডেই বেশিরভাগ দর্শক চলে যায়। তাই শুরুতেই ফলাফল দেখান।"
    out = {}
    for v in ("edge:bn-BD-PradeepNeural", "bn_coqui:female", "bn_mimic3:3"):
        rr = engine.say(bn, d / f"{v.replace(':', '_')}.wav", v)
        out[v] = rr
        tw = json.loads(Path(rr["transcript"]).read_text(encoding="utf-8"))
        ok = len(tw["words"]) == len(T.words(bn)) and len(tw["segments"]) == 2 and 3.0 < rr["duration"] < 15
        method_ok = rr["alignment"]["method"] == ("service" if v.startswith("edge") else "proportional")
        check(f"Bangla voice {v}: speech, two exact sentences, a word time for every word", ok and method_ok,
              f"{rr['duration']} s, {rr['alignment']['method']}, {rr['seconds']} s")
    cers = {v: cer_bn(bn, rr["audio"]) for v, rr in out.items()}
    check("Bangla voices are intelligible (Whisper reads them back: character error rate)",
          cers["edge:bn-BD-PradeepNeural"] <= 0.25 and all(c <= 0.45 for c in cers.values()),
          ", ".join(f"{v.split(':')[0]} {c:.2f}" for v, c in cers.items()))
    # pauses we place are silent
    tr = json.loads(Path(out["bn_coqui:female"]["transcript"]).read_text(encoding="utf-8"))
    x = engine.load_audio(out["bn_coqui:female"]["audio"])
    a, b = tr["segments"][0]["e"], tr["segments"][1]["s"]
    gap = x[int((a + 0.05) * 48000):int((b - 0.05) * 48000)]
    check("the pause between sentences is silence", b - a >= 0.25 and float(np.sqrt((gap ** 2).mean())) < 0.01,
          f"{b - a:.2f} s")
    return out


def test_clone() -> None:
    from vedit.voice import engine
    d = OUT / "clone"
    d.mkdir(parents=True, exist_ok=True)
    target = engine.say("Welcome back to the channel. Today I want to show you how I plan a whole week of videos in one "
                        "afternoon. First I write every hook on a single page, then I record them back to back, and only "
                        "then do I think about editing. It saves me hours every single week.", d / "target.wav",
                        "kokoro:am_michael", align="proportional")
    try:
        engine.clone("nocons", [target["audio"]], consent="")
        ok = False
    except Exception as exc:
        ok = "consent" in str(exc).lower()
    check("cloning refuses without the speaker's consent in words", ok)
    res = engine.clone("synthvoice", [target["audio"]],
                       consent="Synthetic test voice made with Kokoro am_michael for vedit's tests; no real person.")
    meta = json.loads((Path(res["dir"]) / "voice.json").read_text(encoding="utf-8"))
    check("clone keeps samples, a reference and the consent statement",
          meta["consent"]["statement"].startswith("Synthetic") and (Path(res["dir"]) / "reference.wav").exists()
          and 10 <= meta["reference_seconds"] <= 15.1 and any(u.startswith("openvoice:") for u in res["use"]),
          f"reference {meta['reference_seconds']} s")
    en = "This is a short test of the cloned voice. It should sound like the reference recording."
    c = engine.say(en, d / "pocket.wav", "pocket:synthvoice")
    other = engine.say(en, d / "other.wav", "kokoro:af_heart", align="proportional")
    s_clone, s_other = engine.similarity(c["audio"], target["audio"]), engine.similarity(other["audio"], target["audio"])
    check("Pocket TTS clone sounds like the target speaker", s_clone > s_other + 0.2 and s_clone > 0.4,
          f"similarity {s_clone:.2f} vs another voice {s_other:.2f}")
    bn = "এটি একটি পরীক্ষা। কণ্ঠটি মূল রেকর্ডিংয়ের মতো শোনানো উচিত।"
    base = engine.say(bn, d / "base.wav", "edge:bn-BD-PradeepNeural")
    conv = engine.say(bn, d / "openvoice.wav", "openvoice:synthvoice@edge:bn-BD-PradeepNeural")
    s_conv, s_base = engine.similarity(conv["audio"], target["audio"]), engine.similarity(base["audio"], target["audio"])
    check("OpenVoice moves an Edge Bangla voice to the cloned timbre", s_conv > s_base + 0.05,
          f"similarity {s_conv:.2f} vs base {s_base:.2f}")
    check("a clone over an online base voice is flagged online with the stricter licence",
          conv["online"] is True and conv["commercial"] in ("unclear", "verify"), f"{conv['commercial']}")


def test_vo_project() -> None:
    from vedit.captions import build_chunks
    from vedit.project import find
    f = OUT / "faceless"
    shutil.rmtree(f, ignore_errors=True)
    f.mkdir(parents=True)
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=1", "-frames:v", "1",
                    str(f / "cover.png")], check=True)
    vedit("project", "init", str(f), "--ratio", "9:16", "--name", "p5_faceless")
    script = f / "script.txt"
    script.write_text("ভিডিওর প্রথম তিন সেকেন্ডেই বেশিরভাগ দর্শক চলে যায়। তাই শুরুতেই ফলাফল দেখান।\n\n"
                      "তারপর দেখান কীভাবে সেখানে পৌঁছালেন।", encoding="utf-8")
    r = vedit("voice", "vo", str(f), "--voice", "edge:bn-BD-NabanitaNeural", "--file", str(script), "--place", "main")
    vedit("kenburns", str(f), str(f / "cover.png"), "--at", "0", "--duration", f"{r['duration']:.2f}")
    vedit("captions", "build", str(f), "--style", "karaoke_pop")
    vedit("mode", str(f), "auto")
    e = find(f).edit()
    check("faceless voiceover: the voice is the main track, captions come from it",
          bool(e.main) and e.sources[e.main[0].source].kind == "audio" and len(e.captions.chunks) >= 5,
          f"{len(e.captions.chunks)} caption chunks")
    out = Path(vedit("render", str(f), "--preview")["output"])
    lm = measure_loudness(out)
    dur = probe(out).duration
    t_cap = e.captions.chunks[1].start + 0.1
    img = frame(out, t_cap).astype(int)
    band = img[int(img.shape[0] * 0.45):int(img.shape[0] * 0.85)]
    white = ((band.min(axis=2) > 225)).mean()
    check("faceless render: the voice is heard, the length follows it, captions are drawn",
          abs(dur - r["duration"]) < 0.4 and lm["lufs"] > -30 and white > 0.002,
          f"{dur:.2f} s vs voice {r['duration']} s, {lm['lufs']:.1f} LUFS, caption pixels {white:.4f}")
    # parity: the Studio's JS builds the same captions from the VO
    from vedit import studio
    from vedit.knobs import bake
    docs_dir = f / "edit" / "studio" / "docs"
    studio.write_documents(find(f))
    ops = OUT / "noops.json"
    ops.write_text("[]", encoding="utf-8")
    p = subprocess.run(["node", str(ROOT / "tests" / "ops_parity.mjs"), str(docs_dir), str(ops)], capture_output=True,
                       text=True, encoding="utf-8")
    if p.returncode:
        check("Studio JS builds voiceover captions like the engine", False, p.stderr[-300:])
    else:
        js = json.loads(p.stdout)["captions"]
        py = [[round(c.start, 3), round(c.end, 3), c.text] for c in bake(find(f).edit()).captions.chunks]
        same = len(js) == len(py) and all(a[2] == b[2] and abs(a[0] - b[0]) < 0.002 for a, b in zip(js, py))
        check("Studio JS builds voiceover captions like the engine", same, f"py {len(py)} / js {len(js)}")
    # a VO clip over footage: its words join the captions at its time
    vedit("voice", "vo", str(f), "--voice", "edge:en-US-AndrewNeural", "--text", "And that is the whole trick.",
          "--place", "audio", "--at", "1.0", "--name", "vo_over")
    e = find(f).edit()
    eng = [w for c in build_chunks(e) for w in c.words if w.w.strip(".").lower() in ("trick", "whole")]
    check("a voiceover clip over footage adds its words to the captions at its place",
          eng and all(1.0 <= w.s <= 1.0 + 3.0 for w in eng), f"{[(w.w, w.s) for w in eng]}")


# ------------------------------------------------------------------ environments

def test_env() -> None:
    from vedit import env
    from vedit.paths import tools_dir
    rep = vedit("env")
    check("env: this PC is Claude Code on Windows with a ready engine",
          rep["surface"] == "claude-code-windows" and rep["engine_ready"] and rep["everything"], rep["surface"])
    check("env: the MCP route is recognised", vedit("env", "--brief", env={"VEDIT_SURFACE": "claude-app-mcp"})["surface"]
          == "claude-app-mcp")
    check("tool venvs: Windows keeps .cache/tools (other systems get .cache/tools-<os>)", tools_dir().name == "tools")
    sh = (ROOT / "vedit").read_text(encoding="utf-8")
    check("vedit launcher keeps a VM venv outside a shared folder, never on Git Bash",
          "*/mnt/*" in sh and "UV_PROJECT_ENVIRONMENT" in sh and "MINGW*" in sh)
    # MCP config merge on a copy
    cfg = OUT / "desktop_config.json"
    cfg.write_text(json.dumps({"preferences": {"a": 1}, "mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
    r1 = env.install_mcp(path=cfg)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    r2 = env.install_mcp(path=cfg)
    check("MCP registration keeps other settings and servers, backs up, and is idempotent",
          r1["changed"] and Path(r1["backup"]).exists() and data["preferences"] == {"a": 1}
          and set(data["mcpServers"]) == {"other", "vedit"} and not r2["changed"])
    cfg.write_text(json.dumps({"mcpServers": {"vedit": {"command": "C:/elsewhere/server.exe"}}}), encoding="utf-8")
    try:
        env.install_mcp(path=cfg)
        refused = False
    except Exception:
        refused = True
    check("MCP registration refuses to replace someone else's 'vedit' server without --force", refused)
    # the registered command really serves MCP
    entry = env.mcp_entry()
    script = OUT / "mcp_client.py"
    script.write_text('''import asyncio, json, os, sys
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
e = json.loads(sys.argv[1]); img = sys.argv[2]
async def main():
    keep = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "VEDIT_PERSONAL_DIR")}
    async with stdio_client(StdioServerParameters(command=e["command"], args=e["args"], env={**e["env"], **keep})) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = sorted(t.name for t in (await s.list_tools()).tools)
            doc = (await s.call_tool("read_doc", {"name": "voices.md"})).content[0].text
            pic = (await s.call_tool("view_image", {"path": img})).content[0]
            print(json.dumps({"tools": names, "doc": doc[:40], "pic": getattr(pic, "type", ""), "mime": getattr(pic, "mimeType", "")}))
asyncio.run(main())
''', encoding="utf-8")
    png = OUT / "probe.png"
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:d=1", "-frames:v", "1", str(png)], check=True)
    p = subprocess.run([sys.executable, str(script), json.dumps(entry), str(png)], capture_output=True, text=True, timeout=300)
    try:
        res = json.loads(p.stdout.strip().splitlines()[-1])
        ok = {"read_doc", "view_image", "env", "vedit", "studio_apply"} <= set(res["tools"]) and res["doc"].startswith("# Voices") \
            and res["pic"] == "image"
    except Exception:
        res, ok = {"error": p.stderr[-300:]}, False
    check("the registered MCP command serves vedit's tools (docs, images, env)", ok, str(len(res.get("tools", []))) + " tools")
    # launcher
    z = env.build_launcher(OUT / "launcher.zip", skill_path=r"C:\Somewhere\video-editing-skill")
    text = zipfile.ZipFile(z["zip"]).read("video-editing/SKILL.md").decode("utf-8")
    check("launcher zip: this PC's path and mount name filled in, description within limits",
          r"C:\Somewhere\video-editing-skill" in text and 'E="$HOME/mnt/video-editing-skill"' in text
          and "{{" not in text and z["description_chars"] <= 1024, f"{z['description_chars']} chars")
    home = OUT / "home"
    for kind, body in (("old", "Engine at `C:\\Users\\USER\\Downloads\\x`. device_bash"), ("new", text)):
        fdir = home / ".claude" / "skills" / "synced" / kind / "video-editing"
        fdir.mkdir(parents=True, exist_ok=True)
        (fdir / "SKILL.md").write_text(body, encoding="utf-8")
    st = env.launcher_status(home)
    kinds = sorted(r["kind"] for r in st["copies"])
    check("launcher status tells a hand-made copy from the official one", kinds == ["hand-made (v1)", f"official {env.LAUNCHER_VERSION}"],
          str(kinds))


# ------------------------------------------------------------------ analytics

def test_analytics() -> None:
    import httpx
    from vedit import analytics as A
    from vedit.project import find
    from vedit import routes
    check("YouTube links and ids parse", A.video_id("https://youtu.be/AbCdEfGhIjK") == "AbCdEfGhIjK"
          and A.video_id("https://www.youtube.com/watch?v=AbCdEfGhIjK&t=3") == "AbCdEfGhIjK"
          and A.video_id("https://youtube.com/shorts/AbCdEfGhIjK") == "AbCdEfGhIjK" and A.iso_duration("PT1M5.5S") == 65.5)
    src = ROOT / "tests" / "footage" / "e2e" / "edit"
    proj_dir = OUT / "e2e"
    shutil.rmtree(proj_dir, ignore_errors=True)
    shutil.copytree(src, proj_dir / "edit", ignore=shutil.ignore_patterns("render", "capcut", "studio", "qa"))
    p = find(proj_dir)
    e = p.edit()
    D = e.duration
    A.link(p, "https://youtu.be/AbCdEfGhIjK")
    rows = ["Video position (%),Absolute audience retention (%),Relative audience retention"]
    for i in range(101):
        x = i / 100
        y = 100 - 25 * (1 - math.exp(-x * D / 1.2)) - 20 * x
        y -= min(1.0, max(0.0, (x - 0.40) / 0.05)) * 10
        y += 4 * min(1.0, max(0.0, (x - 0.70) / 0.04))
        rows.append(f"{i}%,{y:.1f}%,0.55")
    csv_path = OUT / "retention.csv"
    csv_path.write_text("\n".join(rows), encoding="utf-8")
    imp = A.import_csv(p, csv_path)
    rep = A.report(p)
    drop = next((d for d in rep["drops"] if d["start"] > 3), None)
    rew = rep["rewatches"][0] if rep["rewatches"] else None
    check("retention CSV: the planted drop is found where it was planted",
          imp["points"] == 101 and drop and abs(drop["start"] - 0.40 * D) < 0.7 and abs(drop["end"] - 0.45 * D) < 0.7
          and drop["points"] < -8, f"{drop['start'] if drop else None}-{drop['end'] if drop else None} vs "
                                   f"{0.40 * D:.1f}-{0.45 * D:.1f}")
    check("retention CSV: the planted rewatch is found", rew and abs(rew["start"] - 0.70 * D) < 0.7, str(rew and rew["start"]))
    ctx_words = drop and drop["context"]["words"]
    from vedit.captions import build_chunks
    said = " ".join(w.w for c in build_chunks(e) for w in c.words if 0.40 * D - 0.1 <= w.s <= 0.45 * D)
    check("each drop says what was on screen and being said", bool(ctx_words) and said[:12] in ctx_words
          and "progress_bar" not in drop["context"]["graphics"], (ctx_words or "")[:60])
    check("report: hook numbers, insights and a chart", rep["summary"]["at_3s"] > rep["summary"]["end"] and
          len(rep["insights"]) >= 3 and Path(rep["chart"]).exists(), rep["insights"][0][:70])
    # time-positioned CSV (m:ss) with ratios
    alt = OUT / "retention_time.csv"
    alt.write_text("Video position,Audience retention\n" + "\n".join(f"0:{int(i * D / 20):02d},{0.9 - i * 0.01:.2f}"
                                                                     for i in range(21)), encoding="utf-8")
    pts = A.parse_csv(alt, duration=D)
    check("retention CSV with m:ss positions and ratios reads too", len(pts) == 21 and pts[-1][0] > 0.9 and
          abs(pts[0][1] - 0.9) < 1e-6)
    # API pull against a mock of Google's endpoints
    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if u.startswith(A.TOKEN_URL):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if u.startswith(A.DATA_API):
            assert req.headers["authorization"] == "Bearer tok"
            return httpx.Response(200, json={"items": [{"snippet": {"title": "Test", "publishedAt": "2026-10-30T10:00:00Z"},
                                                        "contentDetails": {"duration": f"PT{int(D)}S"}, "statistics": {}}]})
        if u.startswith(A.ANALYTICS):
            if "elapsedVideoTimeRatio" in u:
                return httpx.Response(200, json={"columnHeaders": [{"name": "elapsedVideoTimeRatio"},
                                                                   {"name": "audienceWatchRatio"},
                                                                   {"name": "relativeRetentionPerformance"}],
                                                 "rows": [[i / 100, max(0.2, 1 - i / 150), 0.5] for i in range(1, 101)]})
            return httpx.Response(200, json={"columnHeaders": [{"name": n} for n in ("views", "estimatedMinutesWatched",
                                                                                    "averageViewDuration",
                                                                                    "averageViewPercentage", "likes",
                                                                                    "shares", "subscribersGained")],
                                             "rows": [[1234, 300, 18, 58.2, 90, 4, 7]]})
        return httpx.Response(404)
    from vedit import config
    config.set_secret(A.SECRET, json.dumps({"client_id": "cid", "client_secret": "cs", "refresh_token": "rt"}))
    pulled = A.pull(p, transport=httpx.MockTransport(handler))
    check("API pull: metrics and the retention curve through the owner's token (mocked Google)",
          pulled["points"] == 100 and pulled["metrics"]["views"] == 1234 and abs(pulled["duration"] - int(D)) < 1e-6)
    # OAuth flow: the "browser" (this test) follows the consent link back to the loopback port
    def browser(url: str) -> None:
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(url).query)
        assert q["code_challenge_method"] == ["S256"] and "yt-analytics.readonly" in q["scope"][0]
        def hit():
            time.sleep(0.3)
            urllib.request.urlopen(f"{q['redirect_uri'][0]}/?code=abc&state={q['state'][0]}", timeout=10).read()
        threading.Thread(target=hit, daemon=True).start()
    def token_handler(req: httpx.Request) -> httpx.Response:
        body = req.content.decode()
        ok = "code_verifier=" in body and "code=abc" in body
        return httpx.Response(200 if ok else 400, json={"access_token": "a", "refresh_token": "r2"} if ok else {})
    client = OUT / "client.json"
    client.write_text(json.dumps({"installed": {"client_id": "cid2", "client_secret": "s2"}}), encoding="utf-8")
    res = A.auth(str(client), open_browser=False, timeout=20, transport=httpx.MockTransport(token_handler), on_url=browser)
    stored = json.loads(config.secret(A.SECRET))
    check("OAuth: PKCE consent link, loopback reply, refresh token kept in personal secrets",
          res["ok"] and stored["refresh_token"] == "r2" and stored["client_id"] == "cid2")
    # learning: two videos -> the route planner sees measured lifts
    A.import_csv(p, csv_path)
    l1 = A.learn_from(p)
    A.link(p, "https://youtu.be/ZyXwVuTsRqP")
    A.import_csv(p, csv_path, video="ZyXwVuTsRqP")
    l2 = A.learn_from(p, video="ZyXwVuTsRqP")
    perf = l2["profile_performance"] or {}
    plan = routes.plan("motion_graphic")
    tpl = next(r for r in plan if r["id"] == "template")
    check("learn: performance in the profile and measured lifts in the route planner",
          l1["elements"] > 0 and perf.get("videos", 0) >= 2 and perf.get("at_3s_median") and tpl.get("performance")
          and tpl["performance"]["n"] >= 2, json.dumps(tpl.get("performance")))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pd = Path(os.environ["VEDIT_PERSONAL_DIR"])
    for sub in ("voices", "learning"):
        shutil.rmtree(pd / sub, ignore_errors=True)
    need = [m for m in ("kokoro_multi", "bn_coqui", "bn_mimic3", "pocket_tts", "openvoice_v2", "speaker_emb")
            if not models.is_ready(m)]
    if need:
        print(f"missing models {need}: ask the owner, then `vedit models get <id>`")
        return 2
    test_voices()
    test_clone()
    test_vo_project()
    test_env()
    test_analytics()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
