"""Mocked Ollama transport and strict factual fallback checks."""

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from local_llm import SummaryError, _evidence, summarize_item, validate_summary
from news_skill import load_news_skill, validate_skill_result
from news_models import NewsItem
from news_store import NewsRepository


NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)
ARTICLE = NewsItem("F1 team confirms driver Alex Smith for 2027", "Formula 1", NOW,
                   "https://www.formula1.com/en/latest/article/test", "Official team announcement",
                   "F1 官方平台报道", body="F1 team confirms driver Alex Smith for 2027.")


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class LocalLLMTests(unittest.TestCase):
    def test_skill_loaded_and_source_status_guarded(self):
        self.assertIn("P0", load_news_skill())
        with self.assertRaisesRegex(ValueError, "官方确认"):
            validate_skill_result(ARTICLE, {"priority": "P1", "category": "driver_team",
                                           "source_status": "official", "related_to_max": False,
                                           "reason": "签约"})

    def test_mocked_generation_validation_and_cache(self):
        response = {"response": json.dumps({"title": "车队确认新车手",
                                            "summary": "F1车队确认Alex Smith将于2027年加入。",
                                            "priority": "P1", "category": "driver_team",
                                            "source_status": "reported", "related_to_max": False,
                                            "reason": "车手正式加盟"})}
        with patch("local_llm.urlopen", return_value=FakeResponse(json.dumps(response).encode())):
            result = summarize_item(ARTICLE)
        self.assertEqual(result.model, "qwen2.5:1.5b")
        with tempfile.TemporaryDirectory() as directory:
            repo = NewsRepository(Path(directory) / "news.sqlite3")
            repo.save_items([ARTICLE], NOW)
            pending = repo.pending_summaries()
            self.assertEqual(len(pending), 1)
            self.assertTrue(repo.save_summary(pending[0], result.title, result.text,
                                              result.model, "ready", NOW))
            self.assertFalse(repo.save_summary(pending[0], result.title, result.text,
                                               result.model, "ready", NOW))
            reopened = NewsRepository(repo.path)
            self.assertEqual(reopened.load()[0].summary_zh, result.text)
            self.assertEqual(reopened.load()[0].title_zh, result.title)
            self.assertEqual(reopened.pending_summaries(), ())
            repo.save_items([ARTICLE], NOW)
            self.assertEqual(repo.pending_summaries(), ())

    def test_unavailable_bad_json_and_fact_checks(self):
        from urllib.error import URLError
        with patch("local_llm.urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(SummaryError, "不可用"):
                summarize_item(ARTICLE)
        with patch("local_llm.urlopen", return_value=FakeResponse(b'{"response":"invalid"}')):
            with self.assertRaisesRegex(SummaryError, "JSON"):
                summarize_item(ARTICLE)
        with self.assertRaisesRegex(SummaryError, "数字"):
            validate_summary(ARTICLE, "车队官宣", "车队确认Alex Smith在2028年加入。")
        with self.assertRaisesRegex(SummaryError, "长度"):
            validate_summary(ARTICLE, "车队官宣", "中" * 101)

    def test_document_status_and_driver_are_guarded(self):
        document = NewsItem("FIA Decision", "FIA 文件", NOW,
                            "https://www.fia.com/system/files/decision-document/test.pdf",
                            "No further action", "官方文件", body="No / Driver 44 - Lewis Hamilton\nDecision No further action.",
                            document_status="no_action", driver="Lewis Hamilton")
        with self.assertRaisesRegex(SummaryError, "车手"):
            validate_summary(document, "FIA裁决", "FIA审查后决定不再采取行动。")
        with self.assertRaisesRegex(SummaryError, "实际处罚"):
            validate_summary(document, "FIA裁决", "Lewis Hamilton已受罚。")

    def test_realistic_penalty_prompt_and_decision_number(self):
        document = NewsItem("FIA Doc 79 - Car 63", "FIA 文件", NOW,
                            "https://www.fia.com/system/files/decision-document/test.pdf",
                            "Official decision", "官方文件",
                            body="Official stewards' decision. Each additional element carries 10 grid places.",
                            document_id="2026:Singapore:79", document_status="penalty",
                            driver="George Russell",
                            decision="Drop of 20 grid positions in the next Race in which the driver participates.")
        response = {"response": json.dumps({
            "title": "车手甲被罚退20个发车位",
            "summary": "FIA裁决车手甲在下场正赛罚退20个发车位。",
            "priority": "P1", "category": "penalty", "source_status": "official",
            "related_to_max": False, "reason": "正式处罚文件"})}

        def fake_urlopen(request, timeout):
            payload = json.loads(request.data)
            self.assertIn("车手甲", payload["prompt"])
            self.assertNotIn("George Russell", payload["prompt"])
            self.assertIn("罚退20个发车位", payload["prompt"])
            return FakeResponse(json.dumps(response).encode())

        with patch("local_llm.urlopen", side_effect=fake_urlopen):
            result = summarize_item(document)
        self.assertIn("George Russell", result.title)
        self.assertIn("George Russell", result.text)
        with self.assertRaisesRegex(SummaryError, "处罚位数"):
            validate_summary(document, "George Russell受罚", "George Russell被罚退10个发车位。")
        with self.assertRaisesRegex(SummaryError, "罚时"):
            validate_summary(document, "George Russell受罚", "George Russell被罚时20秒。")

    def test_article_evidence_and_source_claims(self):
        article = NewsItem("Lindblad, Colapinto and Bortoleto to take penalties",
                           "Formula 1", NOW, "https://www.formula1.com/test",
                           "Grid penalties", "F1 官方平台报道",
                           body=("Arvid Lindblad, Franco Colapinto and Gabriel Bortoleto were penalized.\n"
                                 "Regulations state a 10-place penalty for the first offence.\n"
                                 "Lindblad will lose five places, Colapinto 10 places, Bortoleto 20 places."))
        self.assertIn("Bortoleto 20 places", _evidence(article))
        with self.assertRaisesRegex(SummaryError, "处罚机构"):
            validate_summary(article, "三位车手受罚", "F1官方处以三位车手罚退。")
        africa = NewsItem("Formula 1 returns to Africa", "FIA", NOW,
                          "https://www.fia.com/test", "Returns for first time since 1993",
                          "FIA 官方公告")
        with self.assertRaisesRegex(SummaryError, "历史首次"):
            validate_summary(africa, "F1重返非洲", "F1将首次在非洲大陆举行比赛。")
        validate_summary(africa, "F1重返非洲", "F1将自1993年以来首次在非洲大陆举行比赛。")
        agreement = NewsItem("Formula 1 returns to Africa with 10 year agreement to race in Rwanda",
                             "FIA", NOW, "https://www.fia.com/agreement",
                             "The sport returns to Africa for the first time since 1993.",
                             "FIA 官方公告")
        self.assertIn("10年赛事协议", _evidence(agreement))
        with self.assertRaisesRegex(SummaryError, "协议年限"):
            validate_summary(agreement, "F1重返非洲", "F1自1993年以来重返非洲。")

    def test_skill_rejects_unrelated_p0(self):
        from news_skill import validate_skill_result
        article = NewsItem("Carlos Sainz receives grid penalty", "FIA", NOW,
                           "https://www.fia.com/sainz", "Car 55 grid penalty",
                           "FIA 官方文件", driver="Carlos Sainz")
        fields = {"priority": "P0", "category": "penalty", "source_status": "official",
                  "related_to_max": True, "reason": "FIA decision"}
        with self.assertRaises(ValueError):
            validate_skill_result(article, fields)


if __name__ == "__main__":
    unittest.main()
