# Modes, stages, approvals

State lives in `edit/project.json` under `workflow` (mode, plan_status, stage, approved_stages, history),
so a later session, or the Claude app, continues where this one stopped.

```
vedit mode <p>                     # show
vedit mode <p> plan|step|auto      # set (default for new projects: config mode.default = plan)
vedit workflow status <p>
vedit workflow approve <p> [--stage cut|captions|graphics|sound|look|final]
vedit workflow request-changes <p> --note "..."
vedit execute <p> [--force] [--no-qa]
```

## Plan (default)

1. Intake, discover, understand (SKILL.md loop steps 1-3).
2. Creative directions (2-3) and a full draft built around your recommended one.
3. Critique loop until the draft meets the checklist (`references/director.md` section 7).
4. Studio: build, sync, give the owner the link (`references/studio.md`). Status becomes `in_review` when
   their first edits arrive.
5. Iterate on Send to Claude notes. Nothing renders final, hands off, or spends money meanwhile; preview
   renders (`vedit render --preview`) are fine when you need to look at something.
6. Approve arrives (button or chat): Execute.

## Step-by-step

The same Studio, gated per stage: `cut` → `captions` → `graphics` → `sound` → `look` → `final`. Build
each stage's work, sync, wait for "Approve <stage>". Approving `final` approves the plan. Stage meanings:
cut (structure, takes, pacing), captions (style, fixes, emphasis), graphics (titles, overlays, b-roll),
sound (music, SFX, levels), look (grade, effects, VFX), final (everything together, then Execute).

## Auto

Run the whole loop without stopping: pick the direction yourself, run two critique rounds, Execute,
then sync the Studio so the owner can review afterwards. Edits they make there trigger a re-execute.
Batch the questions you would otherwise ask later (downloads with sizes, paid credits, uploads to
third parties) into the intake question, once.

## Execute

`vedit execute <p>` refuses unless the plan is approved (or the mode is auto, or `--force` because the
owner explicitly asked to render now). It renders every motion graphic, runs every custom FX, renders the
final video (knobs baked, anchors resolved), runs QA, and marks the project executed. Then you:
1. read the QA report and look at its frame sheets; fix and re-run until clean (three rounds at most);
2. make the hand-offs chosen at intake (CapCut: `vedit capcut build`; DaVinci, NLE XML and LosslessCut
   arrive in phase 3);
3. thumbnail and post copy (`references/extras.md`);
4. report the output path, duration, loudness and anything the owner should check.

Claude Code's own plan mode blocks file writes, so the engine cannot run inside it. The skill's Plan mode
is a separate thing: use it from normal (or auto-accept) mode.
