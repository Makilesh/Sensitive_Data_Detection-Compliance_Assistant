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
    summary = generate_summary(_doc(), findings, risk, client=None)
    assert "Compliance Observations" in summary
    assert "Security Risks" in summary
    assert "Recommended Remediation" in summary
    # References the entity types actually found.
    assert "AADHAAR" in summary and "CREDIT_CARD" in summary and "EMAIL" in summary


def test_template_mentions_relevant_regulations() -> None:
    findings = _findings()
    summary = generate_summary(_doc(), findings, classify_risk(findings), client=None)
    assert "PCI-DSS" in summary  # from credit card
    assert "DPDP" in summary  # from aadhaar/email


def test_empty_findings_summary() -> None:
    risk = classify_risk([])
    summary = generate_summary(_doc(), [], risk, client=None)
    assert "No sensitive data" in summary


def test_llm_summary_used_when_available() -> None:
    findings = _findings()
    client = _FakeClient("## Compliance Observations\nAll good.")
    summary = generate_summary(_doc(), findings, classify_risk(findings), client=client)
    assert summary.startswith("## Compliance Observations")
    # Brief passed to the LLM must be masked (no raw card value).
    assert "4111111111111111" not in client.captured


def test_llm_error_falls_back_to_template() -> None:
    class _Boom(_FakeClient):
        def generate(self, prompt, *, json_mode=False, max_output_tokens=1024):
            raise RuntimeError("boom")

    findings = _findings()
    summary = generate_summary(_doc(), findings, classify_risk(findings), client=_Boom(""))
    assert "Recommended Remediation" in summary
