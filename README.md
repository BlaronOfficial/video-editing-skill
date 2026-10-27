# video-editing-skill

A Claude skill that edits your videos like a professional editor and hands you the result twice:
a **finished MP4** and an **editable CapCut project** with every layer intact.

Drop in raw footage, say what you want ("cool girl aesthetic reel", "cut this podcast into five
shorts", "YouTube video with chapters and lower thirds"), approve the storyboard, done.

- Transcript-based editing: removes pauses, filler words and retakes, picks the best takes, builds a hook
- Word-timed animated captions in **English, Bangla and Banglish** (9 styles + your own)
- Motion graphics Claude designs itself: 18 templates plus custom HTML/GSAP/SVG/Canvas/Three.js
  compositions, Remotion and HyperFrames, rendered with real transparency
- B-roll, music with automatic ducking, sound effects (library, CapCut or generated), colour grades
- Editable CapCut desktop project: captions as text, graphics as layers, zooms and reframes as keyframes
- Styles: 10 aesthetic presets, multi-client brand kits, clone a creator's style, learns from your CapCut tweaks
- Extras: long-video → shorts, face-tracked auto-reframe, thumbnails, post copy, AI voiceover and voice clone, batch mode
- Optional: Higgsfield generation (with credit approval), Pinterest research via Claude in Chrome,
  CapCut UI control via Claude Code Desktop computer use or Windows-MCP, MCP server for other apps

## Install

Requirements: Windows 10/11 (macOS planned), [Claude Code](https://claude.com/claude-code),
[uv](https://docs.astral.sh/uv/), Node.js 20+, FFmpeg full build (`winget install Gyan.FFmpeg`),
Google Chrome or Edge, CapCut desktop.

```powershell
git clone https://github.com/<you>/video-editing-skill "$env:USERPROFILE\.claude\skills\video-editing-skill"
cd "$env:USERPROFILE\.claude\skills\video-editing-skill"
.\vedit.cmd setup          # Python deps, fonts, motion-graphics renderer
.\vedit.cmd doctor         # shows anything still missing, with the fix
```
Then open CapCut once, click **Create project**, close CapCut, and run `.\vedit.cmd capcut calibrate`.

Start Claude Code anywhere and ask: *"Edit the clips in D:\shoots\monday into a 40-second reel."*

## Update

```powershell
.\vedit.cmd update
```
Your personal data (brand kits, styles, learned preferences, CapCut calibration, API keys) lives in
`personal/`, which is git-ignored, so updates never overwrite it.

## Privacy and licences
- Everything runs locally except the services you opt into (ElevenLabs, Higgsfield).
- `personal/` and CapCut calibration data (which contains device identifiers) never leave your machine.
- Respect the rights of music, footage and images you use; the skill logs the source of every
  external asset in each project's `edit/assets/provenance.json`.
- MIT licence. Remotion has its own licence (free for individuals and companies of up to 3 people).
  CapCut is a trademark of Bytedance; this project is not affiliated with CapCut.

See `SKILL.md` for how Claude uses the skill and `references/` for the details.
