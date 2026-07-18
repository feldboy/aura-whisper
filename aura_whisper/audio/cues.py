from __future__ import annotations

"""Synthesized audio cues that mark the start and end of a recording.

Offers a small library of gentle, selectable cue "themes" (harp, marimba,
chime, …), each generated once with numpy and played non-blocking through
``sounddevice`` (already a project dependency). The active theme is chosen in
Settings. Everything degrades to a silent no-op when the audio backend is
unavailable, so callers never need to guard the calls.
"""

from typing import Callable, Optional

import numpy as np

_SR = 44_100          # output sample rate
_CUE_VOLUME = 0.26    # soft — a gentle presence, never startling

DEFAULT_CUE = "harp"


# --------------------------------------------------------------------------
# Low-level synthesis helpers
# --------------------------------------------------------------------------

def _place(note: np.ndarray, start: float, total: float) -> np.ndarray:
    """Drop ``note`` into a buffer of ``total`` seconds at offset ``start``."""
    n_total = int(total * _SR)
    out = np.zeros(n_total, dtype=np.float32)
    off = int(start * _SR)
    seg = note[: max(0, n_total - off)]
    out[off:off + len(seg)] += seg
    return out


def _edges(wave: np.ndarray, attack_s: float, release_s: float) -> np.ndarray:
    """Round the very start/end so a note never clicks."""
    n = len(wave)
    a = min(n, max(1, int(attack_s * _SR)))
    wave[:a] *= np.sin(np.linspace(0.0, np.pi / 2, a)) ** 2
    r = min(n, max(1, int(release_s * _SR)))
    wave[-r:] *= np.cos(np.linspace(0.0, np.pi / 2, r)) ** 2
    return wave


def _ks(freq: float, dur: float, *, smoothing: int = 4,
        decay: float = 0.9965, gain: float = 1.0) -> np.ndarray:
    """A plucked string (Karplus-Strong). More smoothing = warmer/softer."""
    n = int(dur * _SR)
    N = max(2, int(_SR / freq))
    rng = np.random.default_rng(int(freq * 100))  # deterministic per pitch
    buf = rng.uniform(-1.0, 1.0, N).astype(np.float64)
    for _ in range(smoothing):
        buf = 0.5 * (buf + np.roll(buf, 1))
    out = np.zeros(n, dtype=np.float64)
    ptr = 0
    for i in range(n):
        out[i] = buf[ptr]
        nxt = (ptr + 1) % N
        buf[ptr] = decay * 0.5 * (buf[ptr] + buf[nxt])
        ptr = nxt
    out = _edges(out, 0.006, 0.03)
    return (out * gain).astype(np.float32)


def _tone(freq: float, dur: float, *, partials=((1.0, 1.0),),
          tau: float = 0.25, attack: float = 0.012, gain: float = 1.0) -> np.ndarray:
    """Additive sine tone with exponential decay (bells, mallets, pure tones)."""
    n = int(dur * _SR)
    t = np.linspace(0.0, dur, n, endpoint=False)
    wave = np.zeros(n, dtype=np.float64)
    for mult, amp in partials:
        wave += amp * np.sin(2 * np.pi * freq * mult * t)
    env = np.exp(-t / tau)
    a = max(1, int(attack * _SR))
    env[:a] *= np.sin(np.linspace(0.0, np.pi / 2, a)) ** 2
    return (wave * env * gain).astype(np.float32)


def _drop(f0: float, f1: float, dur: float, tau: float, *, gain: float = 1.0) -> np.ndarray:
    """A calm water-drop: gentle upward pitch glide + smooth decay."""
    n = int(dur * _SR)
    t = np.linspace(0.0, dur, n, endpoint=False)
    sweep = 1.0 - np.exp(-t / (dur * 0.5))
    freq = f0 + (f1 - f0) * sweep
    phase = 2 * np.pi * np.cumsum(freq) / _SR
    wave = np.sin(phase) + 0.05 * np.sin(2 * phase)
    env = np.exp(-t / tau)
    a = max(1, int(0.008 * _SR))
    env[:a] *= np.sin(np.linspace(0.0, np.pi / 2, a)) ** 2
    return (wave * env * gain).astype(np.float32)


