"""Minimal PySide6 desktop pet. All project assets are read only."""

import argparse
import os
from pathlib import Path
import sqlite3
import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QMouseEvent, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from animation import AnimationLibrary


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_THEME = "public"


def resolve_assets_root(theme: str | None = None) -> Path:
    selected = (theme or os.environ.get("SUPERMAX_THEME", DEFAULT_THEME)).lower()
    if selected == "public":
        return PACKAGE_ROOT / "public_assets"
    if selected == "private":
        location = os.environ.get("SUPERMAX_PRIVATE_ASSETS_ROOT")
        if not location:
            raise ValueError("Set SUPERMAX_PRIVATE_ASSETS_ROOT to a private asset root")
        return Path(location)
    raise ValueError("SUPERMAX_THEME must be 'public' or 'private'")


PROJECT_ROOT = resolve_assets_root()


def load_pixmaps(library: AnimationLibrary) -> tuple[QPixmap, ...]:
    if library.clip.id == "placeholder":
        from placeholder import draw_placeholder_frames
        return draw_placeholder_frames(library.canvas_width, library.canvas_height)
    frames = []
    for path in library.clip.frames:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            raise ValueError(f"无法读取动画帧: {path}")
        if pixmap.width() != library.canvas_width or pixmap.height() != library.canvas_height:
            raise ValueError(f"动画帧尺寸与 manifest 不符: {path}")
        if not pixmap.hasAlphaChannel():
            raise ValueError(f"动画帧没有透明通道: {path}")
        frames.append(pixmap)
    return tuple(frames)


class PetWidget(QWidget):
    def __init__(self, library: AnimationLibrary, frames: tuple[QPixmap, ...]):
        super().__init__()
        self.library = library
        self.frames = frames
        self.height_setting = 140
        self.frame_index = 0
        self.started_at = time.monotonic()
        self.drag_offset = None
        self.focus_state = None  # focus_start / focus_pause / focus_complete

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setWindowTitle("SuperMax Python 桌宠")
        self._resize_to_character_height()
        area = QApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 20,
                  area.bottom() - self._ground_offset())

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.advance_frame)
        self.timer.start()

    def _ground_offset(self) -> int:
        return round(self.library.ground_y * self.height_setting
                     / self.library.character_height)

    def _resize_to_character_height(self) -> None:
        scale = self.height_setting / self.library.character_height
        self.resize(round(self.library.canvas_width * scale),
                    round(self.library.canvas_height * scale))

    def advance_frame(self) -> None:
        elapsed = time.monotonic() - self.started_at
        index = self.library.clip.frame_index(elapsed)
        if index != self.frame_index:
            self.frame_index = index
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.rect(), self.frames[self.frame_index])

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            x = int(event.position().x() * self.library.canvas_width / self.width())
            y = int(event.position().y() * self.library.canvas_height / self.height())
            if (0 <= x < self.library.canvas_width and 0 <= y < self.library.canvas_height
                    and self.frames[self.frame_index].toImage().pixelColor(x, y).alpha() > 20):
                self.drag_offset = event.globalPosition().toPoint() - self.pos()
                event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            menu = QMenu(self)
            menu.addAction("退出", QApplication.instance().quit)
            menu.exec(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()

    def closeEvent(self, event) -> None:
        self.timer.stop()
        super().closeEvent(event)

    def set_focus_state(self, state: str) -> None:
        """State hook for future focus animations; keep the current clip playing."""
        if state not in {"focus_start", "focus_pause", "focus_complete"}:
            raise ValueError(f"Unknown focus state: {state}")
        self.focus_state = state


def main() -> int:
    import faulthandler
    faulthandler.enable(all_threads=True)
    parser = argparse.ArgumentParser(description="SuperMax Python 桌宠")
    parser.add_argument("--check", action="store_true", help="只读检查动画加载，不显示窗口")
    parser.add_argument("--smoke", action="store_true", help="Start UI and exit after one second")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    try:
        library = AnimationLibrary.load(PROJECT_ROOT, allow_placeholder=True)
        frames = load_pixmaps(library)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"启动失败: {error}", file=sys.stderr)
        return 1
    if args.check:
        print(f"PASS {library.clip.id}: {len(frames)} 帧, {library.clip.fps} FPS, "
              f"{library.canvas_width}x{library.canvas_height}, 透明通道可读")
        return 0
    pet = PetWidget(library, frames)
    from demo_ui import DemoController
    from task_store import TaskRepository
    try:
        task_repository = TaskRepository()
    except (OSError, sqlite3.Error) as error:
        print(f"Task storage unavailable; using memory only: {error}", file=sys.stderr)
        task_repository = None
    demo = DemoController(pet, task_repository)
    pet.show()
    demo.show()
    if args.smoke:
        QTimer.singleShot(1000, app.quit)
    exit_code = app.exec()
    demo.shutdown()
    pet.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
