from __future__ import annotations

"""Tiny audio cues that mark the start and end of a recording.

Uses macOS built-in system sounds via ``NSSound`` (preloaded once for
zero-latency playback). Everything degrades to a silent no-op when the
sound backend is unavailable, so callers never need to guard the calls.
"""

import sys
from pathlib import Path
from typing import Optional

_SYSTEM_SOUNDS = Path("/System/Library/Sounds")

# Subtle, short, and clearly distinct from each other.
_START_SOUND = "Tink.aiff"   # a light upward "tick" — recording opened
_STOP_SOUND = "Pop.aiff"     # a soft "pop" — recording closed
_CUE_VOLUME = 0.35


class _CuePlayer:
    """Preloads the cue sounds and plays them without blocking."""

    def __init__(self) -> None:
        self._start = None
        self._stop = None
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if sys.platform != "darwin":
            return
        try:
            from AppKit import NSSound  # type: ignore
        except Exception:
            return
        self._start = self._load(NSSound, _START_SOUND)
        self._stop = self._load(NSSound, _STOP_SOUND)

    @staticmethod
    def _load(ns_sound_cls, filename: str):
        path = _SYSTEM_SOUNDS / filename
        if not path.exists():
            return None
        try:
            sound = ns_sound_cls.alloc().initWithContentsOfFile_byReference_(
                str(path), True
            )
            if sound is not None:
                sound.setVolume_(_CUE_VOLUME)
            return sound
        except Exception:
            return None

    @staticmethod
    def _play(sound) -> None:
        if sound is None:
            return
        try:
            # Rewind so rapid start/stop cues always retrigger cleanly.
            if sound.isPlaying():
                sound.stop()
            sound.play()
        except Exception:
            pass

    def play_start(self) -> None:
        self._ensure_loaded()
        self._play(self._start)

    def play_stop(self) -> None:
        self._ensure_loaded()
        self._play(self._stop)


_player: Optional[_CuePlayer] = None


def _get_player() -> _CuePlayer:
    global _player
    if _player is None:
        _player = _CuePlayer()
    return _player


def play_start() -> None:
    """Play the 'recording started' cue (no-op if unavailable)."""
    _get_player().play_start()


def play_stop() -> None:
    """Play the 'recording stopped' cue (no-op if unavailable)."""
    _get_player().play_stop()
