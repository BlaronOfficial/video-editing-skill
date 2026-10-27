"""FFmpeg/ffprobe wrappers: probing, audio extraction, frames, silence and scene detection, loudness."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from .util import VeditError, run, which

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mts", ".m2ts", ".flv", ".wmv"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".svg"}


def ffmpeg() -> str:
    exe = which("ffmpeg")
    if not exe:
        raise VeditError("ffmpeg not found. Run `vedit doctor` for install instructions.")
    return exe


def ffprobe() -> str:
    exe = which("ffprobe")
    if not exe:
        raise VeditError("ffprobe not found. Run `vedit doctor` for install instructions.")
    return exe


@dataclass
class MediaInfo:
    path: str
    kind: str                 # video | audio | image
    duration: float           # seconds (0 for stills)
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False
    has_alpha: bool = False
    rotation: int = 0
    vcodec: str = ""
    acodec: str = ""
    sample_rate: int = 0
    pix_fmt: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def display_size(self) -> tuple[int, int]:
        """Width/height after applying rotation metadata (phone footage is often rotated)."""
        if self.rotation in (90, 270, -90, -270):
            return self.height, self.width
        return self.width, self.height


def kind_of(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in IMAGE_EXT:
        return "image"
    return "unknown"


def _parse_rate(rate: str | None) -> float:
    if not rate or rate in ("0/0", "0"):
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        return float(num) / float(den) if float(den) else 0.0
    return float(rate)


@lru_cache(maxsize=512)
def _probe_cached(path: str, mtime: float) -> MediaInfo:
    proc = run([ffprobe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    v = next((s for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    kind = kind_of(path)
    if kind == "unknown":
        kind = "video" if v else ("audio" if a else "unknown")
    duration = float(fmt.get("duration") or (v or {}).get("duration") or (a or {}).get("duration") or 0)
    rotation = 0
    if v:
        tags = v.get("tags", {}) or {}
        if "rotate" in tags:
            rotation = int(float(tags["rotate"]))
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rotation = int(float(sd["rotation"]))
    pix_fmt = (v or {}).get("pix_fmt", "")
    has_alpha = bool(v) and ("a" in pix_fmt.replace("yuv", "").replace("gray", "") or pix_fmt in ("argb", "rgba", "bgra", "abgr")
                             or (v.get("codec_name") == "prores" and v.get("profile", "").startswith("4444"))
                             or (v.get("tags", {}) or {}).get("alpha_mode") == "1")
    if kind == "image":
        duration = 0.0
    return MediaInfo(
        path=path, kind=kind, duration=duration,
        width=int((v or {}).get("width", 0) or 0), height=int((v or {}).get("height", 0) or 0),
        fps=_parse_rate((v or {}).get("avg_frame_rate")) or _parse_rate((v or {}).get("r_frame_rate")),
        has_audio=a is not None, has_alpha=has_alpha, rotation=rotation,
        vcodec=(v or {}).get("codec_name", ""), acodec=(a or {}).get("codec_name", ""),
        sample_rate=int((a or {}).get("sample_rate", 0) or 0), pix_fmt=pix_fmt,
    )


def probe(path: str | Path) -> MediaInfo:
    p = Path(path).resolve()
    if not p.exists():
        raise VeditError(f"Media not found: {p}")
    if p.suffix.lower() == ".svg":
        return MediaInfo(path=str(p), kind="image", duration=0.0)
    return _probe_cached(str(p), p.stat().st_mtime)


def list_media(folder: str | Path, recursive: bool = False) -> list[Path]:
    root = Path(folder)
    if root.is_file():
        return [root]
    pattern = "**/*" if recursive else "*"
    exts = VIDEO_EXT | AUDIO_EXT | IMAGE_EXT
    return sorted(p for p in root.glob(pattern) if p.is_file() and p.suffix.lower() in exts and "edit" not in p.parts[-2:-1])


def extract_audio(src: str | Path, dst: str | Path, *, sample_rate: int = 16000, mono: bool = True) -> Path:
    """Speech-friendly WAV for transcription and analysis."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg(), "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1" if mono else "2",
           "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(dst)]
    run(cmd)
    return dst


