# Higgsfield (optional)

Generative video/images for moments the footage can't cover. The skill works fully without it.

## Detect / set up
`vedit higgsfield status` shows whether the CLI or the MCP connector is available.
- Claude Code (recommended): `npm i -g @higgsfield/cli` → `higgsfield auth login` (browser sign-in,
  no API key) → `npx skills add higgsfield-ai/skills` (adds /higgsfield:* skills).
- Connector: `claude mcp add --transport http higgsfield https://mcp.higgsfield.ai/mcp`, or add
  Higgsfield under Connectors in Claude Desktop / claude.ai.
Generations use the user's plan credits (an active subscription is required; "unlimited" web plans do not
cover agent generations). Clips are silent and up to ~15 s; resolution up to 4K depending on model.
Read `higgsfield --help` (and the higgsfield-generate skill) for current commands and models: they change.

## Uses
- **AI b-roll**: establishing shots, metaphors, things you can't film. 3-6 s, match the edit's ratio and grade.
- **Images & stills**: backgrounds, product shots, thumbnail art; animate them with a custom composition
  (parallax, push-in) or Ken Burns via `zoom`.
- **VFX / hero shots**: logo reveals, 3D product spins, stylised transitions.
- **Faceless scenes**: characters/avatars; lip-sync to the user's voiceover where the model supports it.

## Credit approval flow (required)
1. Plan shots: purpose, model, prompt, duration, aspect, estimated credits.
2. `vedit higgsfield propose <p> --file shots.json` (records the plan), show it as a table with the total.
3. Wait for an explicit yes (edit the plan on feedback). Then `vedit higgsfield approve <p> --plan <id>`.
4. Generate only the approved shots (CLI/skill/MCP).
5. `vedit higgsfield import <p> --src <file-or-url> --shot <id> --model <m> --credits <n> --prompt "<p>"`
   → saved in `edit/assets/higgsfield/`, registered as a source, provenance + ledger updated.
6. Place as `broll` or `overlays`. `vedit higgsfield spent <p>` reports credits used.

## Prompting
Describe subject, action, camera (dolly-in, handheld, top-down), lens/light (35 mm, golden hour, soft
key), style matching the edit's grade, and the aspect ratio. Avoid real people's likeness and brands
unless the user owns the rights. Generate one test shot before a batch.
