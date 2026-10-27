# Editing craft

The engine executes; these are the judgement calls that make an edit good.

## Structure
- **Hook in the first 1-2 seconds.** Open on the most surprising, specific or emotional line, even if
  it was said later (move it to the front). Pattern: bold claim / question / result first, then "here's how".
  Pair it with a title_card or kinetic_text and a punch-in.
- **One idea per beat.** Cut tangents that don't serve the promise of the hook.
- **End clean:** last line lands, then CTA (subscribe_cta / handle) or loop back to the hook for shorts.
- Long-form: chapters every 2-4 minutes (chapter_title), re-hook after each section, b-roll every 5-15 s.

## Choosing takes
- `⟲ redone in P#` means the speaker restarted: keep the later, complete take unless the earlier one
  has more energy and is complete.
- Prefer takes with steady pace, no stumbles, eyes on lens, strong ending intonation.
- Use `vedit view` to compare candidates when the transcript can't tell (energy, face, gestures).

## Pacing
- Remove dead air: gaps over the style's `max_pause` (0.12 s hormozi … 0.6 s cinematic).
- Remove hard fillers (`~um~`) always; soft fillers (`°so`, `°like`, `°মানে`) only when they weaken the line.
- Keep breaths that carry emotion; don't machine-gun every gap in calm styles.
- **J/L cuts** (audio leads/trails video) for interviews and b-roll so cuts feel natural: put b-roll
  0.2-0.4 s before the word it illustrates.
- Punch-ins (zoom 1.0→1.08-1.15) hide jump cuts; alternate levels between consecutive cuts of the
  same shot. Never zoom so far that the face is cropped.

## B-roll
- Literal first (show the noun), then emotional. 1-3 s each in shorts, longer in cinematic edits.
- Cover jump cuts and long explanations; never cover the hook's face moment or punchlines.
- Match the grade. B-roll is muted; if its natural sound adds to the moment, add that sound as a quiet
  `ambience` audio clip so the voice always stays on top.

## Captions
- Position: vertical video 38-45% from the bottom edge is clear of TikTok/Reels UI (y ≈ -0.36…-0.45).
  Never under the face; move per chunk (`y`) when the subject is low in frame.
- 1-3 words for shorts, sentence mode for podcasts/long-form. Emphasise the money words.
- Bangla: no uppercase transform; keep spoken English words in English (Banglish).

## Motion graphics
- Every graphic must earn its place: emphasise, explain, or brand. Too many = noise (users often delete
  extras in CapCut; the learned profile will tell you).
- Enter on the word, exit before the next idea. Typical 1.5-4 s.
- Respect the safe zones: keep text out of the top 10% and bottom 20% of vertical frames and away from
  the right edge (platform buttons).

## Sound
- SFX on motion: whoosh on fast transitions/wipes, pop on emoji/text pops, click on UI, impact on
  text_punch, riser into reveals. Keep them 6-12 dB under the voice.
- Music: choose by style mood; duck under speech (automatic); swell in gaps and the outro.
- Final loudness: -14 LUFS for YouTube/TikTok/Reels/Shorts (engine default), true peak ≤ -1.5 dBTP.

## Platform specs
| Platform | Ratio | Length sweet spot | Notes |
|---|---|---|---|
| TikTok | 9:16 1080×1920 | 15-60 s | bottom ~20% and right edge covered by UI |
| Reels | 9:16 | 7-30 s (up to 3 min) | same safe zones; cover frame matters |
| Shorts | 9:16 | up to 3 min | loopable endings do well |
| YouTube | 16:9 1920×1080 or 4K | any | chapters, end screen last 20 s |
| Feed (IG/LinkedIn/FB) | 4:5 or 1:1 | 30-90 s | captions essential (muted autoplay) |

## Self-review checklist (before presenting)
Hook lands in 2 s · no stumbles left · no flash frames or black gaps · captions readable and correct ·
graphics on-beat and inside safe zones · music never fights the voice · ending clean · QA has no errors.
