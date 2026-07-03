"""Regression tests for bugs found in the end-to-end verification report.

Each test maps to a numbered finding in VERIFICATION_RESULTS.md section 4.
"""

from __future__ import annotations

from src.detection import llm_contextual
from src.detection.engine import _dedupe
from src.detection.patterns import detect_patterns
from src.llm.gemini_client import LLMResult
from src.models import EntityType, Finding


# --- Bug 1: dedup must rank trust before span length --------------------
def test_longer_spacy_span_does_not_evict_deterministic() -> None:
    # A spaCy ORG mis-tagging "email=alice@example.com" (long) overlaps the
    # inner EMAIL regex (short). The deterministic EMAIL must survive.
    email = Finding(EntityType.EMAIL, "***", "alice@example.com", 6, 23, "regex", 0.95)
    org = Finding(EntityType.ORG, "***", "email=alice@example.com", 0, 23, "spacy", 0.6)
    kept = _dedupe([org, email])
    types = {f.entity_type for f in kept}
    assert EntityType.EMAIL in types
    assert EntityType.ORG not in types  # longer but lower-trust → dropped


def test_equal_rank_overlap_still_prefers_longer_span() -> None:
    # CREDIT_CARD vs a coincidental inner AADHAAR (both deterministic checksum
    # detectors, rank 5) → the longer card span still wins.
    card = Finding(EntityType.CREDIT_CARD, "x", "4111 1111 1111 1111", 0, 19, "luhn", 0.99)
    aadhaar = Finding(EntityType.AADHAAR, "y", "4111 1111 1111", 0, 14, "verhoeff", 0.99)
    kept = _dedupe([aadhaar, card])
    assert len(kept) == 1
    assert kept[0].entity_type is EntityType.CREDIT_CARD


# --- Bug 2: multi-line snippet in LLM JSON must not crash the parser -----
def test_parse_findings_tolerates_literal_newlines() -> None:
    payload = '{"findings": [{"snippet": "line one\nline two", "rationale": "nda"}]}'
    parsed = llm_contextual._parse_findings(payload)
    assert len(parsed) == 1
    assert parsed[0]["snippet"] == "line one\nline two"


class _FakeClient:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    @property
    def is_configured(self) -> bool:
        return True

    def generate(self, prompt, *, json_mode=False, max_output_tokens=1024, **kwargs):
        return LLMResult(text=self._payload, model_used="fake", prompt_tokens=1, response_tokens=1)


def test_contextual_detects_multiline_snippet() -> None:
    text = "MUTUAL NON-DISCLOSURE AGREEMENT\nThis agreement is confidential."
    payload = (
        '{"findings": [{"snippet": "MUTUAL NON-DISCLOSURE AGREEMENT\n'
        'This agreement is confidential.", "rationale": "NDA"}]}'
    )
    findings = llm_contextual.detect_contextual(text, _FakeClient(payload))
    assert len(findings) == 1
    assert findings[0].entity_type is EntityType.CONFIDENTIAL_INFO
    assert "\n" in findings[0].value_raw  # multi-line snippet preserved


# --- Bug 3: case-insensitive PAN / IFSC / EMPLOYEE_ID -------------------
def test_lowercase_pan_ifsc_employee_id_detected() -> None:
    text = "pan abcde1234f, ifsc hdfc0001234, id emp12345"
    found = {(f.entity_type.value, f.value_raw.lower()) for f in detect_patterns(text)}
    assert ("PAN", "abcde1234f") in found
    assert ("IFSC", "hdfc0001234") in found
    assert ("EMPLOYEE_ID", "emp12345") in found


# --- Bug 4: quoted password label (JSON/dict style) --------------------
def test_quoted_password_label_detected() -> None:
    text = "credentials = { 'password': 'my-super-secret-password-99' }"
    passwords = [f.value_raw for f in detect_patterns(text) if f.entity_type == EntityType.PASSWORD]
    assert "my-super-secret-password-99" in passwords


def test_empty_quoted_password_still_skipped() -> None:
    text = 'password:   "" (empty)'
    passwords = [f for f in detect_patterns(text) if f.entity_type == EntityType.PASSWORD]
    assert passwords == []  # length >= 4 guard still holds


# --- Bug 5: international phone with country code -----------------------
def test_international_phone_detected() -> None:
    text = "Reach the US office at +1-555-0199 anytime."
    phones = [f.value_raw for f in detect_patterns(text) if f.entity_type == EntityType.PHONE]
    assert any("+1" in p for p in phones)


def test_indian_phone_still_detected() -> None:
    phones = [f.value_raw for f in detect_patterns("Call 9876543210 now.") if f.entity_type == EntityType.PHONE]
    assert "9876543210" in phones
