from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from aura_whisper.ui.smooth_scroll import enable_smooth_scroll


_RESOURCES_DIR = Path(__file__).parent.parent / "resources"
_STYLES_PATH = _RESOURCES_DIR / "styles.qss"
_ICONS_DIR = _RESOURCES_DIR / "icons"

# Aura palette tokens (mirrors DESIGN.md / styles.qss) used by painted widgets
# that can't read their colours from the stylesheet.
PRIMARY = "#bdc2ff"
PRIMARY_CONTAINER = "#7886ff"
ON_SURFACE = "#e2e1ee"
ON_SURFACE_VARIANT = "#c6c5d6"
MUTED = "#8f8fa0"


def load_styles() -> str:
    """Read the app stylesheet, resolving the ``__RES__`` token to the
    resources directory so QSS ``url(...)`` icon references resolve no matter
    what the working directory is.
    """
    try:
        qss = _STYLES_PATH.read_text()
    except OSError:
        return ""
    return qss.replace("__RES__", _RESOURCES_DIR.as_posix())


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------


@lru_cache(maxsize=256)
def tinted_icon(name: str, color: str, size: int = 18) -> QIcon:
    """Load a monochrome SVG from ``resources/icons`` and recolour it.

    A single white source glyph is tinted at runtime so the same asset serves
    both the muted (default) and accent (active) states.
    """
    renderer = QSvgRenderer((_ICONS_DIR / f"{name}.svg").as_posix())
    scale = 2  # render at 2x for crisp Retina output
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(pm.rect(), QColor(color))
    painter.end()
    pm.setDevicePixelRatio(scale)
    return QIcon(pm)


def icon_label(
    name: str,
    color: str = ON_SURFACE_VARIANT,
    size: int = 18,
    parent: QWidget | None = None,
) -> QLabel:
    """A QLabel showing a tinted SVG glyph, for use inside rows/pills."""
    lbl = QLabel(parent)
    lbl.setPixmap(tinted_icon(name, color, size).pixmap(size, size))
    lbl.setFixedSize(size, size)
    return lbl


# ---------------------------------------------------------------------------
# Toggle switch (pill) — a painted drop-in replacement for checkbox toggles
# ---------------------------------------------------------------------------


class ToggleSwitch(QAbstractButton):
    """A macOS-style pill toggle. Exposes ``isChecked()``/``setChecked()`` so
    it slots in wherever a boolean checkbox was previously used."""

    def __init__(
        self, checked: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._track_w = 42
        self._track_h = 24
        self._margin = 3
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(self._track_w, self._track_h)
        self._offset = 1.0 if checked else 0.0
        self.setChecked(checked)
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.toggled.connect(self._animate)

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._track_w, self._track_h)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        radius = self._track_h / 2
        t = self._offset

        off = QColor(255, 255, 255, 38)
        on = QColor(PRIMARY_CONTAINER)
        track = QColor(
            round(off.red() + (on.red() - off.red()) * t),
            round(off.green() + (on.green() - off.green()) * t),
            round(off.blue() + (on.blue() - off.blue()) * t),
            round(off.alpha() + (255 - off.alpha()) * t),
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(
            QRectF(0, 0, self._track_w, self._track_h), radius, radius
        )

        knob_d = self._track_h - self._margin * 2
        travel = self._track_w - knob_d - self._margin * 2
        x = self._margin + t * travel
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(x, self._margin, knob_d, knob_d))
        painter.end()



