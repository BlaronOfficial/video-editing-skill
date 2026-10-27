# Captions

Built from word timestamps mapped through the cut, so they stay in sync after every edit.

```
vedit captions styles                       # list presets
vedit captions build <p> --style hormozi    # writes captions.chunks into edit.json
vedit captions export <p> --format srt      # sidecar SRT/VTT/ASS (uploads, translations)
```

## Presets
karaoke_pop (default shorts) · hormozi (1-2 huge words) · bold_box (boxed, ads/explainers) ·
clean_minimal (corporate/education) · soft_serif (aesthetic / "cool girl") · neon_glow (night/gaming) ·
comic_pop (kids/comedy, one word at a time) · bangla_bold (Bangla-first) · podcast_lower (sentences).
Personal presets: `personal/styles/captions/<name>.json` (same keys). Brand kits override highlight
colour and fonts automatically.

Style keys: mode karaoke|word|chunk|sentence, max_words, max_chars, font, font_bangla, size (fraction
of the short side), color, highlight, stroke, stroke_width, shadow, shadow_color, background
{color, alpha}, y, y_landscape, uppercase, bold, pop_scale, animation pop|fade|slide|none,
capcut {font, intro, size_scale}.

## After building, always review chunks
- Fix misheard words, names, brands, numbers (Whisper guesses; Scribe is better).
- Add `emphasis` (word indices) on the words that carry the meaning; add an `emoji` on emotional beats
  (rendered in the MP4; CapCut keeps the text).
- Move a chunk (`y`) when a face, product or on-screen text would be covered.
- Split chunks that span a cut or a speaker change.

## Bangla and Banglish
- Transcribe with `--language bn` for Bangla; for Banglish, Scribe without a language code usually
  keeps English words in Latin script, which reads best. Whisper may write English words in Bangla
  script or translate them: correct chunks by hand when that happens.
- Bangla text is never uppercased or split into characters; fonts: Hind Siliguri (default), Tiro Bangla
  (formal), Galada (display), Atma (playful). Shaping (conjuncts like ক্ষ, ন্ত) is handled by
  libass/HarfBuzz in the render and by CapCut natively.
- Mixed lines use the Bangla font for the whole chunk so the baseline stays consistent.

## Translations / bilingual
Export SRT, translate the chunk texts yourself (keep timings), and either add them as a second caption
track (a `texts` list per chunk with smaller size, higher `y`) or deliver SRT files for platform upload.
