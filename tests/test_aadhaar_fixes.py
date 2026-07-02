"""Regression tests for real-Aadhaar handling: VID, DOB, NER noise, inventory Q&A."""

from __future__ import annotations

from src.detection.engine import _dedupe_ner_by_value
from src.detection.patterns import detect_patterns
from src.models import EntityType, Finding
from src.rag.qa import _try_inventory
from src.redaction.masker import mask_value


# --- VID (Aadhaar Virtual ID) -------------------------------------------
def test_vid_detected_and_masked() -> None:
    text = "VID : 9139 1473 3853 4403 issued to the holder."
    vids = [f for f in detect_patterns(text) if f.entity_type == EntityType.VID]
    assert len(vids) == 1
    assert vids[0].value_raw.replace(" ", "") == "9139147338534403"
    assert vids[0].value_masked.endswith("4403") and "*" in vids[0].value_masked


def test_bare_16_digits_without_vid_label_not_vid() -> None:
    # No "VID" label → not classified as VID (avoids card/random-number FPs).
    text = "Reference number 9139 1473 3853 4403 in the ledger."
    assert not any(f.entity_type == EntityType.VID for f in detect_patterns(text))


# --- DOB -----------------------------------------------------------------
def test_dob_detected_and_fully_masked() -> None:
    text = "Name: X\nDOB: 24/02/2005\n"
    dobs = [f for f in detect_patterns(text) if f.entity_type == EntityType.DOB]
    assert len(dobs) == 1
    assert dobs[0].value_masked == "**/**/****"  # no digit of the DOB revealed


def test_non_dob_date_not_captured() -> None:
    # An issue date without a DOB label must not be flagged as DOB.
    text = "Aadhaar no. issued: 16/10/2015"
    assert not any(f.entity_type == EntityType.DOB for f in detect_patterns(text))


def test_dob_mask_hides_all_digits() -> None:
    assert mask_value(EntityType.DOB, "24/02/2005") == "**/**/****"


# --- NER value-level dedup ----------------------------------------------
def test_ner_value_dedup_collapses_repeats() -> None:
    dupes = [
        Finding(EntityType.LOCATION, "T***", "Town", 0, 4, "spacy", 0.6),
        Finding(EntityType.LOCATION, "T***", "town", 40, 44, "spacy", 0.6),  # same value, later
        Finding(EntityType.ORG, "A***", "Acme", 80, 84, "spacy", 0.6),
    ]
    kept = _dedupe_ner_by_value(dupes)
    assert len(kept) == 2  # the repeated "Town/town" collapsed to one


# --- inventory intent ("what sensitive data exists?") -------------------
def _findings() -> list[Finding]:
    return [
        Finding(EntityType.AADHAAR, "***", "234567890124", 0, 12, "verhoeff", 0.99),
        Finding(EntityType.PHONE, "***", "9876543210", 13, 23, "regex", 0.85),
    ]


def test_inventory_answers_what_sensitive_data() -> None:
    result = _try_inventory("What sensitive data exists in the document?", _findings())
    assert result is not None
    assert result.grounded
    assert "Aadhaar (1)" in result.answer and "Phone (1)" in result.answer


def test_inventory_variants_trigger() -> None:
    for q in ["what PII is in here", "list the personal data", "what sensitive information is present"]:
        assert _try_inventory(q, _findings()) is not None


def test_inventory_ignores_unrelated_questions() -> None:
    assert _try_inventory("summarize this document", _findings()) is None
    assert _try_inventory("who is the author?", _findings()) is None


def test_inventory_empty_findings() -> None:
    result = _try_inventory("what sensitive data exists?", [])
    assert result is not None and "No sensitive data" in result.answer
