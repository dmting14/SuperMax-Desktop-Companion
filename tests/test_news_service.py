"""Offline scheduled sync, isolation, backoff, deduplication and cache tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from dataclasses import replace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_data import NewsError
from news_models import NewsItem, NewsSource
from news_service import NewsService
from news_store import NewsRepository
from local_llm import SummaryError
from fia_documents import DocumentCandidate, ParsedDocument


NOW = datetime(2026, 10, 24, 0, tzinfo=timezone.utc)
CN = NewsSource("中国新闻网", "https://example.cn/rss", "example.cn", 30, 5)
FIA = NewsSource("FIA", "https://example.org/rss", "example.org", 60, 7, "官方发布")
ARTICLE = NewsItem("F1 confirms new calendar", CN.name, NOW,
                   "https://example.cn/f1/calendar", "Confirmed event schedule")


class NewsServiceTests(unittest.TestCase):
    def setUp(self):
        unavailable = patch("news_service.model_available", return_value=False)
        unavailable.start()
        self.addCleanup(unavailable.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = NewsRepository(Path(self.directory.name) / "news.sqlite3")
        self.service = NewsService(self.repo, (CN, FIA))

    def test_normal_update_dedup_cache_and_cadence(self):
        with patch("news_service._fetch_source", return_value=[ARTICLE]) as fetch, \
             patch("news_service.summarize_news", return_value="digest") as summary:
            first = self.service.refresh(now=NOW)
            self.assertEqual(first.changed_count, 1)
            self.assertEqual(len(first.items), 1)
            self.assertEqual(first.new_summary, "digest")
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(summary.call_count, 1)
            self.assertEqual(self.repo.load()[0].url, ARTICLE.url)
            self.assertEqual(self.repo.load()[0].credibility, "媒体报道")
            self.assertEqual(self.repo.state(CN.name).next_due_utc, NOW + timedelta(minutes=30))
            self.assertEqual(self.repo.state(FIA.name).next_due_utc, NOW + timedelta(minutes=60))
            self.service.refresh(now=NOW + timedelta(minutes=20))
            self.assertEqual(fetch.call_count, 2)
            second = self.service.refresh(manual=True, now=NOW + timedelta(minutes=21))
            self.assertEqual(fetch.call_count, 4)
            self.assertEqual(second.changed_count, 0)
            self.assertEqual(summary.call_count, 1)
            self.assertEqual(self.repo.load()[0].synced_utc, NOW + timedelta(minutes=21))
        reopened = NewsRepository(self.repo.path)
        self.assertEqual(len(reopened.load()), 1)

    def test_feedback_persists_and_does_not_demote_p0(self):
        from dataclasses import replace
        newer = replace(ARTICLE, title="Verstappen contract confirmed",
                        url="https://example.cn/f1/max", published_utc=NOW + timedelta(hours=1))
        self.repo.save_items([ARTICLE, newer], NOW)
        with self.repo._connect() as db:
            db.execute("UPDATE news SET priority='P0' WHERE url=?", (newer.url,))
            db.execute("UPDATE news SET priority='P1' WHERE url=?", (ARTICLE.url,))
        self.repo.set_feedback(newer, -1, NOW)
        self.repo.set_feedback(ARTICLE, 1, NOW)
        reopened = NewsRepository(self.repo.path)
        self.assertEqual(reopened.feedback(newer), -1)
        self.assertEqual(reopened.load()[0].url, newer.url)
        reopened.set_feedback(newer, 0, NOW)
        self.assertEqual(reopened.feedback(newer), 0)

    def test_one_source_timeout_and_backoff_do_not_block_domestic(self):
        def fetch(source, timeout):
            if source == FIA:
                raise NewsError("FIA 超时")
            return [ARTICLE]
        with patch("news_service._fetch_source", side_effect=fetch) as mocked:
            result = self.service.refresh(now=NOW)
            self.assertEqual(len(result.items), 1)
            self.assertEqual(result.changed_count, 1)
            self.assertIn("超时", self.repo.state(FIA.name).last_error)
            self.assertEqual(self.repo.state(FIA.name).next_due_utc,
                             NOW + timedelta(minutes=5))
            self.service.refresh(now=NOW + timedelta(minutes=4))
            self.assertEqual(mocked.call_count, 2)
            self.service.refresh(now=NOW + timedelta(minutes=5))
            self.assertEqual(self.repo.state(FIA.name).failures, 2)
            self.assertEqual(self.repo.state(FIA.name).next_due_utc,
                             NOW + timedelta(minutes=15))
            self.assertEqual(len(self.repo.load()), 1)

    def test_all_sources_fail_keeps_cached_news(self):
        self.repo.save_items([ARTICLE], NOW)
        with patch("news_service._fetch_source", side_effect=NewsError("offline")):
            result = self.service.refresh(now=NOW)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.changed_count, 0)
        self.assertTrue(all(state.last_error for state in result.states))

    def test_fia_documents_run_in_separate_source_and_version_cache(self):
        document_source = NewsSource("FIA 裁决文件", "https://www.fia.com/documents/season",
                                     "fia.com", 60, 9, "官方文件", "fia_documents")
        service = NewsService(self.repo, (CN, document_source))
        candidate = DocumentCandidate("Singapore Grand Prix", "85", "Infringement - Car 18",
                                      "11.10.26", "https://www.fia.com/system/files/decision-document/test.pdf",
                                      "infringement")
        parsed = ParsedDocument(candidate, "pdf-a", "text-a", "Decision Driver: Warning.",
                                "penalty", "Lance Stroll", "Driver: Warning.")
        result = SimpleNamespace(race=SimpleNamespace(name="Singapore Grand Prix"))
        with patch("news_service.get_latest_result", return_value=result), \
             patch("news_service.fetch_document_list", return_value=(candidate,)) as listing, \
             patch("news_service.download_pdf", return_value=b"PDF"), \
             patch("news_service.parse_document", return_value=parsed), \
             patch("news_service._fetch_source", return_value=[ARTICLE]):
            first = service.refresh(now=NOW)
            self.assertEqual(first.changed_count, 2)
            self.assertEqual(len(first.items), 2)
            self.assertIn("Singapore%20Grand%20Prix", listing.call_args.args[0])
            self.assertIn("penalty", [item.document_status for item in self.repo.load()])
            second = service.refresh(manual=True, now=NOW + timedelta(minutes=1))
            self.assertEqual(second.changed_count, 0)

    def test_f1_detail_enrichment_and_failed_detail_keeps_cache(self):
        source = NewsSource("Formula 1", "https://www.formula1.com/en/latest",
                            "formula1.com", 60, 8, "F1 官方平台报道", "f1_html")
        service = NewsService(self.repo, (source,))
        headline = NewsItem("F1 confirms 2027 calendar", source.name, NOW,
                            "https://www.formula1.com/en/latest/article/test.1", "",
                            source.credibility)
        rich = replace(headline, body="Formula 1 confirmed the 2027 calendar.",
                       summary="Official calendar announcement")
        with patch("news_service._fetch_source", return_value=[headline]), \
             patch("news_service.fetch_f1_article", return_value=rich):
            first = service.refresh(now=NOW)
        self.assertEqual(first.changed_count, 1)
        self.assertIn("confirmed", first.items[0].body)
        from news_articles import ArticleError
        with patch("news_service._fetch_source", return_value=[headline]), \
             patch("news_service.fetch_f1_article", side_effect=ArticleError("HTTP 503")):
            second = service.refresh(manual=True, now=NOW + timedelta(minutes=1))
        self.assertEqual(second.changed_count, 0)
        self.assertIn("confirmed", second.items[0].body)
        self.assertIn("HTTP 503", self.repo.state(source.name).last_error)

    def test_rejected_ai_output_is_not_displayed_as_summary(self):
        with patch("news_service._fetch_source", return_value=[ARTICLE]), \
             patch("news_service.model_available", return_value=True), \
             patch("news_service.summarize_item", side_effect=SummaryError("unsupported penalty")):
            result = self.service.refresh(now=NOW)
        item = next(entry for entry in result.items if entry.url == ARTICLE.url)
        self.assertEqual(item.summary_status, "rejected")
        self.assertEqual(item.summary_zh, "")
        self.assertEqual(self.repo.pending_summaries(), ())

    def test_fia_partial_pdf_failure_reports_successful_changes(self):
        source = NewsSource("FIA 裁决文件", "https://www.fia.com/documents/season",
                            "fia.com", 60, 9, "官方文件", "fia_documents")
        first = DocumentCandidate("Singapore Grand Prix", "85", "Infringement - Car 18", "",
                                  "https://www.fia.com/system/files/decision-document/85.pdf", "infringement")
        second = DocumentCandidate("Singapore Grand Prix", "62", "Infringement - Car 77", "",
                                   "https://www.fia.com/system/files/decision-document/62.pdf", "infringement")
        parsed = ParsedDocument(first, "pdf-a", "text-a", "Decision Driver: Warning.",
                                "penalty", "Lance Stroll", "Driver: Warning.")
        def read(candidate, timeout):
            if candidate == second:
                raise TimeoutError("PDF timed out")
            return parsed
        race = SimpleNamespace(race=SimpleNamespace(name="Singapore Grand Prix"))
        with patch("news_service.get_latest_result", return_value=race), \
             patch("news_service.fetch_document_list", return_value=(first, second)), \
             patch.object(NewsService, "_read_fia_pdf", side_effect=read):
            result = NewsService(self.repo, (source,)).refresh(now=NOW)
        self.assertEqual(result.changed_count, 1)
        self.assertEqual(len(result.items), 1)
        self.assertIn("Doc 62", self.repo.state(source.name).last_error)


if __name__ == "__main__":
    unittest.main()
