"""Import packages for other editors: everything an editor needs to carry on, in one folder.

    edit/handoff/<target>/
      <name>.fcpxml | .xml | .otio | .edl | .kdenlive | .mlt     timeline(s) for the target
      graphics/   overlays as ProRes 4444 (alpha), styled captions and titles as full-length alpha layers
      stems/      dialogue.wav, music.wav (ducked), effects.wav: 48 kHz 24-bit, pre-master
      captions.srt, look.cube (the grade as a 3D LUT), reference.mp4 (the vedit render, when there is one)
      README.md   how to import it in that editor; what did not translate
      handoff.json  the neutral timeline as handed off (vedit handoff diff compares re-exports with it)
      media/      only with --collect: every source copied in, timelines point here
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import numpy as np

from .. import captions as caps
from ..media import ffmpeg, probe
from ..paths import fonts_dir
from ..project import Project
from ..render import GRADES
from ..util import VeditError, read_json, run, short_hash, write_json, write_text
from . import Handoff, flatten, summary

TARGETS = {
    "resolve": ["fcpxml"],
    "fcp": ["fcpxml"],
    "premiere": ["xml"],
    "kdenlive": ["kdenlive"],
    "shotcut": ["mlt"],
    "otio": ["otio"],
    "edl": ["edl"],
    "nle": ["fcpxml", "xml", "otio", "edl", "kdenlive", "mlt"],
}
SPATIAL = ("vignette", "unsharp", "noise", "gblur", "boxblur", "smartblur", "sharpen")


# ------------------------------------------------------------------ the grade as a LUT

def grade_lut(preset: str | None, lut: str | None, intensity: float, out: str | Path, *, size: int = 33) -> Path | None:
    """Bake the colour part of a grade into a .cube 3D LUT (Hald CLUT through the same FFmpeg filters).
    Spatial parts (vignette, sharpening, grain) cannot live in a LUT; they are listed in the README."""
    chain = []
    if preset:
        if preset not in GRADES:
            raise VeditError(f"Unknown grade '{preset}'")
        chain += [f for f in GRADES[preset].split(",") if not f.split("=")[0] in SPATIAL]
    out = Path(out)
    work = out.parent / f".lut_{short_hash(preset, lut, intensity)}"
    work.mkdir(parents=True, exist_ok=True)
    if lut:
        local = work / ("in" + Path(lut).suffix)
        shutil.copy(lut, local)
        chain.append(f"lut3d=file={local.name}")
    if not chain:
        shutil.rmtree(work, ignore_errors=True)
        return None
    level = 8                                            # 64^3 Hald CLUT, 512x512 image
    raw = work / "hald.rgb"
    run([ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", f"haldclutsrc=level={level}", "-frames:v", "1",
         "-vf", ",".join(["format=rgb48le", *chain, "format=rgb48le"]), "-f", "rawvideo", "-pix_fmt", "rgb48le", raw.name],
        cwd=work)
    n = level * level
    graded = np.frombuffer(raw.read_bytes(), dtype="<u2").astype(np.float64).reshape(-1, 3) / 65535.0
    idx = np.arange(n ** 3)
    ident = np.stack([(idx % n) / (n - 1), (idx // n % n) / (n - 1), (idx // (n * n)) / (n - 1)], axis=1)
    graded = ident + (graded - ident) * max(0.0, min(1.0, intensity))
    # resample the 64^3 cube to `size`^3 (trilinear) so the file stays small; NLEs interpolate anyway
    cube = graded.reshape(n, n, n, 3)                      # [b][g][r]
    pts = np.linspace(0, n - 1, size)
    lo = np.floor(pts).astype(int)
    hi = np.minimum(lo + 1, n - 1)
    fr = pts - lo

    def lerp_axis(arr: np.ndarray, axis: int) -> np.ndarray:
        a = np.take(arr, lo, axis=axis)
        b = np.take(arr, hi, axis=axis)
        shape = [1] * arr.ndim
        shape[axis] = size
        f = fr.reshape(shape)
        return a + (b - a) * f

    small = lerp_axis(lerp_axis(lerp_axis(cube, 0), 1), 2)  # [b][g][r][3]
    rows = small.reshape(-1, 3)                              # r fastest, as .cube expects
    title = preset or Path(lut).stem
    lines = [f'TITLE "vedit {title}"', f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    lines += [f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in np.clip(rows, 0, 1)]
    write_text(out, "\n".join(lines) + "\n")
    shutil.rmtree(work, ignore_errors=True)
    return out


def spatial_parts(preset: str | None) -> list[str]:
    if not preset or preset not in GRADES:
        return []
    return [f for f in GRADES[preset].split(",") if f.split("=")[0] in SPATIAL]


# ------------------------------------------------------------------ graphics

def to_prores(src: str | Path, out: str | Path) -> Path:
    """Any alpha render (WebM VP9, PNG sequence, MOV) -> ProRes 4444 with alpha, which every NLE reads."""
    out = Path(out)
    if out.exists() and out.stat().st_mtime >= Path(src).stat().st_mtime:
        return out
    dec = ["-c:v", "libvpx-vp9"] if str(src).lower().endswith(".webm") else []
    run([ffmpeg(), "-y", "-v", "error", *dec, "-i", str(src), "-map", "0:v:0", "-c:v", "prores_ks", "-profile:v", "4",
         "-pix_fmt", "yuva444p10le", "-vendor", "apl0", "-alpha_bits", "16", str(out)], timeout=3600)
    return out


def ass_alpha_layer(ass: Path, out: Path, *, width: int, height: int, fps: float, duration: float) -> Path:
    """Render an ASS file to a full-length ProRes 4444 layer with real alpha.

    libass draws onto the picture but leaves its alpha alone, so the layer is rendered twice, over black
    and over white; alpha = 1 - (white - black), colour = black / alpha (difference matting, exact for
    8-bit compositing)."""
    work = out.parent / f".ass_{short_hash(str(ass), width, height)}"
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(ass, work / "layer.ass")
    try:
        fdir = os.path.relpath(fonts_dir(), work).replace("\\", "/")
    except ValueError:
        shutil.copytree(fonts_dir(), work / "fonts", dirs_exist_ok=True)
        fdir = "fonts"
    src = f"color=c={{c}}:s={width}x{height}:r={fps}:d={duration:.3f},format=rgb24,subtitles=layer.ass:fontsdir='{fdir}',format=gbrp"
    graph = ";".join([
        src.format(c="black") + ",split=2[b1][b2]",
        src.format(c="white") + "[w]",
        "[w][b1]blend=all_expr='255-(A-B)',split=2[a3][a3b]",
        "[a3]extractplanes=g[a]",
        "[b2][a3b]lut2=c0='if(gt(y,0),min(255,x*255/y),0)':c1='if(gt(y,0),min(255,x*255/y),0)'"
        ":c2='if(gt(y,0),min(255,x*255/y),0)'[un]",
        "[un][a]alphamerge,format=yuva444p10le[out]",
    ])
    write_text(work / "layer.fg", graph)
    run([ffmpeg(), "-y", "-v", "error", "-/filter_complex", "layer.fg", "-map", "[out]", "-c:v", "prores_ks", "-profile:v", "4",
         "-pix_fmt", "yuva444p10le", "-vendor", "apl0", str(out.resolve())], cwd=work, timeout=7200)
    shutil.rmtree(work, ignore_errors=True)
    return out


# ------------------------------------------------------------------ the package

def build(proj: Project, target: str = "resolve", *, out_dir: str | Path | None = None, collect: bool = False,
          stems: bool = True, graphics: bool = True, styled_captions: bool = True) -> dict:
    """Write the hand-off package for `target` (resolve | fcp | premiere | kdenlive | shotcut | otio | edl | nle)."""
    if target not in TARGETS:
        raise VeditError(f"Unknown hand-off target '{target}'. Use one of: {', '.join(TARGETS)}")
    from ..knobs import bake
    t0 = time.time()
    edit = proj.edit()
    e = bake(edit.layout()).active()
    out = Path(out_dir) if out_dir else proj.sub("handoff") / target
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    warnings: list[str] = []

    missing = [o.id for o in e.overlays if o.mg and (not o.path or not Path(o.path).exists())]
    if missing:
        raise VeditError(f"Overlays not rendered yet: {missing}. Run `vedit mg render {proj.root}` first.")

    # graphics: ProRes 4444 for every overlay that is a moving render; stills stay PNG
    ov_files: dict[str, str] = {}
    gdir = out / "graphics"
    if graphics and e.overlays:
        gdir.mkdir(exist_ok=True)
        for ov in e.overlays:
            src = (ov.renders or {}).get(".mov") or ov.path
            if not src or not Path(src).exists():
                continue
            info = probe(src)
            if info.kind == "image" or info.duration <= 0:
                dst = gdir / f"{ov.id}{Path(src).suffix}"
                shutil.copy(src, dst)
            elif str(src).lower().endswith(".mov") and info.vcodec == "prores":
                dst = gdir / f"{ov.id}.mov"
                shutil.copy(src, dst)
            else:
                dst = to_prores(src, gdir / f"{ov.id}.mov")
            ov_files[ov.id] = str(dst)
    layers: dict[str, str] = {}
    if graphics and styled_captions:
        chunks = (e.captions.chunks or caps.build_chunks(e)) if e.captions.enabled else []
        work = proj.sub("render") / "work"
        if chunks:
            style = caps.resolve_style(e.captions.style, e.captions.overrides)
            ass = caps.to_ass(e, chunks, work / "captions_handoff.ass", style)
            gdir.mkdir(exist_ok=True)
            layers["captions"] = str(ass_alpha_layer(ass, gdir / "captions_styled.mov", width=e.canvas.width,
                                                     height=e.canvas.height, fps=e.canvas.fps, duration=e.duration))
        titles = caps.titles_to_ass(e, work / "titles_handoff.ass")
        if titles:
            gdir.mkdir(exist_ok=True)
            layers["titles"] = str(ass_alpha_layer(titles, gdir / "titles.mov", width=e.canvas.width,
                                                   height=e.canvas.height, fps=e.canvas.fps, duration=e.duration))

    lut_path = grade_lut(e.color.preset, e.color.lut, e.color.intensity, out / "look.cube")
    if lut_path:
        files["lut"] = str(lut_path)
    suggestions = read_json(proj.root / "suggestions.json", default=[]) or []
    if isinstance(suggestions, dict):
        suggestions = suggestions.get("items", [])
    h = flatten(edit, overlay_files=ov_files, graphics=layers, lut=str(lut_path) if lut_path else None,
                suggestions=suggestions)

    if collect:
        h = _collect(h, out / "media")
    if h.captions:
        srt = caps.to_srt([caps.CaptionChunk(**c) for c in h.captions], out / "captions.srt")
        files["srt"] = str(srt)
    if stems:
        from ..render import render_stems
        files.update({f"stem_{k}": v for k, v in render_stems(edit, out / "stems", work_dir=proj.sub("render") / "work",
                                                               project_root=proj.root).items()})
    ref = proj.root / "render" / f"{e.name}.mp4"
    if ref.exists():
        files["reference"] = str(ref)

    for fmt in TARGETS[target]:
        path = write_timeline(h, out / f"{e.name}", fmt)
        files[fmt] = str(path)
    if "fcpxml" in TARGETS[target]:
        from .otio import validate_fcpxml
        v = validate_fcpxml(files["fcpxml"]) if _otio_ready() else {"valid": None}
        if v.get("valid") is False:
            warnings += [f"FCPXML DTD: {x}" for x in v.get("errors", [])[:5]]

    files["readme"] = str(write_text(out / "README.md", readme(h, target, files, e.color.preset)))
    manifest = {"target": target, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "edit_revision": edit.revision,
                "files": files, "handoff": h.to_dict(), "warnings": warnings}
    write_json(out / "handoff.json", manifest)
    meta = proj.meta()
    meta.setdefault("handoffs", {})[target] = {"dir": str(out), "at": manifest["created"], "revision": edit.revision}
    proj.save_meta(meta)
    proj.log(f"hand-off package for {target} -> {out}")
    return {"dir": str(out), "target": target, "files": files, "summary": summary(h), "notes": h.notes,
            "warnings": warnings, "seconds": round(time.time() - t0, 1)}


def _otio_ready() -> bool:
    from ..addons import tool_python
    return tool_python("otio") is not None


def write_timeline(h: Handoff, stem: Path, fmt: str) -> Path:
    if fmt == "fcpxml":
        from .fcpxml import write
        return write(h, stem.with_suffix(".fcpxml"))
    if fmt == "mlt":
        from .mlt import write
        return write(h, stem.with_suffix(".mlt"))
    from .otio import ADAPTERS, write
    return write(h, stem.with_suffix(ADAPTERS[fmt][1]), fmt)


def _collect(h: Handoff, media: Path) -> Handoff:
    """Copy every referenced file next to the timelines (portable package) and point the timeline there."""
    media.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    for t in h.tracks:
        for it in t.items:
            src = it.path
            if src not in mapping:
                dst = media / Path(src).name
                n = 2
                while dst.exists() and dst.stat().st_size != Path(src).stat().st_size:
                    dst = media / f"{Path(src).stem}_{n}{Path(src).suffix}"
                    n += 1
                if not dst.exists():
                    shutil.copy2(src, dst)
                mapping[src] = str(dst.resolve())
            it.path = mapping[src]
    return h


def readme(h: Handoff, target: str, files: dict[str, str], preset: str | None) -> str:
    def rel(key: str) -> str:
        return Path(files[key]).name if key in files else ""

    steps = {
        "resolve": [
            "DaVinci Resolve (free or Studio): File > Import > Timeline... and pick "
            f"`{rel('fcpxml')}`. Leave 'Automatically import source clips into media pool' on.",
            "If clips come in offline: right-click them in the Media Pool > Relink Selected Clips, point at the footage.",
            "Grade: Color page > right-click the timeline's node > LUTs > pick `look.cube` (copy it into Resolve's LUT "
            "folder first: Project Settings > Color Management > Open LUT Folder, then Update Lists).",
            "Captions: File > Import > Subtitle... `captions.srt` and drag it to the timeline, or keep the styled layer "
            "`graphics/captions_styled.mov` that is already on its own track.",
            "Mix: the stems in `stems/` are the vedit mix before mastering (music already ducked). Mute the "
            "timeline's music/SFX tracks and use the stems, or rebuild the mix on the Fairlight page.",
        ],
        "fcp": [
            f"Final Cut Pro: File > Import > XML... and pick `{rel('fcpxml')}` (a new event with the project).",
            "Grade: add the Custom LUT effect to an adjustment layer and choose `look.cube`.",
            "Captions: File > Import > Captions... `captions.srt`, or keep the styled layer on its lane.",
        ],
        "premiere": [
            f"Premiere Pro: File > Import... `{rel('xml')}` (Final Cut Pro XML). A sequence and a bin appear.",
            "Grade: Lumetri Color > Creative > Look > Browse... `look.cube` on an adjustment layer.",
            "Captions: File > Import `captions.srt`, drag it onto the sequence, or keep the styled layer.",
        ],
        "kdenlive": [f"Kdenlive: File > Open... `{rel('kdenlive')}` (or Project > Import OpenTimelineIO for the .otio).",
                     "Grade: add the 'Apply LUT' effect with `look.cube` to the top track."],
        "shotcut": [f"Shotcut: File > Open File... `{rel('mlt')}`.",
                    "Grade: add the 'LUT (3D)' filter with `look.cube` to the output (Timeline > Output)."],
        "otio": [f"`{rel('otio')}` opens in any OpenTimelineIO tool (Resolve 18.5+: File > Import > Timeline; "
                 "Kdenlive; Raven; otioview)."],
        "edl": [f"`{rel('edl')}` is the main cut only (CMX 3600, one video track): import it in any editor and relink "
                "to the footage; the full file names are in the comments."],
    }
    steps["nle"] = [s for k in ("resolve", "premiere", "fcp", "kdenlive", "shotcut") for s in steps[k][:1]]
    lines = [f"# {h.name}: hand-off for {target}", "",
             f"{h.width}x{h.height} at {h.fps:g} fps, {h.duration:.2f} s. Made by vedit "
             f"({time.strftime('%Y-%m-%d %H:%M')}).", "", "## Import", ""]
    lines += [f"{i}. {s}" for i, s in enumerate(steps[target], 1)]
    lines += ["", "## Tracks", ""]
    for t in h.tracks:
        lines.append(f"- **{t.name}**: {len(t.items)} clip(s)")
    if h.markers:
        lines += ["", "## Markers (notes from vedit)", ""]
        lines += [f"- {m.t:7.2f}s  {m.name}" + (f": {m.note}" if m.note else "") for m in h.markers]
    extra = list(h.notes)
    sp = spatial_parts(preset)
    if sp:
        extra.append("not in the LUT (spatial, rebuild if you want them): " + ", ".join(x.split("=")[0] for x in sp))
    if extra:
        lines += ["", "## Did not translate 1:1", ""] + [f"- {n}" for n in extra]
    lines += ["", "## Files", ""] + [f"- `{Path(v).name}`: {k}" for k, v in files.items() if k != "readme"]
    lines += ["", "When you have changed the edit, export the timeline again (FCPXML, XML, OTIO or EDL) and run "
              "`vedit handoff diff <project> <exported file>`: vedit learns from your changes and can pull trimmed "
              "cuts back in (`--apply-cuts`).", ""]
    return "\n".join(lines)
