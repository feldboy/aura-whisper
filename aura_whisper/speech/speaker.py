"""Read text aloud with the macOS system voices (local, free, offline).

Uses NSSpeechSynthesizer so reading can be paused, resumed and re-paced
mid-sentence. A speed change restarts from the word being spoken, since a
new rate only reliably applies to a fresh utterance.
"""

from __future__ import annotations

import re
import sys

# The voices' natural pace; the speed setting multiplies it.
BASE_RATE_WPM = 180
MIN_SPEED = 0.5
MAX_SPEED = 3.0

HEBREW_VOICE = "Carmit"
_HEBREW_RE = re.compile(r"[֐-׿]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def pick_voice(text: str) -> str | None:
    """Hebrew voice when the text is mostly Hebrew, else the system voice (None)."""
    hebrew = len(_HEBREW_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    return HEBREW_VOICE if hebrew and hebrew >= latin else None


# Voice identifiers look like com.apple.voice.<quality>.he-IL.Carmit; the
# downloadable enhanced/premium editions sound far more natural.
_QUALITY_RANK = {"premium": 3, "enhanced": 2, "compact": 1}


def best_voice_id(voice_ids, name: str):
    """The highest-quality installed voice called ``name``, or None."""
    best, best_rank = None, -1
    for vid in voice_ids:
        parts = str(vid).split(".")
        if parts[-1].lower() != name.lower():
            continue
        rank = max((_QUALITY_RANK.get(p.lower(), 0) for p in parts), default=0)
        if rank > best_rank:
            best, best_rank = vid, rank
    return best


def clamp_speed(speed: float) -> float:
    return min(MAX_SPEED, max(MIN_SPEED, float(speed)))


def rate_wpm(speed: float) -> int:
    return round(BASE_RATE_WPM * clamp_speed(speed))


_delegate_cls = None


def _make_delegate(on_word):
    """NSObject delegate that reports the character offset of each word."""
    global _delegate_cls
    if _delegate_cls is None:
        from Foundation import NSObject

        class _AuraSpeechDelegate(NSObject):
            def speechSynthesizer_willSpeakWord_ofString_(self, _synth, rng, _s):
                self.on_word(rng.location)

        _delegate_cls = _AuraSpeechDelegate
    delegate = _delegate_cls.alloc().init()
    delegate.on_word = on_word
    return delegate


class Speaker:
    """One reading at a time; ``speak`` replaces whatever is playing."""

    def __init__(self) -> None:
        self._synth = None
        self._delegate = None
        self._text = ""
        # Where the current utterance starts in ``_text``, and the offset of
        # the word being spoken within that utterance.
        self._base = 0
        self._word = 0
        self._speed = 1.0
        self._paused = False
        self._resume_needs_restart = False

    def _ensure_synth(self) -> bool:
        if self._synth is not None:
            return True
        if sys.platform != "darwin":
            return False
        try:
            from AppKit import NSSpeechSynthesizer
        except Exception:
            return False
        self._synth = NSSpeechSynthesizer.alloc().initWithVoice_(None)
        self._delegate = _make_delegate(self._on_word)
        self._synth.setDelegate_(self._delegate)
        return True

    def _on_word(self, location: int) -> None:
        self._word = int(location)

    def is_active(self) -> bool:
        """Speaking or paused mid-reading."""
        return self._paused or self.is_speaking()

    def is_speaking(self) -> bool:
        return self._synth is not None and bool(self._synth.isSpeaking())

    def is_paused(self) -> bool:
        return self._paused

    @property
    def speed(self) -> float:
        return self._speed

    def speak(self, text: str, speed: float) -> bool:
        self.stop()
        text = text.strip()
        if not text or not self._ensure_synth():
            return False
        self._text = text
        self._speed = clamp_speed(speed)
        return self._speak_from(0)

    def _speak_from(self, offset: int) -> bool:
        self._synth.stopSpeaking()
        self._base = offset
        self._word = 0
        self._paused = False
        self._resume_needs_restart = False
        voice = pick_voice(self._text)
        voice_id = None
        if voice:
            from AppKit import NSSpeechSynthesizer

            voice_id = best_voice_id(NSSpeechSynthesizer.availableVoices(), voice)
        self._synth.setVoice_(voice_id)  # None = system default voice
        self._synth.setRate_(rate_wpm(self._speed))
        return bool(self._synth.startSpeakingString_(self._text[offset:]))

    def _position(self) -> int:
        return self._base + self._word

    def set_speed(self, speed: float) -> None:
        speed = clamp_speed(speed)
        if speed == self._speed:
            return
        self._speed = speed
        if self._paused:
            self._resume_needs_restart = True
        elif self.is_speaking():
            self._speak_from(self._position())

    def pause(self) -> None:
        if self.is_speaking() and not self._paused:
            from AppKit import NSSpeechWordBoundary

            self._synth.pauseSpeakingAtBoundary_(NSSpeechWordBoundary)
            self._paused = True

    def resume(self) -> None:
        if not self._paused:
            return
        if self._resume_needs_restart:
            self._speak_from(self._position())
        else:
            self._paused = False
            self._synth.continueSpeaking()

    def toggle_pause(self) -> None:
        if self._paused:
            self.resume()
        else:
            self.pause()

    def stop(self) -> None:
        self._paused = False
        self._resume_needs_restart = False
        if self._synth is not None:
            self._synth.stopSpeaking()
