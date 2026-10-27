"""Styles: shipped aesthetic presets, per-client brand kits, creator-style profiles, learned preferences.

Lookup order for a style name: personal/styles/<name>.json, then presets/aesthetics/<name>.json.
Brand kits live in personal/brands/<name>.json. Learned adjustments (from diffs of the user's own
CapCut edits) accumulate in the profile's "learned" block and are applied on the next edit.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np

from .media import detect_scenes, ffmpeg, measure_loudness, probe
from .paths import personal_dir, presets_dir
from .util import VeditError, read_json, run, write_json


def _dirs(kind: str) -> list[Path]:
    if kind == "brand":
        return [personal_dir() / "brands"]
    return [personal_dir() / "styles", presets_dir() / "aesthetics"]


def list_styles() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for d in reversed(_dirs("style")):
        if d.is_dir():
            for f in sorted(d.glob("*.json")):
                data = read_json(f) or {}
                out[data.get("name", f.stem)] = {"description": data.get("description", ""), "source": str(f)}
    return out


def load_style(name: str) -> dict:
    for d in _dirs("style"):
        f = d / f"{name}.json"
        if f.exists():
            return read_json(f)
    raise VeditError(f"Style '{name}' not found. Available: {', '.join(list_styles())}")


def save_style(profile: dict) -> Path:
    if not profile.get("name"):
        raise VeditError("profile needs a name")
    profile["updated"] = time.strftime("%Y-%m-%d %H:%M")
    return write_json(personal_dir() / "styles" / f"{profile['name']}.json", profile)


def list_brands() -> list[str]:
    d = personal_dir() / "brands"
    return sorted(f.stem for f in d.glob("*.json")) if d.is_dir() else []


def load_brand(name: str) -> dict:
    f = personal_dir() / "brands" / f"{name}.json"
    if not f.exists():
        raise VeditError(f"Brand kit '{name}' not found. Create one with `vedit brand create {name}`.")
    return read_json(f)


BRAND_TEMPLATE = {
    "name": "", "colors": {"accent": "#FFE14D", "accent2": "#FF4D6D", "ink": "#0B0B0F", "paper": "#FFFFFF"},
    "fonts": {"display": "Poppins", "body": "Poppins", "bangla": "Hind Siliguri", "captions": "Poppins ExtraBold"},
    "logo": None, "handle": "", "cta": "Follow for more", "caption_style": None, "grade": None,
    "music": {"moods": [], "avoid": []}, "intro": None, "outro": "logo_sting", "rules": [],
}


def create_brand(name: str, **fields: Any) -> Path:
    data = {**BRAND_TEMPLATE, **fields, "name": name}
    return write_json(personal_dir() / "brands" / f"{name}.json", data)


def brand_mg_data(brand: dict) -> dict:
    """The brand block every motion-graphics template understands (V.brand)."""
    c, f = brand.get("colors", {}), brand.get("fonts", {})
    return {"accent": c.get("accent"), "accent2": c.get("accent2"), "ink": c.get("ink"), "paper": c.get("paper"),
            "font": f.get("display"), "fontBangla": f.get("bangla")}


def caption_overrides(style: dict | None, brand: dict | None) -> dict:
    """Merge caption tweaks: style preset < brand kit < learned adjustments."""
    out: dict = {}
    if style:
        out.update(style.get("captions", {}).get("overrides", {}))
    if brand:
        if brand.get("colors", {}).get("accent"):
            out["highlight"] = brand["colors"]["accent"]
        if brand.get("fonts", {}).get("captions"):
            out["font"] = brand["fonts"]["captions"]
        if brand.get("fonts", {}).get("bangla"):
            out["font_bangla"] = brand["fonts"]["bangla"] + " SemiBold" if " " not in brand["fonts"]["bangla"] else brand["fonts"]["bangla"]
    learned = (style or {}).get("learned", {}).get("captions", {})
    if "size_scale" in learned and "size" in out:
        out["size"] = round(out["size"] * learned["size_scale"], 4)
    elif "size_scale" in learned:
        out["size_scale"] = learned["size_scale"]
    if "y_delta" in learned:
        out["y_delta"] = learned["y_delta"]
    return out


# ------------------------------------------------------------------ creator style analysis

def _frame_stats(src: str, times: list[float]) -> dict:
    import subprocess

    import cv2
    sats, vals, contrasts, warm = [], [], [], []
    w, h = 320, 180
    for t in times:
        # Fixed-size raw frames, read as bytes (the text-mode run() helper would corrupt them).
        proc = subprocess.run([ffmpeg(), "-v", "error", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1",
                               "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
        raw = proc.stdout
        if not raw or len(raw) < w * h * 3:
            continue
        img = np.frombuffer(raw[: w * h * 3], dtype=np.uint8).reshape(h, w, 3)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        sats.append(float(hsv[..., 1].mean()) / 255)
        vals.append(float(hsv[..., 2].mean()) / 255)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        contrasts.append(float(gray.std()) / 128)
        b, g, r = (float(img[..., i].mean()) for i in range(3))
        warm.append((r - b) / 255)
    avg = lambda xs: round(float(np.mean(xs)), 3) if xs else None  # noqa: E731
    return {"saturation": avg(sats), "brightness": avg(vals), "contrast": avg(contrasts), "warmth": avg(warm)}


def analyze_reference(videos: list[str | Path], name: str, out_dir: Path) -> dict:
    """Measure pacing, colour and loudness of reference videos; save frame sheets for Claude to study."""
    from .view import frames_at
    out_dir.mkdir(parents=True, exist_ok=True)
    per = []
    sheets = []
    for v in videos:
        v = str(Path(v).resolve())
        info = probe(v)
        cuts = detect_scenes(v, threshold=0.3)
        shots = np.diff([0.0] + cuts + [info.duration]) if info.duration else np.array([])
        times = list(np.linspace(info.duration * 0.05, info.duration * 0.95, 12)) if info.duration else []
        sheet = frames_at(v, times, out_dir / f"{Path(v).stem}_frames.png", width=240)
        sheets.append(str(sheet))
        per.append({
            "video": v, "duration": round(info.duration, 1), "aspect": f"{info.display_size[0]}x{info.display_size[1]}",
            "cuts_per_min": round(len(cuts) / max(info.duration / 60, 1e-6), 1),
            "avg_shot_s": round(float(shots.mean()), 2) if shots.size else None,
            "median_shot_s": round(float(np.median(shots)), 2) if shots.size else None,
            "loudness": measure_loudness(v) if info.has_audio else {},
            "color": _frame_stats(v, times[::2]),
        })
    profile = {
        "name": name, "kind": "creator_clone", "created": time.strftime("%Y-%m-%d %H:%M"),
        "description": f"Style learned from {len(per)} reference video(s).",
        "metrics": per,
        "pacing": {"avg_shot_s": round(float(np.mean([p["avg_shot_s"] for p in per if p["avg_shot_s"]])), 2) if per else None,
                   "cuts_per_min": round(float(np.mean([p["cuts_per_min"] for p in per])), 1) if per else None},
        "observations": {
            "captions": "TODO (Claude): font family/weight, size, case, colours, highlight style, position, animation",
            "graphics": "TODO (Claude): recurring motion-graphic types, colours, energy",
            "broll": "TODO (Claude): how often, full-frame vs PiP, stock vs filmed",
            "transitions": "TODO (Claude): hard cuts / whips / zooms / flashes",
            "sound": "TODO (Claude): music genre/level, SFX density (whooshes, pops)",
            "hook": "TODO (Claude): how the first 2 seconds are built",
        },
        "frame_sheets": sheets,
        "learned": {},
    }
    save_style(profile)
    return profile


def learn(style_name: str, insights: dict) -> dict:
    """Fold a CapCut diff summary into the style's learned block (rolling, so one edit doesn't dominate)."""
    try:
        profile = load_style(style_name)
    except VeditError:
        profile = {"name": style_name, "kind": "learned", "description": "Preferences learned from your CapCut edits.",
                   "learned": {}}
    learned = profile.setdefault("learned", {})
    cap = learned.setdefault("captions", {})
    if insights.get("caption_size_ratio"):
        prev = cap.get("size_scale", 1.0)
        cap["size_scale"] = round(prev * (0.5 + 0.5 * insights["caption_size_ratio"]), 3)
    if insights.get("caption_y_delta") is not None:
        cap["y_delta"] = round(cap.get("y_delta", 0.0) * 0.5 + insights["caption_y_delta"] * 0.5, 3)
    if insights.get("music_volume_ratio"):
        learned["music_volume_scale"] = round(learned.get("music_volume_scale", 1.0) * (0.5 + 0.5 * insights["music_volume_ratio"]), 3)
    if insights.get("main_duration_ratio"):
        learned["tightness"] = round(learned.get("tightness", 1.0) * (0.5 + 0.5 * insights["main_duration_ratio"]), 3)
    notes = learned.setdefault("notes", [])
    for line in insights.get("notes", []):
        if line not in notes:
            notes.append(line)
    learned["notes"] = notes[-30:]
    learned["updated"] = time.strftime("%Y-%m-%d %H:%M")
    save_style(profile)
    return profile
