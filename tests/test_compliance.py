"""Phase 7 tests: compliance summary grounding + template fallback."""

from __future__ import annotations

from src.classification.risk import classify_risk
from src.compliance import generate_summary
from src.llm.gemini_client import LLMResult
from src.models import Document, EntityType, Finding


def _doc() -> Document:
    return Document(doc_id="d1", filename="f.txt", file_type="txt", text="x", segments=[])


def _findings() -> list[Finding]:
    return [
        Finding(EntityType.AADHAAR, "***", "234567890124", 0, 12, "verhoeff", 0.99),
        Finding(EntityType.CREDIT_CARD, "***", "4111111111111111", 13, 29, "luhn", 0.99),
        Finding(EntityType.EMAIL, "***", "a@b.com", 30, 37, "regex", 0.95),
    ]


class _FakeClient:
    def __init__(self, text: str, configured: bool = True) -> None:
        self._text, self._configured = text, configured

    @property
    def is_configured(self) -> bool:
        return self._configured

    def generate(self, prompt, *, json_mode=False, max_output_tokens=1024):
        self.captured = prompt
        return LLMResult(text=self._text, model_used="fake", prompt_tokens=1, response_tokens=1)


def test_template_fallback_when_no_llm() -> None:
    findings = _findings()
    risk = classify_risk(findings)
    result = generate_summary(_doc(), findings, risk, client=None)
    assert result.model_used is None  # template fallback, no LLM served this
    assert "Compliance Observations" in result.text
    assert "Security Risks" in result.text
    assert "Recommended Remediation" in result.text
    # References the entity types actually found.
    assert "AADHAAR" in result.text and "CREDIT_CARD" in result.text and "EMAIL" in result.text


def test_template_mentions_relevant_regulations() -> None:
    findings = _findings()
    result = generate_summary(_doc(), findings, classify_risk(findings), client=None)
    assert "PCI-DSS" in result.text  # from credit card
    assert "DPDP" in result.text  # from aadhaar/email


def test_empty_findings_summary() -> None:
    risk = classify_risk([])
    result = generate_summary(_doc(), [], risk, client=None)
    assert "No sensitive data" in result.text


def test_llm_summary_used_when_available() -> None:
    findings = _findings()
    client = _FakeClient("## Compliance Observations\nAll good.")
    result = generate_summary(_doc(), findings, classify_risk(findings), client=client)
    assert result.text.startswith("## Compliance Observations")
    assert result.model_used == "fake"  # reports which model generated it
    # Brief passed to the LLM must be masked (no raw card value).
    assert "4111111111111111" not in client.captured


def test_llm_error_falls_back_to_template() -> None:
    class _Boom(_FakeClient):
        def generate(self, prompt, *, json_mode=False, max_output_tokens=1024):
            raise RuntimeError("boom")

    findings = _findings()
    result = generate_summary(_doc(), findings, classify_risk(findings), client=_Boom(""))
    assert result.model_used is None
    assert "Recommended Remediation" in result.text
