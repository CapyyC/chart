"""The app icon, drawn with QPainter (also used to build the .ico for Windows)."""

from __future__ import annotations

import struct

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QLinearGradient, QPainter, QPen, QPixmap

LANES = ["#ff3b4a", "#ffd21f", "#2f9bff", "#2fdc6a"]


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = size / 256.0
    bg = QLinearGradient(0, 0, size, size)
    bg.setColorAt(0, QColor("#ff6a3d"))
    bg.setColorAt(1, QColor("#ff3d77"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(bg))
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 56 * s, 56 * s)
    # Highway in perspective
    p.setBrush(QColor(18, 20, 28, 235))
    from PySide6.QtGui import QPolygonF
    hw = QPolygonF([QPointF(98 * s, 40 * s), QPointF(158 * s, 40 * s), QPointF(214 * s, 214 * s), QPointF(42 * s, 214 * s)])
    p.drawPolygon(hw)
    # Gems
    rows = [(196, [0, 2]), (150, [1, 3]), (112, [0]), (80, [2])]
    for y, lanes in rows:
        t = (y - 40) / 174.0
        left = 98 + (42 - 98) * t
        right = 158 + (214 - 158) * t
        lane_w = (right - left) / 4
        for lane in lanes:
            cx = left + lane_w * (lane + 0.5)
            w = lane_w * 0.8
            h = lane_w * 0.36
            p.setBrush(QColor(LANES[lane]))
            p.setPen(QPen(QColor(255, 255, 255, 200), max(1.0, 3 * s * t)))
            p.drawRoundedRect(QRectF((cx - w / 2) * s, (y - h / 2) * s, w * s, h * s), h * s / 2, h * s / 2)
    # Kick bar
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#ff9a1f"))
    p.drawRoundedRect(QRectF(50 * s, 170 * s, 156 * s, 8 * s), 4 * s, 4 * s)
    p.end()
    return img


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(QPixmap.fromImage(render(size)))
    return icon


def write_ico(path: str, sizes=(16, 24, 32, 48, 64, 128, 256)) -> None:
    """Write a multi-resolution .ico with PNG-compressed images."""
    pngs = []
    for size in sizes:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        render(size).save(buf, "PNG")
        pngs.append((size, bytes(ba)))
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries = b""
    data = b""
    for size, png in pngs:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    with open(path, "wb") as f:
        f.write(header + entries + data)
