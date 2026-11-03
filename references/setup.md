# Setup, updates, MCP, troubleshooting

## Requirements
The core is free and standalone: Windows 10/11 (macOS paths prepared, untested), ffmpeg (full build with
libass), Python via `uv`, Node.js 20+, Google Chrome or Edge. That is all `vedit doctor` needs for READY.

Optional add-ons (`vedit doctor` lists each with cost, licence, size and how to install): CapCut desktop
(9.x verified), DaVinci Resolve (free or Studio), LosslessCut, Blender, OpenTimelineIO (~10 MB, installs on
first use for Premiere/OTIO/EDL/Kdenlive hand-offs: `vedit setup otio`), earshot sound kits and ears,
claude-real-video (watching, speakers, link fetch), Remotion, ElevenLabs, Higgsfield, Pexels/Pixabay/Gemini
API keys; plus whatever the Claude session brings (Claude in Chrome, Canva or Google Drive connectors,
computer use, Windows-MCP).

Light tools that make the free core better, each in its own isolated venv under `.cache/tools/`:
```
vedit setup earshot         # sound kits: 252 code-made SFX with sync points (~70 MB, no models)
vedit setup earshot --ears  # + listening QA: torch CPU and two models (~1.3 GB; ask first)
vedit setup crv             # claude-real-video: watching, speaker labels, yt-dlp (~100 MB)
```
Without them the built-in synth kit, a native frame watcher and Whisper still work.

## First run
```
vedit doctor            # core READY or not; add-ons are listed separately
vedit setup             # fonts + motion-graphics renderer deps (add --whisper to pre-download the model)
vedit capabilities      # everything this machine can use (engine side)
```
Only if the owner uses CapCut: `vedit capcut calibrate` (after creating one empty project and closing
CapCut), then `vedit capcut probe-alpha` → `vedit capcut set-alpha prores|webm|chroma`.
Optional: `vedit setup install-fonts` installs the bundled OFL fonts for the current Windows user so the
same fonts appear inside CapCut. `vedit secret set elevenlabs <key>` stores a key in
`personal/secrets.json` (git-ignored); environment variables (`ELEVENLABS_API_KEY`, `PEXELS_API_KEY`,
`PIXABAY_API_KEY`, `GEMINI_API_KEY`) also work.

## Models (ask first, resumable)
Optional features download models on first use. Small ones (under 5 MB) just download; larger ones make
a command exit with code 3 and print `needs_download` (id, size, ETA from measured bandwidth, licence,
purpose). Ask the owner, then `vedit models get <id>`; an interrupted download resumes where it stopped.
`vedit models list` shows everything known. `config models.policy auto` skips the asking.

| Model | Size | For | Licence |
|---|---|---|---|
| yunet, vittrack | 0.2 / 0.7 MB (no ask) | faces, object tracking | MIT / Apache-2.0 |
| speaker_seg, speaker_emb | 7 / 40 MB | who speaks when | MIT / Apache-2.0 |
| modnet | 26 MB | person cut-outs (text behind people, background swap) | Apache-2.0 |
| depth_small | 27 MB | 3D photos, depth of field | Apache-2.0 |
| birefnet_lite | 224 MB | best object cut-outs for stills (optional) | MIT |

CPU inference uses 8 threads by default (faster than all cores on hybrid CPUs); `VEDIT_ORT_THREADS`
overrides. `vedit vfx check` shows what VFX can run here.

## Personal data and updates
`personal/` holds config, secrets, brand kits, styles (incl. learned preferences), CapCut calibration,
asset index and voices. It is git-ignored, so `vedit update` (= safe `git pull --ff-only` + dependency
sync + config migration) never touches it. Never edit tracked files for personal changes; if you did,
`vedit update` explains how to move them. Back up `personal/` to move to a new machine.
`VEDIT_PERSONAL_DIR` can point several clones at one personal folder.

## MCP server
Same engine as MCP tools. **Name it `vedit`**: the Studio's live link calls it as `host:vedit`.
- Claude Code: `claude mcp add --scope user vedit -- "<base>\vedit.cmd" mcp`
- Claude desktop app (`claude_desktop_config.json`): `{"mcpServers": {"vedit": {"command": "<base>\\vedit.cmd", "args": ["mcp"]}}}`
Tools: doctor, capabilities, route_plan, workflow, project_init, transcribe, pack, plan_apply,
captions_build, storyboard, mg_render, render, qa, capcut_build, capcut_diff, the Studio live link
(studio_apply, studio_state, proxy_build, studio_file, sfx_preview), plus `vedit` (any CLI command).
After registering it in the Claude desktop app, republish the Studio with `capabilities_with_live_link`
(`references/studio.md`).

## Claude app on the owner's PC
In the Claude app (chat) the engine runs on the owner's computer through the remote device tools: a Linux
VM with the owner's folders mounted under `~/mnt/`. Request access to the skill folder and the footage
folder in one call, then run `"$HOME/mnt/<skill folder>/vedit" <command>`. Windows-only steps (CapCut,
screen control, installing fonts for Windows apps) need Claude Code on Windows; everything else works,
and the Studio artifact is the natural way to show work there. An official launcher skill for the Claude
app ships in phase 5.

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
| A command exits with code 3 | It needs a model download: read `needs_download`, ask, `vedit models get <id>` |
| `vedit render` refuses | The project is in plan/step mode without approval: get it approved (Studio or `vedit workflow approve`), or `--force` only if the owner asked to render now |
| Studio shows no video | `vedit studio build` then upload and `register` the files it lists, then `vedit studio docs` and sync (`references/studio.md`) |
