# DaVinci Resolve

Since Resolve 21.1 (Sept 2026) scripting and the built-in MCP server are **Studio-only** ($295). So:

| Edition | Route |
|---|---|
| Free | Import package (`vedit handoff make <p> --to resolve`). The owner imports it: File > Import > Timeline, pick the `.fcpxml`. Or, with the owner's OK, `vedit resolve screen-import <p>` |
| Studio | `vedit resolve import <p>`: live, add-only, verified from Resolve's side. Same package underneath |
| Either | Learn from the owner's work: they export the timeline (FCPXML/OTIO), `vedit handoff diff` |

`vedit doctor` / `vedit capabilities` say which edition is installed (`resolve`, `resolve_studio` add-ons).

## The package
See `references/handoffs.md`. Resolve-specific notes for the README you hand over:
- Media Pool: leave "Automatically import source clips" on; offline clips: Relink Selected Clips.
- Grade: `look.cube` goes into Resolve's LUT folder (Project Settings > Color Management > Open LUT Folder,
  then Update Lists), then on the timeline node or the clips.
- Captions: File > Import > Subtitle `captions.srt` (editable) or keep the styled alpha layer on its track.
- Fairlight: the stems are the vedit mix pre-master; the timeline's own music/SFX tracks are there too, so
  the owner can rebuild the mix. Deliver at -14 LUFS / -1 dBTP for social.

## Studio: live import (`vedit resolve import <p> [--project NAME] [--into-current] [--no-lut]`)
Needs Preferences > System > General > External scripting using: **Local**, and Resolve running. vedit
starts a child process with Blackmagic's `DaVinciResolveScript` module, creates a **new** project (or a
new timeline in the open project with `--into-current`), imports the FCPXML with its source clips, puts
`look.cube` on the V1 clips, adds the SRT to the Media Pool, then reads back track count, V1 clip count,
duration and markers and compares them with the hand-off (`verified`). It never deletes, renames or
overwrites anything; a name clash gets " (2)". Ask before touching a project the owner has open.
`vedit resolve status` shows edition, version and the open project.

Untested here until Resolve Studio is installed: say so when you use it, and check the result on screen.

## Free: screen import (`vedit resolve screen-import <p>`, only with the owner's OK)
Prefer computer use when the session has it: open Resolve's File > Import > Timeline, pick the FCPXML,
OK the Load XML dialog, take a screenshot, look. The fallback in vedit focuses Resolve, sends Ctrl+Shift+I,
types the path, confirms, and screenshots each step into `qa/resolve_screen/`; every keystroke is refused
unless Resolve owns the foreground window. Stop at any dialog that asks to save, convert, upgrade or about
another project, and tell the owner what it says.

## Interactive control (Studio)
For a conversation-style session inside Resolve (colour, Fusion, Fairlight, render queue), the owner can
add Resolve Studio's built-in MCP server or samuelgursky/davinci-resolve-mcp (MIT) to Claude; Fusion 3D
motion design: legionsound/open-fusion-mcp (MIT). They are separate tools: suggest them, don't install
them without a yes.
