from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from aura_whisper.ui.smooth_scroll import enable_smooth_scroll


_RESOURCES_DIR = Path(__file__).parent.parent / "resources"
_STYLES_PATH = _RESOURCES_DIR / "styles.qss"


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
    v.setSpacing(3)
    t = QLabel(title, holder)
    t.setProperty("pageTitle", True)
    v.addWidget(t)
    if subtitle:
        s = QLabel(subtitle, holder)
        s.setProperty("pageSubtitle", True)
        s.setWordWrap(True)
        v.addWidget(s)
    return holder


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
