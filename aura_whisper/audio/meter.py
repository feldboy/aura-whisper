from __future__ import annotations

import numpy as np


class SpectrumMeter:
    """Rolling FFT → log-spaced band magnitudes for waveform visualization."""

    def __init__(
        self,
        n_bands: int = 48,
        window_size: int = 2048,
        samplerate: int = 16_000,
        smoothing: float = 0.6,
    ) -> None:
        self.n_bands = n_bands
        self.window_size = window_size
        self.samplerate = samplerate
        self.smoothing = smoothing
        self._buffer = np.zeros(window_size, dtype=np.float32)
        self._bands = np.zeros(n_bands, dtype=np.float32)
        self._window = np.hanning(window_size).astype(np.float32)
        self._edges = self._log_bin_edges(n_bands, window_size, samplerate)

    @staticmethod
    def _log_bin_edges(n_bands: int, window_size: int, samplerate: int) -> np.ndarray:
        nyquist = samplerate / 2
        low = 80.0
        high = min(nyquist, 6000.0)
        freqs = np.geomspace(low, high, n_bands + 1)
        bin_width = samplerate / window_size
        edges = np.clip((freqs / bin_width).astype(int), 1, window_size // 2 - 1)
        return edges

    def push(self, frame: np.ndarray) -> np.ndarray:
        frame = np.asarray(frame, dtype=np.float32).ravel()
        n = len(frame)
        if n >= self.window_size:
            self._buffer = frame[-self.window_size :].copy()
        else:
            self._buffer = np.concatenate([self._buffer[n:], frame])

        windowed = self._buffer * self._window
        spectrum = np.abs(np.fft.rfft(windowed))
        spectrum = np.log1p(spectrum)

        new = np.empty(self.n_bands, dtype=np.float32)
        for i in range(self.n_bands):
            lo, hi = self._edges[i], max(self._edges[i] + 1, self._edges[i + 1])
            new[i] = float(spectrum[lo:hi].mean()) if hi > lo else 0.0

        peak = float(new.max()) if new.size else 1.0
        if peak > 1e-6:
            new = new / peak

        a = self.smoothing
        self._bands = a * self._bands + (1.0 - a) * new
        return self._bands.copy()

    def decay(self) -> np.ndarray:
        self._bands *= 0.85
        return self._bands.copy()

    def reset(self) -> None:
        self._buffer[:] = 0
        self._bands[:] = 0
