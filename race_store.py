"""Small SQLite cache for the last successfully fetched race pages."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from f1_data import DriverResult, Race, RaceResult, RaceSession, Standing


DEFAULT_RACE_DB = Path(__file__).resolve().parent / "user_data" / "races.sqlite3"


def _datetime(value):
    return datetime.fromisoformat(value) if value else None


def _race(raw):
    return Race(raw["season"], raw["round"], raw["name"], raw["circuit"],
                raw["locality"], raw["country"], _datetime(raw["start_utc"]),
                raw["date"], tuple(RaceSession(row["name"], row["date"],
                                              _datetime(row["start_utc"]))
                                   for row in raw.get("sessions", ())))


class RaceRepository:
    def __init__(self, path: Path = DEFAULT_RACE_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS race_cache ("
                       "page INTEGER PRIMARY KEY CHECK(page IN (0,1)), "
                       "payload TEXT NOT NULL, fetched_utc TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS standings_cache ("
                       "kind TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_utc TEXT NOT NULL)")

    def save(self, page: int, data: Race | RaceResult, now: datetime) -> None:
        if page not in (0, 1):
            raise ValueError("invalid race page")
        payload = json.dumps(asdict(data), ensure_ascii=False, default=lambda x: x.isoformat())
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO race_cache VALUES (?,?,?) ON CONFLICT(page) DO UPDATE SET "
                       "payload=excluded.payload, fetched_utc=excluded.fetched_utc",
                       (page, payload, now.isoformat()))

    def load(self, page: int) -> Race | RaceResult | None:
        if page not in (0, 1):
            raise ValueError("invalid race page")
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT payload FROM race_cache WHERE page=?", (page,)).fetchone()
        if not row:
            return None
        raw = json.loads(row[0])
        if page == 0:
            return _race(raw)
        return RaceResult(_race(raw["race"]),
                          tuple(DriverResult(**driver) for driver in raw["classification"]))

    def save_standings(self, kind: str, rows: tuple[Standing, ...], now: datetime) -> None:
        if kind not in ("drivers", "constructors"):
            raise ValueError("invalid standings kind")
        payload = json.dumps([asdict(row) for row in rows], ensure_ascii=False)
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO standings_cache VALUES (?,?,?) ON CONFLICT(kind) DO UPDATE SET "
                       "payload=excluded.payload, fetched_utc=excluded.fetched_utc",
                       (kind, payload, now.isoformat()))

    def load_standings(self, kind: str) -> tuple[Standing, ...]:
        if kind not in ("drivers", "constructors"):
            raise ValueError("invalid standings kind")
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT payload FROM standings_cache WHERE kind=?", (kind,)).fetchone()
        return tuple(Standing(**entry) for entry in json.loads(row[0])) if row else ()
