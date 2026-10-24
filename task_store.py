"""Small SQLite store for the demo's private task data."""

from pathlib import Path
from contextlib import contextmanager
import sqlite3


DEFAULT_TASK_DB = Path(__file__).resolve().parent / "user_data" / "tasks.sqlite3"


class TaskRepository:
    def __init__(self, path: Path = DEFAULT_TASK_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS tasks ("
                "id INTEGER PRIMARY KEY, title TEXT NOT NULL, "
                "important INTEGER NOT NULL, urgent INTEGER NOT NULL, done INTEGER NOT NULL)"
            )

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def load(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, title, important, urgent, done FROM tasks ORDER BY id"
            ).fetchall()
        return [dict(id=row[0], title=row[1], important=bool(row[2]),
                     urgent=bool(row[3]), done=bool(row[4])) for row in rows]

    def add(self, title: str, important: bool, urgent: bool) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO tasks (title, important, urgent, done) VALUES (?, ?, ?, 0)",
                (title, int(important), int(urgent)),
            )
            return int(cursor.lastrowid)

    def set_done(self, task_id: int, done: bool) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE tasks SET done = ? WHERE id = ?", (int(done), task_id))

    def delete(self, task_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
