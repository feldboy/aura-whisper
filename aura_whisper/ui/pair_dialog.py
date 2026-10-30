from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from aura_whisper.remote.server import PAIR_CODE_TTL, PhoneServer


def qr_pixmap(text: str, size: int = 260) -> QPixmap:
    """Render ``text`` as a QR code (black on white, with a quiet zone)."""
    import qrcode

    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    cell = max(1, size // len(matrix))
    side = cell * len(matrix)
    pm = QPixmap(side, side)
    pm.fill(Qt.white)
    p = QPainter(pm)
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                p.fillRect(x * cell, y * cell, cell, cell, QColor("black"))
    p.end()
    return pm


class PairPhoneDialog(QDialog):
    """Shows a one-time pairing QR for the phone microphone."""

    def __init__(self, server: PhoneServer, parent=None) -> None:
        super().__init__(parent)
        self._server = server
        self.setWindowTitle("Pair phone — AuraWhisper")
        self.setLayoutDirection(Qt.LeftToRight)

        intro = QLabel(
            "Scan with your phone's camera (same Wi-Fi as this Mac). The first "
            "time, the browser warns about the certificate: tap Advanced → "
            "Proceed, then approve the phone here. To get rid of the warning "
            "for good, open “🔒” at the bottom of the phone page.",
            self,
        )
        intro.setWordWrap(True)

        self._qr = QLabel(self)
        self._qr.setAlignment(Qt.AlignCenter)
        self._url = QLabel(self)
        self._url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._url.setAlignment(Qt.AlignCenter)
        self._url.setWordWrap(True)
        self._expiry = QLabel(self)
        self._expiry.setAlignment(Qt.AlignCenter)

        new_btn = QPushButton("New code", self)
        new_btn.clicked.connect(self._refresh)
        self._forget_btn = QPushButton(self)
        self._forget_btn.clicked.connect(self._forget_all)
        close_btn = QPushButton("Close", self)
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self._forget_btn)
        buttons.addStretch(1)
        buttons.addWidget(new_btn)
        buttons.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(intro)
        layout.addWidget(self._qr)
        layout.addWidget(self._url)
        layout.addWidget(self._expiry)
        layout.addLayout(buttons)
        self.setFixedWidth(380)

        self._expire_timer = QTimer(self)
        self._expire_timer.setSingleShot(True)
        self._expire_timer.timeout.connect(self._expired)
        self._refresh()

    def _refresh(self) -> None:
        try:
            url = self._server.pairing_url()
        except Exception as e:
            self._qr.clear()
            self._url.setText(f"Phone microphone server isn't running: {e}")
            self._expiry.clear()
            return
        self._qr.setPixmap(qr_pixmap(url))
        self._url.setText(url)
        self._expiry.setText(f"Code works once, for {PAIR_CODE_TTL // 60} minutes.")
        self._expire_timer.start(PAIR_CODE_TTL * 1000)
        self.refresh_devices()

    def _expired(self) -> None:
        self._qr.clear()
        self._url.clear()
        self._expiry.setText("Code expired — press New code.")

    def refresh_devices(self) -> None:
        n = len(self._server.devices)
        self._forget_btn.setText(f"Disconnect all phones ({n})")
        self._forget_btn.setEnabled(n > 0)

    def on_paired(self, name: str) -> None:
        self._expire_timer.stop()
        self._qr.clear()
        self._url.clear()
        self._expiry.setText(f"✓ {name} is connected. You can close this window.")
        self.refresh_devices()

    def _forget_all(self) -> None:
        answer = QMessageBox.question(
            self,
            "Disconnect phones",
            "Disconnect every paired phone? Each will need a new QR to reconnect.",
        )
        if answer == QMessageBox.Yes:
            self._server.devices.clear()
            self.refresh_devices()
