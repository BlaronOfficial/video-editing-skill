# Writing pass (English)

Anything you write that the audience reads or hears gets a writing pass: titles, hooks set as text, lower
thirds, callouts, chapter titles, thumbnail text, post copy (descriptions, captions for the post,
hashtags) and voiceover scripts. Never "fix" captions of real speech: they show what was said.

```
vedit text check "<text>" [--kind title|onscreen|post|script]
vedit text check <p>          # every text item, graphic text, edit/post/*.md and edit/scripts/*.md
```
It flags patterns that make text sound machine-written. Strong ones are worth fixing on their own; weak
ones only in clusters. Then reread the text yourself: the checker finds patterns, you judge the voice.

## Write like this
- Say the thing. "Cut by the transcript" beats "It's not just about cutting, it's about storytelling."
- Plain words over impressive ones: "use", "show", "help", not "leverage", "showcase", "empower";
  "is" and "has" instead of "serves as", "stands as", "boasts".
- Specific beats grand: numbers, names, what happens. No "pivotal", "testament", "game-changer",
  "in today's fast-paced world".
- No staged run-ups ("Here's the thing:", "The truth is"), no imaginary objections ("You might think..."),
  no trailing "-ing" commentary (", highlighting the importance of...").
- Name the source or drop the authority ("experts agree").
- Lists only when there really are that many things; not every list has three items.
- Commas and full stops over dashes; few exclamation marks; no emoji in headings.
- Match the owner's own voice: reuse their phrases from the transcript, their language mix (Banglish
  stays Banglish).

## Video text formats
- On-screen text: 7 words a line at most, read in under a second per 3 words; keep it inside safe zones.
- Titles: under ~70 characters (cut on mobile); the promise first.
- Thumbnails: 2-5 words, different from the title.
- Post copy: first line works alone (it is all most people see); 3-5 specific hashtags.
- Voiceover scripts: short sentences, written to be said aloud; read them out (or let TTS) and cut what
  trips.

## Credits
The pattern list follows blader/humanizer (MIT, github.com/blader/humanizer) and Wikipedia's "Signs of AI
writing" by WikiProject AI Cleanup. The wording and the checker here are our own.
