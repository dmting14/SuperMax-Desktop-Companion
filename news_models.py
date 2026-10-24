"""Shared types for news sources, cache and UI."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NewsSource:
    name: str
    feed_url: str
    article_domain: str
    interval_minutes: int = 60
    timeout_seconds: float = 6.0
    credibility: str = "媒体报道"
    format: str = "rss"


@dataclass(frozen=True)
class NewsItem:
    title: str
    source: str
    published_utc: datetime | None
    url: str
    summary: str
    credibility: str = "媒体报道"
    synced_utc: datetime | None = None
    body: str = ""
    event_type: str = ""
    content_hash: str = ""
    summary_zh: str = ""
    summary_model: str = ""
    summary_generated_utc: datetime | None = None
    summary_status: str = "pending"
    document_id: str = ""
    document_status: str = ""
    driver: str = ""
    decision: str = ""
    document_date: str = ""
    title_zh: str = ""
    priority: str = ""
    category: str = ""
    source_status: str = ""
    related_to_max: bool = False
    reason: str = ""
