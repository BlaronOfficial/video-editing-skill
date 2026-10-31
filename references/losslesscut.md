# LosslessCut (optional, free)

LosslessCut (mifi, GPL-2.0) is a free app for fast, lossless trimming. vedit only exchanges files with it
and talks to it over its local HTTP API; no code is shared. Good for owners who want to fine-tune the cut
points of a talking-head edit themselves, or to cut long recordings into parts without re-encoding.
vedit can do the same cuts natively (`vedit lossless ...`, `references/handoffs.md`); the app is for the
owner's hands.

## Hand the cut over
```
vedit llc write <p>          # one <video>-proj.llc per source with the main-track segments
vedit handoff make <p> --to losslesscut
```
A `.llc` (JSON5, version 2) holds one file's segments: `{start, end, name, tags: {vedit: <clip id>}}` in
source seconds, in playback order. LosslessCut finds the video by name next to the project, so for footage
inside the project's folder the `.llc` is written beside the video as `<name>-proj.llc` (LosslessCut opens
it automatically with the video); files elsewhere (the owner's library) are left alone and the `.llc`
stays in `edit/handoff/losslesscut/` (the owner opens the video, then File > Import project).

## Bring the tuned cut back
```
vedit llc import <p> <file.llc> [--source <id>]
vedit handoff diff <p> <file.llc> --apply-cuts      # same, plus what changed (learning)
```
Unselected segments are skipped. Graphics, captions and sounds anchored to words follow the new cut.

## Drive the app (`vedit llc open <p>`, `vedit llc export`)
`open` writes the projects and starts LosslessCut with `--http-api 18080 --config-dir .cache/losslesscut/config
--disable-networking`, so the owner's own settings and recent files are untouched; `export` asks the
running app to export the open file (its current export settings) and waits for the paths
(`/api/await-event/export-complete`). The API listens on 127.0.0.1 only. It is experimental upstream:
if an action does not answer, fall back to telling the owner which button to press.

Install (ask first, ~110 MB): the portable zip from github.com/mifi/lossless-cut/releases unpacked to
`.cache/tools/losslesscut/` (vedit finds `LosslessCut.exe` there), or `winget install mifi.losslesscut`.
