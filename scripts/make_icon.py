"""Render the AuraWhisper app icon and pack it into an .icns.

Run:  python scripts/make_icon.py
Writes aura_whisper/resources/AppIcon.icns (referenced by setup.py).
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "aura_whisper" / "resources" / "AppIcon.icns"


def squircle(rect: QRectF) -> QPainterPath:
    """Apple-style continuous-corner rounded square (superellipse approx)."""
    path = QPainterPath()
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    r = w * 0.225
    k = r * 1.28  # stretch the curve for the smooth 'squircle' shoulder
    path.moveTo(x + k, y)
    path.lineTo(x + w - k, y)
    path.cubicTo(x + w - r * 0.35, y, x + w, y + r * 0.35, x + w, y + k)
    path.lineTo(x + w, y + h - k)
    path.cubicTo(x + w, y + h - r * 0.35, x + w - r * 0.35, y + h, x + w - k, y + h)
    path.lineTo(x + k, y + h)
    path.cubicTo(x + r * 0.35, y + h, x, y + h - r * 0.35, x, y + h - k)
    path.lineTo(x, y + k)
    path.cubicTo(x, y + r * 0.35, x + r * 0.35, y, x + k, y)
    return path


def render(size: int = 1024) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 1024

    # macOS icon grid: 824pt body centred on a 1024 canvas.
    body = QRectF(100 * s, 100 * s, 824 * s, 824 * s)
    shape = squircle(body)

    # Soft drop shadow.
    for i, a in enumerate((28, 18, 10)):
        off = (8 + i * 8) * s
        p.fillPath(squircle(body.translated(0, off).adjusted(-i * 4 * s, 0, i * 4 * s, 0)), QColor(0, 0, 0, a))

    grad = QLinearGradient(body.topLeft(), body.bottomRight())
    grad.setColorAt(0.0, QColor("#3FA2FF"))
    grad.setColorAt(0.55, QColor("#6A5CFA"))
    grad.setColorAt(1.0, QColor("#B04BE8"))
    p.fillPath(shape, grad)

    # Top glow for depth.
    glow = QRadialGradient(QPointF(body.center().x(), body.top() + 120 * s), 620 * s)
    glow.setColorAt(0.0, QColor(255, 255, 255, 70))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(shape, glow)
    p.setPen(QPen(QColor(255, 255, 255, 60), 3 * s))
    p.drawPath(shape)

    cx, cy = 512 * s, 500 * s
    white = QColor(255, 255, 255)

    # Waveform bars either side of the mic.
    p.setPen(Qt.NoPen)
    bars = [(-300, 90), (-240, 170), (-180, 120), (180, 120), (240, 170), (300, 90)]
    for dx, h in bars:
        bw = 30 * s
        a = 150 if abs(dx) == 300 else 215
        p.setBrush(QColor(255, 255, 255, a))
        p.drawRoundedRect(QRectF(cx + dx * s - bw / 2, cy - h * s / 2, bw, h * s), bw / 2, bw / 2)

    # Mic capsule.
    p.setBrush(white)
    cap_w, cap_h = 150 * s, 270 * s
    p.drawRoundedRect(QRectF(cx - cap_w / 2, cy - 200 * s, cap_w, cap_h), cap_w / 2, cap_w / 2)
    # Cradle, stem and base.
    pen = QPen(white, 34 * s)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(cx - 125 * s, cy - 50 * s, 250 * s, 220 * s), 180 * 16, 180 * 16)
    p.drawLine(QPointF(cx, cy + 170 * s), QPointF(cx, cy + 240 * s))
    p.drawLine(QPointF(cx - 80 * s, cy + 240 * s), QPointF(cx + 80 * s, cy + 240 * s))
    p.end()
    return img


def main() -> None:
    QGuiApplication(sys.argv)
    master = render(1024)
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        for pt in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = pt * scale
                name = f"icon_{pt}x{pt}{'@2x' if scale == 2 else ''}.png"
                master.scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(
                    str(iconset / name)
                )
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT)], check=True)
        shutil.copy(iconset / "icon_512x512@2x.png", Path(tmp) / "preview.png")
        master.save(str(ROOT / "scripts" / "AppIcon-preview.png"))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
