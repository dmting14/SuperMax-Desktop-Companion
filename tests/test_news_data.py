"""Offline RSS parsing, filtering, and fallback tests."""

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import news_data


SOURCE = news_data.NewsSource("Example", "https://example.com/rss", "example.com")
RSS = b"""<rss><channel>
<item><title>Red Bull confirms Max Verstappen contract</title><link>https://example.com/f1/max?utm=x</link>
<pubDate>Fri, 23 Oct 2026 12:00:00 GMT</pubDate>
<description>&lt;p&gt;Red Bull arrives in Austin.&lt;/p&gt;</description></item>
<item><title>Cooking tips</title><link>https://example.com/food</link></item>
<item><title>F1 fake link</title><link>https://evil-example.com/steal</link></item>
</channel></rss>"""


class NewsDataTests(unittest.TestCase):
    def test_f1_official_html_is_parsed_as_html_not_rss(self):
        source = news_data.NewsSource("Formula 1", "https://www.formula1.com/en/latest",
                                      "formula1.com", format="f1_html")
        html = (b'<a href="/en/latest/article/driver-signs.abc">Driver signs for McLaren</a>'
                b'<a href="/en/latest/article/driver-signs.abc">Duplicate</a>'
                b'<a href="/en/latest/tags/not-news">Ignore</a>')
        items = news_data._parse_f1_page(html, source)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url,
                         "https://www.formula1.com/en/latest/article/driver-signs.abc")

    def test_high_value_screening_positive_and_negative_set(self):
        cases = (
            ("McLaren confirms new driver for 2027 F1 season", "Sky Sports", True),
            ("Red Bull signs Max Verstappen until 2030", "Sky Sports", True),
            ("FIA announces Formula 1 sporting regulation changes", "FIA", True),
            ("Lindblad and Colapinto to take penalties for US GP", "Formula 1", True),
            ("Formula 1 returns to Africa with 10 year agreement", "FIA", True),
            ("迈凯伦官宣新车手加盟F1车队", "中国新闻网", True),
            ("Verstappen wins 24 Hours of Nürburgring title", "Sky Sports", True),
            ("Verstappen backs Mekies' Red Bull contract extension", "Formula 1", False),
            ("Leclerc fastest in first practice", "Formula 1", False),
            ("ANALYSIS: Why McLaren may sign a new F1 driver", "Sky Sports", False),
            ("Red Bull reportedly considering driver change", "Sky Sports", False),
            ("Premier League club signs new coach", "Sky Sports", False),
            ("WEC: Alpine on pole at Fuji after rain leads to qualifying cancellation", "FIA", False),
            ("普通篮球比赛结果", "中国新闻网", False),
        )
        for title, source, expected in cases:
            with self.subTest(title=title):
                item = news_data.NewsItem(title, source, None,
                                          "https://example.com/story", "")
                self.assertEqual(news_data.classify_news(item) is not None, expected)

    def test_parse_filter_and_summary(self):
        items = news_data._parse_feed(RSS, SOURCE)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].url, "https://example.com/f1/max")
        self.assertEqual(items[0].summary, "Red Bull arrives in Austin.")
        self.assertEqual(items[0].published_utc,
                         datetime(2026, 10, 23, 12, tzinfo=timezone.utc))
        selected = news_data.filter_news(items)
        self.assertEqual(len(selected), 1)
        self.assertIn("Red Bull", news_data.summarize_news(tuple(selected)))

    def test_partial_feed_failure(self):
        other = news_data.NewsSource("Other", "https://other.com/rss", "other.com")
        def fake_fetch(source, timeout):
            if source == other:
                raise news_data.NewsError("unavailable")
            return news_data._parse_feed(RSS, SOURCE)
        with patch.object(news_data, "_fetch_source", side_effect=fake_fetch):
            self.assertEqual(len(news_data.fetch_news((SOURCE, other))), 1)
        with patch.object(news_data, "_fetch_source", side_effect=news_data.NewsError("offline")):
            with self.assertRaises(news_data.NewsError):
                news_data.fetch_news((SOURCE, other))


if __name__ == "__main__":
    unittest.main()
