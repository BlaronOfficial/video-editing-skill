"""timeline_view: filmstrip + waveform + word labels for a time range, as one PNG Claude can look at.

Used at decision points (which retake is better, is this pause dead air, where does the gesture land)
instead of dumping every frame.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .captions import transcript_words
from .media import ffmpeg, probe
from .paths import fonts_dir
from .util import run


def _font(size: int):
    for name in ("Poppins-Medium.ttf", "HindSiliguri-Medium.ttf"):
        p = fonts_dir() / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def timeline_view(src: str | Path, start: float, end: float, out_png: str | Path, *, transcript: str | None = None,
                  frames: int = 8, width: int = 1600) -> Path:
    src, out_png = Path(src), Path(out_png)
    info = probe(src)
    end = min(end, info.duration or end)
    dur = max(0.2, end - start)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    strip = out_png.with_name(out_png.stem + "_strip.png")
    wave = out_png.with_name(out_png.stem + "_wave.png")
    tile_w = width // frames
    if info.kind == "video":
        run([ffmpeg(), "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src), "-vf",
             f"fps={frames / dur:.5f},scale={tile_w}:-2,tile={frames}x1", "-frames:v", "1", str(strip)])
    if info.has_audio:
        run([ffmpeg(), "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src), "-filter_complex",
             f"showwavespic=s={width}x140:colors=0x7fd1ff:scale=sqrt", "-frames:v", "1", str(wave)])
    parts = [Image.open(p).convert("RGB") for p in (strip, wave) if p.exists()]
    label_h = 90
    total_h = sum(p.height for p in parts) + label_h + 28
    canvas = Image.new("RGB", (width, total_h), (18, 18, 22))
    d = ImageDraw.Draw(canvas)
    y = 28
    d.text((8, 6), f"{src.name}  {start:.2f}s – {end:.2f}s", fill=(230, 230, 230), font=_font(16))
    for p in parts:
        canvas.paste(p.resize((width, p.height)), (0, y))
        y += p.height
    # time ruler + words
    f_small = _font(14)
    for k in range(11):
        x = int(k / 10 * (width - 1))
        d.line([(x, y), (x, y + 8)], fill=(120, 120, 130))
        d.text((x + 2, y + 8), f"{start + k / 10 * dur:.1f}", fill=(140, 140, 150), font=_font(11))
    if transcript:
        row = 0
        for w in transcript_words(transcript):
            if w["e"] < start or w["s"] > end:
                continue
            x = int((w["s"] - start) / dur * width)
            x2 = int((w["e"] - start) / dur * width)
            yy = y + 26 + (row % 2) * 30
            d.rectangle([x, yy, max(x + 2, x2), yy + 24], outline=(255, 225, 77))
            d.text((x + 3, yy + 3), w["w"], fill=(255, 255, 255), font=f_small)
            row += 1
    canvas.save(out_png)
    for p in (strip, wave):
        p.unlink(missing_ok=True)
    return out_png


def frames_at(src: str | Path, times: list[float], out_png: str | Path, *, width: int = 320, labels: list[str] | None = None) -> Path:
    """Grid of frames at specific timestamps (e.g. both sides of each cut)."""
    tiles = []
    tmp_dir = Path(out_png).parent
    for i, t in enumerate(times):
        f = tmp_dir / f"_fa_{i}.jpg"
        run([ffmpeg(), "-y", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", str(src), "-frames:v", "1", "-vf",
             f"scale={width}:-2", str(f)])
        if f.exists():
            tiles.append(Image.open(f).convert("RGB"))
    if not tiles:
        raise RuntimeError("no frames extracted")
    cols = min(6, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    w, h = tiles[0].size
    sheet = Image.new("RGB", (cols * w, rows * (h + 22)), (12, 12, 14))
    d = ImageDraw.Draw(sheet)
    for i, im in enumerate(tiles):
        x, y = (i % cols) * w, (i // cols) * (h + 22)
        sheet.paste(im, (x, y + 22))
        d.text((x + 4, y + 4), labels[i] if labels else f"{times[i]:.2f}s", fill=(240, 240, 240), font=_font(13))
    sheet.save(out_png)
    for i in range(len(times)):
        (tmp_dir / f"_fa_{i}.jpg").unlink(missing_ok=True)
    return Path(out_png)
