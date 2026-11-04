# Routes: ways to make each thing

`presets/routes.json` lists, per need, the ways vedit and this session can produce it. Each route has
requirements, a cost class, and 1-5 scores for quality and speed, plus a licence and privacy class.

```
vedit route needs                  # needs and their route ids
vedit route plan icon              # ranked, available first, with what is missing for the rest
vedit route plan scene_clip --all  # include unavailable routes with full detail
vedit route log icon webai_image kept --project reel_12 --note "Gemini, 3rd variant"
```

Requirement vocabulary: `core:<key>` (engine), `addon:<id>`, `model:<id>`, `connector:<name>` (an MCP
connector you recorded), `browser`, `webai:<service>` (recorded as logged in), `secret:<name>`,
`tool:<name>`, `web:` (always there). `a|b` means either.

Ranking = 2 x quality + speed + cost (free 3, subscription 2, paid 1, credits 0) + licence (own 3, CC or
stock 2, AI service or unknown 1) + 1 if local, plus the owner's history: a route they kept 3+ times in a
row climbs, rejected routes sink, and failing requirements (`vedit capabilities outcome`) cost points.

Cost rules: free routes run without asking; subscription web AIs run within the per-project budget; paid
and credit routes always need an estimate and a yes.

Add your own: `personal/routes.json` (same shape) or `ROUTES` in a personal extension. Routes are advice,
not rails: combine them, or invent a better way and log it.

Animation:
- `animation` (explainers, histories, stories, product reels) ranks the shipped styles first (`anim_styles`),
  then a look made from the owner's references (`anim_new_style`), custom HTML, and AI video for photoreal
  moments.
- `scene_clip` offers an animated insert (`anim_scene`).
- `motion_graphic` offers doodles over footage (`anim_overlay`).
- `music` offers a bed made in code (`code_score`, below the owner's tracks and good library music).
