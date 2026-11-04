# Directing an edit

The engine is a toolbox. These are the habits that turn it into excellent work: know what you can use,
choose (and mix) the best way to make each moment, build what is missing, and judge the result like an
editor before the owner sees it.

## 1. Discover what you can use

**Engine side**: `vedit capabilities` (add `--refresh` after installing something). It reports the OS and
surface (local, Claude-app VM), core tools, hardware encoders, add-ons (CapCut, Resolve, LosslessCut,
Blender, earshot, paid services), model packs, disk and measured bandwidth.

**Session side**, which only you can see:
- Your tool list. MCP connectors such as Canva (`mcp__claude_ai_Canva__*`), Google Drive, Higgsfield;
  browser tools such as Claude in Chrome (`mcp__claude-in-chrome__*`), the Claude app browser
  (`mcp__Claude_Browser__*`), Kapture (`mcp__kapture__*`), browser-use; computer use; Windows-MCP.
- Web AI accounts, checked only when the plan could use them, once per session. Open each service's home
  page in a **new tab** with the best browser tool, read whether an account is signed in (avatar or
  account menu vs. "Sign in"), close the tab. Services worth checking: gemini.google.com, chatgpt.com,
  canva.com (or use the Canva connector), firefly.adobe.com, ideogram.ai, leonardo.ai, krea.ai,
  freepik.com, suno.com, runwayml.com, klingai.com, lumalabs.ai. Never sign in or type credentials.
  The probe, per service, is in `references/webai.md`.

Record it so routes can use it and later sessions start informed:
```
vedit capabilities record --connectors canva,google_drive --browser claude-in-chrome,kapture \
  --webai gemini=logged_in,chatgpt=logged_out --tools computer-use
vedit capabilities outcome --route webai:gemini --ok yes --note "4 icons, clean backgrounds"
```

## 2. Route every need, and mix

`vedit route plan <need>` ranks the ways to make something (needs: image, icon, scene_clip,
motion_graphic, 3d, vfx, music, sfx, voiceover, font, thumbnail, color_look, background_removal, research,
critique). Available routes come first, scored on quality, speed, cost, licence, privacy and what the owner
kept before. It is a starting point; the best results usually mix routes:
- a Claude-drawn layout with a web-AI texture and an earshot whoosh on the reveal;
- a Gemini scene under natively set type (crisp text, editable later);
- a Three.js product card built from a Canva background-removed cutout;
- the owner's own b-roll first, stock only to fill gaps.

Costs: free and local routes need no ask. Subscription web AIs are fine within the per-project budget
(`config webai.budget_per_project`, default 12 generations). Credit-metered services (Runway, Kling, Luma,
Higgsfield, paid APIs) always get an estimate and a yes first. Afterwards:
`vedit route log <need> <route> kept|rejected|failed --project <name>`.

## 3. Sourcing and web AI generation

