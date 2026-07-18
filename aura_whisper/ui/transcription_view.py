from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from aura_whisper.ui.smooth_scroll import enable_smooth_scroll


class TranscriptionView(QWidget):
    copy_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._text = QTextEdit(self)
        self._text.setReadOnly(True)
        self._text.setPlaceholderText("Hold your hotkey and speak…")
        self._text.setObjectName("transcription")
        self._text.setFrameShape(QTextEdit.NoFrame)
        enable_smooth_scroll(self._text)

        self._copy_btn = QPushButton("Copy", self)
        self._copy_btn.setObjectName("copyBtn")
        self._copy_btn.setCursor(Qt.PointingHandCursor)
        self._copy_btn.clicked.connect(self._on_copy)

        self._clear_btn = QPushButton("Clear", self)
        self._clear_btn.setObjectName("clearBtn")
        self._clear_btn.setCursor(Qt.PointingHandCursor)
        self._clear_btn.clicked.connect(self._text.clear)

        self._status = QLabel("", self)
        self._status.setObjectName("status")

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._status, 1)
        row.addWidget(self._clear_btn)
        row.addWidget(self._copy_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(self._text, 1)
        layout.addLayout(row)

    def append_text(self, text: str) -> None:
        if not text.strip():
            return
        current = self._text.toPlainText()
        sep = " " if current and not current.endswith((" ", "\n")) else ""
        self._text.setPlainText(current + sep + text.strip())
        self._text.moveCursor(QTextCursor.MoveOperation.End)
        self._flash_status("Transcribed")

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def _flash_status(self, text: str) -> None:
        self._status.setText(text)
        QTimer.singleShot(1500, lambda: self._status.setText(""))

    def _on_copy(self) -> None:
        text = self._text.toPlainText()
        if text:
            QGuiApplication.clipboard().setText(text)
            self._flash_status("Copied")
        self.copy_requested.emit()

    def plain_text(self) -> str:
        return self._text.toPlainText()
