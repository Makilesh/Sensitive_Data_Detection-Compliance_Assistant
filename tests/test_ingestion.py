"""Phase 2 tests: PDF/TXT/CSV loading, metadata, and OCR fallback trigger."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import Settings
from src.ingestion import loaders, ocr
from src.ingestion.loaders import UnsupportedFileTypeError, load_document

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"


def _read(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


def test_text_pdf_loads_with_page_metadata() -> None:
    doc = load_document("text_sample.pdf", _read("text_sample.pdf"))
    assert doc.file_type == "pdf"
    assert doc.page_count == 2
    assert "john.doe@example.com" in doc.text
    assert all(seg.page is not None for seg in doc.segments)
    assert not doc.used_ocr


def test_txt_loads_with_line_metadata() -> None:
    raw = b"line one\nline two\nline three\n"
    doc = load_document("notes.txt", raw)
    assert doc.file_type == "txt"
    assert doc.segments[0].line == 1
    assert doc.segments[2].text == "line three"


def test_csv_loads_dataframe_and_rows() -> None:
    doc = load_document("pii_sample.csv", _read("pii_sample.csv"))
    assert doc.file_type == "csv"
    assert "dataframe" in doc.metadata
    assert doc.metadata["row_count"] == 2
    assert "alice@example.com" in doc.text
    # header segment + 2 rows
    assert len(doc.segments) == 3


def test_char_offsets_point_into_full_text() -> None:
    doc = load_document("pii_sample.csv", _read("pii_sample.csv"))
    for seg in doc.segments:
        assert doc.text[seg.char_offset : seg.char_offset + len(seg.text)] == seg.text


def test_unsupported_type_raises() -> None:
    with pytest.raises(UnsupportedFileTypeError):
        load_document("archive.zip", b"PK\x03\x04")


def test_ocr_triggers_on_scanned_pdf(monkeypatch) -> None:
    """With OCR enabled, a text-less scanned page must invoke the OCR path."""
    calls: list[int] = []

    def fake_ocr(page, dpi: int = 200) -> str:
        calls.append(1)
        return "SCANNED DOCUMENT scan@example.com EMP12345"

    monkeypatch.setattr(loaders, "ocr_pdf_page", fake_ocr)
    settings = Settings(enable_ocr=True)
    doc = load_document("scanned_sample.pdf", _read("scanned_sample.pdf"), settings)

    assert calls, "OCR should have been invoked on the scanned page"
    assert doc.used_ocr
    assert "scan@example.com" in doc.text


def test_ocr_not_triggered_when_disabled() -> None:
    settings = Settings(enable_ocr=False)
    doc = load_document("scanned_sample.pdf", _read("scanned_sample.pdf"), settings)
    assert not doc.used_ocr


def test_needs_ocr_heuristic() -> None:
    assert ocr.needs_ocr("", 20)
    assert ocr.needs_ocr("   short   ", 20)
    assert not ocr.needs_ocr("x" * 50, 20)
