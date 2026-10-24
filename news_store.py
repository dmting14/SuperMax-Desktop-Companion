"""SQLite cache for selected headlines and independent source health."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from contextlib import contextmanager
import sqlite3

from news_models import NewsItem, NewsSource


DEFAULT_NEWS_DB = Path(__file__).resolve().parent / "user_data" / "news.sqlite3"


@dataclass(frozen=True)
class SourceState:
    name: str
    last_success_utc: datetime | None = None
    last_error: str = ""
    next_due_utc: datetime | None = None
    failures: int = 0


def _date(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class NewsRepository:
    def __init__(self, path: Path = DEFAULT_NEWS_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS news ("
                       "id TEXT PRIMARY KEY, title TEXT NOT NULL, source TEXT NOT NULL, "
                       "published_utc TEXT, url TEXT NOT NULL UNIQUE, summary TEXT NOT NULL, "
                       "credibility TEXT NOT NULL, synced_utc TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS news_sources ("
                       "name TEXT PRIMARY KEY, last_success_utc TEXT, last_error TEXT NOT NULL DEFAULT '', "
                       "next_due_utc TEXT, failures INTEGER NOT NULL DEFAULT 0)")
            additions = {
                "body": "TEXT NOT NULL DEFAULT ''",
                "event_type": "TEXT NOT NULL DEFAULT ''",
                "content_hash": "TEXT NOT NULL DEFAULT ''",
                "summary_zh": "TEXT NOT NULL DEFAULT ''",
                "summary_model": "TEXT NOT NULL DEFAULT ''",
                "summary_generated_utc": "TEXT",
                "summary_status": "TEXT NOT NULL DEFAULT 'pending'",
                "document_id": "TEXT NOT NULL DEFAULT ''",
                "document_status": "TEXT NOT NULL DEFAULT ''",
                "driver": "TEXT NOT NULL DEFAULT ''",
                "decision": "TEXT NOT NULL DEFAULT ''",
                "document_date": "TEXT NOT NULL DEFAULT ''",
                "updated_utc": "TEXT",
                "title_zh": "TEXT NOT NULL DEFAULT ''",
                "priority": "TEXT NOT NULL DEFAULT ''",
                "category": "TEXT NOT NULL DEFAULT ''",
                "source_status": "TEXT NOT NULL DEFAULT ''",
                "related_to_max": "INTEGER NOT NULL DEFAULT 0",
                "reason": "TEXT NOT NULL DEFAULT ''",
            }
            existing = {row[1] for row in db.execute("PRAGMA table_info(news)")}
            for name, definition in additions.items():
                if name not in existing:
                    db.execute(f"ALTER TABLE news ADD COLUMN {name} {definition}")
            db.execute("CREATE TABLE IF NOT EXISTS fia_documents ("
                       "document_id TEXT PRIMARY KEY, event TEXT NOT NULL, number TEXT NOT NULL, "
                       "title TEXT NOT NULL, published TEXT NOT NULL, url TEXT, kind TEXT NOT NULL, "
                       "status TEXT NOT NULL, driver TEXT, decision TEXT, pdf_hash TEXT NOT NULL, "
                       "text_hash TEXT NOT NULL, body TEXT NOT NULL, updated_utc TEXT NOT NULL, "
                       "parser_version INTEGER NOT NULL DEFAULT 1)")
            document_columns = {row[1] for row in db.execute("PRAGMA table_info(fia_documents)")}
            if "parser_version" not in document_columns:
                db.execute("ALTER TABLE fia_documents ADD COLUMN parser_version INTEGER NOT NULL DEFAULT 1")
            db.execute("CREATE TABLE IF NOT EXISTS fia_document_versions ("
                       "document_id TEXT NOT NULL, pdf_hash TEXT NOT NULL, seen_utc TEXT NOT NULL, "
                       "status TEXT NOT NULL, PRIMARY KEY(document_id,pdf_hash))")
            db.execute("CREATE TABLE IF NOT EXISTS news_feedback ("
                       "news_id TEXT PRIMARY KEY, vote INTEGER NOT NULL CHECK(vote IN (-1,1)), "
                       "updated_utc TEXT NOT NULL)")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def load(self, limit: int = 30) -> tuple[NewsItem, ...]:
        with self._connect() as db:
            rows = db.execute("SELECT title, source, published_utc, url, summary, credibility, "
                              "synced_utc, body, event_type, content_hash, summary_zh, "
                              "summary_model, summary_generated_utc, summary_status, document_id, "
                              "document_status, driver, decision, document_date, title_zh, "
                              "priority, category, source_status, related_to_max, reason FROM news "
                              "ORDER BY COALESCE(published_utc, synced_utc) "
                              "DESC LIMIT ?", (max(limit, 200),)).fetchall()
            votes = dict(db.execute("SELECT news_id, vote FROM news_feedback").fetchall())
        items = tuple(NewsItem(row[0], row[1], _date(row[2]), row[3], row[4], row[5],
                              _date(row[6]), row[7], row[8], row[9], row[10], row[11],
                              _date(row[12]), row[13], row[14], row[15], row[16], row[17], row[18], row[19],
                              row[20], row[21], row[22], bool(row[23]), row[24])
                     for row in rows)
        def rank(item):
            key = item.document_id or item.url
            vote = votes.get(sha256(key.encode("utf-8")).hexdigest(), 0)
            priority = 3 if item.priority == "P0" else 2 if item.priority == "P1" else 1
            if item.priority == "P0":
                vote = max(0, vote)
            timestamp = (item.published_utc or item.synced_utc)
            recency = timestamp.timestamp() if timestamp else 0
            return priority, recency + vote * 86400
        return tuple(sorted(items, key=rank, reverse=True)[:limit])

    def feedback(self, item: NewsItem) -> int:
        key = item.document_id or item.url
        with self._connect() as db:
            row = db.execute("SELECT vote FROM news_feedback WHERE news_id=?",
                             (sha256(key.encode("utf-8")).hexdigest(),)).fetchone()
        return row[0] if row else 0

    def set_feedback(self, item: NewsItem, vote: int, now: datetime) -> None:
        if vote not in (-1, 0, 1):
            raise ValueError("vote must be -1, 0 or 1")
        key = sha256((item.document_id or item.url).encode("utf-8")).hexdigest()
        with self._connect() as db:
            if vote == 0:
                db.execute("DELETE FROM news_feedback WHERE news_id=?", (key,))
            else:
                db.execute("INSERT INTO news_feedback VALUES (?,?,?) ON CONFLICT(news_id) "
                           "DO UPDATE SET vote=excluded.vote, updated_utc=excluded.updated_utc",
                           (key, vote, now.isoformat()))

    def state(self, name: str) -> SourceState:
        with self._connect() as db:
            row = db.execute("SELECT last_success_utc, last_error, next_due_utc, failures "
                             "FROM news_sources WHERE name=?", (name,)).fetchone()
        return SourceState(name, _date(row[0]), row[1], _date(row[2]), row[3]) if row else SourceState(name)

    def save_items(self, items: list[NewsItem], synced_utc: datetime) -> tuple[NewsItem, ...]:
        from news_data import classify_news
        changed: list[NewsItem] = []
        with self._connect() as db:
            for item in items:
                stable_id = sha256(item.url.encode("utf-8")).hexdigest()
                published = item.published_utc.isoformat() if item.published_utc else None
                body = item.body or item.summary
                event_type = item.event_type or classify_news(item) or ""
                old = db.execute("SELECT content_hash, source, credibility, event_type, body, summary "
                                 "FROM news WHERE id=?", (stable_id,)).fetchone()
                if old and not body:
                    body = old[4]
                summary = item.summary or (old[5] if old else "")
                content_hash = sha256((item.title + "\0" + body + "\0" + summary).encode("utf-8")).hexdigest()
                if not old or old[:4] != (content_hash, item.source, item.credibility, event_type):
                    db.execute("INSERT INTO news (id,title,source,published_utc,url,summary,"
                               "credibility,synced_utc,body,event_type,content_hash,updated_utc,"
                               "summary_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'pending') "
                               "ON CONFLICT(id) DO UPDATE SET title=excluded.title, "
                               "source=excluded.source, published_utc=excluded.published_utc, "
                               "summary=excluded.summary, credibility=excluded.credibility, "
                               "synced_utc=excluded.synced_utc, body=excluded.body, "
                               "event_type=excluded.event_type, content_hash=excluded.content_hash, "
                               "updated_utc=excluded.updated_utc, summary_status='pending', "
                               "title_zh='', summary_zh='', summary_model='', summary_generated_utc=NULL",
                               (stable_id, item.title, item.source, published, item.url,
                                summary, item.credibility, synced_utc.isoformat(), body,
                                event_type, content_hash, synced_utc.isoformat()))
                    changed.append(item)
                else:
                    db.execute("UPDATE news SET synced_utc=? WHERE id=?",
                               (synced_utc.isoformat(), stable_id))
        return tuple(changed)

    def document_pdf_hash(self, document_id: str) -> str | None:
        from fia_documents import DOCUMENT_PARSER_VERSION
        with self._connect() as db:
            row = db.execute("SELECT pdf_hash, status, parser_version FROM fia_documents WHERE document_id=?",
                             (document_id,)).fetchone()
        return row[0] if row and row[1] != "withdrawn" and row[2] == DOCUMENT_PARSER_VERSION else None

    def mark_recalled(self, candidate, listing_url: str, now: datetime) -> bool:
        """A recalled listing supersedes prior PDF text without inventing a ruling."""
        stable_id = sha256(candidate.stable_id.encode("utf-8")).hexdigest()
        with self._connect() as db:
            old = db.execute("SELECT pdf_hash, status FROM fia_documents WHERE document_id=?",
                             (candidate.stable_id,)).fetchone()
            if old and old[1] == "withdrawn":
                return False
            pdf_hash = old[0] if old else ""
            db.execute("INSERT INTO fia_documents (document_id,event,number,title,published,url,kind,"
                       "status,driver,decision,pdf_hash,text_hash,body,updated_utc) "
                       "VALUES (?,?,?,?,?,?,?,'withdrawn',NULL,NULL,?,'','',?) "
                       "ON CONFLICT(document_id) DO UPDATE SET status='withdrawn', "
                       "title=excluded.title, updated_utc=excluded.updated_utc",
                       (candidate.stable_id, candidate.event, candidate.number,
                        candidate.title, candidate.published, candidate.url,
                        candidate.kind, pdf_hash, now.isoformat()))
            db.execute("INSERT OR IGNORE INTO fia_document_versions VALUES (?,?,?,'withdrawn')",
                       (candidate.stable_id, "withdrawn", now.isoformat()))
            source_url = listing_url + "#doc-" + candidate.number
            content_hash = sha256(("withdrawn:" + candidate.stable_id + ":" + pdf_hash).encode()).hexdigest()
            db.execute("INSERT INTO news (id,title,source,published_utc,url,summary,credibility,"
                       "synced_utc,body,event_type,content_hash,updated_utc,summary_status,"
                       "document_id,document_status,document_date) "
                       "VALUES (?,?,'FIA 文件',NULL,?,?,'官方文件',?,'','fia_decision',?,?,'unavailable',"
                       "?,'withdrawn',?) ON CONFLICT(id) DO UPDATE SET "
                       "title=excluded.title, url=excluded.url, summary=excluded.summary, "
                       "body='', content_hash=excluded.content_hash, updated_utc=excluded.updated_utc, "
                       "synced_utc=excluded.synced_utc, summary_status='unavailable', "
                       "title_zh='', summary_zh='', summary_model='', summary_generated_utc=NULL, "
                       "document_status='withdrawn'",
                       (stable_id, candidate.title, source_url,
                        "FIA 官方列表标注此文件已撤回，未据此认定处罚。", now.isoformat(),
                        content_hash, now.isoformat(), candidate.stable_id, candidate.published))
        return True

    def pending_summaries(self, limit: int = 8) -> tuple[NewsItem, ...]:
        with self._connect() as db:
            rows = db.execute("SELECT title, source, published_utc, url, summary, credibility, "
                              "synced_utc, body, event_type, content_hash, summary_zh, "
                              "summary_model, summary_generated_utc, summary_status, document_id, "
                              "document_status, driver, decision, document_date, title_zh FROM news "
                              "WHERE summary_status='pending' ORDER BY updated_utc DESC LIMIT ?",
                              (limit,)).fetchall()
        return tuple(NewsItem(row[0], row[1], _date(row[2]), row[3], row[4], row[5],
                              _date(row[6]), row[7], row[8], row[9], row[10], row[11],
                              _date(row[12]), row[13], row[14], row[15], row[16], row[17], row[18], row[19])
                     for row in rows)

    def save_summary(self, item: NewsItem, title_zh: str, summary_zh: str, model: str,
                     status: str, now: datetime, classification=None) -> bool:
        if status not in ("ready", "unavailable", "rejected"):
            raise ValueError("Invalid summary status")
        stable_id = (sha256(item.document_id.encode("utf-8")).hexdigest()
                     if item.document_id else sha256(item.url.encode("utf-8")).hexdigest())
        with self._connect() as db:
            updated = db.execute("UPDATE news SET title_zh=?, summary_zh=?, summary_model=?, "
                                 "summary_generated_utc=?, summary_status=?, priority=?, category=?, "
                                 "source_status=?, related_to_max=?, reason=? "
                                 "WHERE id=? AND content_hash=? AND summary_status='pending'",
                                 (title_zh, summary_zh, model, now.isoformat() if status == "ready" else None,
                                  status, classification.priority if classification else "",
                                  classification.category if classification else "",
                                  classification.source_status if classification else "",
                                  int(classification.related_to_max) if classification else 0,
                                  classification.reason if classification else "",
                                  stable_id, item.content_hash))
            return updated.rowcount == 1

    def save_document(self, parsed, now: datetime) -> bool:
        from fia_documents import DOCUMENT_PARSER_VERSION
        candidate = parsed.candidate
        if self.document_pdf_hash(candidate.stable_id) == parsed.pdf_hash:
            with self._connect() as db:
                previous = db.execute("SELECT title, published, url FROM fia_documents "
                                      "WHERE document_id=?", (candidate.stable_id,)).fetchone()
                if previous == (candidate.title, candidate.published, candidate.url):
                    return False
                db.execute("UPDATE fia_documents SET title=?, published=?, url=?, "
                           "updated_utc=? WHERE document_id=?",
                           (candidate.title, candidate.published, candidate.url,
                            now.isoformat(), candidate.stable_id))
                news_id = sha256(candidate.stable_id.encode("utf-8")).hexdigest()
                db.execute("UPDATE news SET title=?, url=?, document_date=?, updated_utc=? "
                           "WHERE id=?", (f"FIA Doc {candidate.number} · {candidate.event} · "
                                         f"{candidate.title}", candidate.url, candidate.published,
                                         now.isoformat(), news_id))
            return True
        stable_id = sha256(candidate.stable_id.encode("utf-8")).hexdigest()
        title = f"FIA Doc {candidate.number} · {candidate.event} · {candidate.title}"
        summary = parsed.decision or ("调查通知，尚无最终裁决" if parsed.status == "investigation"
                                      else "裁决正文已收录")
        with self._connect() as db:
            db.execute("INSERT INTO fia_documents (document_id,event,number,title,published,url,kind,"
                       "status,driver,decision,pdf_hash,text_hash,body,updated_utc,parser_version) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                       "ON CONFLICT(document_id) DO UPDATE SET event=excluded.event, "
                       "number=excluded.number, title=excluded.title, published=excluded.published, "
                       "url=excluded.url, kind=excluded.kind, status=excluded.status, "
                       "driver=excluded.driver, decision=excluded.decision, pdf_hash=excluded.pdf_hash, "
                       "text_hash=excluded.text_hash, body=excluded.body, "
                       "updated_utc=excluded.updated_utc, parser_version=excluded.parser_version",
                       (candidate.stable_id, candidate.event, candidate.number, candidate.title,
                        candidate.published, candidate.url, candidate.kind, parsed.status,
                        parsed.driver, parsed.decision, parsed.pdf_hash, parsed.text_hash,
                        parsed.text, now.isoformat(), DOCUMENT_PARSER_VERSION))
            db.execute("INSERT OR IGNORE INTO fia_document_versions VALUES (?,?,?,?)",
                       (candidate.stable_id, parsed.pdf_hash, now.isoformat(), parsed.status))
            previous_news = db.execute("SELECT content_hash, document_status FROM news WHERE id=?",
                                       (stable_id,)).fetchone()
            if previous_news == (parsed.text_hash, parsed.status):
                db.execute("UPDATE news SET title=?, url=?, synced_utc=?, updated_utc=?, "
                           "document_date=? WHERE id=?",
                           (title, candidate.url, now.isoformat(), now.isoformat(),
                            candidate.published, stable_id))
                return True
            db.execute("INSERT INTO news (id,title,source,published_utc,url,summary,credibility,"
                       "synced_utc,body,event_type,content_hash,updated_utc,summary_status,"
                       "document_id,document_status,driver,decision,document_date) "
                       "VALUES (?,?,'FIA 文件',NULL,?,?,'官方文件',?,?,"
                       "'fia_decision',?,?,'pending',?,?,?,?,?) "
                       "ON CONFLICT(id) DO UPDATE SET title=excluded.title, url=excluded.url, "
                       "summary=excluded.summary, synced_utc=excluded.synced_utc, "
                       "body=excluded.body, content_hash=excluded.content_hash, "
                       "updated_utc=excluded.updated_utc, summary_status='pending', "
                       "title_zh='', summary_zh='', summary_model='', summary_generated_utc=NULL, "
                       "document_status=excluded.document_status, driver=excluded.driver, "
                       "decision=excluded.decision, document_date=excluded.document_date",
                       (stable_id, title, candidate.url, summary, now.isoformat(), parsed.text,
                        parsed.text_hash, now.isoformat(), candidate.stable_id, parsed.status,
                        parsed.driver or "", parsed.decision or "", candidate.published))
        return True

    def record_success(self, source: NewsSource, now: datetime) -> None:
        from datetime import timedelta
        next_due = now + timedelta(minutes=source.interval_minutes)
        with self._connect() as db:
            db.execute("INSERT INTO news_sources VALUES (?,?,?,?,0) ON CONFLICT(name) "
                       "DO UPDATE SET last_success_utc=excluded.last_success_utc, "
                       "last_error='', next_due_utc=excluded.next_due_utc, failures=0",
                       (source.name, now.isoformat(), "", next_due.isoformat()))

    def record_failure(self, source: NewsSource, error: str, now: datetime) -> None:
        from datetime import timedelta
        failures = self.state(source.name).failures + 1
        delay = min(120, 5 * 2 ** min(failures - 1, 5))
        next_due = now + timedelta(minutes=delay)
        with self._connect() as db:
            db.execute("INSERT INTO news_sources (name,last_error,next_due_utc,failures) "
                       "VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
                       "last_error=excluded.last_error, next_due_utc=excluded.next_due_utc, "
                       "failures=excluded.failures",
                       (source.name, error[:300], next_due.isoformat(), failures))
