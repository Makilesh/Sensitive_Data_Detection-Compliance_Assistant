"""Shared data contracts used across every layer.

These are the small, stable interfaces that ingestion, detection, classification,
RAG, and the UI depend on — never on each other's internals. Keeping them here
enforces loose coupling and a single vocabulary for detectors, findings, and
reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EntityType(StrEnum):
    """Canonical sensitive-entity vocabulary used everywhere."""

    AADHAAR = "AADHAAR"
    PAN = "PAN"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    CREDIT_CARD = "CREDIT_CARD"
    BANK_ACCOUNT = "BANK_ACCOUNT"
    IFSC = "IFSC"
    API_KEY = "API_KEY"
    PASSWORD = "PASSWORD"
    EMPLOYEE_ID = "EMPLOYEE_ID"
    CONFIDENTIAL_INFO = "CONFIDENTIAL_INFO"
    PERSON = "PERSON"
    ORG = "ORG"
    LOCATION = "LOCATION"


class RiskLevel(StrEnum):
    """Overall document risk classification."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


@dataclass
class Segment:
    """A positioned unit of extracted text (a PDF page, a TXT line, a CSV row)."""

    text: str
    page: int | None = None
    line: int | None = None
    column: str | None = None
    char_offset: int = 0  # start offset of this segment within Document.text


@dataclass
class Document:
    """Normalized representation of an uploaded file."""

    doc_id: str  # stable hash of raw bytes
    filename: str
    file_type: str  # "pdf" | "txt" | "csv"
    text: str
    segments: list[Segment] = field(default_factory=list)
    page_count: int = 0
    used_ocr: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass
class Finding:
    """A single detected sensitive item.

    ``value_raw`` is retained in memory for redaction/reveal only and is NEVER
    persisted to logs or the vector store — masked surfaces use ``value_masked``.
    """

    entity_type: EntityType
    value_masked: str
    value_raw: str
    start: int  # char span in Document.text
    end: int
    detector: str  # provenance, e.g. "regex", "verhoeff", "luhn", "spacy", "llm"
    confidence: float = 1.0
    page: int | None = None
    line: int | None = None
    column: str | None = None
    rationale: str | None = None  # for LLM contextual findings


@dataclass
class RiskContributor:
    """One line item explaining what drove the risk score."""

    entity_type: EntityType
    count: int
    weight: int
    contribution: float


@dataclass
class RiskReport:
    """Explainable risk classification result."""

    level: RiskLevel
    score: float
    contributors: list[RiskContributor] = field(default_factory=list)
    summary: str = ""


@dataclass
class Citation:
    """A source pointer backing a Q&A answer."""

    chunk_id: str
    page: int | None
    line: int | None
    snippet: str


@dataclass
class QAResult:
    """Grounded, cited answer to a user question."""

    answer: str
    citations: list[Citation] = field(default_factory=list)
    grounded: bool = True
    model_used: str | None = None
