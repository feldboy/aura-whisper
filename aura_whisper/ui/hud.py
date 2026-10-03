from __future__ import annotations

import math

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget

from aura_whisper.ui.waveform import Waveform


class _RecDot(QWidget):
    """Pulsing dot — red while recording, blue while the AI is working."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(12, 12)
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
        painter.drawEllipse(1, 1, 10, 10)
        painter.setBrush(QColor(c.red(), c.green(), c.blue(), alpha))
        painter.drawEllipse(3, 3, 6, 6)


class RecordingHUD(QWidget):
    """Compact pill shown just above the mouse pointer when dictation starts
    (top-center under the notch if the pointer's screen is unknown).

    Never takes focus, so the paste target keeps its cursor.
    """

    _GAP = 10  # px between the pointer tip and the pill

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
        self.setFixedSize(224, 30)
        self._anchor: QPoint | None = None

        self._dot = _RecDot(self)

        self.waveform = Waveform(self)
        self.waveform.setMinimumHeight(18)
        self.waveform.setMaximumHeight(20)
        self.waveform.setMinimumWidth(56)

        self._status = QLabel("", self)
        self._status.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._status.setStyleSheet(
            "color: rgba(255,255,255,215); font-size: 11px; font-weight: 600; "
            "background: transparent;"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 4, 13, 4)
        layout.setSpacing(7)
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
        # Keep the pill compact: strip mode/model suffixes like
        # "Listening… (Email mode)" or "Rewriting · Cleanup".
        short = text.split(" (")[0].split(" · ")[0]
        if len(short) > 20:
            short = short[:19] + "…"
        self._status.setText(short)

    def set_recording(self, recording: bool) -> None:
        self._dot.set_active(recording)
        self.waveform.set_active(recording)

    def set_busy(self, busy: bool, text: str = "") -> None:
        """Show an animated 'still working…' state while the AI/model runs."""
        if busy:
            self.waveform.set_active(False)
            self._dot.set_active(True, QColor(10, 132, 255))  # blue = working
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
        target = self._target_pos()
        self.move(target)
        self.show()
        if self.pos() != target:
            # macOS can nudge a tool window on its first show; re-apply.
            self.move(target)
        self.raise_()

    def anchor_to_cursor(self) -> None:
        """Show the pill next to where the mouse pointer is right now (the
        user just clicked the field they're dictating into)."""
        self._anchor = QCursor.pos()

    def _target_pos(self) -> QPoint:
        anchor = self._anchor
        screen = QApplication.screenAt(anchor) if anchor is not None else None
        if screen is None:
            anchor = None
            screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            return self.pos()
        avail = screen.availableGeometry()
        if anchor is None:
            # Right under the menu bar / camera notch.
            return QPoint(avail.x() + (avail.width() - self.width()) // 2, avail.y() + 6)
        # Centered just above the pointer, so it covers neither the pointer
        # nor the line being clicked into.
        x = anchor.x() - self.width() // 2
        y = anchor.y() - self._GAP - self.height()
        if y < avail.top() + 4:
            y = anchor.y() + 24  # no room above: below the pointer arrow
        x = max(avail.left() + 4, min(x, avail.right() - self.width() - 4))
        y = max(avail.top() + 4, min(y, avail.bottom() - self.height() - 4))
        return QPoint(x, y)

    def hide_soon(self, delay_ms: int = 1100) -> None:
        self._hide_timer.start(delay_ms)
