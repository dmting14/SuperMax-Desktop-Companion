"""Generate the original public stick-figure walk cycle with Qt vector drawing.

No private image is read. Re-running this script overwrites only the generated
PNG sequence in public_assets/animations/walk_right.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication


WIDTH, HEIGHT = 480, 760
FRAMES, FPS = 24, 24
BASELINE = 730
OUT = Path(__file__).resolve().parent / "animations" / "walk_right"
INK = QColor("#273543")
ACCENT = QColor("#f07562")


def line(painter: QPainter, a: QPointF, b: QPointF, width: float, color: QColor) -> None:
    pen = QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(a, b)


def frame(index: int) -> QImage:
    phase = 2 * math.pi * index / FRAMES
    canvas = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # A small double-frequency body lift keeps the torso continuous at wraparound.
    bob = 5.0 * (1 - math.cos(2 * phase)) / 2
    hip = QPointF(240, 420 - bob)
    shoulder = QPointF(240 + 3 * math.sin(phase), 270 - bob)
    neck = QPointF(shoulder.x(), 252 - bob)
    head = QPointF(shoulder.x(), 204 - bob)

    # Limbs follow opposing joint phases. A planted foot stays on the same baseline.
    for side, offset in ((-1, 0), (1, math.pi)):
        angle = phase + offset
        hip_joint = QPointF(hip.x() + side * 15, hip.y())
        foot = QPointF(hip_joint.x() + 73 * math.sin(angle),
                       BASELINE - 36 * max(0.0, math.cos(angle)))
        knee = QPointF((hip_joint.x() + foot.x()) / 2 + side * 22,
                       566 - bob - 15 * max(0.0, math.cos(angle)))
        line(painter, hip_joint, knee, 19, INK)
        line(painter, knee, foot, 17, INK)
        line(painter, foot + QPointF(-15, 0), foot + QPointF(20, 0), 12, INK)

    line(painter, hip, shoulder, 30, INK)
    line(painter, shoulder, neck, 19, INK)
    for side, offset in ((-1, math.pi), (1, 0)):
        angle = phase + offset
        arm_root = QPointF(shoulder.x() + side * 25, shoulder.y() + 12)
        elbow = QPointF(arm_root.x() + side * 31 + 34 * math.sin(angle),
                        arm_root.y() + 80)
        hand = QPointF(elbow.x() + side * 13 + 16 * math.sin(angle), elbow.y() + 70)
        line(painter, arm_root, elbow, 14, INK)
        line(painter, elbow, hand, 12, INK)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ACCENT)
        painter.drawEllipse(hand, 9, 9)

    # Plain circular head: no helmet, clothing, logo or recognizable character detail.
    painter.setPen(QPen(INK, 12))
    painter.setBrush(QColor("#f8d6b4"))
    painter.drawEllipse(head, 51, 51)
    painter.end()
    return canvas


def main() -> None:
    app = QApplication.instance() or QApplication([])
    OUT.mkdir(parents=True, exist_ok=True)
    for index in range(FRAMES):
        path = OUT / f"frame-{index:04d}.png"
        if not frame(index).save(str(path), "PNG"):
            raise OSError(f"Could not write {path}")
    print(f"Generated {FRAMES} transparent frames at {FPS} FPS: {OUT}")
    _ = app


if __name__ == "__main__":
    main()
