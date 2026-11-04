"""Script text for speech: sentence splitting (English and Bangla), clean-up, numbers spelled for the offline
Bangla voices (they read Bangla script only; Edge and ElevenLabs normalise numbers themselves)."""

from __future__ import annotations

import re

BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# 0-99 in Bangla (each is its own word)
BN_0_99 = (
    "শূন্য এক দুই তিন চার পাঁচ ছয় সাত আট নয় "
    "দশ এগারো বারো তেরো চৌদ্দ পনেরো ষোলো সতেরো আঠারো উনিশ "
    "বিশ একুশ বাইশ তেইশ চব্বিশ পঁচিশ ছাব্বিশ সাতাশ আঠাশ ঊনত্রিশ "
    "ত্রিশ একত্রিশ বত্রিশ তেত্রিশ চৌত্রিশ পঁয়ত্রিশ ছত্রিশ সাঁইত্রিশ আটত্রিশ ঊনচল্লিশ "
    "চল্লিশ একচল্লিশ বিয়াল্লিশ তেতাল্লিশ চুয়াল্লিশ পঁয়তাল্লিশ ছেচল্লিশ সাতচল্লিশ আটচল্লিশ ঊনপঞ্চাশ "
    "পঞ্চাশ একান্ন বাহান্ন তিপ্পান্ন চুয়ান্ন পঞ্চান্ন ছাপ্পান্ন সাতান্ন আটান্ন ঊনষাট "
    "ষাট একষট্টি বাষট্টি তেষট্টি চৌষট্টি পঁয়ষট্টি ছেষট্টি সাতষট্টি আটষট্টি ঊনসত্তর "
    "সত্তর একাত্তর বাহাত্তর তিয়াত্তর চুয়াত্তর পঁচাত্তর ছিয়াত্তর সাতাত্তর আটাত্তর ঊনআশি "
    "আশি একাশি বিরাশি তিরাশি চুরাশি পঁচাশি ছিয়াশি সাতাশি অষ্টাশি ঊননব্বই "
    "নব্বই একানব্বই বিরানব্বই তিরানব্বই চুরানব্বই পঁচানব্বই ছিয়ানব্বই সাতানব্বই আটানব্বই নিরানব্বই"
).split()
assert len(BN_0_99) == 100


def bn_number(n: int) -> str:
    """Integer -> Bangla words (Indian grouping: হাজার, লাখ, কোটি)."""
    if n < 0:
        return "মাইনাস " + bn_number(-n)
    if n < 100:
        return BN_0_99[n]
    parts = []
    for size, word in ((10_000_000, "কোটি"), (100_000, "লাখ"), (1000, "হাজার")):
        if n >= size:
            q, n = divmod(n, size)
            parts.append(f"{bn_number(q)} {word}")
    if n >= 100:
        q, n = divmod(n, 100)
        parts.append(f"{BN_0_99[q]}শো" if q > 1 else "একশো")
    if n:
        parts.append(BN_0_99[n])
    return " ".join(parts)


def bn_spell_numbers(text: str) -> str:
    """Spell digits (ASCII or Bangla) as Bangla words: 2026 -> দুই হাজার ছাব্বিশ, 3.5 -> তিন দশমিক পাঁচ, 40% -> চল্লিশ শতাংশ."""
    def num(m: re.Match) -> str:
        raw = m.group(0).translate(BN_DIGITS).replace(",", "")
        pct = raw.endswith("%")
        raw = raw.rstrip("%")
        if "." in raw:
            whole, frac = raw.split(".", 1)
            words = f"{bn_number(int(whole or 0))} দশমিক " + " ".join(BN_0_99[int(d)] for d in frac if d.isdigit())
        else:
            words = bn_number(int(raw))
        return words + (" শতাংশ" if pct else "")
    return re.sub(r"[0-9০-৯][0-9০-৯,]*(?:\.[0-9০-৯]+)?%?", num, text)


def is_bangla(text: str) -> bool:
    return bool(re.search(r"[ঀ-৿]", text or ""))


EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")


def clean(text: str) -> str:
    """Remove what voices read badly: markdown marks, emoji, URLs, stage directions in [brackets]."""
    t = re.sub(r"\[[^\]]*\]", " ", text)
    t = re.sub(r"https?://\S+", " ", t)
    t = EMOJI.sub(" ", t)
    t = re.sub(r"[*_#>`~]+", " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


SENT = re.compile(r"(?<=[.!?।])[\"'”’)\]]*\s+")


def sentences(text: str, max_chars: int = 220) -> list[tuple[str, float]]:
    """[(sentence, pause after in seconds)]: 0.28 s between sentences, 0.6 s after a paragraph. Long sentences
    split at commas so every piece stays natural for a TTS model."""
    out: list[tuple[str, float]] = []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    for pi, para in enumerate(paras):
        para = re.sub(r"\s*\n\s*", " ", para)
        pieces = [s.strip() for s in SENT.split(para) if s.strip()]
        for si, s in enumerate(pieces):
            chunks = [s]
            if len(s) > max_chars:
                chunks, cur = [], ""
                for part in re.split(r"(?<=[,;:—–])\s+", s):
                    if cur and len(cur) + len(part) + 1 > max_chars:
                        chunks.append(cur)
                        cur = part
                    else:
                        cur = f"{cur} {part}".strip()
                if cur:
                    chunks.append(cur)
            for ci, c in enumerate(chunks):
                last_chunk = ci == len(chunks) - 1
                pause = 0.12 if not last_chunk else (0.6 if si == len(pieces) - 1 and pi < len(paras) - 1 else 0.28)
                out.append((c, pause))
    if out:
        out[-1] = (out[-1][0], 0.0)
    return out


def words(text: str) -> list[str]:
    """Spoken tokens of a sentence (punctuation kept on the word, as captions show it)."""
    return [w for w in re.split(r"\s+", text.strip()) if re.search(r"[\wঀ-৿]", w)]


def norm(token: str) -> str:
    """Comparable form of a word (for matching recognised words to the script)."""
    t = token.lower().translate(BN_DIGITS)
    return re.sub(r"[^\wঀ-৿]+", "", t)
