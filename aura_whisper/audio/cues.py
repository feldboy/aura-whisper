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
_CUE_VOLUME = 0.19    # soft — a gentle presence, never a "hit"


def _drop(f0: float, f1: float, dur: float, tau: float, *,
          start: float, total: float, gain: float = 1.0) -> np.ndarray:
    """A single, calm water-drop 'plink'.

    A real drop's air cavity shrinks as it closes, so its pitch rises gently
    while the sound decays smoothly — that soft upward chirp + gradual decay is
    what the ear recognizes as water. Kept low and mellow so it feels calming
    rather than sharp or startling.
    """
    n_total = int(total * _SR)
    n = int(dur * _SR)
    t = np.linspace(0.0, dur, n, endpoint=False)

    # Gentle exponential pitch rise (a small, unhurried sweep — not a zip).
    sweep = 1.0 - np.exp(-t / (dur * 0.5))
    freq = f0 + (f1 - f0) * sweep
    phase = 2 * np.pi * np.cumsum(freq) / _SR
    wave = np.sin(phase) + 0.05 * np.sin(2 * phase)  # near-pure, warm

    # Soft rounded attack (no click) then a smooth, unhurried decay.
    env = np.exp(-t / tau).astype(np.float32)
    attack = max(1, int(0.010 * _SR))
    env[:attack] *= np.sin(np.linspace(0.0, np.pi / 2, attack)) ** 2
    wave = (wave * env * gain).astype(np.float32)

    out = np.zeros(n_total, dtype=np.float32)
    offset = int(start * _SR)
    seg = wave[: max(0, n_total - offset)]
    out[offset:offset + len(seg)] += seg
    return out


def _normalize(sig: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(sig))) or 1.0
    return (sig / peak * _CUE_VOLUME).astype(np.float32)


def _build_start() -> np.ndarray:
    """A soft, calm water drop — a gentle 'listening' cue."""
    total = 0.55
    return _normalize(
        _drop(470.0, 640.0, 0.48, 0.15, start=0.00, total=total)
    )


def _build_stop() -> np.ndarray:
    """A lower, rounder water drop — a peaceful 'captured' cue."""
    total = 0.55
    return _normalize(
        _drop(360.0, 480.0, 0.50, 0.17, start=0.00, total=total)
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