def extract_frame(src: str | Path, t: float, dst: str | Path, *, width: int = 480) -> Path:
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    run([ffmpeg(), "-y", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", str(src), "-frames:v", "1",
         "-vf", f"scale={width}:-2", "-q:v", "3", str(dst)])
    return dst


def detect_silences(src: str | Path, *, noise_db: float = -35.0, min_dur: float = 0.35) -> list[tuple[float, float]]:
    """Silent ranges (start, end) via ffmpeg silencedetect."""
    proc = run([ffmpeg(), "-v", "info", "-i", str(src), "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
                "-f", "null", "-"], check=False)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", proc.stderr or "")]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", proc.stderr or "")]
    out = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else probe(src).duration
        out.append((max(0.0, s), e))
    return out


def detect_scenes(src: str | Path, *, threshold: float = 0.3, start: float | None = None,
                  duration: float | None = None) -> list[float]:
    """Timestamps of visual scene changes (shot cuts) via ffmpeg scene score.

    With start/duration only that range is analysed and times are relative to `start`.
    """
    seek = (["-ss", f"{start:.3f}"] if start is not None else []) + (["-t", f"{duration:.3f}"] if duration else [])
    proc = run([ffmpeg(), "-v", "info", *seek, "-i", str(src), "-filter:v", f"select='gt(scene,{threshold})',showinfo",
                "-an", "-f", "null", "-"], check=False)
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", proc.stderr or "")]


def luma_at(src: str | Path, times: list[float]) -> list[float]:
    """Mean brightness (0..1) of single frames, e.g. to spot fades at clip boundaries."""
    import subprocess
    out = []
    for t in times:
        raw = subprocess.run([ffmpeg(), "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", str(src), "-frames:v", "1",
                              "-vf", "scale=64:36", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
        out.append(sum(raw) / (len(raw) * 255) if raw else 0.0)
    return out


def measure_loudness(src: str | Path) -> dict:
    """Integrated loudness (LUFS), true peak and LRA via ebur128/loudnorm analysis."""
    proc = run([ffmpeg(), "-v", "info", "-i", str(src), "-af", "loudnorm=print_format=json", "-f", "null", "-"], check=False)
    text = proc.stderr or ""
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", text, re.S)
    if not match:
        return {}
    data = json.loads(match.group(0))
    return {"lufs": float(data["input_i"]), "true_peak": float(data["input_tp"]), "lra": float(data["input_lra"]),
            "threshold": float(data["input_thresh"])}


@lru_cache(maxsize=1)
def available_encoders() -> set[str]:
    proc = run([ffmpeg(), "-hide_banner", "-encoders"], check=False)
    return set(re.findall(r"^\s*[VAS][\w.]{5}\s+(\S+)", proc.stdout or "", re.M))


@lru_cache(maxsize=8)
def encoder_works(name: str) -> bool:
    """Hardware encoders can be listed but unusable (no driver); test with a tiny encode."""
    if name not in available_encoders():
        return False
    proc = run([ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2", "-c:v", name,
                "-frames:v", "3", "-f", "null", "-"], check=False)
    return proc.returncode == 0


def pick_video_encoder(preference: str = "auto") -> str:
    if preference != "auto":
        return preference
    for candidate in ("h264_nvenc", "h264_qsv", "h264_videotoolbox", "h264_amf"):
        if encoder_works(candidate):
            return candidate
    return "libx264"


def video_encoder_args(encoder: str, *, crf: int = 18, preset: str = "medium") -> list[str]:
    """Quality-equivalent args per encoder family."""
    if encoder == "libx264":
        return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"]
    if encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-global_quality", str(crf + 2), "-look_ahead", "0", "-pix_fmt", "nv12"]
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(crf + 1), "-pix_fmt", "yuv420p"]
    if encoder == "h264_videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-q:v", "65", "-pix_fmt", "yuv420p"]
    if encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "quality", "-qp_i", str(crf), "-qp_p", str(crf + 2), "-pix_fmt", "yuv420p"]
    return ["-c:v", encoder]
