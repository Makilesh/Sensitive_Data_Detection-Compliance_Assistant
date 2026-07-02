"""Deterministic person-name detection via document structure.

spaCy NER is unreliable on Indian / multilingual / transliterated names (it
misses "Makilesh M" while mislabelling "Tamil Nadu" as a person). Rather than
depend on a heavier model, this module catches names by the structural cues that
recur across real documents, so it generalizes beyond any single format:

* **field labels** — ``Name:``, ``Account Holder:``, ``Employee Name:`` …
* **relation prefixes** — ``S/O``, ``D/O``, ``W/O``, ``C/O`` (common on Indian IDs)
* **salutations** — ``Mr.``, ``Mrs.``, ``Dr.``, ``Shri``, ``Smt.`` …
* **addressees** — a name on the line(s) after ``To`` / ``Bill To`` / ``Ship To``

Everything here is deterministic (no model), so it is fast and deploy-safe.
"""

from __future__ import annotations

import re

from src.models import EntityType, Finding
from src.redaction.masker import mask_value

# A name: 1–4 capitalized / initial tokens (handles "Makilesh M", "John A Doe").
_NAME = r"[A-Z][A-Za-z.]*(?:[ \t]+[A-Z][A-Za-z.]*){0,3}"

# Capitalized words that are structure/geography, never a person — filtered out
# of the (label-free) addressee capture to avoid over-redaction.
_NOT_A_NAME = {
    "to", "state", "district", "address", "male", "female", "india", "date",
    "details", "enrolment", "enrollment", "mobile", "signature", "identification",
    "authority", "aadhaar", "pin", "code", "sub", "vtc", "po", "dist", "ist",
    "vid", "dob", "digitally", "unique", "nadu", "tamil", "email", "phone",
    "account", "bank", "ifsc", "male/female", "from", "subject", "ref",
}

_LABELED = re.compile(
    r"(?im)^[ \t]*(?:full[ \t]*name|name|holder(?:'s)?[ \t]*name|account[ \t]*holder"
    r"|card[ \t]*holder|customer[ \t]*name|employee[ \t]*name|applicant(?:[ \t]*name)?"
    r"|beneficiary(?:[ \t]*name)?|nominee(?:[ \t]*name)?|father'?s?[ \t]*name"
    r"|mother'?s?[ \t]*name|spouse(?:'s)?[ \t]*name)[ \t]*[:\-][ \t]*(" + _NAME + r")"
)
_RELATION = re.compile(r"(?i)\b(?:s/o|d/o|w/o|c/o)[ \t]*[:\-]?[ \t]*(" + _NAME + r")")
_SALUTATION = re.compile(
    r"\b(?:Mr|Mrs|Ms|Dr|Shri|Smt|Sri|Kum|Miss|Prof)\.?[ \t]+(" + _NAME + r")"
)
_ADDRESSEE_LINE = re.compile(r"(?i)^[ \t]*(?:to|bill[ \t]*to|ship[ \t]*to)[ \t]*[:.]?[ \t]*$")
_ADDRESSEE_INLINE = re.compile(
    r"(?i)^[ \t]*(?:to|bill[ \t]*to|ship[ \t]*to)[ \t]*[:.][ \t]*(" + _NAME + r")[ \t]*,?$"
)


def detect_names(text: str) -> list[Finding]:
    """Return deterministic person-name findings from structural cues."""
    findings: list[Finding] = []
    seen: set[tuple[int, int]] = set()

    def add(value: str, start: int, detector: str) -> None:
        value = value.strip().rstrip(",.;:")
        if len(value) < 2 or value.split()[0].lower() in _NOT_A_NAME:
            return
        span = (start, start + len(value))
        if span in seen:
            return
        seen.add(span)
        findings.append(
            Finding(
                entity_type=EntityType.PERSON,
                value_masked=mask_value(EntityType.PERSON, value),
                value_raw=value,
                start=start,
                end=start + len(value),
                detector=detector,
                confidence=0.85,
            )
        )

    for regex, detector in (
        (_LABELED, "name-label"),
        (_RELATION, "name-relation"),
        (_SALUTATION, "name-salutation"),
    ):
        for m in regex.finditer(text):
            add(m.group(1), m.start(1), detector)

    _detect_addressees(text, add)
    return findings


def _detect_addressees(text: str, add) -> None:
    """Catch the addressee name on/after a ``To`` / ``Bill To`` line."""
    lines = text.split("\n")
    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1

    for i, line in enumerate(lines):
        inline = _ADDRESSEE_INLINE.match(line)
        if inline:
            add(inline.group(1), offsets[i] + inline.start(1), "name-addressee")
            continue
        if not _ADDRESSEE_LINE.match(line):
            continue
        # Bare "To" — take the first Latin-script line within the next few,
        # skipping blank and non-Latin (e.g. Tamil) lines that precede the
        # romanized name on IDs.
        for j in range(i + 1, min(i + 5, len(lines))):
            candidate = lines[j].strip().rstrip(",")
            if not candidate or not re.search(r"[A-Za-z]", candidate):
                continue  # blank or non-Latin → keep looking
            if re.fullmatch(_NAME, candidate) and candidate.split()[0].lower() not in _NOT_A_NAME:
                add(candidate, offsets[j] + lines[j].find(candidate), "name-addressee")
            break  # first Latin line decides; don't run into the address block
