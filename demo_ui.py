"""Tire navigation and compact pages for the animated desktop companion."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import cos, pi, sin
import time

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontDatabase, QLinearGradient, QPainter,
                           QPen, QPixmap, QPolygonF, QRadialGradient)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QStackedWidget, QToolTip, QVBoxLayout, QWidget,
)

from f1_data import F1ApiError, get_latest_result, get_next_race, get_standings
from news_service import NewsService, NewsSnapshot
from news_store import NewsRepository
from task_store import TaskRepository
from race_store import RaceRepository
from ui_icons import IconButton


PAGES = ("赛历", "赛果", "新闻", "To-Do", "番茄钟")
BEIJING = timezone(timedelta(hours=8))
_fonts_loaded = False


def load_ui_fonts() -> None:
    """Use installed Windows fonts without bundling restricted font files."""
    global _fonts_loaded
    if _fonts_loaded:
        return
    for name in ("msyh.ttc", "bahnschrift.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    _fonts_loaded = True


class RaceWorker(QThread):
    loaded = Signal(int, object, str)
    standings_loaded = Signal(str, object)

    def __init__(self, page: int):
        super().__init__()
        self.page = page

    def run(self) -> None:
        try:
            result = get_next_race() if self.page == 0 else get_latest_result()
            self.loaded.emit(self.page, result, "")
            if self.page == 1 and result is not None:
                for kind in ("drivers", "constructors"):
                    try:
                        self.standings_loaded.emit(kind, get_standings(result.race.season, kind))
                    except F1ApiError:
                        pass
        except F1ApiError as exc:
            self.loaded.emit(self.page, None, str(exc))
        except Exception as exc:
            self.loaded.emit(self.page, None, f"数据处理失败：{exc}")


class NewsWorker(QThread):
    loaded = Signal(object, str)

    def __init__(self, service: NewsService, manual: bool):
        super().__init__()
        self.service = service
        self.manual = manual

    def run(self) -> None:
        try:
            self.loaded.emit(self.service.refresh(manual=self.manual), "")
        except Exception as exc:
            self.loaded.emit(None, f"新闻处理失败：{exc}")


class TireRack(QWidget):
    selected = Signal(int)

    COMPOUNDS = ("#e7e8e5", "#ebc941", "#da4548", "#4c9fc2", "#61ad71")

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFixedSize(244, 77)
        self.active: int | None = None
        self.hovered: int | None = None
        self.tire_images: dict[int, QPixmap] = {}
        self.platform_rect = QRectF(3, 5, 238, 6)
        self.tire_rects = tuple(QRectF(23 + i * 38, 24, 44, 44) for i in range(5))

    def set_active(self, index: int | None) -> None:
        self.active = index
        self.update()

    def set_tire_image(self, index: int, path: Path) -> None:
        """Optional local art replacement; painted tires remain the default."""
        if index not in range(5):
            raise ValueError("Tire index must be 0..4")
        image = QPixmap(str(path))
        if image.isNull():
            raise ValueError(f"Cannot load tire image: {path}")
        self.tire_images[index] = image
        self.update()

    def _hit(self, position) -> int | None:
        for index in range(4, -1, -1):
            if self.tire_rects[index].contains(position):
                return index
        return None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._hit(event.position())
            if index is not None:
                self.selected.emit(index)
                event.accept()

    def mouseMoveEvent(self, event) -> None:
        index = self._hit(event.position())
        if index != self.hovered:
            self.hovered = index
            self.update()
            if index is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(event.globalPosition().toPoint(), PAGES[index], self)

    def leaveEvent(self, event) -> None:
        self.hovered = None
        QToolTip.hideText()
        self.update()

    @staticmethod
    def _wheel_point(center: QPointF, radius: float, angle: float) -> QPointF:
        return QPointF(center.x() + radius * cos(angle),
                       center.y() + radius * sin(angle))

    def _paint_tire(self, painter: QPainter, rect: QRectF, index: int) -> None:
        center = rect.center()
        selected = index == self.active
        hovering = index == self.hovered
        accent = QColor(self.COMPOUNDS[index])

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 115))
        painter.drawEllipse(rect.translated(0.8, 2.3))
        tire = QRadialGradient(center + QPointF(-8, -10), 39)
        tire.setColorAt(0, QColor("#393d3e"))
        tire.setColorAt(0.65, QColor("#202325"))
        tire.setColorAt(0.91, QColor("#0b0d0e"))
        tire.setColorAt(1, QColor("#050607"))
        painter.setBrush(tire)
        painter.setPen(QPen(QColor("#07090a"), 1.5))
        painter.drawEllipse(rect)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#45494a"), 0.8))
        painter.drawEllipse(rect.adjusted(2.3, 2.3, -2.3, -2.3))
        painter.setPen(QPen(QColor("#090b0d"), 1.2))
        painter.drawEllipse(rect.adjusted(4.2, 4.2, -4.2, -4.2))

        # Short markings on the rubber sidewall, without a continuous glow ring.
        mark_rect = rect.adjusted(5.4, 5.4, -5.4, -5.4)
        mark_pen = QPen(accent.lighter(110 if selected else 92), 3.5)
        mark_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(mark_pen)
        for start, span in ((19, 49), (123, 48), (206, 43)):
            painter.drawArc(mark_rect, start * 16, span * 16)
        painter.setPen(QPen(QColor("#4a4e4e"), 0.8))
        painter.drawEllipse(rect.adjusted(9.0, 9.0, -9.0, -9.0))

        cavity = rect.adjusted(10.3, 10.3, -10.3, -10.3)
        painter.setBrush(QColor("#070b0d"))
        painter.setPen(QPen(QColor("#7d8584"), 1.2))
        painter.drawEllipse(cavity)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#1f282b"), 1.8))
        painter.drawEllipse(cavity.adjusted(2.1, 2.1, -2.1, -2.1))
        spoke_metal = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        spoke_metal.setColorAt(0, QColor("#bac0bc"))
        spoke_metal.setColorAt(0.42, QColor("#697273"))
        spoke_metal.setColorAt(1, QColor("#313b3e"))
        painter.setBrush(spoke_metal)
        painter.setPen(QPen(QColor("#11191c"), 0.65))
        for step in range(10):
            angle = 2 * pi * step / 10 - pi / 2
            spoke = QPolygonF([
                self._wheel_point(center, 5.5, angle - 0.16),
                self._wheel_point(center, 14.0, angle - 0.115),
                self._wheel_point(center, 14.0, angle + 0.115),
                self._wheel_point(center, 5.5, angle + 0.16),
            ])
            painter.drawPolygon(spoke)
            painter.setPen(QPen(QColor(205, 211, 207, 115), 0.55))
            painter.drawLine(self._wheel_point(center, 7.0, angle - 0.12),
                             self._wheel_point(center, 13.2, angle - 0.09))
            painter.setPen(QPen(QColor("#11191c"), 0.65))
        painter.setBrush(QColor("#333d40"))
        painter.setPen(QPen(QColor("#9aa3a0"), 1.0))
        painter.drawEllipse(center, 6.0, 6.0)
        painter.setBrush(QColor("#0c1518"))
        painter.setPen(QPen(QColor("#707a79"), 0.8))
        painter.drawEllipse(center, 3.2, 3.2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#a8aeaa"))
        for step in range(5):
            painter.drawEllipse(self._wheel_point(center, 4.7, step * 2 * pi / 5), 0.65, 0.65)

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.setPen(QPen(accent, 1.8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(rect.adjusted(-1.4, -1.4, 1.4, 1.4))
        elif hovering:
            painter.setPen(QPen(QColor("#929b9b"), 0.9))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(rect.adjusted(-1, -1, 1, 1))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # A raised walking deck is visually separate from the lower tire cradle.
        deck = QLinearGradient(0, 5, 0, 12)
        deck.setColorAt(0, QColor("#777e83"))
        deck.setColorAt(0.25, QColor("#353c42"))
        deck.setColorAt(1, QColor("#151a1f"))
        painter.setPen(QPen(QColor("#101418"), 1))
        painter.setBrush(deck)
        painter.drawRoundedRect(self.platform_rect, 2, 2)
        painter.setPen(QPen(QColor("#a2a8aa"), 1))
        painter.drawLine(QPointF(8, 6), QPointF(236, 6))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#22282d"))
        painter.drawRoundedRect(QRectF(17, 12, 6, 10), 2, 2)
        painter.drawRoundedRect(QRectF(221, 12, 6, 10), 2, 2)
        frame = QLinearGradient(0, 21, 0, 73)
        frame.setColorAt(0, QColor("#343b40"))
        frame.setColorAt(1, QColor("#11171b"))
        painter.setBrush(frame)
        painter.setPen(QPen(QColor("#586269"), 1))
        painter.drawRoundedRect(QRectF(8, 21, 228, 52), 4, 4)
        painter.setBrush(QColor("#171d20"))
        painter.drawRect(QRectF(12, 24, 220, 44))
        painter.setPen(QPen(QColor("#828b8d"), 1.2))
        painter.drawLine(QPointF(11, 23), QPointF(233, 23))
        for x in (13, 230):
            painter.setPen(QPen(QColor("#687176"), 2))
            painter.drawLine(QPointF(x, 25), QPointF(x, 68))
            painter.setPen(QPen(QColor("#20282c"), 1))
            painter.drawLine(QPointF(x + 2, 27), QPointF(x + 2, 66))
        painter.setPen(QPen(QColor("#818a8a"), 1))
        painter.drawLine(QPointF(12, 69), QPointF(232, 69))
        painter.setPen(QPen(QColor("#0a0f12"), 4))
        painter.drawLine(QPointF(12, 73), QPointF(232, 73))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#14191e"))
        painter.drawRoundedRect(QRectF(21, 74, 10, 3), 1, 1)
        painter.drawRoundedRect(QRectF(213, 74, 10, 3), 1, 1)
        for index, rect in enumerate(self.tire_rects):
            if index in self.tire_images:
                painter.drawPixmap(rect.toRect(), self.tire_images[index])
                if index == self.active:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(self.COMPOUNDS[index]))
                    painter.setPen(QPen(QColor(self.COMPOUNDS[index]), 1.8))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(rect.adjusted(-1.4, -1.4, 1.4, 1.4))
            else:
                self._paint_tire(painter, rect, index)
        painter.end()


class TaskBoard(QWidget):
    """Four-quadrant task board; optional private SQLite persistence."""

    QUADRANTS = ("重要 · 紧急", "重要 · 不紧急", "不重要 · 紧急", "不重要 · 不紧急")

    def __init__(self, repository: TaskRepository | None = None):
        super().__init__()
        self.repository = repository
        self.tasks: list[dict] = repository.load() if repository else []
        self.next_id = max((task["id"] for task in self.tasks), default=0) + 1
        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(5)
        form = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入一项任务")
        self.input.returnPressed.connect(self.add_task)
        self.important = QCheckBox("重要")
        self.urgent = QCheckBox("紧急")
        add_button = QPushButton("添加")
        add_button.clicked.connect(self.add_task)
        for widget in (self.input, self.important, self.urgent, add_button):
            form.addWidget(widget)
        outer.addLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.viewport().setStyleSheet("background: transparent;")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(5)
        self.groups = []
        for i, title in enumerate(self.QUADRANTS):
            box = QFrame()
            box.setObjectName("quadrant")
            box.setFixedSize(141, 88)
            column = QVBoxLayout(box)
            column.setContentsMargins(5, 4, 5, 4)
            heading = QLabel(title)
            heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            heading.setStyleSheet("font-weight: bold; color: #ffb48e; font-size: 10px")
            column.addWidget(heading)
            items = QVBoxLayout()
            column.addLayout(items)
            column.addStretch()
            grid.addWidget(box, i // 2, i % 2)
            self.groups.append(items)
        scroll.setWidget(container)
        outer.addWidget(scroll)
        self.render_tasks()

    def add_task(self) -> None:
        title = self.input.text().strip()
        if not title:
            return
        important, urgent = self.important.isChecked(), self.urgent.isChecked()
        if self.repository:
            task_id = self.repository.add(title, important, urgent)
        else:
            task_id = self.next_id
            self.next_id += 1
        self.tasks.append({"id": task_id, "title": title, "important": important,
                           "urgent": urgent, "done": False})
        self.input.clear()
        self.render_tasks()

    def set_done(self, task_id: int, done: bool) -> None:
        if self.repository:
            self.repository.set_done(task_id, done)
        next(task for task in self.tasks if task["id"] == task_id)["done"] = done
        self.render_tasks()

    def delete_task(self, task_id: int) -> None:
        if self.repository:
            self.repository.delete(task_id)
        self.tasks = [task for task in self.tasks if task["id"] != task_id]
        self.render_tasks()

    def render_tasks(self) -> None:
        for group in self.groups:
            while group.count():
                item = group.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        for task in self.tasks:
            index = (0 if task["important"] else 2) + (0 if task["urgent"] else 1)
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(1, 1, 1, 1)
            done = QCheckBox(task["title"])
            done.setToolTip(task["title"])
            done.setStyleSheet("font-size: 10px")
            done.setChecked(task["done"])
            done.toggled.connect(lambda checked, task_id=task["id"]: self.set_done(task_id, checked))
            delete = QPushButton("×")
            delete.setFixedWidth(24)
            delete.clicked.connect(lambda checked=False, task_id=task["id"]: self.delete_task(task_id))
            line.addWidget(done, 1)
            line.addWidget(delete)
            self.groups[index].addWidget(row)


class Pomodoro(QWidget):
    state_changed = Signal(str)

    def __init__(self, duration_seconds: int = 25 * 60):
        super().__init__()
        self.duration_seconds = duration_seconds
        self.remaining_seconds = duration_seconds
        self.running = False
        self.deadline = 0.0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        self.clock = QLabel()
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock.setStyleSheet("font-family: Bahnschrift; font-size: 38px; font-weight: bold; color: #ff9b5f")
        layout.addWidget(self.clock)
        buttons = QHBoxLayout()
        self.start_button = IconButton("play", "开始")
        self.pause_button = IconButton("pause", "暂停")
        self.reset_button = IconButton("reset", "重置")
        self.start_button.clicked.connect(self.start)
        self.pause_button.clicked.connect(self.pause)
        self.reset_button.clicked.connect(self.reset)
        buttons.addStretch()
        for button in (self.start_button, self.pause_button, self.reset_button):
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addStretch()
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.tick)
        self._update_label()

    def _update_label(self) -> None:
        minutes, seconds = divmod(self.remaining_seconds, 60)
        self.clock.setText(f"{minutes:02d}:{seconds:02d}")

    def start(self) -> None:
        if self.running or self.remaining_seconds == 0:
            return
        self.running = True
        self.deadline = time.monotonic() + self.remaining_seconds
        self.timer.start()
        self.state_changed.emit("focus_start")

    def pause(self) -> None:
        if not self.running:
            return
        self.tick()
        if not self.running:
            return
        self.running = False
        self.timer.stop()
        self.state_changed.emit("focus_pause")

    def reset(self) -> None:
        self.running = False
        self.timer.stop()
        self.remaining_seconds = self.duration_seconds
        self._update_label()
        self.state_changed.emit("focus_pause")

    def tick(self) -> None:
        if not self.running:
            return
        self.remaining_seconds = max(0, int(self.deadline - time.monotonic() + 0.999))
        self._update_label()
        if self.remaining_seconds == 0:
            self.running = False
            self.timer.stop()
            self.state_changed.emit("focus_complete")


class NewsPage(QWidget):
    refresh_requested = Signal()

    def __init__(self, repository: NewsRepository | None = None):
        super().__init__()
        self.repository = repository
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        top = QHBoxLayout()
        self.summary = QLabel("LATEST")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("newsSummary")
        top.addWidget(self.summary, 1)
        self.refresh_button = IconButton("refresh", "刷新新闻")
        self.refresh_button.clicked.connect(self.refresh_requested)
        top.addWidget(self.refresh_button)
        outer.addLayout(top)
        self.source_status = QLabel()
        self.source_status.hide()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.viewport().setStyleSheet("background: transparent;")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self.items_layout = QVBoxLayout(container)
        self.items_layout.setContentsMargins(2, 2, 2, 2)
        self.items_layout.setSpacing(7)
        self.items_layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

    def show_items(self, items, error: str = "", states=(), changed_count: int = 0) -> None:
        while self.items_layout.count():
            item = self.items_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.summary.setText("LATEST" if items else ("暂时无法获取新闻" if error else "暂无重要新闻"))
        self.summary.setToolTip(error)
        statuses = []
        for state in states:
            last = (state.last_success_utc.astimezone(BEIJING).strftime("%m-%d %H:%M")
                    if state.last_success_utc else "尚未成功")
            status = f"{state.name}：{last}"
            if state.last_error:
                status += f" · {state.last_error[:55]}"
            statuses.append(status)
        successful = [state.last_success_utc for state in states if state.last_success_utc]
        latest = (max(successful).astimezone(BEIJING).strftime("%m-%d %H:%M")
                  if successful else "尚未成功")
        failed = [state for state in states if state.last_error]
        overview = f"来源 {len(states)} · 最近同步 {latest}"
        if failed:
            overview += f" · 失败 {len(failed)}"
        self.source_status.setText(overview)
        self.source_status.setToolTip("\n".join(statuses))
        for article in items:
            card = QFrame()
            card.setObjectName("newsCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(8, 7, 8, 7)
            title = QLabel(article.summary_zh or article.title_zh or article.title)
            title.setWordWrap(True)
            title.setObjectName("newsTitle")
            layout.addWidget(title)
            published = (article.published_utc.astimezone(BEIJING).strftime("%m-%d %H:%M")
                         if article.published_utc else "时间未提供")
            source_status = ("官方确认" if article.source_status == "official" or
                             article.credibility.startswith(("官方", "FIA")) else "媒体报道")
            meta = QLabel(f"{article.source}  ·  {published}  ·  {source_status}")
            meta.setObjectName("newsMeta")
            layout.addWidget(meta)
            if article.document_status:
                status_name = {"investigation": "调查中", "no_action": "无进一步行动",
                               "penalty": "实际处罚", "decision": "正式裁决",
                               "decision_unknown": "结果待核对", "withdrawn": "已撤回"}
                status = QLabel("FIA 文件 · " + status_name.get(article.document_status, "待核对"))
                status.setObjectName("newsMeta")
                layout.addWidget(status)
            actions = QHBoxLayout()
            open_link = QPushButton("↗")
            open_link.setToolTip(article.url)
            open_link.setFixedSize(25, 25)
            open_link.clicked.connect(lambda checked=False, url=article.url:
                                      QDesktopServices.openUrl(QUrl(url)))
            actions.addWidget(open_link)
            details = IconButton("down", "查看原文标题和摘要")
            original = QLabel((article.title + "\n" + (article.summary or "")).strip())
            original.setWordWrap(True)
            original.setObjectName("newsMeta")
            original.hide()
            details.clicked.connect(lambda checked=False, label=original, button=details:
                                    (label.setVisible(not label.isVisible()),
                                     setattr(button, "icon_name", "up" if label.isVisible() else "down"),
                                     button.update()))
            actions.addWidget(details)
            actions.addStretch()
            up = IconButton("like", "感兴趣")
            down = IconButton("dislike", "不感兴趣")
            for button, tip in ((up, "感兴趣"), (down, "不感兴趣")):
                button.setToolTip(tip)
                button.setFixedSize(25, 25)
                actions.addWidget(button)
            def vote(value, item=article, up_button=up, down_button=down):
                if self.repository is None:
                    return
                previous = self.repository.feedback(item)
                self.repository.set_feedback(item, 0 if previous == value else value,
                                             datetime.now(timezone.utc))
                current = self.repository.feedback(item)
                up_button.set_selected(current == 1)
                down_button.set_selected(current == -1)
            up.clicked.connect(lambda checked=False, callback=vote: callback(1))
            down.clicked.connect(lambda checked=False, callback=vote: callback(-1))
            if self.repository:
                current = self.repository.feedback(article)
                up.set_selected(current == 1)
                down.set_selected(current == -1)
            layout.addLayout(actions)
            layout.addWidget(original)
            self.items_layout.addWidget(card)
        self.items_layout.addStretch()


class FocusBackdrop(QWidget):
    """A low-contrast, click-through timer positioned behind the pet."""

    def __init__(self, pomodoro: Pomodoro):
        super().__init__()
        self.pomodoro = pomodoro
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(128, 48)
        self.pomodoro.timer.timeout.connect(self.update)
        self.pomodoro.state_changed.connect(self.sync_state)

    def sync_state(self, state: str) -> None:
        if state == "focus_complete":
            self.show()
            self.update()
            QTimer.singleShot(3000, self._hide_when_finished)
        elif state == "focus_start" or self.pomodoro.remaining_seconds < self.pomodoro.duration_seconds:
            self.show()
            self.update()
        else:
            self.hide()

    def _hide_when_finished(self) -> None:
        if not self.pomodoro.running and self.pomodoro.remaining_seconds == 0:
            self.hide()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(255, 150, 84, 105) if self.pomodoro.running else QColor(160, 169, 177, 90), 1))
        painter.setBrush(QColor(37, 42, 47, 205))
        painter.drawRoundedRect(QRectF(1, 2, self.width()-2, self.height()-4), 16, 16)
        painter.setFont(QFont("Bahnschrift", 22, QFont.Weight.DemiBold))
        painter.setPen(QColor(255, 139, 68, 225) if self.pomodoro.running else QColor(155, 164, 171, 160))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                         self.pomodoro.clock.text())
        painter.end()


class DemoPanel(QWidget):
    collapsed = Signal()

    def __init__(self, pet, task_repository: TaskRepository | None = None):
        super().__init__()
        self.pet = pet
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedSize(322, 292)
        self.setStyleSheet(
            "QWidget { color: #eef2f5; font-family: 'Bahnschrift', 'Microsoft YaHei UI'; font-size: 11px; }"
            "QWidget#panel { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, "
            "stop:0 #27304a, stop:0.5 #1a2d3a, stop:1 #381f32); border: 1px solid #60717d; "
            "border-radius: 12px; }"
            "QScrollArea { background: transparent; border: 0; }"
            "QPushButton { background: #394653; color: #f2f5f6; border: 1px solid #667c88; "
            "border-radius: 6px; padding: 3px 6px; }"
            "QPushButton:hover { background: #566977; border-color: #dce8ef; }"
            "QLineEdit { background: #1b2a37; border: 1px solid #778b98; "
            "border-radius: 5px; padding: 4px; }"
            "QFrame#quadrant, QFrame#newsCard, QFrame#sessionRow, QFrame#raceCard { "
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #34435a,stop:1 #263e49); "
            "border: 1px solid #607483; border-radius: 7px; }"
            "QFrame#countdownCard { background: #1a3040; border: 1px solid #9b7272; "
            "border-radius: 7px; }"
            "QLabel#panelTitle { font-size: 15px; font-weight: bold; color: #ffffff; }"
            "QLabel#raceName { font-size: 18px; font-weight: bold; color: #ffffff; }"
            "QLabel#raceMeta { font-size: 10px; color: #cadce4; }"
            "QLabel#countdownNumber { font-size: 24px; font-weight: bold; color: #fff4ed; }"
            "QLabel#countdownUnit { font-size: 10px; color: #ff9c72; }"
            "QLabel#podiumRow { font-size: 12px; font-weight: bold; color: #ffffff; }"
            "QLabel#newsTitle { font-size: 12px; font-weight: bold; color: #ffffff; }"
            "QLabel#newsMeta { color: #b9cbd3; font-size: 10px; }"
            "QLabel#newsSummary { color: #dce7ec; font-size: 12px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 8)
        layout.setSpacing(5)
        header = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("panelTitle")
        close = IconButton("up", "收起")
        close.clicked.connect(self.collapse)
        self.close_button = close
        header.addWidget(self.title, 1)
        header.addWidget(close)
        layout.addLayout(header)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        calendar = QWidget()
        calendar_layout = QVBoxLayout(calendar)
        calendar_layout.setContentsMargins(0, 0, 0, 0)
        calendar_layout.setSpacing(0)
        calendar_scroll = QScrollArea()
        calendar_scroll.setWidgetResizable(True)
        calendar_scroll.viewport().setStyleSheet("background: transparent;")
        calendar_content = QWidget()
        calendar_content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(calendar_content)
        content_layout.setContentsMargins(2, 2, 2, 2)
        content_layout.setSpacing(6)
        self.calendar_text = QLabel("点击赛历轮胎加载比赛周末")
        self.calendar_text.setWordWrap(True)
        content_layout.addWidget(self.calendar_text)
        self.race_card = QFrame()
        self.race_card.setObjectName("raceCard")
        race_layout = QVBoxLayout(self.race_card)
        race_layout.setContentsMargins(9, 7, 9, 7)
        race_layout.setSpacing(2)
        self.race_name = QLabel()
        self.race_name.setObjectName("raceName")
        self.race_name.setWordWrap(True)
        self.race_meta = QLabel()
        self.race_meta.setObjectName("raceMeta")
        self.race_meta.setWordWrap(True)
        self.race_time = QLabel()
        self.race_time.setObjectName("raceMeta")
        race_layout.addWidget(self.race_name)
        race_layout.addWidget(self.race_meta)
        race_layout.addWidget(self.race_time)
        content_layout.addWidget(self.race_card)
        self.countdown_card = QFrame()
        self.countdown_card.setObjectName("countdownCard")
        countdown_layout = QHBoxLayout(self.countdown_card)
        countdown_layout.setContentsMargins(8, 5, 8, 5)
        countdown_layout.setSpacing(3)
        self.countdown_notice = QLabel("距离正赛")
        self.countdown_notice.setObjectName("countdownUnit")
        self.countdown_notice.setFixedWidth(92)
        countdown_layout.addWidget(self.countdown_notice)
        self.countdown_values = []
        for unit in ("D", "H", "M"):
            cell = QWidget()
            cell.setFixedWidth(54)
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(0)
            number = QLabel("--")
            number.setObjectName("countdownNumber")
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption = QLabel(unit)
            caption.setObjectName("countdownUnit")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell_layout.addWidget(number)
            cell_layout.addWidget(caption)
            countdown_layout.addWidget(cell)
            self.countdown_values.append(number)
        countdown_layout.addStretch()
        content_layout.addWidget(self.countdown_card)
        sessions_title = QLabel("周末赛程")
        sessions_title.setStyleSheet("font-weight: bold; color: #aebbc4; font-size: 11px")
        content_layout.addWidget(sessions_title)
        self.session_layout = QVBoxLayout()
        self.session_layout.setSpacing(3)
        content_layout.addLayout(self.session_layout)
        content_layout.addStretch()
        self.race_card.hide()
        self.countdown_card.hide()
        sessions_title.hide()
        self.sessions_title = sessions_title
        calendar_scroll.setWidget(calendar_content)
        calendar_layout.addWidget(calendar_scroll)
        self.stack.addWidget(calendar)
        results = QWidget()
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(2, 2, 2, 2)
        results_layout.setSpacing(6)
        self.results_text = QLabel("暂无赛果")
        self.results_text.setWordWrap(True)
        results_layout.addWidget(self.results_text)
        self.podium_card = QFrame()
        self.podium_card.setObjectName("raceCard")
        self.podium_layout = QVBoxLayout(self.podium_card)
        self.podium_layout.setContentsMargins(9, 6, 9, 6)
        self.podium_layout.setSpacing(4)
        results_layout.addWidget(self.podium_card)
        self.podium_card.hide()
        self.standings_buttons = {}
        self.standings_labels = {}
        for kind, title in (("drivers", "车手积分榜"), ("constructors", "车队积分榜")):
            header = QHBoxLayout()
            heading = QLabel(title)
            button = IconButton("down", title)
            button.clicked.connect(lambda checked=False, key=kind: self.toggle_standings(key))
            header.addWidget(heading, 1)
            header.addWidget(button)
            results_layout.addLayout(header)
            label = QLabel()
            label.setWordWrap(True)
            label.hide()
            results_layout.addWidget(label)
            self.standings_buttons[kind] = button
            self.standings_labels[kind] = label
        results_layout.addStretch()
        self.stack.addWidget(results)
        self.news = NewsPage()
        self.stack.addWidget(self.news)
        self.tasks = TaskBoard(task_repository)
        self.stack.addWidget(self.tasks)
        self.pomodoro = Pomodoro()
        self.pomodoro.state_changed.connect(pet.set_focus_state)
        self.stack.addWidget(self.pomodoro)

    def show_race(self, race) -> None:
        visible = race is not None
        self.calendar_text.setVisible(not visible)
        self.race_card.setVisible(visible)
        self.countdown_card.setVisible(visible)
        self.sessions_title.setVisible(visible)
        if visible:
            self.race_name.setText(race.name)
            self.race_meta.setText(f"{race.circuit} · {race.locality}, {race.country}")

    def show_podium(self, result) -> None:
        while self.podium_layout.count():
            item = self.podium_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.podium_card.setVisible(result is not None)
        if result is None:
            return
        self.results_text.setText(f"{result.race.name}  /  R{result.race.round:02d}")
        for entry in sorted(result.classification, key=lambda row: row.position)[:3]:
            row = QLabel(f"P{entry.position}   {entry.driver_name}   ·   {entry.constructor or '—'}")
            row.setObjectName("podiumRow")
            self.podium_layout.addWidget(row)

    def show_standings(self, kind: str, rows) -> None:
        self.standings_labels[kind].setText("\n".join(
            f"{row.position:>2}   {row.name}   {row.points:g}" for row in rows[:5]) or "暂无积分")

    def toggle_standings(self, kind: str) -> None:
        label = self.standings_labels[kind]
        label.setVisible(not label.isVisible())
        button = self.standings_buttons[kind]
        button.icon_name = "up" if label.isVisible() else "down"
        button.update()

    def show_sessions(self, sessions) -> None:
        while self.session_layout.count():
            item = self.session_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for session in sessions:
            row = QFrame()
            row.setObjectName("sessionRow")
            line = QHBoxLayout(row)
            line.setContentsMargins(7, 3, 7, 3)
            name = QLabel(session.name)
            name.setStyleSheet("font-weight: bold; color: #dce4ea")
            when = (session.start_utc.astimezone(BEIJING).strftime("%m-%d %H:%M")
                    if session.start_utc else f"{session.date} 时间待定")
            line.addWidget(name, 1)
            line.addWidget(QLabel(when))
            self.session_layout.addWidget(row)

    def show_page(self, index: int) -> None:
        self.title.setText(PAGES[index])
        self.stack.setCurrentIndex(index)
        self.setFixedHeight(180 if index == 4 else 292)
        self.show()
        self.raise_()

    def collapse(self) -> None:
        self.hide()
        self.collapsed.emit()


class DemoController(QObject):
    def __init__(self, pet, task_repository: TaskRepository | None = None,
                 news_repository: NewsRepository | None = None,
                 race_repository: RaceRepository | None = None):
        super().__init__(pet)
        load_ui_fonts()
        self.pet = pet
        self.bar = TireRack()
        self.panel = DemoPanel(pet, task_repository)
        self.news_service = NewsService(news_repository or NewsRepository())
        self.race_repository = race_repository or RaceRepository()
        self.panel.news.repository = self.news_service.repository
        self.backdrop = FocusBackdrop(self.panel.pomodoro)
        self.active_page: int | None = None
        self.workers: dict[int, RaceWorker] = {}
        self.news_worker: NewsWorker | None = None
        self._shutting_down = False
        self.next_race = None
        self.pet.installEventFilter(self)
        self.bar.selected.connect(self.toggle_page)
        self.panel.collapsed.connect(self._panel_collapsed)
        self.panel.pomodoro.state_changed.connect(self._focus_changed)
        self.panel.news.refresh_requested.connect(lambda: self.load_news(manual=True))
        self.news_timer = QTimer(self)
        self.news_timer.setInterval(60_000)
        self.news_timer.timeout.connect(self.load_news)
        self.news_timer.start()
        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self.update_countdown)
        self.countdown_timer.start(1000)
        self._app = QApplication.instance()
        self._app.aboutToQuit.connect(self.shutdown)

    def show(self) -> None:
        # Keep the original frames, but render Max smaller and reserve room below.
        self.pet.height_setting = 96
        self.pet._resize_to_character_height()
        area = QApplication.primaryScreen().availableGeometry()
        pet_y = area.bottom() - (self.pet._ground_offset() + self.bar.height() +
                                 self.panel.height() + 20)
        self.pet.move(self.pet.x(), max(area.top() + 8, pet_y))
        self.reposition()
        self.bar.show()
        self.pet.raise_()

    def _focus_changed(self, state: str) -> None:
        if self.backdrop.isVisible():
            self.pet.raise_()
            self.bar.raise_()
            if self.panel.isVisible():
                self.panel.raise_()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.pet and event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            self.reposition()
        return False

    def reposition(self) -> None:
        area = QApplication.primaryScreen().availableGeometry()
        x = self.pet.x() + (self.pet.width() - self.bar.width()) // 2
        x = max(area.left(), min(x, area.right() - self.bar.width() + 1))
        # Character feet meet the upper deck; the tires sit a full level below.
        y = self.pet.y() + self.pet._ground_offset() - 11
        y = max(area.top(), y)
        self.bar.move(x, y)
        panel_x = max(area.left(), min(x + (self.bar.width() - self.panel.width()) // 2,
                                       area.right() - self.panel.width() + 1))
        self.panel.move(panel_x, y + self.bar.height() + 4)
        backdrop_x = max(area.left(), min(self.pet.x() - 84,
                                           area.right() - self.backdrop.width() + 1))
        self.backdrop.move(backdrop_x, self.pet.y() + 20)

    def toggle_page(self, index: int) -> None:
        if self.active_page == index and self.panel.isVisible():
            self.panel.hide()
            self.active_page = None
        else:
            self.active_page = index
            self.panel.show_page(index)
            if index in (0, 1):
                self.load_race(index)
            elif index == 2:
                self.load_news()
        self.bar.set_active(self.active_page)

    def _panel_collapsed(self) -> None:
        self.active_page = None
        self.bar.set_active(None)

    def load_race(self, index: int) -> None:
        if self._shutting_down:
            return
        if index in self.workers:
            return
        try:
            cached = self.race_repository.load(index)
        except Exception:
            cached = None
        if cached is not None:
            self.race_loaded(index, cached, "")
        elif index == 0:
            self.panel.calendar_text.setText("赛程载入中")
        else:
            self.panel.results_text.setText("赛果载入中")
        if index == 1:
            for kind in ("drivers", "constructors"):
                try:
                    self.panel.show_standings(kind, self.race_repository.load_standings(kind))
                except Exception:
                    pass
        worker = RaceWorker(index)
        self.workers[index] = worker
        worker.loaded.connect(self.race_loaded)
        worker.standings_loaded.connect(self.standings_loaded)
        worker.finished.connect(lambda i=index: self.workers.pop(i, None))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def load_news(self, manual: bool = False) -> None:
        if self._shutting_down:
            return
        if self.news_worker is not None:
            return
        try:
            cached = self.news_service.snapshot()
            self.panel.news.show_items(cached.items, states=cached.states)
        except Exception as exc:
            self.panel.news.summary.setText(f"本地新闻缓存读取失败：{exc}")
        self.panel.news.refresh_button.setEnabled(False)
        self.panel.news.refresh_button.set_spinning(True)
        worker = NewsWorker(self.news_service, manual)
        self.news_worker = worker
        worker.loaded.connect(self.news_loaded)
        worker.finished.connect(self._news_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _news_finished(self) -> None:
        if self._shutting_down:
            return
        self.news_worker = None
        self.panel.news.refresh_button.setEnabled(True)
        self.panel.news.refresh_button.set_spinning(False)

    def news_loaded(self, result: object, error: str) -> None:
        if self._shutting_down:
            return
        if isinstance(result, NewsSnapshot):
            self.panel.news.show_items(result.items, states=result.states,
                                       changed_count=result.changed_count)
        else:
            try:
                cached = self.news_service.snapshot()
                self.panel.news.show_items(cached.items, error, cached.states)
            except Exception:
                self.panel.news.show_items((), error)

    def race_loaded(self, index: int, result: object, error: str) -> None:
        if self._shutting_down:
            return
        if error:
            # Preserve the last successful page when a background refresh fails.
            target = self.panel.calendar_text if index == 0 else self.panel.results_text
            target.setToolTip(error)
            if index == 0 and self.next_race is not None:
                return
            if index == 1 and not self.panel.podium_card.isHidden():
                return
        elif result is not None:
            try:
                self.race_repository.save(index, result, datetime.now(timezone.utc))
            except Exception:
                pass
        if index == 0:
            if error:
                self.next_race = None
                self.panel.show_race(None)
                self.panel.calendar_text.setText(f"赛历获取失败：{error}\n可再次点击赛历轮胎重试。")
                self.panel.show_sessions(())
            elif result is None:
                self.next_race = None
                self.panel.show_race(None)
                self.panel.calendar_text.setText("暂无下一场赛程。赛季交替期间可能尚未公布新赛历。")
                self.panel.show_sessions(())
            else:
                self.next_race = result
                self.panel.show_race(result)
                self.panel.show_sessions(result.sessions)
                self.update_countdown()
        else:
            if error:
                self.panel.results_text.setText("赛果暂不可用")
            elif result is None:
                self.panel.show_podium(None)
                self.panel.results_text.setText("暂无最近赛果")
            else:
                self.panel.show_podium(result)

    def standings_loaded(self, kind: str, rows: object) -> None:
        if self._shutting_down:
            return
        self.panel.show_standings(kind, rows)
        try:
            self.race_repository.save_standings(kind, rows, datetime.now(timezone.utc))
        except Exception:
            pass

    def update_countdown(self) -> None:
        race = self.next_race
        if race is None:
            return
        start = race.start_utc
        if start is None:
            self.panel.race_time.setText(f"正赛 · {race.date} 时间待定")
            self.panel.countdown_notice.setText("起跑时间尚未公布")
            for label in self.panel.countdown_values:
                label.setText("--")
        else:
            local_time = start.astimezone(BEIJING).strftime("%m月%d日 %H:%M")
            self.panel.race_time.setText(f"正赛 · {local_time}")
            remaining = max(0, int((start - datetime.now(timezone.utc)).total_seconds()))
            days, remainder = divmod(remaining, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes = remainder // 60
            self.panel.countdown_notice.setText("距离正赛" if remaining else "比赛已开始")
            for label, value in zip(self.panel.countdown_values, (days, hours, minutes)):
                label.setText(f"{value:02d}")

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        try:
            self._app.aboutToQuit.disconnect(self.shutdown)
        except (RuntimeError, TypeError):
            pass
        self.pet.removeEventFilter(self)
        self.news_timer.stop()
        self.countdown_timer.stop()
        self.news_service.cancel()
        for worker in tuple(self.workers.values()):
            worker.wait()
        if self.news_worker is not None:
            self.news_worker.wait()
        self.backdrop.close()
        self.panel.close()
        self.bar.close()
