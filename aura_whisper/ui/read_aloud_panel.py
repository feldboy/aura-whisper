from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

from aura_whisper.speech.speaker import MAX_SPEED, MIN_SPEED

_BUTTON_STYLE = (
    "QPushButton { color: rgba(255,255,255,225); background: rgba(255,255,255,0.10);"
    " border: none; border-radius: 11px; font-size: 12px; }"
    "QPushButton:hover { background: rgba(255,255,255,0.18); }"
    "QPushButton:pressed { background: rgba(255,255,255,0.26); }"
)
_SLIDER_STYLE = (
    "QSlider::groove:horizontal { height: 4px; border-radius: 2px;"
    " background: rgba(255,255,255,0.18); }"
    "QSlider::sub-page:horizontal { border-radius: 2px; background: rgb(10,132,255); }"
    "QSlider::handle:horizontal { width: 12px; height: 12px; margin: -4px 0;"
    " border-radius: 6px; background: white; }"
)


class ReadAloudPanel(QWidget):
    """Floating controls while text is read aloud: pause/resume, live speed,
    stop. Shown above the pointer without taking focus from the user's app."""

    pause_toggled = Signal()
    stop_requested = Signal()
    speed_changed = Signal(float)

    _GAP = 10

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
        # Menu-bar apps are always inactive; keep the tool window visible.
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)
        self.setFixedSize(276, 34)

        self._pause_btn = self._button("⏸", "Pause / resume")
        self._pause_btn.clicked.connect(self.pause_toggled)

        self._slider = QSlider(Qt.Horizontal, self)
        self._slider.setRange(round(MIN_SPEED * 10), round(MAX_SPEED * 10))
        self._slider.setFocusPolicy(Qt.NoFocus)
        self._slider.setStyleSheet(_SLIDER_STYLE)
        self._slider.setToolTip("Reading speed")
        self._slider.valueChanged.connect(self._on_slider)

        self._speed_label = QLabel(self)
        self._speed_label.setFixedWidth(30)
        self._speed_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        self._speed_label.setStyleSheet(
            "color: rgba(255,255,255,215); font-size: 11px; font-weight: 600; "
            "background: transparent;"
        )

        stop_btn = self._button("✕", "Stop reading")
        stop_btn.clicked.connect(self.stop_requested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 6, 7, 6)
        layout.setSpacing(8)
        layout.addWidget(self._pause_btn)
        layout.addWidget(self._slider, 1)
        layout.addWidget(self._speed_label)
        layout.addWidget(stop_btn)

    def _button(self, text: str, tip: str) -> QPushButton:
        btn = QPushButton(text, self)
        btn.setFixedSize(22, 22)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setToolTip(tip)
        btn.setStyleSheet(_BUTTON_STYLE)
        return btn

    def _on_slider(self, value: int) -> None:
        speed = value / 10
        self._speed_label.setText(f"{speed:g}×")
        self.speed_changed.emit(speed)

    def set_speed(self, speed: float) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(round(speed * 10))
        self._slider.blockSignals(False)
        self._speed_label.setText(f"{self._slider.value() / 10:g}×")

    def set_paused(self, paused: bool) -> None:
        self._pause_btn.setText("▶" if paused else "⏸")

    def show_at_cursor(self) -> None:
        anchor = QCursor.pos()
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            x = anchor.x() - self.width() // 2
            y = anchor.y() - self._GAP - self.height()
            if y < avail.top() + 4:
                y = anchor.y() + 24  # no room above: below the pointer arrow
            x = max(avail.left() + 4, min(x, avail.right() - self.width() - 4))
            y = max(avail.top() + 4, min(y, avail.bottom() - self.height() - 4))
            self.move(QPoint(x, y))
        self.show()
        self.raise_()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        radius = self.height() / 2
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), radius, radius)
        painter.fillPath(path, QColor(10, 10, 14, 242))
        painter.setPen(QColor(255, 255, 255, 36))
        painter.drawPath(path)
