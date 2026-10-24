"""Run a live F1 API query without starting the desktop pet."""

from dataclasses import asdict
import json
import sys

from f1_data import F1ApiError, get_latest_result, get_next_race


def main() -> int:
    try:
        next_race = get_next_race()
        latest_result = get_latest_result()
    except F1ApiError as exc:
        print(f"F1 API error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "next_race": asdict(next_race) if next_race else None,
        "latest_result": asdict(latest_result) if latest_result else None,
    }, ensure_ascii=False, indent=2, default=lambda value: value.isoformat()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
