"""Standalone, offline checks for the F1 API adapter."""

from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import f1_data


RACE = {
    "season": "2026", "round": "12", "raceName": "Example Grand Prix",
    "date": "2026-07-12", "time": "14:00:00Z",
    "Circuit": {"circuitName": "Example Circuit", "Location": {
        "locality": "Example City", "country": "Example Country"}},
}
RESULT = {
    "position": "1", "points": "25", "status": "Finished",
    "Driver": {"driverId": "example", "givenName": "Example", "familyName": "Driver"},
    "Constructor": {"name": "Example Team"},
}


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body


class F1DataTests(unittest.TestCase):
    def test_next_race(self):
        with patch.object(f1_data, "_get_json", return_value={"MRData": {"RaceTable": {"Races": [RACE]}}}):
            race = f1_data.get_next_race()
        self.assertEqual((race.season, race.round, race.circuit), (2026, 12, "Example Circuit"))
        self.assertEqual(race.start_utc.isoformat(), "2026-07-12T14:00:00+00:00")
        self.assertEqual([session.name for session in race.sessions], ["Race"])

    def test_full_weekend_sessions(self):
        weekend = dict(RACE, FirstPractice={"date": "2026-07-10", "time": "10:00:00Z"},
                       SecondPractice={"date": "2026-07-10", "time": "14:00:00Z"},
                       ThirdPractice={"date": "2026-07-11", "time": "10:00:00Z"},
                       Qualifying={"date": "2026-07-11", "time": "14:00:00Z"},
                       Sprint={"date": "2026-07-11", "time": "12:00:00Z"},
                       SprintQualifying={"date": "2026-07-10", "time": "18:00:00Z"})
        with patch.object(f1_data, "_get_json", return_value={"MRData": {"RaceTable": {"Races": [weekend]}}}):
            race = f1_data.get_next_race()
        self.assertEqual([session.name for session in race.sessions],
                         ["FP1", "FP2", "Sprint Qualifying", "FP3", "Sprint", "Qualifying", "Race"])

    def test_latest_result_and_optional_fields(self):
        raw = dict(RACE, Results=[RESULT])
        with patch.object(f1_data, "_get_json", return_value={"MRData": {"RaceTable": {"Races": [raw]}}}) as get:
            result = f1_data.get_latest_result()
        self.assertIn("limit=100", get.call_args.args[0])
        self.assertEqual(result.classification[0].driver_name, "Example Driver")
        self.assertEqual(result.classification[0].points, 25.0)

    def test_empty_and_missing(self):
        with patch.object(f1_data, "_get_json", return_value={"MRData": {"RaceTable": {"Races": []}}}):
            self.assertIsNone(f1_data.get_next_race())
            self.assertIsNone(f1_data.get_latest_result())
        with patch.object(f1_data, "_get_json", return_value={"MRData": {"RaceTable": {"Races": [{}]}}}):
            with self.assertRaises(f1_data.F1DataError):
                f1_data.get_next_race()

    def test_season_boundary_fallback(self):
        empty = {"MRData": {"RaceTable": {"Races": []}}}
        next_race = {"MRData": {"RaceTable": {"Races": [RACE]}}}
        with patch.object(f1_data, "_get_json", side_effect=[empty, next_race]) as get:
            self.assertEqual(f1_data.get_next_race().name, "Example Grand Prix")
            self.assertTrue(get.call_args.args[0].endswith("/1.json"))
        completed = {"MRData": {"RaceTable": {"Races": [dict(RACE, Results=[RESULT])]}}}
        with patch.object(f1_data, "_get_json", side_effect=[empty, completed]) as get:
            self.assertEqual(f1_data.get_latest_result().classification[0].position, 1)
            self.assertIn("/last/results.json", get.call_args.args[0])
        with patch.object(f1_data, "_get_json", side_effect=[empty, f1_data.F1HTTPError(404, "next")]):
            self.assertIsNone(f1_data.get_next_race())

    def test_http_timeout_and_bad_json(self):
        cases = [
            (HTTPError("url", 429, "rate limit", None, None), f1_data.F1HTTPError),
            (URLError(socket.timeout()), f1_data.F1TimeoutError),
        ]
        for error, expected in cases:
            with self.subTest(error=error), patch.object(f1_data, "urlopen", side_effect=error):
                with self.assertRaises(expected):
                    f1_data.get_next_race()
        with patch.object(f1_data, "urlopen", return_value=Response(b"not json")):
            with self.assertRaises(f1_data.F1DataError):
                f1_data.get_next_race()


if __name__ == "__main__":
    unittest.main()
