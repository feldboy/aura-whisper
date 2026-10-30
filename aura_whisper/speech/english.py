"""English words inside Hebrew text, as phonemes the Hebrew Kokoro voice can say.

Phonikud only understands Hebrew, so English words were dropped or garbled.
They're looked up in the CMU Pronouncing Dictionary (bundled, BSD license)
and mapped to the Hebrew sound inventory — the way an Israeli says
"GitHub" or "meeting" mid-sentence. The voice was only trained on Hebrew;
raw English IPA came out less intelligible in testing.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

CMUDICT_PATH = Path(__file__).resolve().parent.parent / "resources" / "cmudict" / "cmudict.dict"

# ARPAbet -> phonemes from the Hebrew model's inventory.
_ARPABET = {
    "AA": "a", "AE": "a", "AH": "a", "AO": "o", "AW": "aw", "AY": "aj",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "d", "EH": "e", "ER": "eʁ",
    "EY": "ej", "F": "f", "G": "ɡ", "HH": "h", "IH": "i", "IY": "i",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ",
    "OW": "o", "OY": "oj", "P": "p", "R": "ʁ", "S": "s", "SH": "ʃ",
    "T": "t", "TH": "t", "UH": "u", "UW": "u", "V": "v", "W": "w",
    "Y": "j", "Z": "z", "ZH": "ʒ",
}

# Common words the dictionary lacks or gets wrong in a tech context.
_OVERRIDES = {
    "readme": ["R", "IY1", "D", "M", "IY0"],
}

LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z']*")
# Short all-caps words are acronyms people spell out: API, PDF, CEO.
_ACRONYM = re.compile(r"[A-Z]{2,4}")


@lru_cache(maxsize=1)
def _dictionary() -> dict[str, list[str]]:
    words: dict[str, list[str]] = {}
    with CMUDICT_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            word, *phones = line.split()
            if "(" in word:  # alternate pronunciation; keep the first
                continue
            words[word] = phones
    words.update(_OVERRIDES)
    return words


def _to_phonemes(arpabet: list[str]) -> str:
    out = []
    for ph in arpabet:
        base, stress = ph.rstrip("012"), ph[-1]
        sound = "e" if base == "AH" and stress == "0" else _ARPABET[base]
        out.append(("ˈ" if stress == "1" else "") + sound)
    return "".join(out)


def _spell(word: str) -> str:
    d = _dictionary()
    return " ".join(_to_phonemes(d[c]) for c in word.lower() if c in d)


def _compound(word: str) -> str | None:
    """'readme' -> 'read' + 'me': longest dictionary prefix, then the rest."""
    d = _dictionary()
    for cut in range(len(word) - 2, 1, -1):
        head, tail = word[:cut], word[cut:]
        if head in d:
            rest = d.get(tail) and _to_phonemes(d[tail])
            if rest:
                return _to_phonemes(d[head]) + rest
    return None


def english_phonemes(word: str) -> str:
    if _ACRONYM.fullmatch(word) and word.lower() not in _dictionary():
        return _spell(word)
    lower = word.lower().strip("'")
    d = _dictionary()
    if lower in d:
        return _to_phonemes(d[lower])
    # camelCase / PascalCase: GitHub -> git + hub
    parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", word)
    if len(parts) > 1 and all(p.lower() in d for p in parts):
        return "".join(_to_phonemes(d[p.lower()]) for p in parts)
    return _compound(lower) or _spell(word)


def mixed_phonemes(text: str, hebrew_phonemes) -> str:
    """Phonemes for text mixing Hebrew and English; ``hebrew_phonemes`` turns
    a Hebrew run into phonemes (Phonikud)."""
    parts = []
    pos = 0
    for m in LATIN_WORD.finditer(text):
        parts.append(hebrew_phonemes(text[pos : m.start()]))
        parts.append(english_phonemes(m.group()))
        pos = m.end()
    parts.append(hebrew_phonemes(text[pos:]))
    return " ".join(p.strip() for p in parts if p and p.strip())
