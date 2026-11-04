# Performance learning (YouTube)

How a published video actually held viewers, mapped back onto the edit that made it.

```
vedit publish link <p> --url https://youtu.be/<id>          once, after the owner uploads the render
vedit analytics import <p> --csv retention.csv             a retention export from YouTube Studio (no setup)
vedit analytics pull <p>                                    or the YouTube Analytics API (owner's OAuth, below)
vedit analytics report <p>                                  drops, rewatches, element lifts, chart PNG
vedit analytics learn <p>                                   into the profile and the route planner
```

Read the chart (`edit/analytics/<id>_retention.png`) and the insights, then tell the owner in plain words
what held and what lost viewers, with times. Typical findings: the hook (retention at 3 s and 5 s), drops
during pauses or slow explanations, rewatches on graphics or a punchline.

## Data

- **CSV (no setup)**: YouTube Studio > Analytics > Advanced mode > the video > Audience retention > export.
  Positions as %, ratio or time and retention as % or ratio are all read; with time positions vedit uses the
  linked video's length.
- **API**: the owner creates an OAuth client (Google Cloud console > enable "YouTube Analytics API" and
  "YouTube Data API v3" > Credentials > OAuth client ID > Desktop app > download JSON), then
  `vedit analytics auth --client-secret client.json`. Their browser opens; they sign in and allow read-only
  access themselves (never type their password for them). The refresh token stays in
  `personal/secrets.json`. `pull` reads views, watch time, average view duration and percentage, likes,
  shares, subscribers gained, and the retention curve (`audienceWatchRatio`, relative retention).

## What the report means

- `summary`: retention at the start, 3 s, 5 s, 30 s and the end, the average, and the typical slope
  (points per second in the middle 80 %). `same_cut: false` means the upload is not this edit's length.
- `drops`: stretches losing viewers at 2.5x the typical rate (and at least 1 point/s), each with what was on
  screen: clip, words, pause length, graphics, b-roll, cuts. `rewatches`: stretches where retention rose.
- `lifts`: each graphic, b-roll shot and sound effect against the typical slope (+ = held better). Graphics
  that run most of the video (progress bars) are left out.

`learn` stores the result as a `performance` event and adds each element's lift to its route
(`personal/learning/performance.json`); after two observations the route planner nudges that route up or
down (at most 2 points). The profile's `performance` block keeps median hook and average retention and the
usual drop causes; use them when planning the next edit (`vedit learn profile`).
