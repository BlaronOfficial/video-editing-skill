# Driving the CapCut UI

Project files cover the timeline. Use the UI only for what files cannot do: exporting from CapCut,
CapCut-only AI features (auto captions with CapCut templates, AI effects, enhance voice), adding items
from CapCut's online library (music, SFX, stickers, templates), and visual confirmation.

## Which tool
- **Claude Code Desktop app** (Windows/macOS): built-in computer use. Enable it in Settings; tools are
  `mcp__computer-use__*` (screenshot, click, type, key, scroll).
- **Windows-MCP from the CLI**: `claude mcp add --scope user --transport stdio windows-mcp -- uvx windows-mcp serve`
  (Python 3.13+). Tools: `Screenshot`, `Snapshot`, `Click`, `Type`, `Shortcut`, `Scroll`, `Move`, `App`, `WaitFor`.
- **Neither**: `vedit screen shot --out shot.png` lets you see the screen; `vedit screen click --x --y`
  and `vedit screen keys` act only when CapCut owns the foreground. Prefer asking the user to click.
CapCut draws a custom UI, so accessibility trees are thin: work from screenshots and coordinates.

## Safety (non-negotiable)
- Ask before taking over the screen; the user may be working. Check `vedit screen foreground` first.
- Only interact with the CapCut window. Never touch other apps, the taskbar, or OS dialogs (firewall,
  UAC, permissions): ask the user to answer those.
- Take a screenshot before every click and verify the result after it.
- Never log in, buy, upgrade, or change account/subscription settings.

## Recipes (CapCut 9.x desktop; layouts shift between versions, always confirm visually)
**Open the generated project:** Home → Projects grid → click the card with the project name (newest first).
A "Turn on notifications?" dialog may appear on launch: click Cancel.

**Export:** top-right **Export** → set Name, Resolution (1080p/4K), Frame rate (match the edit: 30),
Format MP4, Codec H.264, (Bit rate: Recommended/Higher) → Export → wait for 100% → close the dialog.
Pro features in a free account trigger a paywall at export: stop and tell the user.

**Auto captions (CapCut styling):** Captions tab → Auto captions → spoken language → Generate.
Then pick a caption template in Text → Templates. Use only if the user prefers CapCut's styles; the
skill's own captions are already on the "captions" text track (delete one set to avoid doubles).

**Library music/SFX:** Audio tab → Music / Sound effects → search → hover → "+" to add at the playhead.
Note: CapCut library music is licensed for use inside CapCut/TikTok; warn before commercial/client use.

**Effects/filters/transitions by name:** use the matching tab's search box, drag onto the clip or click "+".

**Enhance voice / reduce noise:** select the main clip → Audio panel → Enhance voice / Reduce noise.

## Verifying a generated project without driving the UI
Launch CapCut (`vedit capcut launch`), ask the user to open the project, or take one screenshot
(`vedit screen shot`) when the user has said you may. Look for: canvas ratio, clips on the right tracks,
captions visible at the right height, no red "missing media" markers.
