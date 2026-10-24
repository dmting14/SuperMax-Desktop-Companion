"""Refresh the SQLite news cache independently from the desktop UI."""

import sys

from news_service import NewsService
from news_store import NewsRepository


def main() -> int:
    try:
        snapshot = NewsService(NewsRepository()).refresh(manual=True)
    except Exception as exc:
        print(f"News error: {exc}", file=sys.stderr)
        return 1
    print(f"Cached {len(snapshot.items)} high-value F1 articles; "
          f"new or changed: {snapshot.changed_count}")
    for state in snapshot.states:
        print(f"{state.name}: last success {state.last_success_utc or 'never'}; "
              f"error {state.last_error or 'none'}")
    for item in snapshot.items:
        published = item.published_utc.isoformat() if item.published_utc else "unknown date"
        print(f"- [{item.source} / {item.credibility}] {published} "
              f"{item.title_zh or item.title}\n  {item.url}")
        if item.document_status:
            print(f"  FIA status: {item.document_status}; decision: {item.decision or 'unknown'}")
        print(f"  AI: {item.summary_status}"
              + (f" ({item.summary_model}) {item.summary_zh}" if item.summary_zh else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
