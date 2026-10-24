"""Read the next F1 race and latest completed race from the Jolpica API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "https://api.jolpi.ca/ergast/f1"
USER_AGENT = "SuperMaxF1/0.1"


class F1ApiError(Exception):
    """Base error for fetching or parsing F1 data."""


class F1TimeoutError(F1ApiError):
    """The server did not respond within the configured timeout."""


class F1HTTPError(F1ApiError):
    """The server returned an unsuccessful HTTP status."""

    def __init__(self, status_code: int, url: str):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code} from {url}")


class F1DataError(F1ApiError):
    """The response is invalid JSON or lacks required fields."""


@dataclass(frozen=True)
class RaceSession:
    name: str
    date: str
    start_utc: datetime | None


@dataclass(frozen=True)
class Race:
    season: int
    round: int
    name: str
    circuit: str
    locality: str
    country: str
    start_utc: datetime | None
    date: str
    sessions: tuple[RaceSession, ...] = ()


@dataclass(frozen=True)
class DriverResult:
    position: int
    driver_id: str
    driver_name: str
    constructor: str | None
    points: float
    status: str | None


@dataclass(frozen=True)
class RaceResult:
    race: Race
    classification: tuple[DriverResult, ...]


@dataclass(frozen=True)
class Standing:
    position: int
    name: str
    team: str
    points: float


def _get_json(path: str, timeout: float) -> dict:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    url = f"{BASE_URL}/{path}"
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except HTTPError as exc:
        raise F1HTTPError(exc.code, url) from exc
    except (socket.timeout, TimeoutError) as exc:
        raise F1TimeoutError(f"Request timed out after {timeout:g}s: {url}") from exc
    except URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            raise F1TimeoutError(f"Request timed out after {timeout:g}s: {url}") from exc
        raise F1ApiError(f"Network error for {url}: {exc.reason}") from exc
    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise F1DataError(f"Invalid JSON from {url}") from exc
    if not isinstance(data, dict):
        raise F1DataError("Expected a JSON object")
    return data


def _races(data: dict) -> list:
    try:
        races = data["MRData"]["RaceTable"]["Races"]
        if not isinstance(races, list):
            raise TypeError("Races is not a list")
        return races
    except (KeyError, TypeError) as exc:
        raise F1DataError("Missing or invalid MRData.RaceTable.Races") from exc


def _race(raw: dict) -> Race:
    try:
        location = raw["Circuit"]["Location"]
        date = raw["date"]
        race_time = raw.get("time")
        start = _parse_start(date, race_time)
        sessions = []
        for key, name in (
            ("FirstPractice", "FP1"), ("SecondPractice", "FP2"),
            ("ThirdPractice", "FP3"), ("SprintQualifying", "Sprint Qualifying"),
            ("SprintShootout", "Sprint Shootout"), ("Sprint", "Sprint"),
            ("Qualifying", "Qualifying"),
        ):
            session = raw.get(key)
            if isinstance(session, dict) and session.get("date"):
                sessions.append(RaceSession(name, session["date"],
                                            _parse_start(session["date"], session.get("time"))))
        sessions.append(RaceSession("Race", date, start))
        sessions.sort(key=lambda item: (item.start_utc or datetime.fromisoformat(item.date).replace(
            tzinfo=timezone.utc), item.name))
        return Race(
            season=int(raw["season"]), round=int(raw["round"]),
            name=raw["raceName"], circuit=raw["Circuit"]["circuitName"],
            locality=location["locality"], country=location["country"],
            start_utc=start, date=date, sessions=tuple(sessions),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise F1DataError("Missing or invalid race fields") from exc


def _parse_start(date: str, race_time: str | None) -> datetime | None:
    if not race_time:
        return None
    parsed = datetime.fromisoformat(f"{date}T{race_time.replace('Z', '+00:00')}")
    return parsed.astimezone(timezone.utc)


def _result(raw: dict) -> DriverResult:
    try:
        driver = raw["Driver"]
        constructor = raw.get("Constructor")
        return DriverResult(
            position=int(raw["position"]), driver_id=driver["driverId"],
            driver_name=f"{driver['givenName']} {driver['familyName']}",
            constructor=constructor["name"] if constructor else None,
            points=float(raw["points"]), status=raw.get("status"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise F1DataError("Missing or invalid driver result fields") from exc


def get_next_race(timeout: float = 8.0) -> Race | None:
    """Return the next scheduled race, or None when the API has no next race."""
    races = _races(_get_json("current/next.json", timeout))
    if not races:
        next_year = datetime.now(timezone.utc).year + 1
        try:
            races = _races(_get_json(f"{next_year}/1.json", timeout))
        except F1HTTPError as exc:
            if exc.status_code == 404:
                return None
            raise
    return _race(races[0]) if races else None


def get_latest_result(timeout: float = 8.0) -> RaceResult | None:
    """Return the latest completed race and its full classification, if available."""
    races = _races(_get_json("current/last/results.json?limit=100", timeout))
    if not races:
        previous_year = datetime.now(timezone.utc).year - 1
        try:
            races = _races(_get_json(f"{previous_year}/last/results.json?limit=100", timeout))
        except F1HTTPError as exc:
            if exc.status_code == 404:
                return None
            raise
    if not races:
        return None
    raw = races[0]
    try:
        results = raw["Results"]
        if not isinstance(results, list) or not results:
            raise ValueError("Results is empty or invalid")
    except (KeyError, TypeError, ValueError) as exc:
        raise F1DataError("Missing or invalid Results") from exc
    return RaceResult(_race(raw), tuple(_result(item) for item in results))


def get_standings(season: int, kind: str, timeout: float = 8.0) -> tuple[Standing, ...]:
    """Fetch the top five current driver or constructor standings."""
    if kind not in ("drivers", "constructors"):
        raise ValueError("kind must be drivers or constructors")
    data = _get_json(f"{season}/{kind}Standings.json?limit=5", timeout)
    try:
        lists = data["MRData"]["StandingsTable"]["StandingsLists"]
        if not lists:
            return ()
        key = "DriverStandings" if kind == "drivers" else "ConstructorStandings"
        entries = lists[0][key]
        results = []
        for entry in entries[:5]:
            if kind == "drivers":
                driver = entry["Driver"]
                name = f"{driver['givenName']} {driver['familyName']}"
                team = entry["Constructors"][0]["name"] if entry.get("Constructors") else ""
            else:
                name = entry["Constructor"]["name"]
                team = ""
            results.append(Standing(int(entry["position"]), name, team,
                                    float(entry["points"])))
        return tuple(results)
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise F1DataError("Missing or invalid standings") from exc
