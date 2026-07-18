from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget

from aura_whisper.ui.waveform import Waveform


class _RecDot(QWidget):
    """Pulsing dot — red while recording, blue while the AI is working."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self._phase = 0.0
        self._active = False
        self._color = QColor(255, 69, 58)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def set_active(self, active: bool, color: QColor | None = None) -> None:
        self._active = active
        if color is not None:
            self._color = color
        if active:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.12) % (2 * math.pi)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._active:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        alpha = int(140 + 115 * (0.5 + 0.5 * math.sin(self._phase)))
        c = self._color
        glow = QColor(c.red(), c.green(), c.blue(), max(0, alpha - 170))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(1, 1, 14, 14)
        painter.setBrush(QColor(c.red(), c.green(), c.blue(), alpha))
        painter.drawEllipse(4, 4, 8, 8)


class RecordingHUD(QWidget):
    """Dynamic-Island-style pill under the camera notch, top-center.

    Never takes focus, so the paste target keeps its cursor.
    """

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Without this, macOS hides Qt.Tool windows whenever the app is
        # inactive — and a menu-bar background app is always inactive.
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)
        self.setFixedSize(320, 46)

        self._dot = _RecDot(self)

        self.waveform = Waveform(self)
        self.waveform.setMinimumHeight(30)
        self.waveform.setMaximumHeight(34)
        self.waveform.setMinimumWidth(120)

        self._status = QLabel("", self)
        self._status.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._status.setStyleSheet(
            "color: rgba(255,255,255,215); font-size: 12px; font-weight: 600; "
            "background: transparent;"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 18, 6)
        layout.setSpacing(10)
        layout.addWidget(self._dot)
        layout.addWidget(self.waveform, 1)
        layout.addWidget(self._status)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        self._busy_base = ""
        self._busy_phase = 0
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(350)
        self._busy_timer.timeout.connect(self._busy_tick)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        radius = self.height() / 2
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), radius, radius)
        painter.fillPath(path, QColor(10, 10, 14, 242))
        painter.setPen(QColor(255, 255, 255, 36))
        painter.drawPath(path)

    def set_status(self, text: str) -> None:
        # Keep the pill compact: strip long mode/model suffixes for the island.
        short = text
        if len(short) > 34:
            short = short[:33] + "…"
        self._status.setText(short)

    def set_recording(self, recording: bool) -> None:
        self._dot.set_active(recording)
        self.waveform.set_active(recording)

    def set_busy(self, busy: bool, text: str = "") -> None:
        """Show an animated 'still working…' state while the AI/model runs."""
        if busy:
            self.waveform.set_active(False)
            self._dot.set_active(True, QColor(110, 125, 255))  # blue = working
            self._busy_base = text or self._status.text().rstrip(".…")
            self._busy_phase = 0
            self._busy_timer.start()
            self.show_pill()
        else:
            self._busy_timer.stop()
            self._dot.set_active(False)

    def _busy_tick(self) -> None:
        self._busy_phase = (self._busy_phase + 1) % 4
        self.set_status(self._busy_base + "." * self._busy_phase)

    def show_pill(self, status: str = "") -> None:
        self._hide_timer.stop()
        if status:
            self.set_status(status)
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            x = avail.x() + (avail.width() - self.width()) // 2
            y = avail.y() + 6  # right under the menu bar / camera notch
            self.move(x, y)
        self.show()
        self.raise_()

    def hide_soon(self, delay_ms: int = 1100) -> None:
        self._hide_timer.start(delay_ms)
