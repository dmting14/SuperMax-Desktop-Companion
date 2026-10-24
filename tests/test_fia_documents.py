"""Offline FIA document-list, status and PDF failure checks."""

from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pypdf import PdfWriter
from datetime import datetime, timezone
from fia_documents import (DocumentCandidate, DocumentError, ParsedDocument, document_outcome,
                           extract_pdf_text, parse_document, parse_document_list)
from news_store import NewsRepository


LIST = b'''<ul><li class="document-row key-86"><a href="/system/files/decision-document/test.pdf">
<div class="title">Doc 86 - Decision - Car 44 - Alleged leaving the track</div>
<div class="published">Published on <span>11.10.26 16:02</span> CET</div></a></li>
<li class="document-row key-64"><a href="/system/files/decision-document/summons.pdf">
<div class="title">Doc 64 - Summons - Car 55</div></a></li>
<li class="document-row key-15">Recalled - DOC 15 - Decision - Car 2</li></ul>'''


class FIADocumentTests(unittest.TestCase):
    def test_list_types_metadata_and_recall(self):
        docs = parse_document_list(LIST, "Singapore Grand Prix")
        self.assertEqual(len(docs), 3)
        self.assertEqual(docs[0].number, "86")
        self.assertEqual(docs[0].kind, "decision")
        self.assertEqual(docs[0].published, "Published on 11.10.26 16:02 CET")
        self.assertTrue(docs[0].url.endswith("test.pdf"))
        self.assertEqual(docs[1].kind, "summons")
        self.assertTrue(docs[2].recalled)
        self.assertIsNone(docs[2].url)

    def test_outcomes_are_based_on_pdf_text(self):
        decision = DocumentCandidate("Singapore Grand Prix", "86", "Decision - Car 44", "", "https://www.fia.com/system/files/decision-document/test.pdf", "decision")
        summons = DocumentCandidate("Singapore Grand Prix", "64", "Summons - Car 55", "", decision.url, "summons")
        sample = "No / Driver 44 - Lewis Hamilton\nDecision No further action.\nReason Evidence reviewed."
        self.assertEqual(document_outcome(decision, sample)[:2], ("no_action", "Lewis Hamilton"))
        self.assertEqual(document_outcome(summons, sample)[0], "investigation")
        self.assertEqual(document_outcome(decision, sample.replace("No further action.", "Driver: Warning."))[0], "penalty")
        self.assertEqual(document_outcome(decision, sample.replace("No further action.",
                             "Drop of 20 grid positions in the next Race."))[0], "penalty")
        self.assertEqual(document_outcome(decision, sample.replace("No further action.",
                             "Required to start the Race from the pit lane."))[0], "penalty")
        self.assertEqual(document_outcome(decision, "The allegation is described, but no decision line.")[0], "decision_unknown")
        recalled = DocumentCandidate("Singapore Grand Prix", "15", "Recalled", "", None, "decision", True)
        self.assertEqual(document_outcome(recalled, sample)[0], "withdrawn")

    def test_pdf_extraction_failure_never_invents_penalty(self):
        with self.assertRaises(DocumentError):
            extract_pdf_text(b"not a PDF")
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        output = BytesIO()
        writer.write(output)
        with self.assertRaisesRegex(DocumentError, "no reliably extractable text"):
            extract_pdf_text(output.getvalue())
        candidate = DocumentCandidate("Singapore Grand Prix", "86", "Decision - Penalty", "",
                                      "https://www.fia.com/system/files/decision-document/test.pdf", "decision")
        with self.assertRaises(DocumentError):
            parse_document(candidate, output.getvalue())

    def test_document_version_change_reprocesses_cache(self):
        candidate = DocumentCandidate("Singapore Grand Prix", "85", "Infringement - Car 18",
                                      "11.10.26", "https://www.fia.com/system/files/decision-document/test.pdf",
                                      "infringement")
        first = ParsedDocument(candidate, "hash-a", "text-a", "Document 85 Driver Warning",
                               "penalty", "Lance Stroll", "Driver: Warning.")
        revised = ParsedDocument(candidate, "hash-b", "text-b", "Document 85 No action",
                                 "no_action", "Lance Stroll", "No further action.")
        with tempfile.TemporaryDirectory() as directory:
            repo = NewsRepository(Path(directory) / "news.sqlite3")
            now = datetime(2026, 10, 24, tzinfo=timezone.utc)
            self.assertTrue(repo.save_document(first, now))
            self.assertFalse(repo.save_document(first, now))
            renamed = ParsedDocument(DocumentCandidate(candidate.event, candidate.number,
                                     "Revised infringement - Car 18", "12.10.26", candidate.url,
                                     candidate.kind), first.pdf_hash, first.text_hash, first.text,
                                     first.status, first.driver, first.decision)
            self.assertTrue(repo.save_document(renamed, now))
            self.assertEqual(repo.load()[0].document_date, "12.10.26")
            with repo._connect() as db:
                db.execute("UPDATE fia_documents SET parser_version=1 WHERE document_id=?",
                           (candidate.stable_id,))
            self.assertTrue(repo.save_document(first, now))
            self.assertEqual(repo.load()[0].document_status, "penalty")
            self.assertTrue(repo.save_document(revised, now))
            self.assertEqual(repo.load()[0].document_status, "no_action")
            with repo._connect() as db:
                count = db.execute("SELECT COUNT(*) FROM fia_document_versions").fetchone()[0]
            self.assertEqual(count, 2)

    def test_recalled_document_overrides_old_decision_and_can_be_reinstated(self):
        candidate = DocumentCandidate("Singapore Grand Prix", "85", "Infringement - Car 18",
                                      "11.10.26", "https://www.fia.com/system/files/decision-document/test.pdf",
                                      "infringement")
        recalled = DocumentCandidate(candidate.event, candidate.number, "Recalled - Doc 85",
                                     candidate.published, None, candidate.kind, True)
        parsed = ParsedDocument(candidate, "pdf-a", "text-a", "Decision Driver: Warning.",
                                "penalty", "Lance Stroll", "Driver: Warning.")
        with tempfile.TemporaryDirectory() as directory:
            repo = NewsRepository(Path(directory) / "news.sqlite3")
            now = datetime(2026, 10, 24, tzinfo=timezone.utc)
            self.assertTrue(repo.save_document(parsed, now))
            self.assertTrue(repo.mark_recalled(recalled, "https://www.fia.com/documents/event", now))
            self.assertFalse(repo.mark_recalled(recalled, "https://www.fia.com/documents/event", now))
            self.assertEqual(repo.load()[0].document_status, "withdrawn")
            self.assertEqual(repo.load()[0].summary_status, "unavailable")
            self.assertEqual(repo.load()[0].body, "")
            self.assertTrue(repo.save_document(parsed, now))
            self.assertEqual(repo.load()[0].document_status, "penalty")

    def test_pdf_byte_revision_with_same_text_keeps_ai_cache(self):
        candidate = DocumentCandidate("Singapore Grand Prix", "85", "Infringement - Car 18",
                                      "11.10.26", "https://www.fia.com/system/files/decision-document/test.pdf",
                                      "infringement")
        first = ParsedDocument(candidate, "pdf-a", "same-text", "Decision Driver: Warning.",
                               "penalty", "Lance Stroll", "Driver: Warning.")
        second = ParsedDocument(candidate, "pdf-b", "same-text", first.text,
                                first.status, first.driver, first.decision)
        with tempfile.TemporaryDirectory() as directory:
            repo = NewsRepository(Path(directory) / "news.sqlite3")
            now = datetime(2026, 10, 24, tzinfo=timezone.utc)
            repo.save_document(first, now)
            pending = repo.pending_summaries()[0]
            self.assertTrue(repo.save_summary(pending, "FIA警告", "FIA向Lance Stroll发出警告。",
                                              "test-model", "ready", now))
            repo.save_document(second, now)
            self.assertEqual(repo.load()[0].summary_status, "ready")
            self.assertEqual(repo.pending_summaries(), ())


if __name__ == "__main__":
    unittest.main()
