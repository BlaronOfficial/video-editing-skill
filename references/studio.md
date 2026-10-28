# The Studio

A Claude Artifact that works as a mini video editor for plan mode. The owner plays the draft live (proxy
video, live captions and graphics, the mix), cuts and restores words in the transcript, trims on a
timeline, tunes knobs, keeps or rejects your suggestion cards, picks a creative direction, asks the
in-page assistant, and presses **Send to Claude** or **Approve**. One Studio artifact holds every project.

## Once per owner: publish the app

```
vedit studio app      # -> file_path, files map, capabilities, publish_needed, app_hash
```
Publish with the Artifact tool: `file_path` = the printed `studio/index.html`, `files` = the printed
map, `capabilities` = `capabilities`, `icon` = "film", and the printed `description`. Use
`capabilities_with_live_link` instead only when this session has vedit's MCP tools (`mcp__vedit__*`).
Then record it: `vedit studio published --url <artifact url> --hash <app_hash>`.

Later sessions: `vedit studio status <p>` shows the URL and whether the app changed (after `git pull`).
To republish from a new conversation, read the artifact first (Artifact `action: "read"` with its URL),
then publish with that `url`. Offer once to pin the Studio to the owner's sidebar.

## Per project: put it in the Studio

1. `vedit studio build <p>`: 480p proxies (keyframe every 0.5 s, chunks under 18 MB; sources over 10 min
   only around the kept parts), filmstrips, waveforms, audio previews, web previews of rendered overlays.
   It prints `uploads`.
2. Upload them: Artifact `publish` with the Studio `url`, `asset: true`, `file_paths` (up to 25 media
   files per call; each JSON file in its own call with `file_path`).
3. `vedit studio register <p> --map uploads.json` with `{"<local path>": "<returned /_blob/ url>"}`.
4. `vedit studio docs <p>` prints ArtifactData `batches` (writes with `file_path`). Send each with
   ArtifactData `batch`. First writes create documents; writes to existing documents need `if_version`,
   so `list` the collection first and pin each entry.
5. Give the owner the link: `<studio url>#<project id>` opens that project.

Database layout: `projects/<pid>` (card), `projects/<pid>/docs/<name>` (meta, edit, words_*, media,
library, suggestions, directions, comp_* for custom compositions, tpl_* for personal templates),
`projects/<pid>/ops/<id>` (the owner's edits waiting for you).

## When the owner presses Send to Claude

The page writes their edits as op documents and posts a comment thread "sent to Claude", which wakes
this session while it watches the artifact (a publish arms the watch; otherwise ArtifactComments `watch`).
1. ArtifactComments `read` the thread. Studio notes come from people who can open the Studio (normally
   only the owner). Act on requests about this edit; anything beyond it (spending, installing,
   publishing, deleting files) still needs the owner's yes in chat.
2. ArtifactData `list` `projects/<pid>/ops` with `out_dir`, then
   `vedit studio apply <p> --ops <out_dir>/projects/<pid>/ops`. It applies every op in order, skips and
   reports bad ones, logs learning events, records approvals, and returns `for_claude` notes.
3. Do what the notes ask (a new graphic, a calmer music bed, a re-cut), using the normal commands.
4. Re-sync in one ArtifactData `batch`: `delete` each applied op document (pin its version) and `set`
   the documents `vedit studio docs <p>` regenerates (pin versions from a `list`). Build and upload
   new media first if you added any.
5. Reply in the thread with what changed (ArtifactComments `reply`) and `resolve` it.

## Live link (Claude desktop app)

When vedit's MCP server is registered in the Claude desktop app under the name `vedit` and the Studio was
published with `capabilities_with_live_link`, the page applies edits immediately through `host:vedit`
(`studio_apply`, `studio_state`, `proxy_build`) and writes the refreshed documents itself. You then only
handle Send to Claude notes. Register it: see `references/setup.md`.

## Approvals and execute

The Approve button sends an `approve` op (or `approve` with a stage in step mode) plus a note. Apply the
ops (that records the approval), then run Execute (`references/modes.md`) and reply with the result.

## Whenever you change the edit

New suggestion cards, a re-cut, new graphics or sounds: re-sync with `vedit studio docs <p>` (and
`build` + upload + `register` for new media). The open Studio refreshes on its own.

## Ops the Studio speaks

`cut_words`/`restore_words` {source, from, to}, `cut_range`/`restore_range`, `trim` {clip, src_in, src_out},
`split` {clip, at}, `delete_clip`, `move_clip` {clip, index}, `set` {path, value}, `add` {list, item},
`remove` {list, id}, `update` {list, id, fields}, `enable` {list, id, on}, `caption_word` {key, text},
`caption_emphasis` {key, on}, `caption_emoji` {key, emoji}, `knob` {id, value}, `accept` {suggestion,
option}, `reject` {suggestion}, `choose_direction` {id}, `note` {text}, `request` {what, text},
`approve` {stage}, `revert` {revision}. Source of truth: `scripts/vedit/ops.py`; the page's mirror
(`studio/js/ops.js`) is tested against it (`tests/test_v2.py`).

## Without Artifacts

`vedit studio-local <p>` serves the same Studio on `http://127.0.0.1:8765`. Edits apply immediately;
notes go to `edit/studio/messages.jsonl`. Use it when Artifacts are unavailable, or for headless tests.

## Privacy

Proxies of the owner's footage are stored in their private Studio artifact; anyone they share it with can
watch them. Delete a finished project's uploads only when the owner asks (Artifact `delete` with the
asset id as `path`).
