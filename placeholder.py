"""Code-drawn generic walking silhouette for public clones without local art."""

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap


def draw_placeholder_frames(width: int, height: int) -> tuple[QPixmap, ...]:
    frames = []
    for index in range(22):
        phase = 2 * math.pi * index / 22
        swing = math.sin(phase)
        frame = QPixmap(width, height)
        frame.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#331f2b"), 9, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        painter.setBrush(QColor("#bc4a4d"))
        painter.drawEllipse(QPointF(width / 2, 170), 80, 74)
        painter.setBrush(QColor("#282d3a"))
        painter.drawRoundedRect(175, 240, 130, 225, 35, 35)
        painter.setPen(QPen(QColor("#282d3a"), 24, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(218, 454), QPointF(206 + 49 * swing, 700))
        painter.drawLine(QPointF(264, 454), QPointF(274 - 49 * swing, 700))
        painter.drawLine(QPointF(178, 290), QPointF(150 - 25 * swing, 475))
        painter.drawLine(QPointF(302, 290), QPointF(330 + 25 * swing, 475))
        painter.end()
        frames.append(frame)
    return tuple(frames)