def hint(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setProperty("hint", True)
    label.setWordWrap(True)
    return label


def page_header(parent: QWidget, title: str, subtitle: str) -> QWidget:
    """A large title + one-line description shown at the top of each page."""
    holder = QWidget(parent)
    v = QVBoxLayout(holder)
    v.setContentsMargins(0, 0, 0, 2)
    v.setSpacing(4)
    t = QLabel(title, holder)
    t.setProperty("pageTitle", True)
    v.addWidget(t)
    if subtitle:
        s = QLabel(subtitle, holder)
        s.setProperty("pageSubtitle", True)
        s.setWordWrap(True)
        v.addWidget(s)
    return holder


# ---------------------------------------------------------------------------
# Inset-grouped sections (caption above a card) — the core new layout idiom
# ---------------------------------------------------------------------------


def section_caption(parent: QWidget, text: str) -> QLabel:
    """The small uppercase caption that sits above an inset-grouped card."""
    lbl = QLabel(text.upper(), parent)
    lbl.setProperty("sectionCaption", True)
    return lbl


def _divider(parent: QWidget) -> QFrame:
    div = QFrame(parent)
    div.setProperty("rowDivider", True)
    div.setFrameShape(QFrame.NoFrame)
    div.setFixedHeight(1)
    return div


def grouped_card(parent: QWidget, rows: list[QWidget]) -> QFrame:
    """An inset-grouped card: rows stacked flush, separated by hairlines."""
    frame = QFrame(parent)
    frame.setProperty("card", True)
    v = QVBoxLayout(frame)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    for i, row in enumerate(rows):
        if i > 0:
            v.addWidget(_divider(frame))
        v.addWidget(row)
    return frame


def section(parent: QWidget, caption: str, rows: list[QWidget]) -> QWidget:
    """Uppercase caption above an inset-grouped card of divided rows."""
    holder = QWidget(parent)
    v = QVBoxLayout(holder)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(8)
    if caption:
        v.addWidget(section_caption(holder, caption))
    v.addWidget(grouped_card(holder, rows))
    return holder


def panel_section(
    parent: QWidget, caption: str, items: list, description: str = ""
) -> QWidget:
    """Uppercase caption above a padded card holding arbitrary widgets/layouts
    (for forms and free-form content rather than divided rows)."""
    holder = QWidget(parent)
    v = QVBoxLayout(holder)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(8)
    if caption:
        v.addWidget(section_caption(holder, caption))
    frame = QFrame(holder)
    frame.setProperty("card", True)
    inner = QVBoxLayout(frame)
    inner.setContentsMargins(16, 16, 16, 16)
    inner.setSpacing(12)
    for item in items:
        if isinstance(item, QWidget):
            inner.addWidget(item)
        else:
            inner.addLayout(item)
    if description:
        inner.addWidget(hint(description, frame))
    v.addWidget(frame)
    return holder


def setting_row(
    parent: QWidget,
    title: str,
    subtitle: str = "",
    control: QWidget | None = None,
    *,
    icon: str | None = None,
) -> QWidget:
    """A single card row: title (+ optional subtitle/icon) left, control right."""
    row = QWidget(parent)
    row.setProperty("settingRow", True)
    h = QHBoxLayout(row)
    h.setContentsMargins(16, 12, 16, 12)
    h.setSpacing(12)

    if icon is not None:
        h.addWidget(icon_label(icon, MUTED, 18, row), 0, Qt.AlignVCenter)

    text_col = QVBoxLayout()
    text_col.setContentsMargins(0, 0, 0, 0)
    text_col.setSpacing(2)
    t = QLabel(title, row)
    t.setProperty("rowTitle", True)
    text_col.addWidget(t)
    if subtitle:
        s = QLabel(subtitle, row)
        s.setProperty("rowSubtitle", True)
        s.setWordWrap(True)
        text_col.addWidget(s)
    h.addLayout(text_col, 1)

    if control is not None:
        h.addWidget(control, 0, Qt.AlignVCenter)
    return row


def pill(
    text: str, tone: str = "neutral", parent: QWidget | None = None
) -> QLabel:
    """A small rounded status/badge label. ``tone`` ∈ {neutral, accent, success}."""
    lbl = QLabel(text, parent)
    lbl.setProperty("pill", True)
    lbl.setProperty("tone", tone)
    return lbl


# ---------------------------------------------------------------------------
# Legacy helpers (still used by not-yet-ported call sites)
# ---------------------------------------------------------------------------


def card(parent: QWidget, title: str, rows: list, description: str = "") -> QFrame:
    """A rounded panel grouping one section of settings."""
    frame = QFrame(parent)
    frame.setProperty("card", True)
    v = QVBoxLayout(frame)
    v.setContentsMargins(16, 14, 16, 16)
    v.setSpacing(10)
    if title:
        title_label = QLabel(title, frame)
        title_label.setProperty("sectionTitle", True)
        v.addWidget(title_label)
    if description:
        v.addWidget(hint(description, frame))
    for row in rows:
        if isinstance(row, QWidget):
            v.addWidget(row)
        else:
            v.addLayout(row)
    return frame


def checkbox_with_sub(
    parent: QWidget, title: str, subtitle: str, checked: bool
) -> QCheckBox:
    """A checkbox with a muted one-line explanation shown beneath it."""
    box = QCheckBox(title, parent)
    box.setChecked(checked)
    if subtitle:
        sub = QLabel(subtitle, parent)
        sub.setProperty("toggleHint", True)
        sub.setWordWrap(True)
        box.setProperty("_subtitle_label", sub)  # consumed by subgroup()
    return box


def subgroup(parent: QWidget, label: str, widgets: list) -> QWidget:
    """A small caption over a cluster of related toggles inside a card."""
    holder = QWidget(parent)
    v = QVBoxLayout(holder)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(8)
    if label:
        caption = QLabel(label, holder)
        caption.setProperty("groupCaption", True)
        v.addWidget(caption)
    for w in widgets:
        row = QVBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(1)
        row.addWidget(w)
        sub = w.property("_subtitle_label")
        if sub is not None:
            row.addWidget(sub)
        v.addLayout(row)
    return holder


def scroll_page(inner: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidget(inner)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    enable_smooth_scroll(scroll)
    return scroll
