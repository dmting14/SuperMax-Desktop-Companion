"""Extract public Formula 1 article text after headline screening."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from news_models import NewsItem


class ArticleError(Exception):
    pass


class _F1Article(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rich_depth = 0
        self.in_paragraph = False
        self.paragraph_parts: list[str] = []
        self.paragraphs: list[str] = []
        self.in_jsonld = False
        self.jsonld_parts: list[str] = []
        self.metadata: list[dict] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "div" and self.rich_depth:
            self.rich_depth += 1
        elif tag == "div" and "content-rich-text" in attributes.get("class", ""):
            self.rich_depth = 1
        if tag == "p" and self.rich_depth:
            self.in_paragraph = True
            self.paragraph_parts = []
        if tag == "script" and attributes.get("type") == "application/ld+json":
            self.in_jsonld = True
            self.jsonld_parts = []

    def handle_data(self, data):
        if self.in_paragraph:
            self.paragraph_parts.append(data)
        if self.in_jsonld:
            self.jsonld_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self.in_paragraph:
            paragraph = re.sub(r"\s+", " ", unescape(" ".join(self.paragraph_parts))).strip()
            if paragraph:
                self.paragraphs.append(paragraph)
            self.in_paragraph = False
        if tag == "div" and self.rich_depth:
            self.rich_depth -= 1
        if tag == "script" and self.in_jsonld:
            try:
                parsed = json.loads("".join(self.jsonld_parts))
                if isinstance(parsed, dict):
                    self.metadata.append(parsed)
            except ValueError:
                pass
            self.in_jsonld = False


def parse_f1_article(payload: bytes, item: NewsItem) -> NewsItem:
    parser = _F1Article()
    parser.feed(payload.decode("utf-8", "replace"))
    metadata = next((entry for entry in parser.metadata
                     if entry.get("@type") in ("NewsArticle", "Article")), {})
    description = str(metadata.get("description") or "").strip()
    body = "\n".join(parser.paragraphs)[:8000]
    if len(body) < 80 and len(description) < 40:
        raise ArticleError("F1 article has no reliable body or description")
    published = item.published_utc
    date_text = metadata.get("datePublished")
    if date_text:
        try:
            published = datetime.fromisoformat(date_text.replace("Z", "+00:00")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
    return replace(item, body=body or description, summary=description[:200],
                   published_utc=published)


def fetch_f1_article(item: NewsItem, timeout: float = 8) -> NewsItem:
    parsed = urlparse(item.url)
    if parsed.scheme != "https" or parsed.hostname != "www.formula1.com" or not parsed.path.startswith(
            "/en/latest/article/"):
        raise ArticleError("Article URL is outside the public Formula 1 news path")
    try:
        request = Request(item.url, headers={"User-Agent": "SuperMaxDemo/0.3 news reader",
                                             "Accept": "text/html"})
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(1_000_001)
    except Exception as exc:
        raise ArticleError(f"F1 article unavailable: {exc}") from exc
    if len(payload) > 1_000_000:
        raise ArticleError("F1 article page too large")
    return parse_f1_article(payload, item)
