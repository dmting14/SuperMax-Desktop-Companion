"""Offline checks for selected Formula 1 HTML article bodies."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_articles import ArticleError, parse_f1_article
from news_models import NewsItem


ARTICLE = NewsItem("Team confirms driver", "Formula 1", None,
                   "https://www.formula1.com/en/latest/article/example.123", "",
                   "F1 官方平台报道")
HTML = b'''<p>Store</p><script type="application/ld+json">
{"@type":"NewsArticle","description":"The team confirmed a new Formula 1 driver.",
"datePublished":"2026-10-24T02:00:00Z"}</script>
<div class="content-rich-text"><div><p>The team confirmed a new driver for 2027.</p>
<p>The agreement was announced on Saturday.</p></div></div><p>More news</p>'''


class NewsArticleTests(unittest.TestCase):
    def test_body_date_and_description_exclude_site_navigation(self):
        parsed = parse_f1_article(HTML, ARTICLE)
        self.assertEqual(parsed.published_utc.isoformat(), "2026-10-24T02:00:00+00:00")
        self.assertIn("new driver for 2027", parsed.body)
        self.assertNotIn("Store", parsed.body)
        self.assertNotIn("More news", parsed.body)
        self.assertIn("confirmed", parsed.summary)

    def test_missing_content_fails_without_fabricating_text(self):
        with self.assertRaisesRegex(ArticleError, "no reliable body"):
            parse_f1_article(b"<html><p>Store</p></html>", ARTICLE)


if __name__ == "__main__":
    unittest.main()