Everything external comes in with provenance (source, licence, author, prompt):
- **Free libraries**: `vedit sources search <words> [--kind video|audio]` (Openverse, Wikimedia Commons,
  Pexels and Pixabay with the owner's free keys), then `vedit sources get <p> --pick N --register`.
- **The browser**: Google Images, Pinterest, Behance, YouTube, LottieFiles, Iconify, Google Fonts for
  ideas and mood boards; download only what the licence allows (`references/sourcing.md`).
- **The owner's logged-in web AIs** (Gemini, ChatGPT, Firefly, Ideogram, Canva, Suno, Veo/Runway/Kling):
  `vedit inbox mark`, generate in a new tab with an art-directed prompt, download, then
  `vedit inbox pull <p> --service gemini --prompt "..." --register`. Prompting, budgets, licences and when
  to stop: `references/webai.md`.
- **Post-process**: background removal (Canva connector `remove-background`, chroma, or native matting
  in phase 4), `vedit inbox vectorize <png>` for icons, resize and colour-match to the grade.
- **Second opinion on the render**: Gemini watches video natively. Ask per project before uploading the
  owner's video there; treat its notes as hints and verify them on the frames.

## 4. Build what is missing

When templates fall short, write it: a composition in `edit/custom/<name>.html` (GSAP, SVG, Canvas,
Three.js, shaders), a Python FX that draws per frame, an FFmpeg filter at a render hook, or audio DSP.
Save the good ones for next time (`vedit template save`, `vedit fx save`). See `references/extending.md`.
If a capability is truly missing (a tracker, a matting model, a converter), find an open-source tool and
install it through `vedit tools vet` / `vedit tools add`, with the owner's yes.

## 5. Learn techniques you don't know yet

Asked for a look you can't name the recipe for ("Apple keynote text reveal", "MrBeast glitch title")?
1. `vedit technique list` first; maybe it is already known.
2. Search the web and YouTube tutorials; watch one: `vedit fetch <url> --to <folder>` (reference only),
   `vedit watch <file> --file` for the frame grids, `vedit transcribe` or its captions; or study a reference
   with `vedit style analyze`.
3. Rebuild it natively, check it on frames, then save the recipe: `vedit technique save <name> --file
   recipe.md` (what it is, when to use it, the exact parameters, which engine).

## 6. Creative directions (plan mode opens with these)

Write 2-3 genuinely different treatments, not three shades of one. Each has a title, a one-line
treatment, which line opens (hook), pacing (with the pace value), look (grade), sound palette, caption
style, a mood board (3-6 images from the browser, Pinterest, web AI or your own drawings, logged with
provenance), and the ops that set it up:
```json
{"id": "punchy", "title": "Punchy retention", "treatment": "Fast cuts, bold captions, firmer zooms",
 "hook": "Opens on 'I thought I couldn't do it'", "pacing": "Tight (pace 0.8)", "look": "Punchy",
 "sound": "Whooshes on moves, pop on reveals", "captions": "Hormozi",
 "moodboard": [{"src": "/_blob/<asset id>", "credit": "pinterest:<url>"}],
 "ops": [{"op": "knob", "id": "pace", "value": 0.8}, {"op": "set", "path": "captions.style", "value": "hormozi"}]}
```
`vedit directions add <p> --file directions.json`. The owner picks one in the Studio; build the draft
around it (or around your recommendation in auto mode).

## 7. The critique loop: judge before the owner sees it

Look and listen to evidence, not the JSON: `vedit watch <p> --render` (scene grids of the draft), a
preview render (`vedit render --preview`) with `vedit qa` (cut sheets, SFX sync, and earshot's ears when
installed), the storyboard. Score the draft against this bar, fix, and look again (three rounds at most;
two automatic rounds in auto mode):

- **Hook**: the strongest line or image lands in the first 1.5 s; no dead air or throat-clearing before it.
- **Rhythm**: on short-form something changes every 2-4 s (cut, punch-in, graphic, b-roll, caption
  emphasis); on long-form every 6-10 s. Pace varies: faster through lists, room after a punchline.
- **Clean cuts**: no retakes, false starts, clipped words, source title cards or fades at cut points
  (QA flags `source_cut` / `source_fade`).
- **Captions**: three words or fewer on shorts, emphasis on the words that matter, never over faces or
  platform UI (check the safe zone), Bangla shaped and never uppercased.
- **Graphics**: pinned to their words, clear of faces and safe zones, one visual system (brand colours
  and type), motion that eases in and out.
- **Sound**: SFX on motion and reveals (not on every cut), each one audible and on its cue (QA
  `sfx_sync`), music ducks under speech and steps down before big hits, -14 LUFS integrated, true peak at
  or under -1 dBTP, no pops at cuts.
- **Words on screen**: titles, lower thirds and post copy pass `vedit text check <p>` (no machine-sounding
  phrasing; short enough to read in a glance).
- **Look**: one consistent grade, natural skin.
- **Ending**: the payoff, then a CTA, then out. No trailing silence or black.
- **Platform**: ratio, length, captions burned or sidecar as the platform needs.

QA measures parts of this bar for you. Trust a measured flag over your eye: a label cut off at the frame edge
looks fine on a contact sheet.
- `text_cut` / `text_ui` / `text_overlap`: words in graphics and animated pieces cut off by the frame, under
  the platform UI, or over other words; caption words too wide to wrap.
- `static`: no cut, graphic, b-roll or move for over 4 s on shorts (8 s on long-form) while the picture barely
  changes. The knob `qa_static_max` changes the limit.
- `pace`: generated VO lines over 3.5 words/s in English (3.0 in Bangla): rewrite them, or give them time.
- `beat_grid`: cuts off the grid of a music clip marked `sync` (`vedit beats snap` fixes them).
- `sound_arc`: with a `payoff` marker, no silence (at least 0.4 s at -40 dBFS or quieter) before the loudest
  moment, or the loudest moment is not on the payoff.

What is a matter of taste rather than quality becomes a suggestion card (below) instead of your silent
choice.

## 8. Suggestion cards

Offer cards for real choices: hook A/B, caption style, a graphic or none, music mood, how tight the cut
is. Don't turn every detail into a question. Each option is concrete ops; `default` is your
recommendation; `reason` is one line in plain words.
```json
{"id": "hook_ab", "kind": "hook", "title": "Which line opens?", "reason": "B is stronger but 2 s longer",
 "at": {"start": 0, "end": 3},
 "options": [{"id": "a", "label": "Keep 'I thought I couldn't'", "ops": []},
             {"id": "b", "label": "Open on the lesson", "ops": [{"op": "move_clip", "clip": "m005", "index": 0}]}],
 "default": "b"}
```
`vedit suggest add <p> --file cards.json`. Ops vocabulary: `scripts/vedit/ops.py` (and
`references/studio.md`).

## 9. Deep review (only when the owner asks for agents)

For a high-stakes edit the owner can ask for parallel critics. Give each lens (director, pacing,
captions, sound, look) the same evidence (frames, QA report, transcript) and the checklist above; merge
their findings, verify each on the frames, fix.
