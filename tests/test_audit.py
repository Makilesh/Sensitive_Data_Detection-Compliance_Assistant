"""Phase 9 tests: audit log is populated and contains no raw PII."""

from __future__ import annotations

from src.audit import log_detection, log_query, read_recent
from src.config import Settings


def _settings(tmp_path):
    return Settings(audit_log_file=str(tmp_path / "audit.jsonl"))


def test_detection_event_written(tmp_path) -> None:
    s = _settings(tmp_path)
    log_detection("doc1", {"EMAIL": 2, "AADHAAR": 1}, "High", "gemini-x", 42.5, settings=s)
    events = read_recent(settings=s)
    assert len(events) == 1
    e = events[0]
    assert e["event"] == "detection"
    assert e["counts"] == {"EMAIL": 2, "AADHAAR": 1}
    assert e["risk_level"] == "High"
    assert e["model_used"] == "gemini-x"


def test_query_hashes_question_no_raw_text(tmp_path) -> None:
    s = _settings(tmp_path)
    secret_question = "does john.doe@example.com appear here?"
    log_query("doc1", secret_question, grounded=True, model_used="m", settings=s)
    raw = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "john.doe@example.com" not in raw  # question never stored verbatim
    event = read_recent(settings=s)[0]
    assert event["event"] == "query"
    assert event["grounded"] is True
    assert len(event["question_hash"]) == 12


def test_no_raw_values_in_detection_log(tmp_path) -> None:
    s = _settings(tmp_path)
    log_detection("doc1", {"CREDIT_CARD": 1}, "High", settings=s)
    raw = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "4111" not in raw  # only counts, never values


def test_read_recent_limit_and_order(tmp_path) -> None:
    s = _settings(tmp_path)
    for i in range(5):
        log_detection(f"doc{i}", {"EMAIL": i}, "Low", settings=s)
    recent = read_recent(limit=3, settings=s)
    assert len(recent) == 3
    assert recent[-1]["doc_id"] == "doc4"  # newest last
