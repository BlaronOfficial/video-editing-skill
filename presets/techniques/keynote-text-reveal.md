---
name: keynote-text-reveal
tags: text, title, premium, apple, minimal
description: Calm premium title: each line rises out of a mask while blur clears and tracking tightens
---
# Keynote text reveal

**Use for**: product launches, calm explainers, premium brands, chapter titles. Not for meme energy.

**Engine**: custom HTML composition (GSAP), `edit/custom/<name>.html`, rendered with alpha.

**Recipe**
- Type: a grotesk at weight 600-700 (Poppins SemiBold or the brand face), white or ink, size 7-9 vmin,
  letter-spacing starting at 0.08em and easing to -0.01em.
- Each line sits in a `overflow: hidden` wrapper. Animate `yPercent: 100 -> 0`, `filter: blur(12px) -> 0`,
  `opacity 0 -> 1` over 0.9 s with `expo.out`, lines staggered by 0.12 s.
- Optional underline: a 0.4vmin bar scaling `scaleX 0 -> 1` from the left, 0.6 s `power3.inOut`, starting
  0.3 s after the last line.
- Hold at least 1.2 s. Exit: `yPercent 0 -> -100` with `power3.in` over 0.4 s, lines in reverse order.
- Sound: a soft riser into the reveal is too much; use one rounded pop or nothing.
- Bangla: split by word only (`V.split(el)` does this), never by character.
