"""Compact painted controls that do not need third-party icon assets."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton


class IconButton(QPushButton):
    def __init__(self, icon: str, tooltip: str = "", parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.setToolTip(tooltip)
        self.setFixedSize(25, 25)
        self.phase = 0
        self.spinning = False
        self.selected = False
        self.spin_timer = QTimer(self)
        self.spin_timer.setInterval(35)
        self.spin_timer.timeout.connect(self._spin)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_spinning(self, active: bool) -> None:
        self.spinning = active
        if active:
            self.spin_timer.start()
        else:
            self.spin_timer.stop()
            self.phase = 0
        self.update()

    def _spin(self) -> None:
        self.phase = (self.phase + 15) % 360
        self.update()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#5a6470"), 1))
        painter.setBrush(QColor("#242a31") if not self.isDown() else QColor("#39434c"))
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width()-1, self.height()-1), 6, 6)
        painter.translate(self.width()/2, self.height()/2)
        if self.icon_name == "refresh":
            painter.rotate(self.phase)
        pen = QPen(QColor("#ffad72" if self.selected else "#e9eef0"), 1.9)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.icon_name in ("up", "down"):
            if self.icon_name == "up":
                painter.drawLine(-5, 2, 0, -3)
                painter.drawLine(0, -3, 5, 2)
            else:
                painter.drawLine(-5, -2, 0, 3)
                painter.drawLine(0, 3, 5, -2)
        elif self.icon_name in ("like", "dislike"):
            if self.icon_name == "dislike":
                painter.rotate(180)
            path = QPainterPath()
            path.moveTo(-6, -3)
            path.lineTo(-3, -3)
            path.lineTo(-3, 4)
            path.lineTo(-6, 4)
            path.closeSubpath()
            path.moveTo(-2, -3)
            path.lineTo(0, -3)
            path.lineTo(2, -7)
            path.lineTo(4, -7)
            path.lineTo(3, -3)
            path.lineTo(6, -3)
            path.lineTo(5, 4)
            path.lineTo(-2, 4)
            path.closeSubpath()
            painter.drawPath(path)
        elif self.icon_name == "play":
            path = QPainterPath()
            path.moveTo(-3, -6)
            path.lineTo(6, 0)
            path.lineTo(-3, 6)
            path.closeSubpath()
            painter.setBrush(QColor("#e9eef0"))
            painter.drawPath(path)
        elif self.icon_name == "pause":
            painter.setPen(QPen(QColor("#e9eef0"), 3))
            painter.drawLine(-3, -5, -3, 5)
            painter.drawLine(3, -5, 3, 5)
        elif self.icon_name in ("refresh", "reset"):
            painter.drawArc(QRectF(-6, -6, 12, 12), 35*16, 295*16)
            painter.drawLine(5, -5, 6, 0)
            painter.drawLine(6, 0, 1, -1)
        painter.end()
