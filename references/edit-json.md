# edit.json reference

Single source of truth for one edit. Times are seconds. `src_in/src_out` are inside the source file;
`start` is on the timeline. Positions use CapCut's convention: `x`, `y` in half-canvas units from the
centre, **+y is up** (`y: -0.42` = lower third of a vertical frame). Full JSON schema: `vedit plan schema`.

```json
{
  "name": "reel_ai_editing",
  "canvas": {"width": 1080, "height": 1920, "fps": 30, "background": "#000000"},
  "style": "cool_dude", "brand": "arete",
  "sources": {
    "a_roll": {"id": "a_roll", "path": "D:/shoot/a_roll.mp4", "kind": "video", "duration": 312.4,
               "width": 1920, "height": 1080, "transcript": "D:/shoot/edit/transcripts/a_roll.json", "origin": "camera"},
    "song": {"id": "song", "path": "D:/lib/music/drive.mp3", "kind": "audio", "origin": "library"}
  },
  "main": [
    {"id": "m001", "source": "a_roll", "src_in": 14.32, "src_out": 17.9, "label": "hook",
     "zoom": {"start_scale": 1.0, "end_scale": 1.12, "ease": "out"}},
    {"id": "m002", "source": "a_roll", "src_in": 31.0, "src_out": 39.4, "fit": "cover",
     "crop": [{"t": 0, "cx": 0.42, "cy": 0.4}, {"t": 3.2, "cx": 0.55, "cy": 0.4}],
     "transition_in": {"type": "dissolve", "duration": 0.3, "capcut": "叠化"}}
  ],
  "broll": [
    {"id": "b01", "source": "city", "src_in": 2.0, "src_out": 4.5, "start": 6.1, "fade_in": 0.15, "label": "city"}
  ],
  "overlays": [
    {"id": "hook_title", "start": 0.2, "duration": 2.6,
     "mg": {"engine": "auto", "template": "title_card",
            "data": {"kicker": "NEW", "title": "Edit 10x faster", "highlight": ["10x"], "y": 0.3}}},
    {"id": "custom_graph", "start": 9.0, "duration": 3.5,
     "mg": {"engine": "html", "file": "D:/shoot/edit/mg/growth_curve.html", "data": {"values": [3, 7, 19]}}}
  ],
  "captions": {"enabled": true, "style": "hormozi", "overrides": {"highlight": "#39FF6A"},
               "max_words": 2, "chunks": []},
  "texts": [{"id": "t1", "text": "@arete.studio", "start": 0, "duration": 3,
             "style": {"size": 0.04, "color": "#FFFFFF"}, "transform": {"y": 0.82}, "capcut_intro": "fade"}],
  "audio": [
    {"id": "mus", "source": "song", "start": 0, "volume": 0.18, "role": "music", "fade_in": 0.5, "fade_out": 1.5},
    {"id": "s1", "source": "whoosh1", "start": 6.0, "volume": 0.7, "role": "sfx"}
  ],
  "effects": [{"id": "fx1", "start": 12.0, "duration": 0.4, "render": "flash", "capcut": "闪白"}],
  "color": {"preset": "teal_orange", "capcut_filter": "teal_orange", "intensity": 0.8},
  "capcut": {"project_name": "reel_ai_editing_v1", "pro_allowed": false, "overlay_mode": "auto"},
  "output": {"audio": {"denoise": true, "voice_enhance": true, "target_lufs": -14, "duck_db": -14}}
}
```

## Fields

**main[]** (back-to-back; `start` is computed) - `speed`, `volume` (linear), `mute`, `fit` cover|contain
(contain = blurred background) |stretch, `transform` {scale, x, y, rotation, opacity}, `zoom`
{start_scale, end_scale, ease linear|in|out|inout|hold, anchor_x, anchor_y}, `crop` (auto-reframe keys,
written by `vedit reframe`), `transition_in` (drawn across the cut from handles; never changes timing),
`fade_in/out`, `audio_fade_in/out`, `color` (per-clip grade), `capcut_filter`,
`capcut_animation_in/out`, `label`. VFX (source space, `references/vfx.md`): `redact[]` entries with
`track` (tracked blur), `screen[]` (planar inserts), `subject` {background, outline, glow, above} (person
cut-out), `dof` {focus auto|0..1, range, blur, pull}. Transitions also take whip_left|whip_right|whip_up|
whip_down|zoom_blur; a clip with no source handle holds its edge frame.

**broll[]** - like main clips plus required `start`. Muted. `fit`, `transform` (PiP: scale 0.45, x 0.45, y 0.5).

