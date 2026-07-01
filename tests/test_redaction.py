"""Phase 8 tests: sanitized TXT/CSV/PDF export leaks no raw values."""

from __future__ import annotations

from pathlib import Path

import fitz

from src.config import Settings
from src.detection.engine import run_detection
from src.detection.patterns import detect_patterns
from src.ingestion.loaders import load_document
from src.models import EntityType, Finding
from src.redaction.export import redact_csv, redact_pdf, redact_txt
from src.redaction.masker import mask_value, replacement_for

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
GOLDEN = (SAMPLES / "golden.txt").read_text(encoding="utf-8")


def _findings(doc):
    return run_detection(doc, enable_ner=False, enable_llm=False, client=None)


def test_txt_redaction_removes_all_raw_values() -> None:
    doc = load_document("golden.txt", GOLDEN.encode("utf-8"))
    findings = _findings(doc)
    redacted = redact_txt(doc, findings, Settings(redaction_style="placeholder"))
    for f in findings:
        assert f.value_raw not in redacted, f"leaked {f.entity_type}"
    assert "[REDACTED:" in redacted


def test_partial_mask_style() -> None:
    f = Finding(EntityType.CREDIT_CARD, "****1111", "4111111111111111", 0, 16, "luhn", 0.99)
    assert replacement_for(f, "mask") == "****1111"
    assert replacement_for(f, "placeholder") == "[REDACTED:CREDIT_CARD]"
    assert mask_value(EntityType.CREDIT_CARD, "4111111111111111").endswith("1111")


def test_csv_redaction_masks_cells() -> None:
    raw = (SAMPLES / "pii_sample.csv").read_bytes()
    doc = load_document("pii_sample.csv", raw)
    findings = _findings(doc)
    out = redact_csv(doc, findings, Settings(redaction_style="placeholder")).decode("utf-8")
    assert "alice@example.com" not in out
    assert "bob@example.com" not in out
    assert "name,email" in out.splitlines()[0]  # header preserved


def test_pdf_redaction_removes_underlying_text() -> None:
    raw = (SAMPLES / "text_sample.pdf").read_bytes()
    doc = load_document("text_sample.pdf", raw)
    findings = detect_patterns(doc.text)
    redacted_bytes = redact_pdf(raw, findings)
    with fitz.open(stream=redacted_bytes, filetype="pdf") as pdf:
        text = "".join(page.get_text("text") for page in pdf)
    assert "john.doe@example.com" not in text
    assert "ABCDE1234F" not in text  # PAN gone too