def _pop(freq: float, dur: float, *, gain: float = 1.0) -> np.ndarray:
    """A soft bubble 'pop': slight downward pitch + very fast decay."""
    n = int(dur * _SR)
    t = np.linspace(0.0, dur, n, endpoint=False)
    freq_arr = freq * (1.0 - 0.4 * (t / dur))
    phase = 2 * np.pi * np.cumsum(freq_arr) / _SR
    wave = np.sin(phase)
    env = np.exp(-t / (dur * 0.28))
    a = max(1, int(0.003 * _SR))
    env[:a] *= np.linspace(0.0, 1.0, a)
    return (wave * env * gain).astype(np.float32)


def _normalize(sig: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(sig))) or 1.0
    return (sig / peak * _CUE_VOLUME).astype(np.float32)


# --------------------------------------------------------------------------
# Theme builders — each returns the full start / stop cue
# --------------------------------------------------------------------------

def _harp_start() -> np.ndarray:
    t = 0.62
    return _normalize(_place(_ks(196.00, 0.55), 0.00, t)
                      + _place(_ks(293.66, 0.55, gain=0.9), 0.07, t))


def _harp_stop() -> np.ndarray:
    t = 0.62
    return _normalize(_place(_ks(293.66, 0.50), 0.00, t)
                      + _place(_ks(196.00, 0.55, gain=0.9), 0.07, t))


def _marimba(freq: float, dur: float = 0.5, gain: float = 1.0) -> np.ndarray:
    return _tone(freq, dur, partials=((1.0, 1.0), (3.9, 0.5), (9.2, 0.12)),
                 tau=0.16, attack=0.004, gain=gain)


def _marimba_start() -> np.ndarray:
    t = 0.5
    return _normalize(_place(_marimba(392.00), 0.00, t)
                      + _place(_marimba(587.33, gain=0.9), 0.09, t))


def _marimba_stop() -> np.ndarray:
    t = 0.5
    return _normalize(_place(_marimba(587.33), 0.00, t)
                      + _place(_marimba(392.00, gain=0.9), 0.09, t))


def _chime(freq: float, dur: float = 0.6, gain: float = 1.0) -> np.ndarray:
    return _tone(freq, dur, partials=((1.0, 1.0), (2.0, 0.45), (3.0, 0.2)),
                 tau=0.45, attack=0.008, gain=gain)


def _chime_start() -> np.ndarray:
    t = 0.7
    return _normalize(_place(_chime(587.33), 0.00, t)
                      + _place(_chime(880.00, gain=0.85), 0.12, t))


def _chime_stop() -> np.ndarray:
    t = 0.7
    return _normalize(_place(_chime(880.00), 0.00, t)
                      + _place(_chime(587.33, gain=0.85), 0.12, t))


def _crystal(freq: float, dur: float = 0.7, gain: float = 1.0) -> np.ndarray:
    return _tone(freq, dur, partials=((1.0, 1.0), (2.76, 0.35), (5.4, 0.12)),
                 tau=0.5, attack=0.006, gain=gain)


def _crystal_start() -> np.ndarray:
    t = 0.75
    return _normalize(_place(_crystal(880.00), 0.00, t)
                      + _place(_crystal(1174.66, gain=0.8), 0.10, t))


def _crystal_stop() -> np.ndarray:
    t = 0.75
    return _normalize(_place(_crystal(1174.66), 0.00, t)
                      + _place(_crystal(880.00, gain=0.8), 0.10, t))


def _pluck_start() -> np.ndarray:
    t = 0.5
    return _normalize(_place(_ks(329.63, 0.42, smoothing=1, decay=0.994), 0.00, t)
                      + _place(_ks(493.88, 0.42, smoothing=1, decay=0.994, gain=0.9), 0.06, t))


def _pluck_stop() -> np.ndarray:
    t = 0.5
    return _normalize(_place(_ks(493.88, 0.40, smoothing=1, decay=0.994), 0.00, t)
                      + _place(_ks(329.63, 0.42, smoothing=1, decay=0.994, gain=0.9), 0.06, t))


def _water_start() -> np.ndarray:
    return _normalize(_place(_drop(470.0, 640.0, 0.48, 0.15), 0.00, 0.55))


def _water_stop() -> np.ndarray:
    return _normalize(_place(_drop(360.0, 480.0, 0.50, 0.17), 0.00, 0.55))


