"""Append-only JSONL audit log — masked and PII-free.

Records every detection run and every Q&A query for traceability. Only
non-sensitive metadata is written: timestamps, the document hash, entity-type
counts (never raw values), risk level, the model used, and latency. User
questions are stored as a short hash + length, never verbatim, since they may
themselves contain sensitive data.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from src.config import Settings, get_settings

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _log_path(settings: Settings | None) -> Path:
    return Path((settings or get_settings()).audit_log_file)


def _append(event: dict, settings: Settings | None = None) -> None:
    """Append one JSON event as a line; best-effort, never raises to the caller."""
    path = _log_path(settings)
    line = json.dumps(event, separators=(",", ":"))
    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except OSError:
        pass


def log_detection(
    doc_id: str,
    counts: dict[str, int],
    risk_level: str,
    model_used: str | None = None,
    latency_ms: float | None = None,
    settings: Settings | None = None,
) -> None:
    """Record a detection run. ``counts`` must be type→int only (no raw values)."""
    _append(
        {
            "ts": _now_iso(),
            "event": "detection",
            "doc_id": doc_id,
            "counts": {str(k): int(v) for k, v in counts.items()},
            "risk_level": risk_level,
            "model_used": model_used,
            "latency_ms": round(latency_ms, 1) if latency_ms is not None else None,
        },
        settings,
    )


def log_query(
    doc_id: str,
    question: str,
    grounded: bool,
    model_used: str | None = None,
    latency_ms: float | None = None,
    settings: Settings | None = None,
) -> None:
    """Record a Q&A query. The question is hashed, never stored verbatim."""
    _append(
        {
            "ts": _now_iso(),
            "event": "query",
            "doc_id": doc_id,
            "question_hash": hashlib.sha256(question.encode("utf-8")).hexdigest()[:12],
            "question_len": len(question),
            "grounded": bool(grounded),
            "model_used": model_used,
            "latency_ms": round(latency_ms, 1) if latency_ms is not None else None,
        },
        settings,
    )


def read_recent(limit: int = 20, settings: Settings | None = None) -> list[dict]:
    """Return the most recent audit events (newest last), up to ``limit``."""
    path = _log_path(settings)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    events: list[dict] = []
    for line in lines[-limit:]:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events
