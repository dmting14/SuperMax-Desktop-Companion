from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from f1_data import DriverResult, Race, RaceResult, RaceSession
from race_store import RaceRepository


class RaceStoreTests(unittest.TestCase):
    def test_cache_reopens_with_sessions_and_podium(self):
        now = datetime(2026, 10, 24, tzinfo=timezone.utc)
        race = Race(2026, 20, "Grand Prix", "Circuit", "City", "Country", now,
                    "2026-10-24", (RaceSession("Race", "2026-10-24", now),))
        result = RaceResult(race, (DriverResult(1, "max_verstappen", "Max Verstappen",
                                                   "Red Bull", 25, "Finished"),))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "race.sqlite3"
            repo = RaceRepository(path)
            repo.save(0, race, now)
            repo.save(1, result, now)
            reopened = RaceRepository(path)
            self.assertEqual(reopened.load(0), race)
            self.assertEqual(reopened.load(1), result)
