# Learning from the owner

Everything below lives in `personal/` (git-ignored) and is read at the start of each project.

| Source | How it gets in | What it teaches |
|---|---|---|
| Studio decisions | `vedit studio apply` logs every op | knob values per style/brand/format, which suggestion kinds and templates they keep, caption fixes |
| Chat feedback | `vedit learn note "<rule>" --scope global\|style:<s>\|brand:<b>\|format:9:16` | plain rules you must follow ("never use risers", "captions one size bigger on 9:16") |
| Routes | `vedit route log <need> <route> kept\|rejected\|failed` | which ways of making things this owner likes; ranking follows |
| Editor diffs | `vedit capcut diff <p> --learn <style>` (DaVinci, NLE XML and LosslessCut in phase 3) | what they change after the hand-off: caption size and position, music level, trims |
| Video performance | phase 5: YouTube Analytics with their own OAuth | which hooks and pacing keep viewers |

```
vedit learn profile --style hormozi --brand acme --ratio 9:16    # knob defaults + favourites + rules
vedit learn rules
vedit learn rebuild                                               # re-aggregate events
vedit learn events --tail 30
```

How to use it:
- At intake, read `vedit learn profile` and `vedit learn rules`; apply the knob defaults to the new edit
  (`vedit knobs set`) and follow every rule.
- When you write suggestion cards, put the option the owner usually keeps as the default, and skip cards
  for choices they always make the same way.
- When the owner corrects you in chat ("too choppy"), fix it, then save it as a rule with the right scope,
  and say so in one line.
- Never store secrets or other people's data here; the profile is the owner's taste, nothing else.
