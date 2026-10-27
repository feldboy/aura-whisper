from __future__ import annotations

import re

# Hesitation sounds whisper writes out literally: "אה", "אממ", "uh", "umm"…
# None of these spellings is a real word, so dropping them is safe. Optional
# niqqud marks are allowed between letters ("אֶה").
_M = "[֑-ׇ]*"
_FILLERS = "|".join(
    [
        f"(?:א{_M})+(?:ה{_M})+(?:מ{_M})*",  # אה, אהה, אהמ
        f"(?:א{_M})+(?:מ{_M})+",  # אמ, אממ
        f"(?:ה{_M})?(?:מ{_M}){{2,}}",  # ממ, הממ
        r"u+h+m*",  # uh, uhh, uhm
        r"u+m+",  # um, umm
        r"e+r+m+",  # erm
        r"h+m{2,}",  # hmm
        r"m{2,}",  # mm
    ]
)
# A filler swallows the commas around it: "אני, אה, רוצה" → "אני רוצה".
_FILLER_RE = re.compile(
    rf"[,،]?\s*(?<!\w)(?:{_FILLERS})(?!\w)\s*[,،]?", re.IGNORECASE
)
_ELLIPSIS_RE = re.compile(r"\s*(?:…|\.{2,})\s*")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?،])")
_REPEATED_PUNCT_RE = re.compile(r"([,.;:!?،])(?:\s*[,.;:،])+")
# Cut-off word: "ה- הבית", "א-אני" → "הבית", "אני".
_FALSE_START_RE = re.compile(r"(?<!\w)([^\W\d_]{1,2})-\s*(?=\1)")
# A word or short phrase said twice in a row: "אני אני רוצה", "את ה את ה".
_REPEAT_RE = re.compile(r"(?<!\w)((?:[^\W\d_]+\s+){0,2}[^\W\d_]+)(?:,?\s+\1)+(?!\w)")
# Doubled on purpose ("לאט לאט", "very very"): leave these alone.
_EMPHATIC = {
    "לאט", "מאוד", "ממש", "כן", "לא", "רגע", "טוב", "בדיוק", "יותר", "פחות",
    "very", "really", "no", "yes", "so", "bye",
}


def _collapse_repeat(m: re.Match) -> str:
    phrase = m.group(1)
    return m.group(0) if phrase.lower() in _EMPHATIC else phrase


def strip_fillers(text: str) -> str:
    """Remove hesitation sounds ("אה", "אממ", "um"), trailing-off ellipses
    ("…"), cut-off words and stuttered repeats from a transcript, then tidy
    the punctuation left behind."""
    if not text:
        return text
    # An ellipsis at the very end closes the sentence; mid-text it's a pause.
    out = re.sub(r"\s*(?:…|\.{2,})\s*$", ".", text.strip())
    out = _ELLIPSIS_RE.sub(" ", out)
    out = _FILLER_RE.sub(" ", out)
    out = " ".join(out.split())
    out = _FALSE_START_RE.sub("", out)
    out = _REPEAT_RE.sub(_collapse_repeat, out)
    out = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", out)
    out = _REPEATED_PUNCT_RE.sub(r"\1", out)
    out = " ".join(out.split())
    out = out.lstrip(",.;:!?،- ").strip()
    # "um, so…" → "So…", but leave text that started lowercase on its own.
    lead_dropped = not text.lstrip().startswith(out[:1])
    if lead_dropped and out[:1].isascii() and out[:1].islower():
        out = out[0].upper() + out[1:]
    # Nothing left but punctuation (the whole recording was "אה…").
    if not re.search(r"\w", out):
        return ""
    return out
