"""Phase 4 tests: checksums, golden-file counts, dedupe, NER, LLM contextual."""

from __future__ import annotations

from pathlib import Path

from src.detection import llm_contextual
from src.detection.engine import run_detection, summarize_counts
from src.detection.ner import detect_ner
from src.detection.patterns import (
    card_network,
    detect_patterns,
    luhn_check,
    verhoeff_check,
)
from src.ingestion.loaders import load_document
from src.models import EntityType, Finding

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
GOLDEN = (SAMPLES / "golden.txt").read_text(encoding="utf-8")

EXPECTED_COUNTS = {
    "EMAIL": 1,
    "PHONE": 1,
    "PAN": 1,
    "AADHAAR": 1,
    "CREDIT_CARD": 1,
    "IFSC": 1,
    "BANK_ACCOUNT": 1,
    "API_KEY": 1,
    "PASSWORD": 1,
    "EMPLOYEE_ID": 1,
}


# --- checksums -----------------------------------------------------------
def test_verhoeff_accepts_valid_and_rejects_invalid() -> None:
    assert verhoeff_check("234567890124")
    assert not verhoeff_check("234567890125")
    assert not verhoeff_check("1234")  # wrong length


def test_luhn_and_network() -> None:
    assert luhn_check("4111111111111111")
    assert not luhn_check("4111111111111112")
    assert card_network("4111111111111111") == "Visa"
    assert card_network("340000000000009") == "Amex"


# --- golden file ---------------------------------------------------------
def test_golden_counts_exact() -> None:
    counts = summarize_counts(detect_patterns(GOLDEN))
    assert counts == EXPECTED_COUNTS


def test_invalid_aadhaar_not_detected() -> None:
    aadhaars = [f.value_raw for f in detect_patterns(GOLDEN) if f.entity_type == EntityType.AADHAAR]
    assert aadhaars == ["234567890124"]  # the invalid one is checksum-rejected


def test_values_are_masked() -> None:
    for f in detect_patterns(GOLDEN):
        assert "*" in f.value_masked or f.entity_type in {EntityType.EMAIL}


# --- dedupe --------------------------------------------------------------
def test_overlapping_spans_prefer_longer_deterministic() -> None:
    from src.detection.engine import _dedupe

    long_det = Finding(EntityType.CREDIT_CARD, "x", "4111 1111 1111 1111", 0, 19, "luhn", 0.99)
    short_llm = Finding(EntityType.AADHAAR, "y", "4111 1111 1111", 0, 14, "llm", 0.7)
    result = _dedupe([long_det, short_llm])
    assert len(result) == 1
    assert result[0].detector == "luhn"


# --- location ------------------------------------------------------------
def test_findings_get_line_metadata() -> None:
    doc = load_document("golden.txt", GOLDEN.encode("utf-8"))
    findings = run_detection(doc, enable_ner=False, enable_llm=False, client=None)
    email = next(f for f in findings if f.entity_type == EntityType.EMAIL)
    assert email.line is not None


# --- NER -----------------------------------------------------------------
def test_ner_detects_person() -> None:
    findings = detect_ner("John Doe works at Acme Corporation in London.")
    types = {f.entity_type for f in findings}
    # spaCy model is installed in this env; expect at least a PERSON or ORG.
    assert types & {EntityType.PERSON, EntityType.ORG, EntityType.LOCATION}


# --- LLM contextual ------------------------------------------------------
class _FakeClient:
    def __init__(self, payload: str, configured: bool = True) -> None:
        self._payload = payload
        self._configured = configured

    @property
    def is_configured(self) -> bool:
        return self._configured

    def generate(self, prompt, *, json_mode=False, max_output_tokens=1024):
        from src.llm.gemini_client import LLMResult

        return LLMResult(text=self._payload, model_used="fake", prompt_tokens=1, response_tokens=1)


def test_contextual_keeps_verified_snippet_drops_hallucination() -> None:
    text = "This agreement contains a strict Non-Disclosure clause."
    payload = (
        '{"findings": ['
        '{"snippet": "Non-Disclosure clause", "rationale": "NDA"},'
        '{"snippet": "made up secret merger", "rationale": "fabricated"}]}'
    )
    findings = llm_contextual.detect_contextual(text, _FakeClient(payload))
    assert len(findings) == 1
    assert findings[0].value_raw == "Non-Disclosure clause"
    assert findings[0].entity_type == EntityType.CONFIDENTIAL_INFO


def test_contextual_skips_when_unconfigured() -> None:
    assert llm_contextual.detect_contextual("text", _FakeClient("{}", configured=False)) == []
    assert llm_contextual.detect_contextual("text", None) == []
