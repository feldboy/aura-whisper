from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from aura_whisper.audio.meter import SpectrumMeter


class Waveform(QWidget):
    """Siri-style animated spectrum bars with glow."""

    N_BANDS = 64

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._meter = SpectrumMeter(n_bands=self.N_BANDS)
        self._bands = np.zeros(self.N_BANDS, dtype=np.float32)
        # Eased values actually drawn — interpolated toward _bands each frame
        # so the motion is smooth instead of snapping between audio frames.
        self._display = np.zeros(self.N_BANDS, dtype=np.float32)
        self._active = False
        self._idle_phase = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_active(self, active: bool) -> None:
        if not active and self._active:
            self._meter.reset()
        self._active = active

    def push_frame(self, frame: np.ndarray) -> None:
        if not self._active:
            return
        self._bands = self._meter.push(frame)

    def _tick(self) -> None:
        if self._active:
            self._bands = self._meter.decay() if not self._bands.any() else self._bands
            target = self._bands
        else:
            self._bands = self._meter.decay()
            self._idle_phase = (self._idle_phase + 0.045) % (2 * np.pi)
            target = np.maximum(self._bands, self._idle_shape())

        # Asymmetric easing: snap up quickly on attack, glide down on release —
        # this reads as lively yet smooth, like Siri / Voice Memos.
        rising = target > self._display
        ease = np.where(rising, 0.65, 0.22).astype(np.float32)
        self._display += (target - self._display) * ease
        self.update()

    def _idle_shape(self) -> np.ndarray:
        i = np.arange(self.N_BANDS)
        center = (self.N_BANDS - 1) / 2
        envelope = np.exp(-((i - center) ** 2) / (2 * (self.N_BANDS / 3.5) ** 2))
        # Two overlapping travelling waves + a slow breath give organic motion.
        wave = 0.5 + 0.5 * np.sin(self._idle_phase * 1.3 - i * 0.28)
        ripple = 0.5 + 0.5 * np.sin(self._idle_phase * 0.7 + i * 0.11)
        breath = 0.65 + 0.35 * np.sin(self._idle_phase * 0.5)
        return (envelope * (0.55 * wave + 0.45 * ripple) * breath * 0.16).astype(
            np.float32
        )

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt signature)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        w = rect.width()
        h = rect.height()
        cy = h / 2

        bands = self._display

        n = self.N_BANDS
        gap = 3.0
        bar_w = max(2.0, (w - gap * (n + 1)) / n)
        max_h = h * 0.9

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(130, 170, 255))
        grad.setColorAt(0.5, QColor(110, 120, 255))
        grad.setColorAt(1.0, QColor(180, 100, 230))

        glow_grad = QLinearGradient(0, 0, 0, h)
        glow_grad.setColorAt(0.0, QColor(130, 170, 255, 60))
        glow_grad.setColorAt(0.5, QColor(120, 130, 255, 60))
        glow_grad.setColorAt(1.0, QColor(180, 100, 230, 60))

        painter.setPen(Qt.NoPen)

        x = gap
        for i in range(n):
            mag = float(bands[i]) if i < len(bands) else 0.0
            bh = max(2.0, mag * max_h)

            core = QRectF(x, cy - bh / 2, bar_w, bh)
            glow = QRectF(x - 2.5, cy - bh / 2 - 2.5, bar_w + 5.0, bh + 5.0)

            path = QPainterPath()
            path.addRoundedRect(glow, bar_w, bar_w)
            painter.fillPath(path, glow_grad)

            core_path = QPainterPath()
            core_path.addRoundedRect(core, bar_w / 2, bar_w / 2)
            painter.fillPath(core_path, grad)

            x += bar_w + gap

        painter.end()
