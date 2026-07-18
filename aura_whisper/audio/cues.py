from __future__ import annotations

"""Soft, synthesized audio cues that mark the start and end of a recording.

Instead of relying on macOS system sounds (harsh and inconsistent), these cues
are generated once with numpy as gentle two-note chimes and played non-blocking
through ``sounddevice`` (already a project dependency). Everything degrades to a
silent no-op when the audio backend is unavailable, so callers never need to
guard the calls.
"""

from typing import Optional

import numpy as np

_SR = 44_100          # output sample rate
_CUE_VOLUME = 0.30    # overall gain — present but never startling


def _note(freq: float, dur: float, *, start: float, total: float) -> np.ndarray:
    """A single soft sine note with a warm harmonic and a click-free envelope."""
    n_total = int(total * _SR)
    n = int(dur * _SR)
    t = np.linspace(0.0, dur, n, endpoint=False)

    # Sine + quiet upper harmonics give a soft, bell-like body.
    wave = (
        1.00 * np.sin(2 * np.pi * freq * t)
        + 0.18 * np.sin(2 * np.pi * freq * 2 * t)
        + 0.07 * np.sin(2 * np.pi * freq * 3 * t)
    )

    # Fast raised-cosine attack + smooth decay — no clicks at either edge.
    env = np.ones(n, dtype=np.float32)
    attack = max(1, int(0.008 * _SR))
    env[:attack] = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, attack))
    env[attack:] = np.linspace(1.0, 0.0, n - attack) ** 1.8
    wave = (wave * env).astype(np.float32)

    out = np.zeros(n_total, dtype=np.float32)
    offset = int(start * _SR)
    seg = wave[: max(0, n_total - offset)]
    out[offset:offset + len(seg)] += seg
    return out


def _normalize(sig: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(sig))) or 1.0
    return (sig / peak * _CUE_VOLUME).astype(np.float32)


def _build_start() -> np.ndarray:
    """A gentle rising two-note chime — a bright, welcoming 'listening' cue."""
    total = 0.34
    return _normalize(
        _note(587.33, 0.16, start=0.00, total=total)   # D5
        + _note(880.00, 0.24, start=0.09, total=total)  # A5
    )


def _build_stop() -> np.ndarray:
    """A soft falling two-note chime — a calm 'captured' cue."""
    total = 0.34
    return _normalize(
        _note(783.99, 0.16, start=0.00, total=total)   # G5
        + _note(523.25, 0.24, start=0.09, total=total)  # C5
    )


class _CuePlayer:
    """Synthesizes the cue sounds once and plays them without blocking."""

    def __init__(self) -> None:
        self._start: Optional[np.ndarray] = None
        self._stop: Optional[np.ndarray] = None
        self._sd = None
        self._built = False

    def _ensure_built(self) -> None:
        if self._built:
            return
        self._built = True
        try:
            import sounddevice as sd  # type: ignore
        except Exception:
            return
        self._sd = sd
        try:
            self._start = _build_start()
            self._stop = _build_stop()
        except Exception:
            self._start = self._stop = None

    def _play(self, samples: Optional[np.ndarray]) -> None:
        if self._sd is None or samples is None:
            return
        try:
            self._sd.play(samples, _SR)  # non-blocking
        except Exception:
            pass

    def play_start(self) -> None:
        self._ensure_built()
        self._play(self._start)

    def play_stop(self) -> None:
        self._ensure_built()
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
