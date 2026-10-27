# Pinterest research and assets (Claude in Chrome)

Use the Claude in Chrome connector (tools `mcp__claude-in-chrome__*`; load the browser skill first if one
is available). Work in a new tab, browse like a person (a few searches, scroll, open pins), never bulk-scrape.

## Modes
1. **Ideas + mood board (default)**: research layout, typography, colour, motion and thumbnail ideas.
   Save references locally for your own design work:
   `vedit download <p> <image-url> --source pinterest --page <pin-url> --notes "moodboard: caption style"`
   (saved under `edit/assets/pinterest/` with provenance). Summarise what you learned (palette hex codes,
   font vibes, composition patterns) and apply it to captions, graphics and the grade.
2. **Download and use**: when the user wants a specific pin in the video, download it the same way with
   `--register` (adds it as a source) and place it as b-roll/overlay. Most pins are someone else's
   copyrighted work: say so once, especially for client/commercial work, and respect the user's call.
   Prefer pins that link to a source with a clear licence; record the licence with `--license`.

## Getting the image URL
Open the pin, then read the main image element's `src` (prefer the `originals` size if present) via the
page reading or JavaScript tool. Videos/GIF pins: download the media URL the page exposes; if it is
streamed (m3u8), note it and ask the user for the file instead.

## Good research queries
"<niche> reels editing style", "<colour> aesthetic caption font", "kinetic typography poster",
"<brand vibe> colour palette", "youtube thumbnail <topic>", "lower third design minimal".
Always tie findings back to the current edit: what you'll change and why.
