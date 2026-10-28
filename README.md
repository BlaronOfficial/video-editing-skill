# video-editing-skill

A Claude skill that edits your videos like a professional editor, with Claude as the director.
Drop in raw footage and say what you want ("cool girl aesthetic reel", "cut this podcast into five
shorts", "YouTube video with chapters and lower thirds"). Claude drafts the edit, opens it in a live
**Studio** where you preview, tweak and approve it, then renders the final video and any hand-off you
asked for.

- **Standalone and free at its core**: FFmpeg, Python, Node and Chrome/Edge. Nothing paid is required.
- **Studio** (a private Claude Artifact): play the draft live, cut or restore words in the transcript,
  trim on a timeline, tune pace/zoom/levels/look/captions, keep or reject Claude's suggestion cards, pick
  a creative direction, ask Claude inside the page, then Send to Claude or Approve.
- **Modes**: Plan (Studio first, default), Step-by-step (approve each stage), Auto (end to end).
- **Director, not a fixed pipeline**: Claude checks what it can use right now (your web AI accounts such
  as Gemini or ChatGPT, Canva and Google Drive connectors, the browser for research and assets), ranks the
  ways to make each thing, mixes them, and writes custom code when nothing fits.
- Transcript-based editing: removes pauses, filler words and retakes, picks the best takes, builds a hook.
- Word-timed animated captions in **English, Bangla and Banglish** (9 styles + your own).
- Motion graphics Claude designs itself: 18 templates plus custom HTML/GSAP/SVG/Canvas/Three.js
  compositions, Remotion and HyperFrames, rendered with real transparency; custom Python and FFmpeg FX.
- B-roll, music with automatic ducking, sound effects, colour grades, reframes, long-video → shorts,
  thumbnails, post copy, voiceover, batch mode.
- Learns your taste from Studio decisions, chat feedback, the routes you keep and your edits.
- **Optional hand-offs**: an editable CapCut project today; DaVinci Resolve, Premiere/Final Cut XML and
  LosslessCut are coming in the next phases.
- Optional add-ons: Higgsfield, ElevenLabs, Pexels/Pixabay, Blender, earshot and more (`vedit doctor`
  lists them with cost and licence).

## Install

Requirements: Windows 10/11 (macOS prepared, untested), [Claude Code](https://claude.com/claude-code),
[uv](https://docs.astral.sh/uv/), Node.js 20+, FFmpeg full build (`winget install Gyan.FFmpeg`),
Google Chrome or Edge.

```powershell
git clone https://github.com/BlaronOfficial/video-editing-skill "$env:USERPROFILE\.claude\skills\video-editing-skill"
cd "$env:USERPROFILE\.claude\skills\video-editing-skill"
.\vedit.cmd setup          # Python deps, fonts, motion-graphics renderer
.\vedit.cmd doctor         # core READY or not, plus every optional add-on with its fix
```
Using CapCut too? Open it once, click **Create project**, close it, and run `.\vedit.cmd capcut calibrate`.

Start Claude Code anywhere and ask: *"Edit the clips in D:\shoots\monday into a 40-second reel."*
Claude opens the Studio for you the first time.

## Update

```powershell
.\vedit.cmd update
```
Your personal data (brand kits, styles, rules, learned preferences, templates, extensions, calibration,
API keys) lives in `personal/`, which is git-ignored, so updates never overwrite it.

## Privacy and licences
- Processing runs on your machine. Things leave it only when you opt in: low-res previews in your private
  Studio artifact, services you enable (ElevenLabs, Higgsfield, web AI tools), and research in your browser.
- `personal/` and CapCut calibration data (which contains device identifiers) never leave your machine.
- Respect the rights of music, footage and images you use; the skill logs the source and licence of every
  external asset in each project's `edit/assets/provenance.json` and flags unclear licences.
- MIT licence. Remotion has its own licence (free for individuals and companies of up to 3 people).
  CapCut is a trademark of Bytedance and DaVinci Resolve of Blackmagic Design; this project is not
  affiliated with either.

See `SKILL.md` for how Claude uses the skill and `references/` for the details.
