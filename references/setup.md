# Setup, updates, MCP, troubleshooting

## Requirements
Windows 10/11 (macOS support is planned), ffmpeg (full build with libass), Python via `uv`, Node.js 20+,
Google Chrome or Edge, CapCut desktop (9.x verified). Optional: ElevenLabs key, Higgsfield subscription,
Claude in Chrome, Claude Code Desktop (computer use) or Windows-MCP.

## First run
```
vedit doctor            # what's missing and how to fix it
vedit setup             # fonts + motion-graphics renderer deps (add --whisper to pre-download the model)
vedit capcut calibrate  # after creating one empty project in CapCut and closing CapCut
vedit capcut probe-alpha  →  vedit capcut set-alpha prores|webm|chroma
```
Optional: `vedit setup install-fonts` installs the bundled OFL fonts for the current Windows user so the
same fonts appear inside CapCut. `vedit secret set elevenlabs <key>` stores the key in
`personal/secrets.json` (git-ignored); an `ELEVENLABS_API_KEY` env var also works.

## Personal data and updates
`personal/` holds config, secrets, brand kits, styles (incl. learned preferences), CapCut calibration,
asset index and voices. It is git-ignored, so `vedit update` (= safe `git pull --ff-only` + dependency
sync + config migration) never touches it. Never edit tracked files for personal changes; if you did,
`vedit update` explains how to move them. Back up `personal/` to move to a new machine.
`VEDIT_PERSONAL_DIR` can point several clones at one personal folder.

## MCP server
Same engine as MCP tools (for Claude Desktop/Cowork or other agents):
`claude mcp add --scope user video-editing -- "<base>\vedit.cmd" mcp`
Tools: doctor, project_init, transcribe, pack, plan_apply, captions_build, storyboard, mg_render, render,
qa, capcut_build, capcut_diff, plus `vedit` (any CLI command).

## Troubleshooting
| Symptom | Fix |
|---|---|
| CapCut says the project is damaged / won't open | Re-calibrate after CapCut updates; 10.x may reject tool-written projects (render is unaffected) |
| Project not listed in CapCut | CapCut was open during the build (it rewrites its index on exit): close CapCut, rebuild with `--overwrite` |
| Overlays show black boxes in CapCut | `vedit capcut set-alpha chroma` (or the format that passed the probe) and rebuild |
| Missing fonts in renders | `vedit setup fonts`; for CapCut text, `vedit setup install-fonts` |
| Whisper slow | Use `--engine scribe`, or a smaller model: `vedit config set transcription.whisper_model medium` |
| Bangla words wrong | Scribe, `--language bn`, then correct caption chunks |
| Motion graphics render fails | `vedit doctor` (Chrome/Edge + `vedit setup renderer`); check `[page error]` lines for JS errors |
| Audio pops at cuts in QA | Move the cut to a pause (`vedit view`), or raise `audio_fade_in/out` on that clip |
| `ffmpeg` drawtext crash | Not used by the skill; labels are drawn with Pillow |
