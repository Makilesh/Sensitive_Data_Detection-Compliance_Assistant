"""Deterministic pattern-based detection: regex + checksum validators.

Structured PII (Aadhaar, PAN, cards, etc.) is detected here — never by the LLM —
so results are exact and reproducible. Checksum validators (Verhoeff for Aadhaar,
Luhn for cards) cut false positives from lookalike digit runs. Every match is
returned as a :class:`Finding` with a character span, provenance, confidence, and
an already-masked value.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from src.config import Settings, get_settings
from src.models import EntityType, Finding
from src.redaction.masker import mask_value

# --------------------------------------------------------------------------
# Checksum validators
# --------------------------------------------------------------------------

# Verhoeff dihedral group tables.
_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_check(number: str) -> bool:
    """Return True if the digit string passes the Verhoeff checksum (Aadhaar)."""
    digits = [c for c in number if c.isdigit()]
    if len(digits) != 12:
        return False
    check = 0
    for i, d in enumerate(reversed([int(x) for x in digits])):
        check = _VERHOEFF_D[check][_VERHOEFF_P[i % 8][d]]
    return check == 0


def luhn_check(number: str) -> bool:
    """Return True if the digit string passes the Luhn checksum (cards)."""
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 12:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def card_network(number: str) -> str:
    """Identify the card network from the leading digits."""
    digits = "".join(c for c in number if c.isdigit())
    if digits.startswith("4"):
        return "Visa"
    if digits[:2] in {"34", "37"}:
        return "Amex"
    if digits[:2] in {str(n) for n in range(51, 56)} or (
        len(digits) >= 4 and 2221 <= int(digits[:4]) <= 2720
    ):
        return "Mastercard"
    if digits[:2] in {"60", "65"} or digits[:4] == "6011":
        return "Discover"
    return "Unknown"


# --------------------------------------------------------------------------
# Pattern registry
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternSpec:
    """One deterministic detector: a compiled regex + optional validator.

    ``group`` selects which regex capture group holds the sensitive value (0 =
    whole match). ``validator`` receives that value and must return True to keep
    the finding. ``confidence`` is the score for a validator-less match; a passing
    validator raises it to ``validated_confidence``.
    """

    entity_type: EntityType
    regex: re.Pattern[str]
    detector: str
    group: int = 0
    validator: Callable[[str], bool] | None = None
    confidence: float = 0.85
    validated_confidence: float = 0.99


def _spec(entity, pattern, detector, **kw) -> PatternSpec:
    flags = kw.pop("flags", 0)
    return PatternSpec(entity, re.compile(pattern, flags), detector, **kw)


PATTERN_SPECS: list[PatternSpec] = [
    _spec(
        EntityType.EMAIL,
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "regex",
        confidence=0.95,
    ),
    _spec(
        EntityType.CREDIT_CARD,
        r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)",
        "luhn",
        validator=luhn_check,
        confidence=0.4,
    ),
    _spec(
        EntityType.AADHAAR,
        r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)",
        "verhoeff",
        validator=verhoeff_check,
        confidence=0.4,
    ),
    # Aadhaar Virtual ID (16-digit), keyed on the VID label to avoid card FPs.
    _spec(
        EntityType.VID,
        r"(?i)\bVID\b\s*[:.]?\s*(\d{4}\s?\d{4}\s?\d{4}\s?\d{4})",
        "vid-keyword",
        group=1,
        confidence=0.9,
    ),
    _spec(
        EntityType.PAN,
        r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
        "regex",
        confidence=0.9,
        flags=re.IGNORECASE,  # PANs may appear lowercase in free text
    ),
    _spec(
        EntityType.IFSC,
        r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
        "regex",
        confidence=0.9,
        flags=re.IGNORECASE,  # IFSCs may appear lowercase in free text
    ),
    _spec(
        EntityType.PHONE,
        r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)",
        "regex",
        confidence=0.85,
    ),
    # International numbers: require a leading + country code to keep FPs low.
    _spec(
        EntityType.PHONE,
        r"(?<!\d)\+\d{1,3}(?:[\s-]?\d){6,12}(?!\d)",
        "intl",
        confidence=0.7,
    ),
    # Date of birth — keyed on a DOB label so issue/other dates are not caught.
    _spec(
        EntityType.DOB,
        r"(?i)(?:DOB|date\s*of\s*birth)\s*[:.]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        "dob-keyword",
        group=1,
        confidence=0.85,
    ),
    _spec(
        EntityType.BANK_ACCOUNT,
        r"(?i)(?:a/c|acc(?:ount)?)\s*(?:no|number|#)?\s*[:.]?\s*(\d{9,18})",
        "keyword-proximity",
        group=1,
        confidence=0.8,
    ),
    # API keys / tokens — provider-specific high-signal patterns.
    _spec(EntityType.API_KEY, r"\bAKIA[0-9A-Z]{16}\b", "aws-key", confidence=0.97),
    _spec(EntityType.API_KEY, r"\bsk-[A-Za-z0-9]{20,}\b", "openai-key", confidence=0.9),
    _spec(EntityType.API_KEY, r"\bghp_[A-Za-z0-9]{36}\b", "github-token", confidence=0.97),
    _spec(
        EntityType.API_KEY,
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
        "jwt",
        confidence=0.9,
    ),
    _spec(
        EntityType.API_KEY,
        r"(?i)(?:api[_-]?key|secret|token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{16,})",
        "assigned-secret",
        group=1,
        confidence=0.75,
    ),
    _spec(
        EntityType.PASSWORD,
        r"(?i)['\"]?password['\"]?\s*[:=]\s*['\"]?([^\s'\"]{4,})",
        "assigned-password",
        group=1,
        confidence=0.8,
    ),
]


def detect_patterns(text: str, settings: Settings | None = None) -> list[Finding]:
    """Run every deterministic pattern over ``text`` and return findings."""
    settings = settings or get_settings()
    findings: list[Finding] = []

    specs = list(PATTERN_SPECS)
    # Employee-ID pattern is config-driven (single source of truth).
    specs.append(
        _spec(EntityType.EMPLOYEE_ID, settings.employee_id_pattern, "regex", confidence=0.85)
    )

    for spec in specs:
        for match in spec.regex.finditer(text):
            value = match.group(spec.group)
            start, end = match.span(spec.group)
            if not value:
                continue
            confidence = spec.confidence
            if spec.validator is not None:
                if not spec.validator(value):
                    continue
                confidence = spec.validated_confidence
            rationale = None
            if spec.entity_type == EntityType.CREDIT_CARD:
                rationale = f"Network: {card_network(value)}"
            findings.append(
                Finding(
                    entity_type=spec.entity_type,
                    value_masked=mask_value(spec.entity_type, value),
                    value_raw=value,
                    start=start,
                    end=end,
                    detector=spec.detector,
                    confidence=confidence,
                    rationale=rationale,
                )
            )
    return findings
