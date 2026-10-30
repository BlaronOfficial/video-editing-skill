# Web AI tools in the owner's browser (optional)

If the owner is already signed in to an AI tool in their browser, you can use it for images, icons,
elements, illustrations, scenes, video clips and music, the way they would by hand. Nothing here is
required: the free core and your own drawings always work. This is opportunistic: use it when it makes
the edit better.

## 1. Probe (once per session, only when the plan could use it)
With the best browser tool (Claude in Chrome first), for each service the plan could use: open its home
page in a **new tab**, wait for it to load, read whether an account is signed in (an avatar, account menu
or the app itself vs. a "Sign in" button), note the plan if it is visible, close the tab. Record it:
```
vedit capabilities record --webai gemini=logged_in,chatgpt=logged_out,ideogram=logged_in
```
Never sign in, type credentials, approve 2FA, accept new terms or solve CAPTCHAs: if a service is signed
out, it is simply unavailable. Tell the owner in one line which ones you found.

| Service | URL | Good for |
|---|---|---|
| Gemini (Imagen / Nano Banana, Veo) | gemini.google.com | images, edits of an image, icons and elements, Veo clips (quota) |
| ChatGPT | chatgpt.com | images with text in them, edits, consistent characters |
| Canva | canva.com or the Canva connector | backgrounds removed, layered designs, thumbnails with the brand kit |
| Adobe Firefly / Express | firefly.adobe.com | commercially safe images, text effects, generative fill |
| Ideogram | ideogram.ai | typography and logos inside images |
| Leonardo / Krea / Freepik | leonardo.ai, krea.ai, freepik.com | stylised images, upscales, quick variants |
| Suno / Udio | suno.com, udio.com | music beds (free tiers non-commercial) |
| Runway / Kling / Luma | runwayml.com, klingai.com, lumalabs.ai | short generated shots (credits: always ask) |

## 2. Budget and asking
- Subscription tools: fine within `config webai.budget_per_project` (default 12 generations); past that,
  ask.
- Credit-metered tools (Runway, Kling, Luma, Veo beyond the free quota, Higgsfield): estimate and ask
  before every batch.
- Bulk generation on the owner's account (more than a handful at once), and uploading the owner's own
  footage or photos to a service: ask once per project.

## 3. Prompt like an art director
Write prompts from the brand kit and the chosen creative direction so every asset belongs to one visual
system:
- subject and action; composition with room for the text that goes over it; camera, lens and light;
- the brand colours as hex; the direction's mood words; the aspect ratio of the slot (9:16 full-frame,
  1:1 card, 16:9 plate);
- for **elements and icons**: one object, centred, flat single-colour background (pure green #00FF00 or
  white, whichever the object does not use), no shadow, no text: easy to cut out and vectorise;
- **no text inside images** unless the tool is good at it (Ideogram, ChatGPT) and the text is final;
  otherwise set type natively on top (crisp, editable, captions-safe);
- for a series, reuse one style line in every prompt and generate in one conversation.
Generate 2-4 variants, pick, refine one. Look at each before using it.

## 4. Bring it in
```
vedit inbox mark                                   # before you generate
... generate, then use the site's own Download button (files land in Downloads) ...
vedit inbox pull <p> --service gemini --prompt "<the prompt>" --url <conversation url> --register --wait 30
```
Then post-process: background removal (Canva connector `remove-background`, `colorkey` on a flat
background, or native matting), `vedit inbox vectorize <png>` for icons that should scale, resize and
colour-match to the grade. Generated video clips are silent: add sound in vedit.

## 5. Licences
Note each service's terms for the owner's plan in provenance (`inbox pull` adds a reminder per service)
and flag before publishing: free-tier music (Suno, Udio) and some free image tiers are non-commercial or
public; Firefly is positioned as commercially safe; Gemini images carry an invisible SynthID watermark.
Terms change: when the use is commercial, check the current terms page and tell the owner.

## 6. Stop and tell the owner
At login walls, CAPTCHAs, payment or upgrade prompts, new-terms dialogs, error pages that repeat, or
anything that looks like the owner's private data (other chats, email). Work only in tabs you opened.

## 7. Second opinion on a render (ask per project)
Gemini can watch a video. With the owner's yes, upload the preview render in a new Gemini chat and ask
for a critique against the checklist in `references/director.md`. Treat its notes as hints: verify each
on the frames before changing anything.
