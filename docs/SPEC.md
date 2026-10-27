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
