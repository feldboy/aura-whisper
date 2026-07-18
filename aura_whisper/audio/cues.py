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
_CUE_VOLUME = 0.22    # soft — a gentle presence, never a "hit"


def _blip(f0: float, f1: float, dur: float, *, start: float, total: float) -> np.ndarray:
    """A soft sine 'blip' that glides from ``f0`` to ``f1``.

    The rounded attack (no sharp transient) and the pitch glide give a smooth,
    liquid, water-drop feel — pleasant and calm, never percussive like a key
    strike. A quiet fifth above adds a touch of warmth.
    """
    n_total = int(total * _SR)
    n = int(dur * _SR)
    t = np.linspace(0.0, dur, n, endpoint=False)

    # Exponential pitch glide reads as more natural than a linear ramp.
    freq = f0 * (f1 / f0) ** (t / dur)
    phase = 2 * np.pi * np.cumsum(freq) / _SR
    wave = np.sin(phase) + 0.10 * np.sin(1.5 * phase)  # + a soft fifth

    # Rounded swell-in (no click, no percussive attack) and a smooth fade-out.
    env = np.ones(n, dtype=np.float32)
    attack = max(1, int(0.030 * _SR))
    env[:attack] = np.sin(np.linspace(0.0, np.pi / 2, attack)) ** 2
    env[attack:] = np.cos(np.linspace(0.0, np.pi / 2, n - attack)) ** 1.4
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
    """A soft rising water-drop cue — gentle 'listening' feel."""
    total = 0.30
    return _normalize(
        _blip(520.0, 740.0, 0.26, start=0.00, total=total)
        + 0.5 * _blip(780.0, 1110.0, 0.20, start=0.05, total=total)
    )


def _build_stop() -> np.ndarray:
    """A soft falling water-drop cue — calm 'captured' feel."""
    total = 0.30
    return _normalize(
        _blip(660.0, 460.0, 0.26, start=0.00, total=total)
        + 0.5 * _blip(990.0, 690.0, 0.20, start=0.05, total=total)
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
