"""Private SQLite task persistence using a temporary database."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from task_store import TaskRepository


class TaskStoreTests(unittest.TestCase):
    def test_add_reload_complete_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.sqlite3"
            store = TaskRepository(path)
            task_id = store.add("Prepare demo", important=True, urgent=False)
            self.assertEqual(TaskRepository(path).load(), [{
                "id": task_id, "title": "Prepare demo", "important": True,
                "urgent": False, "done": False,
            }])
            store.set_done(task_id, True)
            self.assertTrue(TaskRepository(path).load()[0]["done"])
            store.delete(task_id)
            self.assertEqual(TaskRepository(path).load(), [])


if __name__ == "__main__":
    unittest.main()
