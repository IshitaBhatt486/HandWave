"""Small line-drawn icons for gesture names."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

def gesture_icon(name: str, theme: str = "dark") -> QIcon:
    """Build a local theme-aware icon; unknown names receive a safe fallback."""
    pixmap = QPixmap(24, 24); pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor("#9c7a3c" if theme == "light" else "#c9a96e")
    painter.setPen(QPen(color, 1.4)); painter.setBrush(Qt.BrushStyle.NoBrush)
    if "Swipe" in name:
        painter.drawLine(5, 12, 19, 12)
        if "Left" in name: painter.drawLine(5, 12, 10, 7); painter.drawLine(5, 12, 10, 17)
        elif "Right" in name: painter.drawLine(19, 12, 14, 7); painter.drawLine(19, 12, 14, 17)
        elif "Up" in name: painter.drawLine(12, 5, 12, 19); painter.drawLine(12, 5, 7, 10); painter.drawLine(12, 5, 17, 10)
        else: painter.drawLine(12, 5, 12, 19); painter.drawLine(12, 19, 7, 14); painter.drawLine(12, 19, 17, 14)
    else:
        painter.drawEllipse(8, 8, 8, 8)
    painter.end()
    return QIcon(pixmap)
