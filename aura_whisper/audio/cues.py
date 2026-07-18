from __future__ import annotations

"""Soft, synthesized audio cues that mark the start and end of a recording.

The cues are gentle plucked-string (harp-like) tones, generated once with numpy
via Karplus-Strong synthesis and played non-blocking through ``sounddevice``
(already a project dependency). Everything degrades to a silent no-op when the
audio backend is unavailable, so callers never need to guard the calls.
"""

from typing import Optional

import numpy as np

_SR = 44_100          # output sample rate
_CUE_VOLUME = 0.26    # soft — a gentle presence, never startling


def _pluck(freq: float, dur: float, *, start: float, total: float,
           gain: float = 1.0, decay: float = 0.9965) -> np.ndarray:
    """A warm plucked-string (harp) note via Karplus-Strong synthesis.

    A short excitation is fed through a short delay line with a gentle
    low-pass in the feedback path, so the tone starts soft and its overtones
    fade naturally — the characteristic mellow 'pluck' of a harp string. The
    excitation is pre-smoothed so the attack is round and never startling.
    """
    n_total = int(total * _SR)
    n = int(dur * _SR)
    N = max(2, int(_SR / freq))

    rng = np.random.default_rng(int(freq * 100))  # deterministic per pitch
    buf = rng.uniform(-1.0, 1.0, N).astype(np.float64)
    # Pre-smooth the excitation → a softer, warmer, less noisy attack.
    for _ in range(4):
        buf = 0.5 * (buf + np.roll(buf, 1))

    out = np.zeros(n, dtype=np.float64)
    ptr = 0
    for i in range(n):
        out[i] = buf[ptr]
        nxt = (ptr + 1) % N
        buf[ptr] = decay * 0.5 * (buf[ptr] + buf[nxt])
        ptr = nxt

    # Gentle attack + smooth tail so start/end are click-free.
    attack = max(1, int(0.006 * _SR))
    out[:attack] *= np.sin(np.linspace(0.0, np.pi / 2, attack)) ** 2
    tail = max(1, int(0.03 * _SR))
    out[-tail:] *= np.cos(np.linspace(0.0, np.pi / 2, tail)) ** 2
    out = (out * gain).astype(np.float32)

    result = np.zeros(n_total, dtype=np.float32)
    offset = int(start * _SR)
    seg = out[: max(0, n_total - offset)]
    result[offset:offset + len(seg)] += seg
    return result


def _normalize(sig: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(sig))) or 1.0
    return (sig / peak * _CUE_VOLUME).astype(np.float32)


def _build_start() -> np.ndarray:
    """A deep, short harp roll (rising) — a warm 'listening' cue."""
    total = 0.62
    return _normalize(
        _pluck(196.00, 0.55, start=0.00, total=total)          # G3
        + _pluck(293.66, 0.55, start=0.07, total=total, gain=0.9)  # D4
    )


def _build_stop() -> np.ndarray:
    """A deep, short harp roll (falling) — a calm 'captured' cue."""
    total = 0.62
    return _normalize(
        _pluck(293.66, 0.50, start=0.00, total=total)          # D4
        + _pluck(196.00, 0.55, start=0.07, total=total, gain=0.9)  # G3
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
