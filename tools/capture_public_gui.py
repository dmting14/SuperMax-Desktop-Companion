"""Capture live public Qt widgets using empty temporary SQLite databases."""

import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from animation import AnimationLibrary
from demo_ui import DemoController
from main import PetWidget, PROJECT_ROOT, load_pixmaps
from news_store import NewsRepository
from race_store import RaceRepository
from task_store import TaskRepository


def main() -> None:
    app = QApplication([])
    library = AnimationLibrary.load(PROJECT_ROOT)
    if not all(root / "public_assets" in frame.parents for frame in library.clip.frames):
        raise RuntimeError("Screenshot capture requires the original public animation")
    pet = PetWidget(library, load_pixmaps(library))
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        demo = DemoController(pet, TaskRepository(temp / "tasks.sqlite3"),
                              NewsRepository(temp / "news.sqlite3"),
                              RaceRepository(temp / "races.sqlite3"))
        pet.show()
        demo.show()
        QTest.qWait(120)
        output = root / "docs" / "screenshots"
        output.mkdir(parents=True, exist_ok=True)
        for index, name in ((4, "pomodoro"), (3, "todo"), (2, "news")):
            demo.panel.show_page(index)
            demo.bar.set_active(index)
            app.processEvents()
            canvas = QImage(350, 520, QImage.Format.Format_ARGB32)
            canvas.fill(QColor("#eef0f2"))
            painter = QPainter(canvas)
            painter.drawPixmap(115, 0, pet.grab())
            painter.drawPixmap(53, 130, demo.bar.grab())
            painter.drawPixmap(14, 210, demo.panel.grab())
            painter.end()
            path = output / f"public-{name}.png"
            if not canvas.save(str(path), "PNG"):
                raise OSError(f"Could not save {path}")
            print(path)
        demo.shutdown()
        pet.close()


if __name__ == "__main__":
    main()
