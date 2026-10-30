"""Runs inside claude-real-video's own venv (never imported by vedit): its watching pieces on vedit's files.

    python -I crv_bridge.py <command> <request.json> <result.json>

frames:   {"video", "out", "scene", "fps_floor", "start", "end", "width", "max_frames"} -> scene-aware frames,
          near-duplicates dropped (crv's two-channel dedup), frames.json and 3x3 grids. Reads the file in place
          (crv's own entry point copies local files first).
speakers: {"audio", "num_speakers", "threshold"} -> [{start, end, speaker}] (sherpa-onnx, offline; the models
          download once, ~45 MB).
fetch:    {"url", "out", "sub_lang", "cookies_from_browser"} -> {"file", "subtitles": [...]} via yt-dlp.
"""

import glob
import json
import os
import shutil
import sys


def frames(req):
    from claude_real_video import core
    out = req["out"]
    frames_dir = os.path.join(out, "frames")
    for d in (frames_dir, os.path.join(out, "grids")):
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    n, times = core.extract_frames(req["video"], frames_dir, req.get("scene", 0.3), req.get("fps_floor", 1.0),
                                   start=req.get("start"), end=req.get("end"), frame_width=req.get("width", 480))
    kept, records = core.dedup_frames(frames_dir, 8, 4, req.get("max_frames", 150), times=times or None)
    core.write_frames_json(out, records)
    grids = core.make_grids(frames_dir, out, cell_width=min(480, req.get("width", 480)))
    with open(os.path.join(out, "frames.json"), encoding="utf-8") as f:
        fr = json.load(f).get("frames", [])
    return {"extracted": n, "kept": len(fr), "frames": fr, "grids": grids}


def speakers(req):
    from claude_real_video import speakers as sp
    if req.get("seg") and req.get("emb"):          # models vedit downloaded (ask-first, resumable)
        sp._ensure_models = lambda: (req["seg"], req["emb"])
    diarize = sp.diarize
    return {"turns": diarize(req["audio"], num_speakers=req.get("num_speakers", -1),
                             cluster_threshold=req.get("threshold", 0.9))}


def fetch(req):
    from claude_real_video import core
    os.makedirs(req["out"], exist_ok=True)
    path = core.fetch_video(req["url"], req["out"], cookies_from_browser=req.get("cookies_from_browser"),
                            sub_lang=req.get("sub_lang"))
    subs = [p for p in glob.glob(os.path.join(req["out"], "source*")) if p.endswith(core.SUBTITLE_EXTS)]
    info = core._remote_info(req["url"]) or {}
    keep = {k: info.get(k) for k in ("title", "uploader", "channel", "webpage_url", "license", "duration",
                                      "upload_date") if info.get(k) is not None}
    return {"file": path, "subtitles": subs, "info": keep}


def main():
    cmd, req_path, out_path = sys.argv[1:4]
    with open(req_path, encoding="utf-8") as f:
        req = json.load(f)
    res = {"frames": frames, "speakers": speakers, "fetch": fetch}[cmd](req)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
