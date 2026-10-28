"""FFmpeg renderer: edit.json -> final.mp4 (or a fast preview).

Stage 1  assemble the main track: one cached intermediate per clip (fit/crop/zoom/speed/grade, 20 ms
         audio fades so cuts never pop), joined by stream copy, or by xfade/acrossfade built from
         source handles so transitions never change the timing.
Stage 2  compose: b-roll, overlays (alpha video / images), effects, captions (ASS via libass, Bangla
         shaped by HarfBuzz), global grade, then the audio mix: voice chain, music ducked under speech
         with sidechain compression, SFX, loudness normalisation to the platform target.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import captions as caps
from . import config
from .media import ffmpeg, pick_video_encoder, probe, video_encoder_args
from .paths import fonts_dir
from .timeline import Clip, Edit, Overlay
from .util import VeditError, run, short_hash, write_text

GRADES: dict[str, str] = {
    "warm_cinematic": "eq=contrast=1.06:saturation=1.08:gamma=0.98,colorbalance=rs=0.04:gs=0.01:bs=-0.05:rm=0.03:bm=-0.03:rh=0.02:bh=-0.04",
    "moody": "eq=contrast=1.12:saturation=0.80:brightness=-0.03,colorbalance=bs=0.06:bm=0.03:rh=0.03,vignette=PI/5",
    "clean": "eq=contrast=1.04:saturation=1.05:brightness=0.01,unsharp=5:5:0.35",
    "teal_orange": "colorbalance=rs=-0.06:bs=0.08:rh=0.08:bh=-0.08,eq=saturation=1.1:contrast=1.06",
    "bw": "hue=s=0,eq=contrast=1.15",
    "vintage": "curves=preset=vintage,noise=alls=5:allf=t",
    "pastel": "eq=saturation=0.85:brightness=0.04:contrast=0.95,colorbalance=rh=0.03:bh=0.02",
    "vibrant": "eq=saturation=1.25:contrast=1.08",
    "cool": "colorbalance=bs=0.06:bm=0.04:rs=-0.03,eq=saturation=0.95",
    "golden": "colorbalance=rs=0.06:gs=0.03:bs=-0.06:rm=0.05:gm=0.02:bm=-0.05,eq=saturation=1.1",
    "matte": "curves=all='0/0.06 0.5/0.5 1/0.94',eq=saturation=0.92",
    "punchy": "eq=contrast=1.14:saturation=1.15,unsharp=5:5:0.5",
}

XFADE_NAMES = {"dissolve": "fade", "crossfade": "fade", "fade": "fade", "fade_black": "fadeblack", "flash": "fadewhite",
               "white_flash": "fadewhite", "slide_left": "slideleft", "slide_right": "slideright", "slide_up": "slideup",
               "slide_down": "slidedown", "wipe": "wipeleft", "zoom_in": "zoomin", "push": "smoothleft",
               "circle": "circleopen", "blur": "hblur", "glitch": "pixelize", "spin": "radial"}


class RenderSettings:
    def __init__(self, edit: Edit, preview: bool):
        cfg = config.load()["render"]
        self.preview = preview
        self.W, self.H = edit.canvas.width, edit.canvas.height
        if preview:
            scale = 540 / min(self.W, self.H)
            self.W, self.H = int(self.W * scale) // 2 * 2, int(self.H * scale) // 2 * 2
        self.fps = edit.canvas.fps
        self.encoder = "libx264" if preview else pick_video_encoder(edit.output.encoder or cfg["encoder"])
        self.crf = 30 if preview else (edit.output.crf or cfg["crf"])
        self.preset = "ultrafast" if preview else (edit.output.preset or cfg["preset"])
        self.lufs = edit.output.audio.target_lufs or cfg["target_lufs"]
        self.abitrate = cfg["audio_bitrate"]

    def inter_args(self) -> list[str]:
        """Intermediate segments: identical params so the concat demuxer can stream-copy them."""
        if self.preview or self.encoder == "libx264":
            v = ["-c:v", "libx264", "-preset", "ultrafast" if self.preview else "veryfast", "-crf", "28" if self.preview else "16",
                 "-pix_fmt", "yuv420p"]
        else:
            v = video_encoder_args(self.encoder, crf=max(12, self.crf - 4))
        return v + ["-g", str(int(self.fps * 2)), "-r", f"{self.fps}", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2"]


# ------------------------------------------------------------------ helpers

def _ease_expr(p: str, ease: str) -> str:
    if ease == "in":
        return f"({p})*({p})"
    if ease == "out":
        return f"(1-(1-({p}))*(1-({p})))"
    if ease == "inout":
        return f"(({p})*({p})*(3-2*({p})))"
    if ease == "hold":
        return "1"
    return f"({p})"


def _piecewise(keys: list[tuple[float, float]], var: str = "t") -> str:
    """Piecewise-linear expression through (time, value) keys."""
    if not keys:
        return "0"
    keys = sorted(keys)
    expr = f"{keys[-1][1]:.5f}"
    for (t0, v0), (t1, v1) in reversed(list(zip(keys, keys[1:]))):
        span = max(t1 - t0, 1e-3)
        seg = f"({v0:.5f}+({v1 - v0:.5f})*({var}-{t0:.4f})/{span:.4f})"
        expr = f"if(lt({var},{t1:.4f}),{seg},{expr})"
    return f"if(lt({var},{keys[0][0]:.4f}),{keys[0][1]:.5f},{expr})"


def _fit_chain(info_w: int, info_h: int, W: int, H: int, fit: str, *, bg: str = "blur", tag: str = "f") -> tuple[str, bool]:
    """Filter chain mapping a source frame to the canvas. Returns (chain, uses_split).

    `tag` keeps the internal labels unique when several chains share one filtergraph.
    """
    if fit == "stretch":
        return f"scale={W}:{H},setsar=1", False
    if fit == "contain":
        if bg == "blur":
            return (f"split=2[{tag}fg][{tag}bg];[{tag}bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                    f"gblur=sigma=40,eq=brightness=-0.08[{tag}bgb];[{tag}fg]scale={W}:{H}:force_original_aspect_ratio=decrease[{tag}fgs];"
                    f"[{tag}bgb][{tag}fgs]overlay=(W-w)/2:(H-h)/2,setsar=1"), True
        return f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1", False
    return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1", False


def _atempo(speed: float) -> str:
    parts = []
    s = speed
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.5f}")
    return ",".join(parts)


def _filter_arg(graph_file: Path) -> list[str]:
    return ["-/filter_complex", str(graph_file)]


def _grade_chain(name: str | None, lut: str | None, intensity: float, work: Path) -> str:
    chain = []
    if name:
        if name not in GRADES:
            raise VeditError(f"Unknown grade '{name}'. Available: {', '.join(GRADES)}")
        chain.append(GRADES[name])
    if lut:
        local = work / ("lut_" + short_hash(lut) + Path(lut).suffix)
        if not local.exists():
            shutil.copy(lut, local)
        chain.append(f"lut3d=file={local.name}")
    if not chain:
        return ""
    graded = ",".join(chain)
    if intensity >= 0.999:
        return graded
    return f"split=2[g0][g1];[g1]{graded}[g2];[g0][g2]blend=all_mode=normal:all_opacity={intensity:.3f}"


# ------------------------------------------------------------------ stage 1

def _clip_segment(edit: Edit, clip: Clip, s: RenderSettings, work: Path, *, head: float = 0.0, tail: float = 0.0) -> Path:
    """Render one main-track clip (plus optional transition handles) to an intermediate file."""
    src = edit.sources[clip.source]
    info = probe(src.path)
    W, H, fps = s.W, s.H, s.fps
    head = min(head, clip.src_in) if src.kind != "image" else head
    tail = min(tail, max(0.0, info.duration - clip.src_out)) if src.kind != "image" else tail
    src_in, src_out = clip.src_in - head, clip.src_out + tail
    dur_src = src_out - src_in
    out_dur = dur_src / clip.speed
    key = short_hash(clip.model_dump(mode="json"), head, tail, W, H, fps, s.preview, s.encoder, edit.color.model_dump(),
                     src.path, os.path.getmtime(src.path))
    out = work / f"seg_{key}.mp4"
    if out.exists() and out.stat().st_size > 0:
        return out

    args = [ffmpeg(), "-y", "-v", "error", "-nostdin"]
    if src.kind == "image":
        args += ["-loop", "1", "-framerate", f"{fps}", "-t", f"{out_dur:.4f}", "-i", src.path]
    else:
        args += ["-ss", f"{src_in:.4f}", "-t", f"{dur_src:.4f}", "-i", src.path]
    has_audio = src.kind != "image" and info.has_audio and not clip.mute
    if not has_audio:
        args += ["-f", "lavfi", "-t", f"{out_dur:.4f}", "-i", "anullsrc=r=48000:cl=stereo"]

    iw, ih = info.display_size
    v = [f"[0:v]setpts=(PTS-STARTPTS)/{clip.speed:.5f},fps={fps}"]
    if clip.crop:
        # Auto-reframe: moving crop window with the canvas aspect, then scale to the canvas.
        cw_expr = f"min(iw,ih*{W}/{H})"
        ch_expr = f"min(ih,iw*{H}/{W})"
        keys_x = [(k.t, k.cx) for k in clip.crop]
        keys_y = [(k.t, k.cy) for k in clip.crop]
        v.append(f"crop=w='{cw_expr}':h='{ch_expr}':x='max(0,min(iw-ow,({_piecewise(keys_x)})*iw-ow/2))'"
                 f":y='max(0,min(ih-oh,({_piecewise(keys_y)})*ih-oh/2))'")
        v.append(f"scale={W}:{H},setsar=1")
    else:
        chain, _ = _fit_chain(iw, ih, W * (2 if clip.zoom else 1), H * (2 if clip.zoom else 1), clip.fit)
        v.append(chain)
    if clip.zoom:
        z = clip.zoom
        D = max(out_dur, 1e-3)
        prog = _ease_expr(f"min(1,max(0,t/{D:.4f}))", z.ease)
        zexpr = f"({z.start_scale:.4f}+({z.end_scale - z.start_scale:.4f})*{prog})"
        W2, H2 = (W * 2, H * 2) if not clip.crop else (W, H)
        ax, ay = z.anchor_x, z.anchor_y
        v.append(f"scale=w='trunc({W2}*{zexpr}/2)*2':h='trunc({H2}*{zexpr}/2)*2':eval=frame")
        v.append(f"crop={W2}:{H2}:x='(iw-{W2})/2*(1+{ax:.3f})':y='(ih-{H2})/2*(1-{ay:.3f})'")
        if W2 != W:
            v.append(f"scale={W}:{H}")
    t = clip.transform
    if abs(t.scale - 1) > 1e-3 or abs(t.x) > 1e-3 or abs(t.y) > 1e-3 or abs(t.rotation) > 1e-3:
        sw, sh = int(W * t.scale) // 2 * 2, int(H * t.scale) // 2 * 2
        rot = f",rotate={t.rotation}*PI/180:c=none:ow=rotw({t.rotation}*PI/180):oh=roth({t.rotation}*PI/180)" if t.rotation else ""
        v.append(f"scale={sw}:{sh},format=rgba{rot}[fgt];color=c={edit.canvas.background}:s={W}x{H}:r={fps}[bgt];"
                 f"[bgt][fgt]overlay=x='(W-w)/2+{t.x:.4f}*W/2':y='(H-h)/2-{t.y:.4f}*H/2':shortest=1")
    grade = _grade_chain(clip.color, None, 1.0, work) if clip.color else ""
    if grade:
        v.append(grade)
    if clip.fade_in:
        v.append(f"fade=t=in:st=0:d={clip.fade_in:.3f}")
    if clip.fade_out:
        v.append(f"fade=t=out:st={max(0, out_dur - clip.fade_out):.3f}:d={clip.fade_out:.3f}")
    v.append("format=yuv420p")
    vgraph = ",".join(v) + "[vout]"

    a_in = "[0:a]" if has_audio else "[1:a]"
    a = [f"{a_in}asetpts=PTS-STARTPTS", "aresample=48000", "aformat=channel_layouts=stereo"]
    if has_audio and abs(clip.speed - 1) > 1e-3:
        a.append(_atempo(clip.speed))
    if has_audio and abs(clip.volume - 1) > 1e-3:
        a.append(f"volume={clip.volume:.3f}")
    fin = max(0.02, clip.audio_fade_in) if head == 0 else 0
    fout = max(0.02, clip.audio_fade_out) if tail == 0 else 0
    if fin:
        a.append(f"afade=t=in:st=0:d={fin:.3f}")
    if fout:
        a.append(f"afade=t=out:st={max(0, out_dur - fout):.3f}:d={fout:.3f}")
    a.append(f"atrim=0:{out_dur:.4f}")
    agraph = ",".join(a) + "[aout]"
    graph_file = work / f"seg_{key}.fg"
    write_text(graph_file, vgraph + ";" + agraph)
    args += _filter_arg(graph_file) + ["-map", "[vout]", "-map", "[aout]", "-t", f"{out_dur:.4f}"] + s.inter_args() + [str(out)]
    run(args)
    return out


def assemble_main(edit: Edit, s: RenderSettings, work: Path) -> Path:
    if not edit.main:
        raise VeditError("The main track is empty; add clips to edit.json (see `vedit plan apply`).")
    clips = edit.main
    handles = []
    for i, clip in enumerate(clips):
        head = clips[i].transition_in.duration / 2 if (i > 0 and clips[i].transition_in) else 0.0
        tail = clips[i + 1].transition_in.duration / 2 if (i + 1 < len(clips) and clips[i + 1].transition_in) else 0.0
        handles.append((head, tail))
    segs = [_clip_segment(edit, c, s, work, head=h, tail=t) for c, (h, t) in zip(clips, handles)]

    # Group hard-cut runs, stream-copy each run, then xfade between runs.
    runs: list[list[int]] = [[0]]
    for i in range(1, len(clips)):
        if clips[i].transition_in:
            runs.append([i])
        else:
            runs[-1].append(i)
    run_files = []
    for r in runs:
        if len(r) == 1:
            run_files.append(segs[r[0]])
            continue
        lst = work / f"run_{short_hash([str(segs[i]) for i in r])}.txt"
        write_text(lst, "".join(f"file '{segs[i].name}'\n" for i in r))
        out = lst.with_suffix(".mp4")
        if not out.exists():
            run([ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", out.name], cwd=work)
        run_files.append(out)
    if len(run_files) == 1:
        return run_files[0]

    out = work / f"aroll_{short_hash([str(p) for p in run_files])}.mp4"
    if out.exists():
        return out
    args = [ffmpeg(), "-y", "-v", "error", "-nostdin"]
    for f in run_files:
        args += ["-i", f.name]
    parts = []
    cur_v, cur_a = "[0:v]", "[0:a]"
    acc = probe(work / run_files[0].name).duration
    for k in range(1, len(run_files)):
        first_clip = clips[runs[k][0]]
        tr = first_clip.transition_in
        d = tr.duration
        offset = max(0.0, acc - d)
        name = XFADE_NAMES.get(tr.type, tr.type)
        parts.append(f"{cur_v}[{k}:v]xfade=transition={name}:duration={d:.3f}:offset={offset:.4f}[v{k}]")
        parts.append(f"{cur_a}[{k}:a]acrossfade=d={d:.3f}:c1=tri:c2=tri[a{k}]")
        cur_v, cur_a = f"[v{k}]", f"[a{k}]"
        acc = acc + probe(work / run_files[k].name).duration - d
    graph_file = work / "aroll.fg"
    write_text(graph_file, ";".join(parts))
    args += ["-/filter_complex", graph_file.name, "-map", cur_v, "-map", cur_a] + s.inter_args() + [out.name]
    run(args, cwd=work)
    return out


# ------------------------------------------------------------------ stage 2

def _overlay_xy(ov_w: str, ov_h: str, x: float, y: float) -> tuple[str, str]:
    return f"(W-{ov_w})/2+{x:.4f}*W/2", f"(H-{ov_h})/2-{y:.4f}*H/2"


def _effect_filters(edit: Edit, s: RenderSettings) -> list[str]:
    out = []
    for fx in edit.effects:
        kind = (fx.render or "").lower()
        a, b = fx.start, fx.start + fx.duration
        en = f"between(t,{a:.3f},{b:.3f})"
        k = fx.intensity
        if kind == "vignette":
            out.append(f"vignette=angle={0.6 * k:.3f}:enable='{en}'")
        elif kind == "film_grain":
            out.append(f"noise=alls={int(12 * k)}:allf=t:enable='{en}'")
        elif kind == "blur":
            out.append(f"gblur=sigma={8 * k:.1f}:enable='{en}'")
        elif kind == "bw":
            out.append(f"hue=s=0:enable='{en}'")
        elif kind in ("glitch", "rgb_split"):
            out.append(f"rgbashift=rh={int(8 * k)}:bh={-int(8 * k)}:enable='{en}'")
            if kind == "glitch":
                out.append(f"noise=alls={int(25 * k)}:allf=t+u:enable='{en}'")
        elif kind == "shake":
            amp = int(18 * k)
            out.append(f"crop=iw-{2 * amp}:ih-{2 * amp}:x='{amp}+if({en},{amp}*sin(t*61),0)':y='{amp}+if({en},{amp}*cos(t*47),0)',"
                       f"scale={s.W}:{s.H}")
        elif kind == "zoom_pulse":
            z = f"(1+{0.08 * k:.3f}*if({en},sin(PI*(t-{a:.3f})/{max(fx.duration, 0.01):.3f}),0))"
            out.append(f"scale=w='trunc({s.W}*{z}/2)*2':h='trunc({s.H}*{z}/2)*2':eval=frame,crop={s.W}:{s.H}")
        elif kind == "flash":
            out.append(f"eq=brightness='if({en},{0.6 * k:.2f}*(1-(t-{a:.3f})/{max(fx.duration, 0.01):.3f}),0)':eval=frame")
    return out


def compose(edit: Edit, aroll: Path, s: RenderSettings, work: Path, out: Path, ass_path: Path | None,
            titles_path: Path | None = None, hooks: dict[str, list[str]] | None = None) -> Path:
    W, H, fps = s.W, s.H, s.fps
    hooks = hooks or {}
    args = [ffmpeg(), "-y", "-v", "error", "-stats", "-nostdin", "-i", str(aroll)]
    n_in = 1
    v_parts: list[str] = []
    a_parts: list[str] = []
    grade = _grade_chain(edit.color.preset, edit.color.lut, edit.color.intensity, work)
    pre = ",".join(x for x in [grade, *hooks.get("video_pre_overlays", [])] if x)
    base = "[0:v]" + (pre if pre else "null")
    v_parts.append(base + "[base0]")
    cur = "[base0]"

    # b-roll (full-frame or transformed), audio muted
    for i, clip in enumerate(edit.broll):
        if clip.start is None:
            continue
        src = edit.sources[clip.source]
        info = probe(src.path)
        if src.kind == "image":
            args += ["-loop", "1", "-framerate", f"{fps}", "-t", f"{clip.duration:.3f}", "-i", src.path]
        else:
            args += ["-ss", f"{clip.src_in:.3f}", "-t", f"{clip.src_out - clip.src_in:.3f}", "-i", src.path]
        idx = n_in
        n_in += 1
        iw, ih = info.display_size
        chain, _ = _fit_chain(iw, ih, W, H, clip.fit, tag=f"b{i}")
        body = f"[{idx}:v]setpts=(PTS-STARTPTS)/{clip.speed:.4f},fps={fps},{chain}"
        if clip.zoom:
            z = clip.zoom
            D = max(clip.duration, 1e-3)
            prog = _ease_expr(f"min(1,max(0,t/{D:.4f}))", z.ease)
            zexpr = f"({z.start_scale:.4f}+({z.end_scale - z.start_scale:.4f})*{prog})"
            body += f",scale=w='trunc({W}*{zexpr}/2)*2':h='trunc({H}*{zexpr}/2)*2':eval=frame,crop={W}:{H}"
        t = clip.transform
        if abs(t.scale - 1) > 1e-3:
            body += f",scale=trunc(iw*{t.scale:.4f}/2)*2:-2"
        fade = ""
        if clip.fade_in:
            fade += f",fade=t=in:st=0:d={clip.fade_in:.3f}:alpha=1"
        if clip.fade_out:
            fade += f",fade=t=out:st={max(0, clip.duration - clip.fade_out):.3f}:d={clip.fade_out:.3f}:alpha=1"
        body += f",format=yuva420p{fade},setpts=PTS+{clip.start:.4f}/TB[br{i}]"
        v_parts.append(body)
        x, y = _overlay_xy("w", "h", t.x, t.y)
        v_parts.append(f"{cur}[br{i}]overlay=x='{x}':y='{y}':eof_action=pass:enable='between(t,{clip.start:.3f},{clip.end:.3f})'[bb{i}]")
        cur = f"[bb{i}]"

    # motion graphics / image overlays, by layer
    for i, ov in enumerate(sorted(edit.overlays, key=lambda o: o.layer)):
        if not ov.path or not Path(ov.path).exists():
            raise VeditError(f"Overlay {ov.id} has no rendered file. Run `vedit mg render` first.")
        info = probe(ov.path)
        if info.kind == "image" or info.duration <= 0:
            args += ["-loop", "1", "-framerate", f"{fps}", "-t", f"{ov.duration:.3f}", "-i", ov.path]
        else:
            if ov.path.lower().endswith(".webm"):
                args += ["-c:v", "libvpx-vp9"]
            args += ["-t", f"{ov.duration:.3f}", "-i", ov.path]
        idx = n_in
        n_in += 1
        chain = f"[{idx}:v]setpts=PTS-STARTPTS,fps={fps},format=rgba"
        if ov.chroma:
            chain += f",colorkey={ov.chroma.replace('#', '0x')}:0.28:0.08"
        t = ov.transform
        if ov.fit in ("cover", "contain"):
            chain += f",scale={W}:{H}:force_original_aspect_ratio={'increase' if ov.fit == 'cover' else 'decrease'}"
        elif s.preview or abs(t.scale - 1) > 1e-3:
            factor = t.scale * (W / edit.canvas.width)
            chain += f",scale=trunc(iw*{factor:.4f}/2)*2:-2"
        if ov.fade_in:
            chain += f",fade=t=in:st=0:d={ov.fade_in:.3f}:alpha=1"
        if ov.fade_out:
            chain += f",fade=t=out:st={max(0, ov.duration - ov.fade_out):.3f}:d={ov.fade_out:.3f}:alpha=1"
        if t.opacity < 0.999:
            chain += f",colorchannelmixer=aa={t.opacity:.3f}"
        chain += f",setpts=PTS+{ov.start:.4f}/TB[ov{i}]"
        v_parts.append(chain)
        x, y = _overlay_xy("w", "h", t.x, t.y)
        v_parts.append(f"{cur}[ov{i}]overlay=x='{x}':y='{y}':eof_action=pass:format=auto:"
                       f"enable='between(t,{ov.start:.3f},{ov.start + ov.duration:.3f})'[oo{i}]")
        cur = f"[oo{i}]"

    fx = _effect_filters(edit, s)
    tail = list(hooks.get("video_pre_captions", [])) + list(fx)
    try:
        fdir = os.path.relpath(fonts_dir(), work).replace("\\", "/")
    except ValueError:  # footage on another drive than the skill: no relative path exists, copy the fonts
        local = work / "fonts"
        if not local.exists():
            shutil.copytree(fonts_dir(), local)
        fdir = "fonts"
    for sub in (titles_path, ass_path):
        if sub:
            tail.append(f"subtitles={sub.name}:fontsdir='{fdir}'")
    tail += list(hooks.get("video_post", []))
    tail.append(f"format=yuv420p")
    v_parts.append(f"{cur}{','.join(tail)}[vfinal]")

    # ---------------- audio
    au = edit.output.audio
    voice = ["highpass=f=70"]
    if au.denoise and not s.preview:
        voice.append("afftdn=nf=-28:tn=1")
    if au.voice_enhance and not s.preview:
        voice += ["equalizer=f=180:t=q:w=1:g=-1.5", "equalizer=f=3200:t=q:w=1.2:g=2.5",
                  "acompressor=threshold=0.09:ratio=3:attack=8:release=180:makeup=1.6", "deesser=i=0.35"]
    voice += list(hooks.get("audio_voice", []))
    a_parts.append(f"[0:a]{','.join(voice)}[voice]")
    music_labels, sfx_labels, vo_labels = [], [], []
    for i, clip in enumerate(edit.audio):
        src = edit.sources[clip.source]
        info = probe(src.path)
        src_out = clip.src_out if clip.src_out is not None else info.duration
        total = edit.duration
        if clip.loop:
            args += ["-stream_loop", "-1"]
        args += ["-ss", f"{clip.src_in:.3f}", "-i", src.path]
        idx = n_in
        n_in += 1
        length = (min(src_out - clip.src_in, max(0.1, total - clip.start)) if clip.role in ("music", "ambience") and not clip.loop
                  else (max(0.1, total - clip.start) if clip.loop else src_out - clip.src_in))
        chain = [f"[{idx}:a]atrim=0:{length:.3f}", "asetpts=PTS-STARTPTS", "aresample=48000",
                 "aformat=channel_layouts=stereo", f"volume={clip.volume:.3f}"]
        if clip.fade_in:
            chain.append(f"afade=t=in:st=0:d={clip.fade_in:.3f}")
        if clip.fade_out:
            chain.append(f"afade=t=out:st={max(0, length - clip.fade_out):.3f}:d={clip.fade_out:.3f}")
        delay = int(round(clip.start * 1000))
        chain.append(f"adelay={delay}|{delay}")
        label = f"au{i}"
        a_parts.append(",".join(chain) + f"[{label}]")
        (music_labels if clip.ducks else vo_labels if clip.role == "vo" else sfx_labels).append(label)

    speech = ["[voice]"] + [f"[{l}]" for l in vo_labels]
    if len(speech) > 1:
        a_parts.append("".join(speech) + f"amix=inputs={len(speech)}:normalize=0[speech]")
    else:
        a_parts.append("[voice]anull[speech]")
    mix_inputs = []
    if music_labels:
        a_parts.append("[speech]asplit=2[sp_mix][sp_key]")
        bed = "".join(f"[{l}]" for l in music_labels)
        if len(music_labels) > 1:
            a_parts.append(f"{bed}amix=inputs={len(music_labels)}:normalize=0[bed]")
        else:
            a_parts.append(f"{bed}anull[bed]")
        ratio = max(2.0, min(20.0, abs(au.duck_db) / 1.5))
        a_parts.append(f"[bed][sp_key]sidechaincompress=threshold=0.025:ratio={ratio:.1f}:attack=25:release=450:makeup=1[ducked]")
        mix_inputs += ["[sp_mix]", "[ducked]"]
    else:
        mix_inputs.append("[speech]")
    mix_inputs += [f"[{l}]" for l in sfx_labels]
    if len(mix_inputs) > 1:
        a_parts.append("".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:normalize=0:duration=first[mix]")
    else:
        a_parts.append(f"{mix_inputs[0]}anull[mix]")
    # limit 0.84 = -1.5 dBFS ceiling, so true peaks stay at the -1.5 dBTP platform target after loudnorm.
    master = "".join(f"{h}," for h in hooks.get("audio_master", []))
    a_parts.append(f"[mix]{master}loudnorm=I={s.lufs}:TP=-1.5:LRA=11,alimiter=limit=0.84:level=false,aresample=48000[afinal]")

    graph_file = work / "compose.fg"
    write_text(graph_file, ";\n".join(v_parts + a_parts))
    enc = video_encoder_args(s.encoder, crf=s.crf, preset=s.preset)
    args += ["-/filter_complex", graph_file.name, "-map", "[vfinal]", "-map", "[afinal]", "-t", f"{edit.duration:.4f}",
             "-r", f"{fps}"] + enc + ["-c:a", "aac", "-b:a", s.abitrate, "-movflags", "+faststart", str(out.resolve())]
    run(args, cwd=work, capture=True)
    return out


# ------------------------------------------------------------------ entry point

def render(edit: Edit, out: str | Path, *, preview: bool = False, work_dir: str | Path | None = None,
           burn_captions: bool = True, project_root: str | Path | None = None) -> dict:
    from .knobs import bake
    edit = bake(edit.layout()).active()
    hooks: dict[str, list[str]] = {}
    if edit.custom_fx and project_root:
        from .custom import materialize
        edit, hooks = materialize(edit, Path(project_root))
    s = RenderSettings(edit, preview)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(work_dir) if work_dir else out.parent / "work"
    work.mkdir(parents=True, exist_ok=True)
    ass_path = None
    if burn_captions and edit.captions.enabled:
        chunks = edit.captions.chunks or caps.build_chunks(edit)
        if chunks:
            style = caps.resolve_style(edit.captions.style, edit.captions.overrides)
            if preview:
                preview_edit = edit.model_copy(deep=True)
                preview_edit.canvas.width, preview_edit.canvas.height = s.W, s.H
                ass_path = caps.to_ass(preview_edit, chunks, work / "captions.ass", style)
            else:
                ass_path = caps.to_ass(edit, chunks, work / "captions.ass", style)
    titles_path = caps.titles_to_ass(edit, work / "titles.ass", canvas=(s.W, s.H))
    aroll = assemble_main(edit, s, work)
    compose(edit, aroll, s, work, out, ass_path, titles_path, hooks=hooks)
    info = probe(out)
    return {"output": str(out.resolve()), "duration": round(info.duration, 3), "width": info.width, "height": info.height,
            "encoder": s.encoder, "preview": preview}
