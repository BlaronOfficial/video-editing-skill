---
name: video-editing-skill
description: Professional AI video editing with CapCut. Turns raw footage (talking-head shorts, long-form YouTube, ads, faceless/voiceover) into finished videos - transcript-based cuts (pauses, fillers, retakes), word-timed animated captions (English, Bangla, Banglish), custom motion graphics (HTML/GSAP, Remotion, SVG), b-roll, music ducking, SFX, colour grades, auto-reframe, long-to-shorts, thumbnails and AI voiceover - and delivers BOTH a rendered MP4 and an editable CapCut desktop project. Optional Higgsfield generation and Pinterest research through Claude in Chrome. Use whenever the user wants to edit, cut, trim, caption, subtitle, reframe, clip, or add motion graphics/effects to video, make reels, shorts, TikToks or YouTube videos, batch-edit clips, or mentions CapCut.
---

# Video editing with CapCut

You are the editor. This skill gives you an engine (`vedit`) that turns your editorial decisions into
a finished MP4 **and** the same edit as an editable CapCut project, so the user can take over any layer.

## Locate the engine

The skill's base directory is the folder containing this file (Claude Code prints it when the skill
loads). Call the engine with `"<base>/vedit" <command>` from Bash or `& "<base>\vedit.cmd" <command>` from
PowerShell. Every command prints JSON. Below, `vedit` means that full path.

First use on a machine: run `vedit doctor`. If it is not READY, run `vedit setup` and follow the fixes
(CapCut calibration needs one empty CapCut project: `vedit capcut calibrate`). Details: `references/setup.md`.

## Rules that always apply

1. **Ask, don't assume, per project:** transcription engine (`whisper` local/free, or `scribe` ElevenLabs,
   better for Bangla/Banglish), whether CapCut **Pro** resources are allowed, the target platform/ratio,
   and the style if the user gave none. Batch these into one AskUserQuestion call.
2. **Storyboard first.** Show the storyboard and get approval before rendering or writing to CapCut,
   unless the user said "auto", "batch" or "no review".
3. **Never spend Higgsfield credits** without showing the shot list with an estimate and getting a yes.
4. **The screen belongs to the user.** Ask before closing CapCut or taking over the mouse/keyboard.
   Never click into other apps and never answer OS security prompts. `vedit screen` refuses input
   unless CapCut owns the foreground; keep it that way.
5. **Never edit tracked skill files while editing videos.** Everything personal (brands, styles,
   learned preferences, keys, calibration) lives in `<base>/personal/` so `git pull` updates cleanly.
6. **Provenance:** every asset from outside the camera goes through `vedit download` or
   `vedit provenance add` (source URL + licence). Warn about copyright when the user wants to publish
   Pinterest or CapCut-library material commercially, then respect their decision.
7. **Log decisions** with `vedit project log <project> "<decision>"` so later sessions can continue.
8. **Verify, then claim.** Look at QA frame sheets and fix problems before presenting a render.

## Workflow

| Step | What you do | Commands |
|---|---|---|
| 1. Intake | Ask the per-project questions; read the brand/style the user names | `vedit style list`, `vedit brand list` |
| 2. Project | Create the workspace next to the footage | `vedit project init <footage> --ratio 9:16` |
| 3. Listen | Transcribe, pack, then **read `edit/takes_packed.md`** | `vedit transcribe <p> --engine whisper --language bn` · `vedit pack <p>` |
| 4. Cut | Choose the hook, structure, best takes; drop retakes, tangents, fillers, dead air | write `keeps.json` → `vedit plan apply <p> keeps.json` |
| 5. Design | Captions, graphics, b-roll, SFX, music, grade, effects: edit `edit/edit.json` | `vedit captions build <p> --style <s>` · `vedit mg templates` |
| 6. Approve | Build the storyboard, show it, iterate on feedback | `vedit storyboard <p> --open` |
| 7. Make assets | Render graphics; Higgsfield (approved only); Pinterest/library assets | `vedit mg render <p>` · `vedit download ...` |
| 8. Render + QA | Preview, look, fix, final render, QA, look at the frame sheets | `vedit render <p> --preview` · `vedit render <p>` · `vedit qa <p>` |
| 9. CapCut | Write the editable project; offer to open/export it | `vedit capcut build <p> --pro yes\|no` |
| 10. Learn | After the user edits in CapCut, learn from the changes | `vedit capcut diff <p> --learn <style>` |

Decide which motion-graphics engine fits each moment (templates, custom HTML/GSAP/SVG/Canvas/Three.js
compositions, Remotion, Higgsfield clips), and mix them freely. Custom compositions written for the
specific video are how edits go from good to excellent.

## Which reference to read

| Need | Read |
|---|---|
| Full step-by-step with examples | `references/workflow.md` |
| `edit.json` fields and examples | `references/edit-json.md` |
| Editing judgement: hooks, pacing, takes, b-roll, SFX, platform specs | `references/editing-craft.md` |
| Captions, Bangla/Banglish, emphasis | `references/captions.md` |
| Motion graphics: engines, templates, writing compositions | `references/motion-graphics.md` |
| CapCut: calibration, Pro, alpha overlays, resources, versions | `references/capcut.md` |
| Driving the CapCut UI (export, auto-captions, library) | `references/screen-control.md` |
| Styles, brand kits, cloning a creator, learned preferences | `references/styles.md` |
| Music, voice, ducking, beats, SFX | `references/audio.md` |
| Higgsfield generation | `references/higgsfield.md` |
| Pinterest research and assets (Claude in Chrome) | `references/pinterest.md` |
| Shorts from long videos, reframe, thumbnails, post copy, voiceover, batch | `references/extras.md` |
| Setup, updates, MCP server, troubleshooting | `references/setup.md` |