**overlays[]** - `start`, `duration`, `layer` (stacking), `transform`, `fit` none|cover|contain,
`fade_in/out`, `chroma` (#hex key colour if the media uses a green screen), and either `path`
(ready media: alpha .webm/.mov, .png, .gif) or `mg` {engine auto|html|hyperframes|remotion|pil,
template | file, data, width, height}. `vedit mg render` fills `path` and `renders`.

**captions** - `style` (see `vedit captions styles`), `overrides` (any style key), `engine` ass,
`max_words`, `max_chars`, `uppercase`, `chunks[]` {start, end, text, words[{w,s,e}], emphasis[idx],
emoji, y}. Empty chunks = generated from transcripts through the cut at render/build time.

**texts[]** - titles/labels as native CapCut text (and burned in the render): `style` {font, size
(fraction of the short side), color, stroke, stroke_width, background {color, alpha}, bold, animation
pop|fade|slide}, `transform`, `capcut_intro/outro/loop` (CapCut text animation names or aliases).

**audio[]** - `source`, `start`, `src_in`, `src_out`, `volume`, `role` music|sfx|vo|ambience, `duck`
(default true for music/ambience), `fade_in/out`, `loop`.

**tracks[]** - written by `vedit vfx track|faces|screen`: `{id, source, kind object|face|planar, t0, t1, file}`.
Overlays take `attach` {track, offset [x, y], point center|top|bottom, smooth} to follow one.

**effects[]** - `start`, `duration`, `render` (motion_blur|handheld|whip|flash|shake|zoom_pulse|blur|glitch|rgb_split|vignette|
film_grain|bw) and/or `capcut` (+ `capcut_params`), `intensity`.

**color** - `preset` (warm_cinematic, moody, clean, teal_orange, bw, vintage, pastel, vibrant, cool,
golden, matte, punchy), `lut` (.cube path), `capcut_filter` (name or alias), `intensity` 0-1.

**capcut** - `project_name`, `pro_allowed`, `include_captions`, `overlay_mode` auto|alpha|chroma|flatten.

**anchor** (on overlays, texts, audio, effects, custom_fx, markers) - `{source, t, offset, policy}`: pins the item
to a moment inside a source (usually a word's start). Its `start` is recomputed through the cut, so it
follows its word when clips are trimmed, removed or re-paced. `offset` shifts it on the timeline;
`policy` decides what happens when the moment is cut out: `nearest` (default, snap to the closest kept
point), `drop` (disable it), `keep` (leave `start` alone). Get anchors with `vedit words <p> --find "try it"`.

**enabled** (same items) - `false` hides an item without deleting it (the Studio's Hide).

**custom_fx[]** - code you write for this edit: `{id, kind python|ffmpeg|html, file, hook, filter,
params, inputs, output overlay|audio|source, start, duration, anchor, transform, fit, layer, volume}`.
See `references/extending.md`.

**markers[]** - notes on the timeline that travel into every hand-off: `{id, t, duration, name, note,
kind note|chapter|todo, color, anchor}`. Chapters become NLE chapter markers, YouTube chapter lines and
file chapters; `vedit marker add <p> --t 12.4 --name ... [--kind chapter]` anchors them to the words under
that moment so they follow re-cuts. See `references/handoffs.md`.

**knobs** - Studio tuning values applied at bake time without touching your decisions: `pace` 0-1,
`transitions`, `zoom_strength`, `grade_preset`, `grade_intensity`, `captions_on`, `caption_style`,
`caption_size`, `caption_y`, `caption_words`, `voice_level`, `music_level`, `sfx_level`, `duck_db`,
`graphics_on`. `vedit knobs list|get|set|unset|bake <p>`; definitions in `presets/knobs.json`.

**captions** (v2 additions) - `word_fixes` {"<source>@<start>": "text"} corrects misheard words (empty
text hides a word), `emphasis_keys` and `emoji_keys` mark words, and all three survive re-cuts. Set
`from_words: false` when you wrote the chunks yourself (a translation, reworded captions) so they are
kept as written.

**revision** - bumped on every save; the Studio uses it to know which edit is newest.

**output** - `audio` {denoise, voice_enhance, target_lufs, duck_db}, `encoder`, `crf`, `preset`.

## Editing tips
- Keep ids stable when revising so QA notes, suggestion cards and the Studio stay meaningful.
- Pin graphics, texts and SFX that belong to words with an `anchor` instead of a fixed `start`; then
  re-cuts and the pace knob never knock them off their word.
- After changing `main`, rebuild captions (`vedit captions build`) unless you hand-edited chunks
  (`from_words: false`).
- Every output (render, QA, CapCut, Studio) uses the baked edit: `vedit knobs bake <p>` shows its timing.
