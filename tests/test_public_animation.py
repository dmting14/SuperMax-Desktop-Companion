"""Public art checks never read the private Max animation."""

import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from animation import AnimationLibrary
from main import PetWidget, load_pixmaps
from public_assets.generate_walk import frame


class PublicAnimationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_generated_cycle_and_transparency(self):
        library = AnimationLibrary.load(ROOT / "public_assets")
        self.assertEqual((library.clip.id, library.clip.fps, len(library.clip.frames)),
                         ("walk_right", 24, 24))
        self.assertEqual(library.clip.frame_index(1.0), 0)
        for path in library.clip.frames:
            image = QImage(str(path))
            self.assertEqual((image.width(), image.height()), (480, 760))
            self.assertTrue(image.hasAlphaChannel())
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
            self.assertEqual(image.pixelColor(240, 205).alpha(), 255)

    def test_wraparound_motion_is_continuous(self):
        first, last, quarter = frame(0), frame(23), frame(6)
        def difference(a, b):
            return sum(a.pixelColor(x, y) != b.pixelColor(x, y)
                       for y in range(130, 745, 6) for x in range(120, 365, 6))
        self.assertLess(difference(first, last), difference(first, quarter))
        for index in range(24):
            image = frame(index)
            bottom = max(y for y in range(720, 745)
                         if any(image.pixelColor(x, y).alpha() for x in range(145, 335, 4)))
            self.assertGreaterEqual(bottom, 732)
            self.assertLessEqual(bottom, 738)

    def test_qt_widget_plays_public_frames(self):
        library = AnimationLibrary.load(ROOT / "public_assets")
        widget = PetWidget(library, load_pixmaps(library))
        try:
            widget.show()
            start = widget.frame_index
            QTest.qWait(120)
            self.assertNotEqual(widget.frame_index, start)
            self.assertFalse(widget.grab().isNull())
        finally:
            widget.close()
            self.assertFalse(widget.timer.isActive())


if __name__ == "__main__":
    unittest.main()
