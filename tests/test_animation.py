"""Read-only checks against the real manifest and 22-frame animation."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from animation import AnimationLibrary


class AnimationTests(unittest.TestCase):
    def test_existing_walk_loop(self):
        root = Path(__file__).resolve().parents[1] / "public_assets"
        library = AnimationLibrary.load(root, allow_placeholder=True)
        self.assertEqual(library.clip.id, "walk_right")
        self.assertEqual(len(library.clip.frames), 24)
        self.assertEqual(library.clip.fps, 24)
        self.assertEqual(library.clip.frame_index(0), 0)
        self.assertEqual(library.clip.frame_index(23 / 24), 23)
        self.assertEqual(library.clip.frame_index(24 / 24), 0)
        self.assertEqual((library.canvas_width, library.canvas_height), (480, 760))


if __name__ == "__main__":
    unittest.main()
