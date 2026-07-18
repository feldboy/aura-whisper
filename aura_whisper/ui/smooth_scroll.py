from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
)
from PySide6.QtWidgets import QAbstractScrollArea


class SmoothScroller(QObject):
    """Adds animated, faster mouse-wheel scrolling to a scroll area.

    High-precision devices (trackpads, which send pixel deltas) keep their
    native smooth scrolling untouched; only classic notched mouse wheels are
    animated so every notch glides to its target instead of snapping.
    """

    def __init__(
        self,
        area: QAbstractScrollArea,
        *,
        step: int = 140,
        duration: int = 260,
    ) -> None:
        super().__init__(area)
        self._area = area
        self._bar = area.verticalScrollBar()
        self._step = step
        self._duration = duration
        self._target = self._bar.value()
        self._anim = QPropertyAnimation(self._bar, b"value", self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        area.viewport().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt signature)
        if event.type() != QEvent.Wheel or obj is not self._area.viewport():
            return False

        # Let precise devices (trackpads) scroll natively.
        if not event.pixelDelta().isNull():
            return False

        delta = event.angleDelta().y()
        if delta == 0:
            return False

        if self._anim.state() != QPropertyAnimation.Running:
            self._target = self._bar.value()

        self._target -= round(delta / 120 * self._step)
        self._target = max(
            self._bar.minimum(), min(self._bar.maximum(), self._target)
        )

        self._anim.stop()
        self._anim.setDuration(self._duration)
        self._anim.setStartValue(self._bar.value())
        self._anim.setEndValue(self._target)
        self._anim.start()
        return True


def enable_smooth_scroll(
    area: QAbstractScrollArea, *, step: int = 140, duration: int = 260
) -> SmoothScroller:
    """Attach smooth wheel scrolling to *area* and return the scroller."""

    return SmoothScroller(area, step=step, duration=duration)
