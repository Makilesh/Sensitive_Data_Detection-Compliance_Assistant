"""Masking rules — the single source of truth for how sensitive values are hidden.

``mask_value`` is used at detection time (Phase 4) so raw values never surface by
default, and again for document-level sanitized export (Phase 8). Keeping the
rules here avoids duplicating masking logic across the detection and redaction
layers.
"""

from __future__ import annotations

from src.models import EntityType, Finding

# Entity types that must be fully masked (never reveal any part).
_FULLY_MASKED: frozenset[EntityType] = frozenset(
    {EntityType.API_KEY, EntityType.PASSWORD}
)


def _keep_last(raw: str, keep: int = 4) -> str:
    """Mask everything but the last ``keep`` alphanumeric characters."""
    digits = [c for c in raw if c.isalnum()]
    if len(digits) <= keep:
        return "*" * len(raw)
    visible = "".join(digits[-keep:])
    return f"{'*' * (len(digits) - keep)}{visible}"


def _mask_email(raw: str) -> str:
    if "@" not in raw:
        return "*" * len(raw)
    local, _, domain = raw.partition("@")
    masked_local = (local[0] + "***") if local else "***"
    if "." in domain:
        name, _, tld = domain.rpartition(".")
        masked_domain = f"{(name[0] + '***') if name else '***'}.{tld}"
    else:
        masked_domain = "***"
    return f"{masked_local}@{masked_domain}"


def mask_value(entity_type: EntityType, raw: str) -> str:
    """Return a masked rendering of ``raw`` appropriate to its entity type."""
    if not raw:
        return ""
    if entity_type in _FULLY_MASKED:
        return "********"
    if entity_type == EntityType.EMAIL:
        return _mask_email(raw)
    if entity_type in {
        EntityType.AADHAAR,
        EntityType.CREDIT_CARD,
        EntityType.PHONE,
        EntityType.BANK_ACCOUNT,
        EntityType.PAN,
        EntityType.EMPLOYEE_ID,
        EntityType.IFSC,
    }:
        return _keep_last(raw, keep=4)
    # Names / orgs / locations / confidential snippets: partial mask.
    if len(raw) <= 2:
        return "*" * len(raw)
    return f"{raw[0]}{'*' * (len(raw) - 2)}{raw[-1]}"


def replacement_for(finding: Finding, style: str = "mask") -> str:
    """Return the string that replaces a finding's raw value.

    ``style`` = "mask" → partial masked value (e.g. ``****1234``);
    ``style`` = "placeholder" → ``[REDACTED:TYPE]``.
    """
    if style == "placeholder":
        return f"[REDACTED:{finding.entity_type.value}]"
    return finding.value_masked


def redact_text(
    text: str,
    findings: list[Finding],
    base_offset: int = 0,
    style: str = "mask",
) -> str:
    """Replace each finding's span in ``text`` with its redacted rendering.

    ``base_offset`` is the absolute char offset of ``text`` within the document,
    so a segment can be redacted using document-relative finding spans. Spans are
    applied right-to-left so earlier offsets stay valid. This is the single
    document-level redaction primitive, reused by RAG (P6, "mask") and export
    (P8, configurable style).
    """
    length = len(text)
    spans = sorted(findings, key=lambda f: f.start, reverse=True)
    for finding in spans:
        start = finding.start - base_offset
        end = finding.end - base_offset
        if 0 <= start < end <= length:
            text = text[:start] + replacement_for(finding, style) + text[end:]
    return text
