"""Fetch, filter, and briefly summarize F1 RSS headlines without scraping articles."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree


from news_models import NewsItem, NewsSource
from news_sources import SOURCES


class NewsError(Exception):
    """No configured news source could be loaded."""


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _TextOnly()
    parser.feed(value)
    return re.sub(r"\s+", " ", unescape(" ".join(parser.parts))).strip()


def _parse_feed(payload: bytes, source: NewsSource) -> list[NewsItem]:
    root = ElementTree.fromstring(payload)
    items: list[NewsItem] = []
    for raw in root.findall(".//item"):
        title = _plain_text(raw.findtext("title") or "")
        link = (raw.findtext("link") or "").strip()
        parsed_link = urlparse(link)
        host = parsed_link.hostname or ""
        if (not title or parsed_link.scheme != "https" or
                not (host == source.article_domain or host.endswith("." + source.article_domain))):
            continue
        published = None
        date_text = raw.findtext("pubDate")
        if date_text:
            try:
                published = parsedate_to_datetime(date_text).astimezone(timezone.utc)
            except (TypeError, ValueError):
                pass
        summary = _plain_text(raw.findtext("description") or "")[:200]
        clean_link = urlunparse(parsed_link._replace(query="", fragment="", path=parsed_link.path.rstrip("/")))
        items.append(NewsItem(title, source.name, published, clean_link, summary,
                              source.credibility))
    return items


class _F1Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current: str | None = None
        self.parts: list[str] = []
        self.items: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href.startswith("/en/latest/article/"):
                self.current = href
                self.parts = []

    def handle_data(self, data):
        if self.current:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current:
            title = _plain_text(" ".join(self.parts))
            if title:
                self.items.append((title, self.current))
            self.current = None


def _parse_f1_page(payload: bytes, source: NewsSource) -> list[NewsItem]:
    parser = _F1Links()
    parser.feed(payload.decode("utf-8", "replace"))
    seen: set[str] = set()
    items = []
    for title, href in parser.items:
        url = urljoin(source.feed_url, href)
        if url not in seen:
            items.append(NewsItem(title, source.name, None, url, "", source.credibility))
            seen.add(url)
    return items


def _fetch_source(source: NewsSource, timeout: float) -> list[NewsItem]:
    request = Request(source.feed_url, headers={
        "User-Agent": "SuperMaxDemo/0.1 RSS reader", "Accept": "application/rss+xml, application/xml, text/xml",
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(1_000_001)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        kind = "超时" if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower() else "网络错误"
        raise NewsError(f"{source.name} {kind}: {exc}") from exc
    if len(payload) > 1_000_000:
        raise NewsError(f"{source.name}: RSS feed too large")
    try:
        items = (_parse_f1_page(payload, source) if source.format == "f1_html"
                 else _parse_feed(payload, source))
    except ElementTree.ParseError as exc:
        raise NewsError(f"{source.name}: invalid RSS XML") from exc
    if not items:
        raise NewsError(f"{source.name}: response contained no usable articles")
    return items


F1_SUBJECT = re.compile(
    r"\b(f1|formula 1|formula one|grand prix|verstappen|red bull|mclaren|ferrari|"
    r"mercedes|aston martin|racing bulls|cadillac|williams|haas|alpine)\b|"
    r"一级方程式|大奖赛|维斯塔潘|红牛车队|法拉利车队|迈凯伦|梅赛德斯|"
    r"威廉姆斯车队|阿斯顿马丁|周冠宇|国际汽联", re.I)
OTHER_SERIES = re.compile(r"\b(WEC|Formula E|WRC|Karting|World Endurance|"
                          r"Rally-Raid|IndyCar)\b|世界耐力锦标赛|世界拉力锦标赛", re.I)
SPECULATION = re.compile(r"\b(rumou?r|reportedly|could|may |might |linked with|"
                         r"expected to|set to|potential|analysis|preview|reacts?|backs|"
                         r"explains|why )\b|传闻|或将|据悉|可能|分析|前瞻|回应", re.I)
EVENTS = (
    ("fia_decision", re.compile(r"\b(penalt\w*|sanction\w*|disqualif\w*|stewards?|decision|"
                                 r"ruling|infringement|appeal|fine[ds]?|ban[ned]*)\b|"
                                 r"处罚|罚款|裁决|调查|禁赛|取消资格|判罚", re.I)),
    ("rules_calendar", re.compile(r"\b(regulation\w*|rule change|calendar|schedule|"
                                   r"postpon\w*|cancel\w*|new grand prix|agreement)\b|"
                                   r"规则|赛历|延期|停办|新增分站|协议", re.I)),
    ("major_verstappen", re.compile(r"\b(verstappen).*\b(wins? (?:the )?(?:title|"
                                     r"championship|24 hours)|world champion)\b|"
                                     r"维斯塔潘.*(?:夺冠|冠军|赢得耐力赛)", re.I)),
    ("driver_team", re.compile(r"\b(signs?|signed|re-sign\w*|contract|join[s]?|depart[s]?|"
                                r"leav(?:e|es|ing)|appoint\w*|confirm\w*|announc\w*|extends?)\b|"
                                r"官宣|签约|加盟|离队|续约|确认|任命|宣布", re.I)),
)


def classify_news(item: NewsItem) -> str | None:
    """Conservative event type; a media headline never becomes official confirmation."""
    if OTHER_SERIES.search(item.title) and not re.search(r"verstappen|维斯塔潘", item.title, re.I):
        return None
    if SPECULATION.search(item.title):
        return None
    if item.source != "Formula 1" and not F1_SUBJECT.search(item.title + " " + item.summary):
        return None
    for event_type, pattern in EVENTS:
        if pattern.search(item.title):
            return event_type
    return None


def filter_news(items: list[NewsItem]) -> list[NewsItem]:
    return [item for item in items if classify_news(item) is not None]


def fetch_news(sources: tuple[NewsSource, ...] = SOURCES, timeout: float = 6.0,
               limit: int = 12) -> tuple[NewsItem, ...]:
    """Fetch configured RSS feeds concurrently; tolerate an individual source failure."""
    if timeout <= 0 or limit <= 0:
        raise ValueError("timeout and limit must be positive")
    if not sources:
        raise ValueError("at least one news source is required")
    all_items: list[NewsItem] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=min(len(sources), 3)) as pool:
        futures = {pool.submit(_fetch_source, source, min(timeout, source.timeout_seconds)): source
                   for source in sources}
        for future in as_completed(futures):
            try:
                all_items.extend(future.result())
            except NewsError as exc:
                failures.append(str(exc))
    if failures and len(failures) == len(sources):
        raise NewsError("所有新闻源均不可用：" + "; ".join(failures))
    seen: set[str] = set()
    selected = []
    for item in sorted(filter_news(all_items),
                       key=lambda entry: entry.published_utc or datetime.min.replace(
                           tzinfo=timezone.utc), reverse=True):
        if item.url not in seen:
            selected.append(item)
            seen.add(item.url)
        if len(selected) >= limit:
            break
    return tuple(selected)


def summarize_news(items: tuple[NewsItem, ...]) -> str:
    """Replaceable summarization hook; currently uses headlines only, without an AI model."""
    if not items:
        return "暂无符合关键词的新闻。"
    return "规则速览：" + "；".join(item.title for item in items[:2])
