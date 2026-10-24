"""Offscreen checks for the five tires, task board, and timer."""

import os
from pathlib import Path
import sys
import threading
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from animation import AnimationLibrary
from demo_ui import DemoController, NewsPage, Pomodoro, TaskBoard
from f1_data import DriverResult, Race, RaceResult, RaceSession
from main import PetWidget, load_pixmaps
from news_data import NewsItem
from news_store import NewsRepository
from race_store import RaceRepository
from ui_icons import IconButton
from task_store import TaskRepository


class DemoUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_tires_switch_and_animation_continues(self):
        library = AnimationLibrary.load(Path(__file__).resolve().parents[1] / 'public_assets', allow_placeholder=True)
        pet = PetWidget(library, load_pixmaps(library))
        with patch.object(DemoController, "load_race"), patch.object(DemoController, "load_news"):
            demo = DemoController(pet)
            try:
                pet.show()
                demo.show()
                self.assertEqual(len(demo.bar.tire_rects), 5)
                self.assertFalse(demo.bar.grab().isNull())
                self.assertEqual(pet.height_setting, 96)
                self.assertLess(demo.bar.platform_rect.bottom(), demo.bar.tire_rects[0].top())
                self.assertTrue(demo.bar.platform_rect.contains(
                    demo.bar.platform_rect.center().x(),
                    pet.y() + pet._ground_offset() - demo.bar.y()))
                self.assertEqual(len({rect.size().toSize() for rect in demo.bar.tire_rects}), 1)
                for index, rect in enumerate(demo.bar.tire_rects):
                    QTest.mouseClick(demo.bar, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
                    self.assertEqual(demo.active_page, index)
                    self.assertTrue(demo.panel.isVisible())
                    self.assertEqual(demo.panel.stack.currentIndex(), index)
                    self.assertGreaterEqual(demo.panel.y(), demo.bar.y() + demo.bar.height())
                QTest.mouseClick(demo.bar, Qt.MouseButton.LeftButton,
                                 pos=demo.bar.tire_rects[4].center().toPoint())
                self.assertIsNone(demo.active_page)
                self.assertFalse(demo.panel.isVisible())
                QTest.mouseClick(demo.bar, Qt.MouseButton.LeftButton,
                                 pos=demo.bar.tire_rects[2].center().toPoint())
                QTest.mouseClick(demo.panel.close_button, Qt.MouseButton.LeftButton)
                self.assertIsNone(demo.active_page)
                self.assertFalse(demo.panel.isVisible())
                old = pet.frame_index
                QTest.qWait(100)
                self.assertNotEqual(pet.frame_index, old)
            finally:
                demo.shutdown()
                pet.close()

    def test_tasks_four_quadrants_and_delete(self):
        board = TaskBoard()
        for important, urgent in ((True, True), (True, False), (False, True), (False, False)):
            board.input.setText(f"Task {important} {urgent}")
            board.important.setChecked(important)
            board.urgent.setChecked(urgent)
            board.add_task()
        self.assertEqual(len(board.tasks), 4)
        self.assertEqual([group.count() for group in board.groups], [1, 1, 1, 1])
        board.set_done(1, True)
        self.assertTrue(board.tasks[0]["done"])
        board.delete_task(1)
        self.assertEqual(len(board.tasks), 3)

    def test_task_board_reloads_private_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.sqlite3"
            board = TaskBoard(TaskRepository(path))
            board.input.setText("Persisted task")
            board.important.setChecked(True)
            board.add_task()
            reloaded = TaskBoard(TaskRepository(path))
            self.assertEqual(reloaded.tasks[0]["title"], "Persisted task")
            self.assertTrue(reloaded.tasks[0]["important"])

    def test_pomodoro_states(self):
        timer = Pomodoro(duration_seconds=2)
        states = []
        timer.state_changed.connect(states.append)
        timer.start()
        self.assertTrue(timer.running)
        timer.pause()
        self.assertFalse(timer.running)
        timer.start()
        timer.deadline -= 5
        timer.tick()
        self.assertEqual(timer.remaining_seconds, 0)
        timer.reset()
        self.assertEqual(timer.remaining_seconds, 2)
        self.assertEqual(states, ["focus_start", "focus_pause", "focus_start",
                                  "focus_complete", "focus_pause"])

    def test_focus_countdown_stays_visible_after_panel_closes(self):
        library = AnimationLibrary.load(Path(__file__).resolve().parents[1] / 'public_assets', allow_placeholder=True)
        pet = PetWidget(library, load_pixmaps(library))
        demo = DemoController(pet)
        try:
            pet.show()
            demo.show()
            demo.toggle_page(4)
            demo.panel.pomodoro.start()
            demo.panel.collapse()
            self.assertTrue(demo.backdrop.isVisible())
            self.assertFalse(demo.panel.isVisible())
            demo.panel.pomodoro.reset()
            self.assertFalse(demo.backdrop.isVisible())
        finally:
            demo.shutdown()
            pet.close()

    def test_public_clone_uses_generated_placeholder(self):
        root = Path(__file__).resolve().parents[1] / 'public_assets'
        with patch.object(Path, "glob", return_value=[]):
            library = AnimationLibrary.load(root, allow_placeholder=True)
        frames = load_pixmaps(library)
        self.assertEqual(library.clip.id, "placeholder")
        self.assertEqual(len(frames), 22)
        self.assertTrue(all(not frame.isNull() for frame in frames))

    def test_race_pages_and_error_message(self):
        library = AnimationLibrary.load(Path(__file__).resolve().parents[1] / 'public_assets', allow_placeholder=True)
        pet = PetWidget(library, load_pixmaps(library))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        demo = DemoController(pet, race_repository=RaceRepository(Path(directory.name) / "races.sqlite3"))
        try:
            race = Race(2026, 18, "Example GP", "Example Circuit", "Austin", "USA",
                        None, "2026-10-25", (
                            RaceSession("FP1", "2026-10-23", datetime(2026, 10, 23, 17, tzinfo=timezone.utc)),
                            RaceSession("Race", "2026-10-25", None),
                        ))
            demo.race_loaded(0, race, "")
            self.assertIn("Example GP", demo.panel.race_name.text())
            self.assertIn("Example Circuit", demo.panel.race_meta.text())
            self.assertIn("起跑时间尚未公布", demo.panel.countdown_notice.text())
            self.assertFalse(demo.panel.calendar_text.isVisible())
            self.assertEqual(demo.panel.session_layout.count(), 2)
            result = RaceResult(race, (
                DriverResult(1, "winner", "First Driver", "Team A", 25, "Finished"),
                DriverResult(3, "max_verstappen", "Max Verstappen", "Team B", 15, "Finished"),
            ))
            demo.race_loaded(1, result, "")
            self.assertIn("Example GP", demo.panel.results_text.text())
            podium = [label.text() for label in demo.panel.podium_card.findChildren(QLabel)]
            self.assertTrue(any("P1" in row and "First Driver" in row for row in podium))
            self.assertTrue(any("P3" in row and "Max Verstappen" in row for row in podium))
            demo.race_loaded(1, None, "HTTP 429")
            self.assertIn("Example GP", demo.panel.results_text.text())
            demo.race_loaded(0, None, "")
            self.assertIn("暂无下一场", demo.panel.calendar_text.text())
        finally:
            demo.shutdown()
            pet.close()

    def test_news_list_and_failure_message(self):
        library = AnimationLibrary.load(Path(__file__).resolve().parents[1] / 'public_assets', allow_placeholder=True)
        pet = PetWidget(library, load_pixmaps(library))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        demo = DemoController(pet, news_repository=NewsRepository(Path(directory.name) / "news.sqlite3"))
        try:
            item = NewsItem("Red Bull confirms Verstappen contract", "Sky Sports",
                            datetime(2026, 10, 23, 12, tzinfo=timezone.utc),
                            "https://www.skysports.com/f1/example", "Team statement")
            from news_service import NewsSnapshot
            demo.news_loaded(NewsSnapshot((item,), (), 1), "")
            self.assertEqual("LATEST", demo.panel.news.summary.text())
            self.assertEqual(demo.panel.news.items_layout.count(), 2)
            card = demo.panel.news.items_layout.itemAt(0).widget()
            buttons = {button.icon_name: button for button in card.findChildren(IconButton)}
            buttons["like"].click()
            self.assertEqual(NewsRepository(Path(directory.name) / "news.sqlite3").feedback(item), 1)
            buttons["dislike"].click()
            self.assertEqual(NewsRepository(Path(directory.name) / "news.sqlite3").feedback(item), -1)
            buttons["dislike"].click()
            self.assertEqual(NewsRepository(Path(directory.name) / "news.sqlite3").feedback(item), 0)
            ai_item = NewsItem(item.title, item.source, item.published_utc, item.url,
                               item.summary, summary_zh="红牛车队确认车手合同。",
                               summary_status="ready", title_zh="红牛车队官宣")
            demo.news_loaded(NewsSnapshot((ai_item,), (), 0), "")
            labels = [label.text() for label in demo.panel.news.findChildren(QLabel)]
            self.assertIn("红牛车队确认车手合同。", labels)
            demo.news_loaded(None, "HTTP 503")
            self.assertIn("HTTP 503", demo.panel.news.summary.toolTip())
            self.assertEqual(demo.panel.news.items_layout.count(), 1)
        finally:
            demo.shutdown()
            pet.close()

    def test_api_worker_keeps_animation_running(self):
        library = AnimationLibrary.load(Path(__file__).resolve().parents[1] / 'public_assets', allow_placeholder=True)
        pet = PetWidget(library, load_pixmaps(library))
        demo = DemoController(pet)
        release = threading.Event()
        def delayed_result():
            release.wait(1)
            return None

        with patch("demo_ui.get_next_race", side_effect=delayed_result):
            try:
                pet.show()
                demo.show()
                start_frame = pet.frame_index
                demo.toggle_page(0)
                QTest.qWait(120)
                self.assertNotEqual(pet.frame_index, start_frame)
                self.assertTrue(demo.workers[0].isRunning())
            finally:
                release.set()
                QTest.qWait(30)
                demo.shutdown()
                pet.close()

    def test_manual_news_refresh_keeps_animation_running(self):
        library = AnimationLibrary.load(Path(__file__).resolve().parents[1] / 'public_assets', allow_placeholder=True)
        pet = PetWidget(library, load_pixmaps(library))
        demo = DemoController(pet)
        release = threading.Event()
        from news_service import NewsSnapshot

        def delayed_refresh(manual=False):
            release.wait(1)
            return NewsSnapshot((), ())

        with patch.object(demo.news_service, "refresh", side_effect=delayed_refresh) as refresh:
            try:
                pet.show()
                demo.show()
                demo.toggle_page(2)
                QTest.qWait(30)
                release.set()
                QTest.qWait(60)
                release.clear()
                old = pet.frame_index
                QTest.mouseClick(demo.panel.news.refresh_button, Qt.MouseButton.LeftButton)
                QTest.qWait(120)
                self.assertNotEqual(pet.frame_index, old)
                self.assertFalse(demo.panel.news.refresh_button.isEnabled())
                self.assertTrue(demo.panel.news.refresh_button.spinning)
                self.assertGreater(demo.panel.news.refresh_button.phase, 0)
                self.assertTrue(refresh.call_args.kwargs.get("manual"))
            finally:
                release.set()
                QTest.qWait(120)
                self.assertFalse(demo.panel.news.refresh_button.spinning)
                demo.shutdown()
                pet.close()

    def test_race_cache_is_visible_before_network_finishes(self):
        library = AnimationLibrary.load(Path(__file__).resolve().parents[1] / 'public_assets', allow_placeholder=True)
        pet = PetWidget(library, load_pixmaps(library))
        with tempfile.TemporaryDirectory() as directory:
            repository = RaceRepository(Path(directory) / "races.sqlite3")
            race = Race(2026, 18, "Cached Grand Prix", "Circuit", "Austin", "USA",
                        None, "2026-10-25")
            repository.save(0, race, datetime.now(timezone.utc))
            demo = DemoController(pet, race_repository=repository)
            release = threading.Event()
            def delayed_race():
                release.wait(1)
                return None
            with patch("demo_ui.get_next_race", side_effect=delayed_race):
                try:
                    demo.load_race(0)
                    self.assertEqual(demo.panel.race_name.text(), "Cached Grand Prix")
                    self.assertTrue(demo.workers[0].isRunning())
                finally:
                    release.set()
                    demo.shutdown()
                    pet.close()

    def test_repeated_news_render_releases_old_widgets(self):
        page = NewsPage()
        item = NewsItem("Example", "FIA", datetime.now(timezone.utc),
                        "https://www.fia.com/example", "Summary")
        for _ in range(60):
            page.show_items((item,))
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()
        self.assertLess(len(page.findChildren(QLabel)), 20)
        page.close()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
