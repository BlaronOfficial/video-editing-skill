# video-editing-skill — Specification

Status: agreed with the owner on 2026-10-25 (6 rounds of Q&A). This file is the source of truth for
architecture decisions. Change it deliberately, not as a side effect.

## 1. Goal

A public Claude skill that turns raw footage into finished, professional videos with Claude Opus
doing the editing judgement and motion graphics, and CapCut as the editable hand-off. The skill
should do the best possible job on its own; Higgsfield is an optional power-up.

## 2. Decisions

| Area | Decision |
|---|---|
| Architecture | **Hybrid**: Claude renders `final.mp4` itself (FFmpeg + its own motion graphics) AND writes the same edit as an editable CapCut project. The MP4 never depends on CapCut working. |
| CapCut target | CapCut desktop (international). Verified build: 9.6.0.4097 (Windows). Plaintext drafts, nested `Timelines/` layout. Draft writes are seeded from a blank project created by the user's own CapCut (calibration), never from a shipped template. |
| CapCut Pro | Varies per project: per-project flag filters Pro-only resources. |
| Screen control | Support both Claude Code Desktop built-in computer use and Windows-MCP (CLI). Detect what the session has. |
| Formats | Short-form vertical, long-form YouTube, ads/client promos, faceless/animated. |
| Languages | English, Bangla, mixed (Banglish) — Bangla-capable fonts and shaping are mandatory. |
| Transcription | Ask per project: local Whisper (default offline engine) or ElevenLabs Scribe (optional, needs key). |
| Autonomy | Storyboard approval by default; "auto"/"batch" skips approval. |
| Motion graphics | All engines: HyperFrames (HTML/GSAP), Remotion (React), FFmpeg/Python (PIL), SVG. Claude picks per job or mixes. |
| Higgsfield | Optional. Uses: AI B-roll, images/stills, VFX/hero shots, faceless scenes. Always show a credit estimate and wait for approval before spending. |
| Pinterest | Via Claude in Chrome. Both modes: (1) ideas + private mood boards (default) and (3) download-and-use. Every downloaded asset is logged with its source URL (provenance log). Light, human-like browsing only. |
| Assets | Own library (indexed), CapCut built-in library (screen control), generated (Claude-made SVG/HTML/shader visuals, procedural SFX, Higgsfield). No stock APIs in v1. |
| Styles | Brand kits (multi-client), creator style cloning, named aesthetic presets, learn-from-my-edits (diff the user's CapCut changes). |
| Packaging | All of: Python CLI (primary), our own MCP server (same engine), screen-control recipes, optional VectCutAPI backend (the Atx-Guy idea with corrected parameter mapping). |
| Distribution | Public. `git clone` only. Updates via `git pull`. Personalisation lives in git-ignored `personal/` inside the skill folder; runtime never edits tracked files. |
| OS | Windows first; macOS later (keep OS-specific code behind one module). |
| Extras v1 | Long-to-shorts clipping, auto-reframe, thumbnails + post copy, AI voiceover / voice clone, plus everything in section 6. |
| Build | Everything at once; test with public Creative-Commons sample clips. |
| Licence | MIT for this repo. Remotion has its own licence (free for individuals / companies of 3 or fewer people) — documented, never bundled. |

## 3. Research facts that shaped the design (Oct 2026)

- CapCut has no official editing API or MCP. All community tools write draft files.
- CapCut 10.x reportedly rejects tool-written drafts; 8.7–9.3 accept drafts seeded from an
  app-created project. Installed 9.6.0.4097 writes plaintext JSON (`version` 360000,
  `new_version` "189.0.0") with root files mirrored in `Timelines/<timeline_id>/`
  (`draft_content.json`, `template-2.tmp`, `.bak`), plus `Timelines/project.json`
  (`main_timeline_id`) and the store index `root_meta_info.json`.
- Draft files embed `device_id` and `mac_address` → never ship drafts; calibrate per user.
- Atx-Guy/capcut-mcp-server: thin TS wrapper over VectCutAPI; wrong endpoint (`/add_keyframe` vs
  `/add_video_keyframe`) and wrong params (`effect_name`/`effect_type`, `sticker_url`/`sticker_id`,
  `srt_content`/`srt`; position/scale/animation/fade silently ignored). Not ported as-is.
- Claude Code CLI computer use is macOS-only; on Windows use Claude Code Desktop or Windows-MCP.
- Higgsfield for Claude Code: `npm i -g @higgsfield/cli` → `higgsfield auth login` →
  `npx skills add higgsfield-ai/skills`; hosted MCP `https://mcp.higgsfield.ai/mcp`. Uses plan
  credits; generated clips are silent, up to 15 s.
- CapCut alpha-video import support is build-dependent → probe once per install
  (ProRes 4444 / WebM alpha), fall back to green-screen + chroma key.
- Owner hardware: no CUDA. Local Whisper must run CPU int8; FFmpeg can use Intel QSV.

## 4. Pipeline

```
footage/ ─► probe ─► transcribe (whisper|scribe, word timestamps)
        ─► pack (takes_packed.md: phrases, pauses, fillers, retake hints)
        ─► Claude edit plan ─► edit.json (single source of truth: the timeline)
        ─► storyboard.html (frames + transcript + caption/MG/B-roll notes) ─► user approval
        ─► assets: motion graphics renders, B-roll, SFX, music, Higgsfield, Pinterest
        ─► render final.mp4 (FFmpeg)      ─► QA (frames at every cut, audio pops, loudness, safe zones)
        ─► CapCut project from edit.json  ─► open in CapCut (optional screen-control export)
        ─► learn-from-edits (diff user's CapCut changes → style profile)
```

## 5. Repository layout

```
SKILL.md              entry point (workflow + routing to references)
README.md             public install / update guide
references/           progressive-disclosure docs Claude loads on demand
scripts/vedit/        Python engine + CLI (`vedit ...`), uv-managed
mg/                   motion graphics engines and templates (hyperframes, remotion, html renderer)
presets/              shipped aesthetic presets (tracked)
templates/            storyboard HTML etc.
mcp/                  MCP server over the same engine
setup/                install / doctor / update scripts
personal/             GIT-IGNORED per-user data (config, brand kits, styles, learned prefs,
                      CapCut calibration, asset index, keys, project registry)
docs/                 this spec and design notes
```

## 6. Implementation status (2026-10-26)

Verified on the owner's machine (Windows 11, CapCut 9.6.0.4097):
- CapCut round trip: seed calibration → generated project (3 clips, transition, zoom keyframes,
  title, captions incl. Bangla, ducked music with fades) listed and opened in the CapCut 9.6 editor.
  Canvas ratio must be written explicitly ("original" follows the first clip).
- CapCut text size calibrated: `CAPCUT_TEXT_SIZE_PER_FRAC = 160` (105 rendered at ~0.66x).
- CapCut ignores WM_CLOSE in the editor; close uses Alt+F4 only after verifying CapCut owns the
  foreground (input guard: never type/click into the user's window).
- FFmpeg render: karaoke captions, Bangla shaping (libass/HarfBuzz), dissolve via handles, blurred
  contain background. `drawtext` without fontfile segfaults on the gyan build (fontconfig) → Pillow.
- MG renderer: frame-accurate capture with real alpha (ProRes 4444 / VP9 / green key). Parallel workers
  need one browser per worker (background tabs never produce frames) and no rAF waits.
- `mcp` 2.x renamed FastMCP → MCPServer (both supported).

End-to-end test (public-domain CDC interview, 4:43, 16:9 → 31 s 9:16 short): transcribe (whisper
base.en, 72 s) → pack → keeps → face-tracked reframe (YuNet) → captions → 7 graphics + 4 procedural
SFX → storyboard → render (h264_qsv, 62 s) → QA 0 issues (-13.9 LUFS, -1.15 dBTP) → CapCut project
(46 editable captions, 16 keyframes, 7 layers) → diff = no changes. Bugs found and fixed on the way:
faster-whisper/PyAV API drift (feed samples), OpenCV 5 dropped Haar (YuNet), overlays extending the
video length, captions past the end, source title cards/fades at cut boundaries (new QA check).

Open items:
- `vedit capcut probe-alpha` project created; visual verdict (prores/webm/chroma) pending user check.
- Bangla glyphs inside CapCut text (default font fallback) not yet visually confirmed.
- macOS paths prepared in `paths.py`; untested.

## 7. Feature inventory (v1)

Core editing: silence and filler removal, bad-take / retake selection, J/L cuts, 30 ms audio
crossfades at cuts, punch-in zooms, hook-first restructuring, pacing by style profile.
Captions: word-level animated captions (karaoke highlight, 1–3 word chunks, sentence mode), Bangla
shaping, emoji/keyword emphasis, SRT/VTT export, translation (bn⇄en).
Motion graphics: titles, lower thirds, kinetic typography, callouts/arrows, counters, lists,
quote cards, progress bars, CTAs/end screens, logo stings, charts, SVG illustrations, shaders.
Audio: denoise, loudness normalisation per platform, music ducking, beat detection, SFX design
(library + procedural whoosh/pop/riser/impact/click).
Visual: colour grade presets/LUTs, B-roll placement, background removal hooks, safe-zone checks.
Extras: long-to-shorts clipping, auto-reframe (face tracking), thumbnails, titles/descriptions/
hashtags, AI voiceover / voice clone (ElevenLabs), batch mode ("a week of reels"), multi-ratio
exports, chapters, multicam sync by audio.

## 8. v2 (agreed 2026-10-28, built in phases on branch `v2`)

Owner's direction: unlock the full potential of Opus 5.5 as director; dynamic and hybrid, not fixed
pipelines; standalone free core, everything paid or proprietary optional. Full plan:
`~/.claude/plans/lovely-crafting-pearl.md` (owner's machine).

| Area | Decision |
|---|---|
| Philosophy | Director layer: capability discovery, route planning, mixing, custom code, verify, learn |
| Modes | Plan (default, Studio first), Step-by-step (stage approvals), Auto; Execute needs approval |
| Studio | Claude Artifact only (one per owner, projects as db collections), live preview only, all edit tools, in-page Claude (`sample`), Send to Claude (comments), live link via `host:vedit` MCP in the Claude desktop app |
| Hand-offs | CapCut asked at intake; DaVinci (free import package, Studio live, screen control, learn), Premiere/FCP/any NLE, LosslessCut (phase 3) |
| Web AI | Owner's logged-in services (Gemini, ChatGPT, Canva, Firefly, Ideogram, ...) used opportunistically with provenance; never log in; ask before credits/bulk |
| VFX / 3D | Three.js, Blender (installed: 5.2), Fusion (Studio), Higgsfield; tracking, cutout, depth (phase 4, built 2026-11-04) |
| Sound / eyes | earshot full (kits + ears), claude-real-video watching, speakers, memory, link ingest (phase 2) |
| Writing pass | English only (from blader/humanizer MIT rules; humanizer-cli was a malware lure, not used) |
| Learning | Studio decisions, editor diffs, chat rules, route outcomes, YouTube analytics (phase 5, built 2026-11-04) |

### Phase 1 status (2026-10-28): standalone core, director layer, modes, Studio

Built: config v2 (+ migration), add-on registry, ask-first resumable model downloads (exit 3 =
needs_download), capability map (engine + session records + outcomes), route planner
(`presets/routes.json`), modes + approval gate (`vedit render` final refuses in plan/step until
approved), edit model v2 (anchors that follow re-cuts, enabled flags, CustomFX, knobs, revision,
word-keyed caption fixes/emphasis/emoji, `from_words`), knob baking (`bake()` used by render, QA,
CapCut, storyboard, Studio), the op language (`ops.py`, mirrored in `studio/js/ops.js`), suggestion
cards and creative directions, custom FX (python overlay/audio/source, ffmpeg hooks, html) + `fxkit`,
personal templates/FX/techniques, self-extension with vetting (`vedit tools vet/add`), personal
extensions, learning (events, profile, rules), Studio engine (proxies, sprites, peaks, docs, apply,
revert history), local Studio server, MCP live-link tools, the Studio web app.

Verified on the owner's machine:
- `tests/test_v2.py`: 22/22, including Python vs JS parity of ops + bake (clips, overlays, audio,
  duration, knobs, fixes, all 46 caption chunks).
- Headless Studio (`tests/studio_smoke.mjs` on `vedit studio-local`): loads, plays proxies with
  reframe keys, live karaoke captions and live template graphics, transcript cut applied through the
  engine (rev +1), pace knob shortens the edit, no horizontal scroll at phone width, clean console.
- Studio published as a private artifact; previews uploaded (mp4/jpg/json; the asset store rejects mp3,
  so audio previews are AAC .mp4); 8 db docs written atomically and read back.
- `vedit doctor` READY with CapCut optional; found Blender 5.2 installed.

### Phase 2 status (2026-10-31): senses and smart sourcing

Built: `sound.py` (earshot kits rendered in an isolated venv, built-in synth kit as the standalone
fallback, cue proposal from the edit, placement on sync points with role offsets, anchors, take rotation,
min gaps, levels against the music bed or the voice through numpy K-weighting, music stop-downs in the
renderer and the Studio, sync check through earshot's model-free detector, ears in QA when installed),
`earshot_bridge.py`, `watch.py` + `crv_bridge.py` (claude-real-video frames/dedup in place, timestamped
grids, native fallback, speaker diarization with ask-first models, multicam by speaker with audio sync,
footage memory in SQLite FTS5 trigram, link fetch with captions and provenance), Whisper no-speech gate,
`--engine subs` transcripts, `writing.py` (English writing pass + video text formats), `sources/`
(Openverse, Wikimedia, Pexels, Pixabay; licence flags; credits), `inbox.py` (Downloads pickup with
provenance and duplicate check; vtracer vectorize), routes updated, Studio "Pin sound" chooser by kit
role, references audio/sourcing/webai/watching/writing (pinterest.md folded into sourcing.md).

Verified on the owner's machine:
- `tests/test_phase2.py --render --net`: 26/26 (placement lands on cues, anchored effects follow a
  re-cut, Python == Studio JS stop-downs, preview render heard on its cues, subtitles, writing, licences,
  inbox, memory, multicam merge, Wikimedia search + download). `tests/test_v2.py` still 22/22.
- earshot launch/crisp kits render without torch (64-72 takes, ~2-4 min once, then cached); in a real
  render 5/6 effects answered within 40 ms (median 11 ms); the one buried pop is flagged by QA.
- Watching the 4:43 E2E source: 179 frames kept of 284, photo inserts and crossfades caught.
- Two-voice dialogue (Windows voices): 2 speakers, every line attributed correctly; multicam with a
  1.3 s offset angle synced exactly and the render transcribes back word for word.
- Headless Studio with kit sounds + music: loads, plays, clean console; Pin sound adds an anchored
  kit effect (rev +1).

Waiting on the owner: ears download (~1.3 GB), the logged-in browser probe + one Gemini image through the
inbox, Canva background removal on one image. Openverse's image API returned 504 for every client during
testing (their outage; audio search worked earlier the same day).

### Phase 3 status (2026-10-31): hand-offs

Built: `exports/` (one neutral hand-off timeline from edit.json: tracks without overlaps, zoom and
reframe paths as scale/position keyframes, loops laid end to end, markers for what a timeline cannot
hold), `fcpxml.py` (native FCPXML 1.10 + reader), `otio.py` + `otio_bridge.py` (OpenTimelineIO in an
isolated venv: .otio, FCP7 XML for Premiere, CMX EDL, Kdenlive; reads any of them back), `mlt.py`
(native Shotcut MLT + reader), `package.py` (ProRes 4444 graphics, styled caption/title layers with real
alpha by black/white difference matting, stems from the renderer's own mix chain, the grade as a 33-point
.cube through a Hald CLUT, SRT, README per editor, handoff.json), `diff.py` (learn from re-exports, median
head/tail trims, `--apply-cuts`), `resolve/` (Studio live import through the scripting API in a child
process, add-only with read-back; screen import for the free edition), `llc.py` (.llc with a JSON5 reader,
LosslessCut HTTP API on our own config dir), `lossless.py` (native smart cut: re-encoded head/tail, whole
GOPs copied via the segment muxer, exact piece durations, sample-exact audio; keyframe and accurate modes;
merge, split, chapters, selects; `render --lossless`), `cutlist.py` (csv, YouTube chapters, llc, srt and
the timeline formats, both ways), `Marker` in edit.json (anchored, chapters/to-dos), Execute writes the
hand-offs picked at intake (`vedit handoffs`).

Verified on the owner's machine (`tests/test_phase3.py --full --apps`: 38/38; test_v2 22/22, test_phase2
22/22 offline):
- FCPXML valid against Apple's FCPXML 1.10 DTD; storyline and connected clips read back to the frame.
- OTIO, Premiere XML, EDL and Kdenlive read back through OpenTimelineIO with the same cut.
- Model geometry vs the vedit render: SSIM 0.97. LUT vs the FFmpeg grade: SSIM 0.996, 1.5/255 mean diff.
- Stems sample-identical in length; styled caption layer composites exactly like the burned captions.
- Smart cut on H.264 with B-frames and a 3 s GOP: 397/397 frames, 45 % copied bit for bit, every frame
  SSIM >= 0.98 against the source (mean 0.997), even timestamps across joins.
- Shotcut 26.9.27's melt renders our MLT like vedit (framing, zoom path, graphics, LUT; SSIM 0.81-0.95
  above the captions between two different renderers). The first run caught a real bug (producer filter
  ranges), fixed.
- LosslessCut 3.70.2 opened our .llc, exported both named segments through its HTTP API, and its own
  re-saved .llc (JSON5) read back.
- Not testable here: DaVinci Resolve (not installed) and Premiere/Final Cut imports; marked untested.

### ffmpeg-skill port (agreed 2026-10-31, built 2026-11-01)

Hybrid port of kajisho5/ffmpeg-skill (MIT): HDR/Dolby Vision to SDR, Log detection, VFR guard and device
notes in probe/render; delivery presets, size targets, compliance checks, SSIM compare, repair in
QA/export; clean-up and time FX (stabilize, denoise, deinterlace, redact/delogo, straighten, cropdetect,
360 reframe, speed ramps, freeze, reverse, loop, smooth slow motion); audio (drift-corrected sync, gate,
compressor, limiter, widen, 5.1 downmix, speech-aware silence, filler removal); extras (grid,
audiogram/waveform, Ken Burns stills, batch with caching, HTML report); its working rules (fixed end-of-job
report, never overwrite originals, dry-run plans). Its gotchas and device notes go into references.

Built: `footage.py` (per-source analysis on project init: PQ/HLG/Dolby Vision, BT.2020 SDR, BT.601 matrix,
Log by signalstats, interlacing, frame timing by packets, black bars, device; one input chain used by
render segments, b-roll, Studio proxies and frozen frames: deinterlace, tone map (zscale, mobius, 100-nit
reference white), gamut/matrix conversion, camera LUT), renders tagged BT.709 in the filter graph;
`delivery.py` (platform table with specs and safe zones, PASS/WARN/FAIL checks split into format and
judgement rows, export presets with fit pad/crop/blur, measured two-pass loudnorm that never lifts
ambience, two-pass size targets, SSIM/PSNR compare, repair, safe-zone frames; QA checks
`output.platform`); `fx.py` (clip fields rendered at decode: redact, src_crop, 360 projection, two-pass
vidstab, denoise, reverse, smooth slow motion; edit operations for speed ramps and freeze frames;
one-off `vedit fix` tools that never overwrite); `audiotools.py` (multi-window drift-corrected sync with
a weighted line fit, recorder replacement by resampling, gate/compressor/limiter/widen in
`output.audio`, downmix, extract, speech-aware rough cut); `extras.py` (grid, audiogram/waveform, Ken
Burns stills, cached parallel batch, HTML report); smart cut falls back to accurate cuts on variable frame
rate and open-GOP streams; `render --dry-run`; the end-of-job report and never-overwrite rules in SKILL.md;
references footage, delivery, cleanup (+ audio, extras, workflow).

Verified (`tests/test_port.py`: 50/50; test_v2 22/22, test_phase2 --render 24/24, test_phase3 35/35):
- HDR -> SDR: tone-mapped PQ is 4x closer to the SDR original than the raw decode (mean diff 21 vs 95),
  HLG likewise; an HDR b-roll in a real render comes out saturated, not washed out. BT.601 sources match
  the original after conversion (2.3/255); renders carry BT.709 tags.
- Detection: PQ, HLG, Log-looking, interlaced, VFR, black bars, open-GOP HEVC all found; SDR stays clean.
- Stabilize: jitter on a shaken real shot 11.8 -> 6.8. Denoise on real grain: +0.8 / +3 dB (hqdn3d),
  +4-6 dB (nlmeans, slow). Redact, reverse, smooth (2x with new frames), loop, v360, straighten measured.
- Ramp/freeze/denoise/stabilize/HDR b-roll render together at the right length; `--dry-run` plans only.
- Delivery: reels export 1080x1920 passes every row at -14.0 LUFS; HDR delivered as BT.709 for X; a 30 s
  clip fits 2 MB by two-pass; an HDR 16:9 file fails Reels on colour and aspect; repair recovers a
  damaged recording; QA adds platform rows and a safe-zone frame.
- Sync: 200 ppm injected drift found as 188 ppm, start offset within 1 ms; the replaced recorder track
  lines up at both ends (1 ms, ~20 ppm residual). Speech-aware cuts land only on sentence ends or long
  pauses. Grid, audiogram, Ken Burns, cached batch (second run all cached), HTML report.

### Phase 4 status (2026-11-04): VFX and 3D

Built:
- **3D templates** (Three.js, `mg/lib/three-kit.js`): title_3d (extruded bevelled TTF glyphs for Latin,
  shaped "slab" text for Bangla and any script), logo_3d (SVG extruded in its own fills, PNG slab, name
  fallback), product_spin, device_mockup (phone/tablet/laptop, frame-exact video screens), particles
  (dust, bokeh, snow, stars, sparks, confetti; deterministic), camera_flythrough, chart_3d, globe. Same
  HTML in the renderer and the Studio (three.js from jsDelivr through an import map).
- **Blender** (`scripts/vedit/blender.py`, `blender/*.py`): title_3d, logo_3d, product_turntable; overlay
  `mg.engine: "blender"` and CustomFX `kind: "blender"`; RGBA PNG frames -> WebM alpha / ProRes 4444 /
  green key. Bangla refused (Blender does not shape it) with a pointer to the Three.js template.
- **VFX in source space** (`scripts/vedit/vfx/`): object tracking (optical flow + VitTrack hybrid),
  multi-face tracking (YuNet), planar tracking (RANSAC homography from the reference frame, re-seeded),
  screen suggestions, tracked redaction (mask layers), screen inserts (`screen[]`), overlays that follow a
  track (`attach`, per-frame sendcmd), person matting (MODNet + fast guided filter + motion-gated temporal
  smoothing) for `subject` (background blur/swap/darken, outline, glow, `above` = text behind the person
  via a framed RGBA subject layer), depth (Depth-Anything-V2-Small): 3D photo parallax, depth of field on
  stills and clips with auto focus on the face. Camera FX: whip / zoom-blur transitions, motion blur,
  handheld drift, whip effect. `vedit vfx ...` CLI, Studio clip controls (cut-out, text behind, depth of
  field, face blur request, four-corner screen picker), routes, hand-off notes, references vfx.md and
  blender.md.

Fixed on the way (all renders benefit):
- FFmpeg 8.1 dropped main-track frames when an overlay that starts later shares a process with loudnorm
  (345 of 414 frames survived; the picture froze for seconds per graphic). Picture and sound now run as
  separate processes and are muxed.
- A `-loop 1` still image feeding an overlay could stall the compose: stills now loop inside the graph.
- Segments from differently tagged sources (untagged, BT.601, RGB-blended VFX) made FFmpeg reconfigure
  mid-stream and an xfade stopped early: every segment now leaves tagged BT.709 / TV range.
- A transition on a clip starting at source 0 (no handle) shortened the timeline: the edge frame is held.
- tmix with `enable` dropped frames: motion blur blurs a trimmed copy and overlays it.
- Segment cache keys carry a version, so filter-chain changes re-render cached clips.

Verified (`tests/test_phase4.py --blender`: 46/46; regressions test_v2 22/22, test_phase2 --render 24/24,
test_phase3 35/35, test_port 50/50):
- Tracking on synthetic footage with ground truth: object centre error 2.4 px (IoU 0.97, VitTrack alone
  7 px); planar corners 0.43 px mean, 0.61 px p95; the screen suggestion lands 12 px from the true corners.
- In renders: the insert fills 95 % of the moving screen with 0.2 % outside it; the attached label sits
  within 2-5 px of the tracked box centre; a tracked face blur drops detail 31 -> 5 and YuNet no longer
  finds the face; every render keeps 414/414 frames.
- Cut-outs: titles never draw over the person (0.00 %), background detail 0.29 of the original while the
  person keeps it, outline on 45 % of the edge; still cut-outs keep the person and remove the room
  (MODNet 2 s, BiRefNet ~1 min per still).
- Depth: the speaker reads nearer than the wall (0.71 vs 0.27); auto-focus keeps the face and softens the
  wall to 0.48 of its detail; 3D photo moves without revealing edges.
- Camera: whip keeps 13.8 s / 414 frames with detail 1421 -> 54 at the cut; motion blur softens only its
  window; handheld drift moves ~9 px per 0.4 s.
- Speed here (no NVIDIA): 3D templates ~5 frames/s at 1080x1920; MODNet matte ~3 frames/s (8 ORT threads:
  250 ms vs 409 ms default, 1115 ms with all 18); Blender EEVEE ~2 s per frame at 540p.
- Not tested: Fusion (needs Resolve Studio); Studio UI clicks of the new controls (JS syntax and
  bake/ops parity checked; driving the owner's browser needs their OK).

### Phase 5 status (2026-11-04): voices, environments, performance learning

Built:
- **Voices** (`scripts/vedit/voice/`, `vedit voice list|say|vo|clone|compare`): one interface over Kokoro
  (54 offline voices, English + 7 languages; full-precision weights optional and 3-4x faster here), offline
  Bangla (Coqui VITS female, Mimic 3 multi-speaker), Microsoft Edge online voices (best free Bangla, exact
  word times), Pocket TTS cloning from a 15 s reference, OpenVoice V2 tone conversion (the owner's voice in
  any language, e.g. Edge Bangla moved to their timbre) and ElevenLabs. Sentences are spoken one by one with
  pauses vedit places, so sentence boundaries are exact; word times come from the service, from Whisper
  aligned to the script (English) or are spread inside each sentence. Bangla numbers are spelled for the
  offline Bangla voices. Every voice carries its licence and a commercial flag; clones need the speaker's
  consent in words, stored with the voice. Tool venvs: `voice` (sherpa-onnx 1.13.8 + edge-tts) and
  `openvoice` (PyTorch CPU). Voiceovers go into an edit as the main track (faceless; the renderer now draws
  a canvas-colour picture for audio-only main clips) or as VO clips whose words join the captions (engine
  and Studio JS alike).
- **Environments** (`vedit env`, `references/environments.md`): surface detection (Claude Code on Windows,
  Claude app via local MCP, Claude app VM, macOS, lite), Claude desktop app MCP registration that merges
  into the Microsoft Store build's config under `%LOCALAPPDATA%\Claude-Data` (backup, idempotent, refuses
  while the app is open because it rewrites its config from memory), new MCP tools `read_doc`, `view_image`,
  `env`, and the official Claude-app launcher skill (`app/claude-app/video-editing/SKILL.md`, zip via
  `vedit env launcher`; routes: MCP tools, remote device tools, lite). Tool venvs are per OS
  (`.cache/tools-<os>` off Windows) and the `vedit` shell launcher keeps a VM-local engine venv when the
  folder is shared with Windows, so neither side rebuilds the other's.
- **Performance learning** (`vedit publish link`, `vedit analytics auth|pull|import|report|learn`,
  `references/analytics.md`): retention from YouTube Studio CSV exports or the YouTube Analytics API through
  the owner's own OAuth client (PKCE, loopback; they sign in), mapped onto the edit: drops and rewatches with
  what was on screen and being said, element lifts per graphic / b-roll / sound, a chart PNG; `learn` feeds
  the profile (`performance`: median hook and average retention, drop causes) and nudges routes in
  `vedit route plan` by measured lift (2+ observations, at most 2 points).

Found on the way:
- sherpa-onnx 2.0 removed its built-in espeak-ng: Kokoro silently skipped English words missing from its
  lexicon (names, brands), could not speak its other languages, and Piper/Mimic 3 voices failed. Pinned
  1.13.8 (the last release with espeak inside, already with Pocket TTS).
- Giving Whisper the script as its prompt made it skip and invent words (it treats a prompt as text already
  said); alignment uses no prompt (100 % of words matched on Kokoro English).
- The int8 Kokoro export ran 2.6-3.5x slower than real time on this CPU; the fp32 export runs at 0.87x.

Verified (`tests/test_phase5.py`: 38/38; regressions test_v2 22/22, test_phase2 --render 24/24, test_phase3
35/35, test_port 50/50, test_phase4 42/42 (Blender checks unchanged since phase 4)):
- Kokoro English re-transcribes word for word (WER 0.00) with Whisper-aligned times (100 % matched); names
  outside the lexicon are spoken; the Spanish voice speaks Spanish (WER 0.00).
- Bangla: Edge, Coqui and Mimic 3 each give two exact sentences and a time for every word; Whisper reads
  them back at character error rates of about 0.14 (Edge), 0.32 (Coqui) and 0.29 (Mimic 3); the placed pause
  between sentences is silent.
- Cloning: no consent, no clone; Pocket TTS lands on the target speaker (similarity 0.58 vs 0.12 for
  another voice); OpenVoice moves Edge Bangla towards the target (0.45 vs 0.39 for the base voice); a clone
  over an online base voice inherits the stricter licence flag.
- A faceless Bangla voiceover project renders at the voice's length (8.07 s) with audible voice (-15 LUFS)
  and captions drawn from it; the Studio's JS builds the same voiceover captions as the engine; a VO clip
  over footage adds its words at its place.
- Environments: surface and engine readiness reported; the MCP config merge keeps other settings and
  servers, backs up, is idempotent and will not replace someone else's server; the registered command
  serves 24 tools over stdio, including docs and images; the launcher zip carries this PC's path; synced
  hand-made launchers are told apart from the official one.
- Analytics: a drop planted at 40-45 % of the e2e edit is found at 12.58-14.15 s (planted 12.6-14.1 s) with
  the words being said; a planted rewatch at 22.0 s; m:ss CSVs read; the API pull works against mocked Google
  endpoints; the OAuth flow (PKCE, loopback) completes against a mocked token endpoint; learning puts
  performance into the profile and measured lifts into the route planner.
- Not tested live: the owner's YouTube account (needs their OAuth client), the Claude app with the MCP entry
  (the app must be closed to register it; the owner restarts it), the launcher in the Claude app (the owner
  uploads the zip), the Studio player with an audio-only main track, macOS.
