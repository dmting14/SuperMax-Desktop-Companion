"""Read public FIA F1 steward documents without inferring outcomes from titles."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
import re
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from pypdf import PdfReader


SEASON_DOCUMENTS_URL = ("https://www.fia.com/documents/championships/"
                        "fia-formula-one-world-championship-14/season/season-2026-2072")
DOCUMENT_PARSER_VERSION = 2


class DocumentError(Exception):
    pass


@dataclass(frozen=True)
class DocumentCandidate:
    event: str
    number: str
    title: str
    published: str
    url: str | None
    kind: str
    recalled: bool = False

    @property
    def stable_id(self) -> str:
        return f"2026:{self.event}:{self.number}"


@dataclass(frozen=True)
class ParsedDocument:
    candidate: DocumentCandidate
    pdf_hash: str
    text_hash: str
    text: str
    status: str
    driver: str | None
    decision: str | None


class _DocumentList(HTMLParser):
    def __init__(self, event: str):
        super().__init__()
        self.event = event
        self.in_row = False
        self.section = ""
        self.link: str | None = None
        self.title_parts: list[str] = []
        self.date_parts: list[str] = []
        self.row_parts: list[str] = []
        self.items: list[DocumentCandidate] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "li" and "document-row" in attributes.get("class", ""):
            self.in_row = True
            self.link = None
            self.title_parts = []
            self.date_parts = []
            self.row_parts = []
        if not self.in_row:
            return
        if tag == "a":
            href = attributes.get("href", "")
            if "/decision-document/" in href and href.lower().endswith(".pdf"):
                self.link = urljoin("https://www.fia.com", href)
        if tag == "div":
            css = attributes.get("class", "")
            if "title" in css:
                self.section = "title"
            elif "published" in css:
                self.section = "published"

    def handle_data(self, data):
        if self.in_row:
            self.row_parts.append(data)
            if self.section == "title":
                self.title_parts.append(data)
            elif self.section == "published":
                self.date_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "div":
            self.section = ""
        if tag != "li" or not self.in_row:
            return
        full = " ".join(" ".join(self.row_parts).split())
        title = " ".join(" ".join(self.title_parts).split()) or full
        match = re.search(r"\bDOC(?:UMENT)?\s*(\d+)\b", title, re.I)
        kind_match = re.search(r"\b(Decision|Infringement|Summons)\b", title, re.I)
        if match and kind_match:
            published = " ".join(" ".join(self.date_parts).split())
            self.items.append(DocumentCandidate(self.event, match.group(1), title,
                                                published, self.link,
                                                kind_match.group(1).lower(),
                                                bool(re.search(r"\brecalled\b", full, re.I))))
        self.in_row = False
        self.section = ""


def parse_document_list(payload: bytes, event: str) -> tuple[DocumentCandidate, ...]:
    parser = _DocumentList(event)
    parser.feed(payload.decode("utf-8", "replace"))
    return tuple(parser.items)


def fetch_document_list(url: str = SEASON_DOCUMENTS_URL,
                        event: str = "United States Grand Prix", timeout: float = 9) -> tuple[DocumentCandidate, ...]:
    if urlparse(url).hostname != "www.fia.com" or not url.startswith("https://"):
        raise DocumentError("Only the public FIA document listing is allowed")
    try:
        with urlopen(Request(url, headers={"User-Agent": "SuperMaxDemo/0.3 document reader"}),
                     timeout=timeout) as response:
            payload = response.read(700_001)
    except Exception as exc:
        raise DocumentError(f"FIA document list unavailable: {exc}") from exc
    if len(payload) > 700_000:
        raise DocumentError("FIA document list too large")
    documents = parse_document_list(payload, event)
    if not documents:
        raise DocumentError("FIA document list contained no relevant documents")
    return documents


def download_pdf(url: str, timeout: float = 9) -> bytes:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname != "www.fia.com" or
            "/decision-document/" not in parsed.path or not parsed.path.lower().endswith(".pdf")):
        raise DocumentError("PDF URL is outside the public FIA document path")
    try:
        with urlopen(Request(url, headers={"User-Agent": "SuperMaxDemo/0.3 document reader"}),
                     timeout=timeout) as response:
            payload = response.read(3_000_001)
    except Exception as exc:
        raise DocumentError(f"FIA PDF unavailable: {exc}") from exc
    if len(payload) > 3_000_000 or not payload.startswith(b"%PDF-"):
        raise DocumentError("FIA response is not a supported PDF")
    return payload


def extract_pdf_text(payload: bytes) -> str:
    if not payload.startswith(b"%PDF-"):
        raise DocumentError("Invalid PDF signature")
    try:
        reader = PdfReader(BytesIO(payload))
        if not 1 <= len(reader.pages) <= 10:
            raise DocumentError("Unsupported FIA PDF page count")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError(f"PDF text extraction failed: {exc}") from exc
    text = text.replace("\xa0", " ").replace("\u200b", "").strip()
    if len(text) < 80:
        raise DocumentError("PDF has no reliably extractable text")
    return text[:30_000]


def document_outcome(candidate: DocumentCandidate, text: str) -> tuple[str, str | None, str | None]:
    if candidate.recalled:
        return "withdrawn", None, None
    driver_match = re.search(r"No\s*/\s*Driver\s+\d+\s*-\s*([^\n]+)", text, re.I)
    driver = driver_match.group(1).strip() if driver_match else None
    decision_match = re.search(r"(?im)^\s*Decision\s+([^\n]+)", text)
    decision = decision_match.group(1).strip() if decision_match else None
    if candidate.kind == "summons":
        return "investigation", driver, None
    if not decision:
        return "investigation" if candidate.kind == "infringement" else "decision_unknown", driver, None
    if re.search(r"no further action|no penalty|no investigation necessary", decision, re.I):
        return "no_action", driver, decision
    if re.search(r"penalt|warning|reprimand|fine|disqualif|grid drop|"
                 r"drop of \d+ grid positions|time added|black flag|"
                 r"required to start .* from the pit lane", decision, re.I):
        return "penalty", driver, decision
    return "decision", driver, decision


def parse_document(candidate: DocumentCandidate, payload: bytes) -> ParsedDocument:
    text = extract_pdf_text(payload)
    status, driver, decision = document_outcome(candidate, text)
    return ParsedDocument(candidate, sha256(payload).hexdigest(),
                          sha256(text.encode("utf-8")).hexdigest(), text,
                          status, driver, decision)