def _bubble_start() -> np.ndarray:
    t = 0.3
    return _normalize(_place(_pop(520.0, 0.22), 0.00, t)
                      + _place(_pop(760.0, 0.16, gain=0.5), 0.06, t))


def _bubble_stop() -> np.ndarray:
    return _normalize(_place(_pop(420.0, 0.24), 0.00, 0.3))


def _sine_note(freq: float, dur: float, gain: float = 1.0) -> np.ndarray:
    return _tone(freq, dur, partials=((1.0, 1.0), (2.0, 0.06)),
                 tau=0.3, attack=0.016, gain=gain)


def _sine_start() -> np.ndarray:
    t = 0.42
    return _normalize(_place(_sine_note(659.25, 0.16), 0.00, t)
                      + _place(_sine_note(987.77, 0.24), 0.13, t))


def _sine_stop() -> np.ndarray:
    t = 0.42
    return _normalize(_place(_sine_note(987.77, 0.16), 0.00, t)
                      + _place(_sine_note(659.25, 0.24), 0.13, t))


# key -> (label, start-builder, stop-builder). Order defines the dropdown order.
THEMES: dict[str, tuple[str, Callable[[], np.ndarray], Callable[[], np.ndarray]]] = {
    "harp": ("Harp — deep & warm", _harp_start, _harp_stop),
    "marimba": ("Marimba — wooden mallet", _marimba_start, _marimba_stop),
    "chime": ("Chime — soft bell", _chime_start, _chime_stop),
    "crystal": ("Crystal — bright bell", _crystal_start, _crystal_stop),
    "pluck": ("Pluck — nylon string", _pluck_start, _pluck_stop),
    "water": ("Water drop — calm", _water_start, _water_stop),
    "bubble": ("Bubble — soft pop", _bubble_start, _bubble_stop),
    "tone": ("Tone — Siri-style", _sine_start, _sine_stop),
}

# [(key, label), …] for building the settings dropdown.
CUE_SOUND_OPTIONS: list[tuple[str, str]] = [(k, v[0]) for k, v in THEMES.items()]


class _CuePlayer:
    """Lazily synthesizes cue themes (cached) and plays them non-blocking."""

    def __init__(self) -> None:
        self._sd = None
        self._checked = False
        self._theme = DEFAULT_CUE
        self._cache: dict[tuple[str, str], Optional[np.ndarray]] = {}

    def _ensure_sd(self) -> None:
        if self._checked:
            return
        self._checked = True
        try:
            import sounddevice as sd  # type: ignore
            self._sd = sd
        except Exception:
            self._sd = None

    def set_theme(self, name: str) -> None:
        if name in THEMES:
            self._theme = name

    def _get(self, theme: str, which: str) -> Optional[np.ndarray]:
        if theme not in THEMES:
            theme = DEFAULT_CUE
        key = (theme, which)
        if key not in self._cache:
            _label, start_fn, stop_fn = THEMES[theme]
            try:
                self._cache[key] = (start_fn if which == "start" else stop_fn)()
            except Exception:
                self._cache[key] = None
        return self._cache[key]

    def _play(self, samples: Optional[np.ndarray]) -> None:
        self._ensure_sd()
        if self._sd is None or samples is None:
            return
        try:
            self._sd.play(samples, _SR)  # non-blocking
        except Exception:
            pass

    def play_start(self) -> None:
        self._play(self._get(self._theme, "start"))

    def play_stop(self) -> None:
        self._play(self._get(self._theme, "stop"))

    def preview(self, theme: str, which: str = "start") -> None:
        self._play(self._get(theme, which))


_player: Optional[_CuePlayer] = None


def _get_player() -> _CuePlayer:
    global _player
    if _player is None:
        _player = _CuePlayer()
    return _player


def set_theme(name: str) -> None:
    """Select the active cue theme (see ``CUE_SOUND_OPTIONS``)."""
    _get_player().set_theme(name)


def preview(theme: str, which: str = "start") -> None:
    """Play a specific theme's cue for auditioning in Settings."""
    _get_player().preview(theme, which)


def play_start() -> None:
    """Play the 'recording started' cue (no-op if unavailable)."""
    _get_player().play_start()


def play_stop() -> None:
    """Play the 'recording stopped' cue (no-op if unavailable)."""
    _get_player().play_stop()
