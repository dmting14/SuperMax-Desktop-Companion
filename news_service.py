"""Scheduled and manual news sync, isolated per source."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event
from urllib.parse import quote

from news_data import NewsError, _fetch_source, filter_news, summarize_news
from news_models import NewsItem, NewsSource
from news_sources import SOURCES
from news_store import NewsRepository, SourceState
from fia_documents import (SEASON_DOCUMENTS_URL, fetch_document_list,
                           download_pdf, parse_document)
from f1_data import get_latest_result
from local_llm import MODEL, SummaryError, model_available, summarize_item
from news_articles import ArticleError, fetch_f1_article


@dataclass(frozen=True)
class NewsSnapshot:
    items: tuple[NewsItem, ...]
    states: tuple[SourceState, ...]
    changed_count: int = 0
    new_summary: str = ""


class NewsService:
    def __init__(self, repository: NewsRepository,
                 sources: tuple[NewsSource, ...] = SOURCES):
        self.repository = repository
        self.sources = sources
        self._stop = Event()

    def cancel(self) -> None:
        self._stop.set()

    def snapshot(self) -> NewsSnapshot:
        return NewsSnapshot(self.repository.load(),
                            tuple(self.repository.state(source.name) for source in self.sources))

    def _sync_fia_documents(self, source: NewsSource, now: datetime) -> tuple[int, str]:
        result = get_latest_result(timeout=source.timeout_seconds)
        if result is None:
            raise NewsError("No completed race available for FIA document lookup")
        event = result.race.name
        url = SEASON_DOCUMENTS_URL + "/event/" + quote(event, safe="")
        candidates = fetch_document_list(url, event, source.timeout_seconds)
        recalled_count = sum(self.repository.mark_recalled(item, url, now)
                             for item in candidates if item.recalled)
        final_documents = [item for item in candidates if item.url and not item.recalled
                           and item.kind != "summons" and
                           ("car " in item.title.lower() or item.kind == "decision")]
        investigations = [item for item in candidates if item.url and not item.recalled
                          and item.kind == "summons" and "car " in item.title.lower()][:4]
        selected = final_documents[:26] + investigations
        if not selected and not recalled_count:
            raise NewsError("FIA list has no accessible relevant decision PDFs")
        changed = recalled_count
        failures = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(self._read_fia_pdf, item, source.timeout_seconds): item
                       for item in selected}
            for future in as_completed(futures):
                candidate = futures[future]
                try:
                    changed += self.repository.save_document(future.result(), now)
                except Exception as exc:
                    failures.append(f"Doc {candidate.number}: {exc}")
        return changed, "; ".join(failures[:3])

    @staticmethod
    def _read_fia_pdf(candidate, timeout: float):
        return parse_document(candidate, download_pdf(candidate.url, timeout))

    def refresh(self, manual: bool = False, now: datetime | None = None) -> NewsSnapshot:
        now = now or datetime.now(timezone.utc)
        due = [source for source in self.sources if manual or
               (self.repository.state(source.name).next_due_utc or now) <= now]
        changed_items: list[NewsItem] = []
        changed_count = 0
        if due:
            with ThreadPoolExecutor(max_workers=min(4, len(due))) as pool:
                futures = {pool.submit(self._sync_fia_documents, source, now)
                           if source.format == "fia_documents" else
                           pool.submit(_fetch_source, source, source.timeout_seconds): source
                           for source in due}
                for future in as_completed(futures):
                    source = futures[future]
                    try:
                        if source.format == "fia_documents":
                            document_count, document_error = future.result()
                            changed_count += document_count
                            if document_error:
                                self.repository.record_failure(source, document_error, now)
                                continue
                        else:
                            selected = filter_news(future.result())
                            detail_errors = []
                            if source.format == "f1_html":
                                enriched = []
                                for item in selected:
                                    try:
                                        enriched.append(fetch_f1_article(item, source.timeout_seconds))
                                    except ArticleError as exc:
                                        enriched.append(item)
                                        detail_errors.append(str(exc))
                                selected = enriched
                            fresh = self.repository.save_items(selected, now)
                            changed_items.extend(fresh)
                            changed_count += len(fresh)
                            if detail_errors:
                                self.repository.record_failure(source, detail_errors[0], now)
                                continue
                        self.repository.record_success(source, now)
                    except Exception as exc:
                        self.repository.record_failure(source, str(exc), now)
        # This is the only summary trigger. A cache read or unchanged feed never calls it.
        digest = summarize_news(tuple(changed_items)) if changed_items else ""
        if not self._stop.is_set() and model_available(MODEL):
            for item in self.repository.pending_summaries(limit=2):
                if self._stop.is_set():
                    break
                try:
                    result = summarize_item(item, MODEL)
                    self.repository.save_summary(item, result.title, result.text,
                                                 result.model, "ready", now, result)
                except SummaryError as exc:
                    self.repository.save_summary(item, "", "", MODEL, "rejected", now)
        snapshot = self.snapshot()
        return NewsSnapshot(snapshot.items, snapshot.states, changed_count, digest)
