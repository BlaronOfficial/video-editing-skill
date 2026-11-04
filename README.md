# video-editing-skill

A Claude skill that edits your videos like a professional editor, with Claude as the director.
Drop in raw footage and say what you want ("cool girl aesthetic reel", "cut this podcast into five
shorts", "YouTube video with chapters and lower thirds", "a 40-second animated history of the
smartphone"). Claude drafts the edit, opens it in a live **Studio** where you preview, tweak and approve
it, then renders the final video and any hand-off you asked for.

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
- Motion graphics Claude designs itself: 27 templates, 8 of them in 3D (titles, logos, product spins,
  device mockups, particles, fly-throughs, charts, globes; Three.js, or Blender when installed), plus
  custom HTML/GSAP/SVG/Canvas compositions, Remotion and HyperFrames, rendered with real transparency;
  custom Python and FFmpeg FX.
- **Animated pieces**: illustrated animation drawn in code, in 7 looks (cut paper, ink crosshatch,
  risograph, sketchbook, math, pixel art, isometric) or one matched from your references. Use them as
  inserts in footage edits, whole faceless shorts, history and timeline explainers, product reels, or
  hand-drawn doodles over your footage. Scenes are timed to the voice-over word by word and to your music,
  and Bangla is drawn whole (adapted from [animate](https://github.com/cth9191/animate), MIT).
- VFX: tracking of objects, faces and screens; screen replacement; person cut-outs (text behind you,
  background swap or blur, sticker outlines); depth parallax and focus; whip and zoom transitions, motion
  blur, speed ramps, stabilising and denoising.
- Voices with their licences shown: 54 offline Kokoro voices, offline Bangla, Microsoft Edge voices (the
  best free Bangla), cloning from 15 seconds (with the speaker's consent), your own voice in other
  languages, ElevenLabs. Voiceovers become faceless videos or narration over footage, captions included.
- Sound design like an editor: sound kits (earshot's 252 code-made effects, or a built-in synth kit)
  placed on the moments that need them, in sync and levelled against the music or voice; the music dips
  before big hits; cuts snap onto the beat of your track (a beat map accurate to about a millisecond, and
  never a cut through a word); music made in code shaped to your edit when you have none (7 moods, silence
  before the payoff).
- QA measures instead of guessing: text cut off by the frame, overlapping or under the platform's buttons,
  stretches where nothing new happens, voice-over that's too fast, cuts off the beat, loudness, black or
  frozen frames, plus frame sheets and (with earshot) listening.
- Watches footage the way you would: scene frames with duplicates dropped, speaker labels, multicam cut
  by who is talking, a searchable memory of everything you ever filmed, videos from links.
- Assets from everywhere, with licences logged: Openverse, Wikimedia Commons, Pexels, Pixabay, the
  browser (Google, Pinterest...), and your own logged-in Gemini, ChatGPT, Canva or Firefly.
- A writing pass for titles, on-screen text and post copy, so nothing sounds machine-written.
- B-roll, music with automatic ducking, colour grades, reframes, long-video → shorts, thumbnails, post
  copy, batch mode.
- Learns your taste from Studio decisions, chat feedback, the routes you keep, your edits and your YouTube
  retention (drops and rewatches mapped onto what was on screen and being said).
- **Optional hand-offs**: an editable CapCut project; DaVinci Resolve (free import package, or live in
  Studio), Premiere Pro, Final Cut Pro, Kdenlive, Shotcut, OpenTimelineIO and EDL timelines with ProRes
  graphics, stems and the grade as a LUT; LosslessCut projects; edits made there come back and teach vedit.
- Lossless smart cut: frame-accurate trims that re-encode only a few frames around each cut.
- Works in Claude Code, in the Claude desktop app (local tools plus a launcher skill) and in the Claude app
  without your PC (a lite mode).
- Optional add-ons: Higgsfield, ElevenLabs, Pexels/Pixabay, Blender, earshot and more (`vedit doctor`
  lists them with cost and licence).

## Install

Requirements: Windows 10/11 (macOS prepared, untested), [Claude Code](https://claude.com/claude-code)
or the Claude desktop app, [uv](https://docs.astral.sh/uv/), Node.js 20+, FFmpeg full build
(`winget install Gyan.FFmpeg`), Google Chrome or Edge.

```powershell
git clone https://github.com/BlaronOfficial/video-editing-skill "$env:USERPROFILE\.claude\skills\video-editing-skill"
cd "$env:USERPROFILE\.claude\skills\video-editing-skill"
.\vedit.cmd setup          # Python deps, fonts, motion-graphics renderer
.\vedit.cmd doctor         # core READY or not, plus every optional add-on with its fix
```
Optional, each in its own folder under `.cache/tools/`:
```powershell
.\vedit.cmd setup earshot    # sound kits (~70 MB); add --ears for listening QA (~1.3 GB)
.\vedit.cmd setup crv        # watching, speaker labels, link downloads (~100 MB)
.\vedit.cmd setup voice      # offline and Edge voices (~20 MB; voice models download when you ask)
.\vedit.cmd setup openvoice  # your voice in other languages (~0.8 GB)
```
Bigger models (voices, cut-outs, depth, Whisper) are never downloaded silently: Claude tells you the size
first, and downloads resume if interrupted.

Using CapCut too? Open it once, click **Create project**, close it, and run `.\vedit.cmd capcut calibrate`.

Using the Claude desktop app? Quit it fully (the tray icon too), run `.\vedit.cmd env mcp --install`, and
start it again. Then run `.\vedit.cmd env launcher` and upload `app\claude-app\video-editing.zip` in
claude.ai under Settings → Capabilities → Skills.

Start Claude and ask: *"Edit the clips in D:\shoots\monday into a 40-second reel."*
Claude opens the Studio for you the first time.

## Update

```powershell
.\vedit.cmd update
```
Your personal data (brand kits, styles, animation looks, rules, learned preferences, templates,
extensions, calibration, API keys) lives in `personal/`, which is git-ignored, so updates never overwrite
it.

## Privacy and licences
- Processing runs on your machine. Things leave it only when you opt in: low-res previews in your private
  Studio artifact, services you enable (ElevenLabs, Higgsfield, Edge voices, web AI tools, YouTube
  Analytics through your own sign-in), and research in your browser.
- `personal/` and CapCut calibration data (which contains device identifiers) never leave your machine.
- Respect the rights of music, footage and images you use; the skill logs the source and licence of every
  external asset in each project's `edit/assets/provenance.json` and flags unclear licences. Voices carry
  their own licence and a commercial-use flag; a cloned voice needs the speaker's consent.
- MIT licence. Remotion has its own licence (free for individuals and companies of up to 3 people).
  CapCut is a trademark of Bytedance and DaVinci Resolve of Blackmagic Design; this project is not
  affiliated with either.

See `SKILL.md` for how Claude uses the skill, `references/` for the details and `ATTRIBUTIONS.md` for the
open-source projects it builds on.
