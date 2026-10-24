"""Offscreen Qt integration check without touching legacy settings or assets."""

import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from animation import AnimationLibrary
from main import PetWidget, load_pixmaps


class WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_draws_and_advances(self):
        root = Path(__file__).resolve().parents[1] / "public_assets"
        library = AnimationLibrary.load(root, allow_placeholder=True)
        widget = PetWidget(library, load_pixmaps(library))
        try:
            widget.show()
            self.assertEqual((widget.width(), widget.height()), (96, 152))
            self.assertFalse(widget.grab().isNull())
            QTest.qWait(120)
            self.assertGreater(widget.frame_index, 0)

            local = QPointF(48, 40)
            global_pos = QPointF(widget.pos()) + local
            origin = widget.pos()
            widget.mousePressEvent(QMouseEvent(
                QEvent.Type.MouseButtonPress, local, global_pos,
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ))
            self.assertIsNotNone(widget.drag_offset)
            widget.mouseMoveEvent(QMouseEvent(
                QEvent.Type.MouseMove, local, global_pos + QPointF(20, 0),
                Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ))
            self.assertEqual(widget.pos(), origin + QPoint(20, 0))

            feet = widget.y() + widget._ground_offset()
            widget.wheelEvent(QWheelEvent(
                local, global_pos, QPoint(), QPoint(0, 120),
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.ScrollUpdate, False,
            ))
            self.assertEqual(widget.height_setting, 140)
            self.assertEqual(widget.y() + widget._ground_offset(), feet)
        finally:
            widget.close()
            self.assertFalse(widget.timer.isActive())


if __name__ == "__main__":
    unittest.main()
