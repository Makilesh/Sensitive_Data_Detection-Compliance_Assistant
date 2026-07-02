"""End-to-end coverage over the manual sample documents (all 9 categories).

Runs deterministic detection (no network) on the realistic sample files and
asserts each category is caught, decoys are rejected, and redaction leaks nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import Settings
from src.detection.engine import run_detection, summarize_counts
from src.detection.patterns import detect_patterns
from src.ingestion.loaders import load_document
from src.redaction.export import redact_txt

SAMPLES = Path(__file__).resolve().parents[1] / "test_data" / "manual_samples"
pytestmark = pytest.mark.skipif(not SAMPLES.exists(), reason="manual_samples not present")


def _detect(filename: str):
    doc = load_document(filename, (SAMPLES / filename).read_bytes())
    return doc, run_detection(doc, None, enable_llm=False)  # deterministic + NER


def _types(findings) -> set[str]:
    return {f.entity_type.value for f in findings}


def _raw(findings) -> set[str]:
    return {f.value_raw for f in findings}


def test_01_aadhaar_kyc() -> None:
    doc, f = _detect("01_aadhaar_kyc.txt")
    assert {"AADHAAR", "EMPLOYEE_ID", "DOB", "PERSON"} <= _types(f)
    assert "234567890124" in _raw(f)  # valid Aadhaar
    assert "234567890125" not in _raw(f)  # invalid-checksum decoy rejected
    assert "15 August 1985" in _raw(f)  # written-form DOB
    red = redact_txt(doc, f, Settings(redaction_style="placeholder"))
    assert "234567890124" not in red and "Rajesh" not in red


def test_02_pan_written_dob_and_lowercase() -> None:
    _, f = _detect("02_pan_verification.txt")
    assert "PAN" in _types(f) and "DOB" in _types(f)
    assert "ABCDE1234F" in _raw(f) and "abcde1234f" in _raw(f)  # case-insensitive
    assert "04 November 1990" in _raw(f)


def test_03_emails_and_phones_with_decoys() -> None:
    _, f = _detect("03_client_emails.txt")
    assert "EMAIL" in _types(f) and "PHONE" in _types(f)
    assert "priya.sharma@example.com" in _raw(f)
    # No-TLD decoys must not match.
    assert "admin@localdomain" not in _raw(f) and "mailer@localdomain" not in _raw(f)


def test_04_bank_details() -> None:
    _, f = _detect("04_bank_statement.txt")
    assert {"BANK_ACCOUNT", "IFSC", "PHONE", "EMAIL"} <= _types(f)
    assert "123456789012" in _raw(f)
    assert "hdfc0001234" in _raw(f)  # lowercase IFSC


def test_05_credit_card_valid_only() -> None:
    doc, f = _detect("05_payment_invoice.txt")
    assert "CREDIT_CARD" in _types(f)
    cards = {r.replace("-", "") for r in _raw(f) if r.startswith("4111")}
    assert "4111111111111111" in cards  # valid Luhn
    assert "4111111111111112" not in cards  # invalid-checksum decoy


def test_06_api_keys_and_password() -> None:
    _, f = _detect("06_database_config.txt")
    assert "PASSWORD" in _types(f)
    detectors = {x.detector for x in f if x.entity_type.value == "API_KEY"}
    assert {"aws-key", "github-token", "jwt", "openai-key"} <= detectors  # incl sk-proj


def test_07_employee_id_lowercase() -> None:
    _, f = _detect("07_payroll_slip.txt")
    ids = _raw([x for x in f if x.entity_type.value == "EMPLOYEE_ID"])
    assert "EMP12345" in ids and "emp12345" in ids  # both cases


def test_09_csv_all_categories_and_decoys() -> None:
    _, f = _detect("09_customer_table.csv")
    counts = summarize_counts(f)
    assert counts.get("EMAIL") == 3
    assert counts.get("PAN") == 2  # INVALIDPAN rejected
    assert counts.get("AADHAAR") == 1  # invalid-checksum decoy rejected
    assert "1234567890" not in _raw(f)  # phone decoy (not 6-9 start)


def test_confidential_info_is_llm_only() -> None:
    # The NDA's confidential info is contextual → deterministic pass finds none;
    # the LLM pass (network) handles it. This guards the deterministic contract.
    text = (SAMPLES / "08_nda_agreement.txt").read_text(encoding="utf-8")
    assert not any(x.entity_type.value == "CONFIDENTIAL_INFO" for x in detect_patterns(text))
