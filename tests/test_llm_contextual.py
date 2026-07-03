"""Tests for the LLM contextual pass: truncation-tolerant parse + snippet locate."""

from __future__ import annotations

from src.detection import llm_contextual
from src.detection.llm_contextual import _locate_snippet, _parse_findings
from src.llm.gemini_client import LLMResult
from src.models import EntityType


def test_parse_findings_full_object() -> None:
    raw = '{"findings": [{"snippet": "secret merger", "rationale": "M&A"}]}'
    items = _parse_findings(raw)
    assert len(items) == 1 and items[0]["snippet"] == "secret merger"


def test_parse_findings_salvages_truncated_json() -> None:
    # Array never closed (max-token truncation) — the two complete objects survive.
    raw = (
        '{"findings": [\n'
        '{"snippet": "M&A transaction", "rationale": "deal"},\n'
        '{"snippet": "financial projections", "rationale": "financials"},\n'
        '{"snippet": "trade secre'  # cut off mid-object
    )
    items = _parse_findings(raw)
    assert len(items) == 2
    assert {i["snippet"] for i in items} == {"M&A transaction", "financial projections"}


def test_parse_findings_code_fence() -> None:
    raw = '```json\n{"findings": [{"snippet": "x"}]}\n```'
    assert _parse_findings(raw) == [{"snippet": "x"}]


def test_locate_snippet_exact() -> None:
    text = "The quick brown fox."
    assert _locate_snippet(text, "quick brown") == (4, 15)


def test_locate_snippet_whitespace_tolerant() -> None:
    # Source has a mid-sentence newline; the LLM quotes it with a single space.
    text = "explore a strategic M&A\ntransaction whereby Acme acquires"
    start, end = _locate_snippet(text, "strategic M&A transaction whereby Acme")
    assert start != -1
    assert text[start:end] == "strategic M&A\ntransaction whereby Acme"  # original kept


def test_locate_snippet_absent_is_rejected() -> None:
    assert _locate_snippet("nothing relevant here", "fabricated merger") == (-1, -1)


class _FakeClient:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    @property
    def is_configured(self) -> bool:
        return True

    def generate(self, prompt, *, json_mode=False, max_output_tokens=1024, **kwargs):
        return LLMResult(text=self._payload, model_used="fake", prompt_tokens=1, response_tokens=1)


def test_contextual_recovers_multiline_truncated() -> None:
    text = "The parties will share proprietary financial data and\ntrade secrets openly."
    # Truncated array, snippet quoted with a space where the source has a newline.
    payload = (
        '{"findings": [\n'
        '{"snippet": "proprietary financial data and trade secrets", "rationale": "trade secret"},\n'
        '{"snippet": "cut off'
    )
    findings = llm_contextual.detect_contextual(text, _FakeClient(payload))
    assert len(findings) == 1
    assert findings[0].entity_type is EntityType.CONFIDENTIAL_INFO
    assert "\n" in findings[0].value_raw  # mapped back to the original text
