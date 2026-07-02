"""Tests for deterministic name detection + occurrence-complete redaction.

Names must be caught by document structure (labels, relations, salutations,
addressees) so detection generalizes beyond Aadhaar to bank/HR/letter formats,
and redaction must remove every occurrence of a detected value.
"""

from __future__ import annotations

from src.detection.names import detect_names
from src.models import EntityType, Finding
from src.redaction.masker import redact_all_occurrences


def _names(text: str) -> set[str]:
    return {f.value_raw for f in detect_names(text) if f.entity_type == EntityType.PERSON}


def test_labeled_names_across_document_types() -> None:
    text = (
        "Account Holder: Priya Sharma\n"
        "Employee Name: Rahul Verma\n"
        "Customer Name: Sunita Rao\n"
        "Nominee: Arjun Mehta\n"
    )
    assert _names(text) == {"Priya Sharma", "Rahul Verma", "Sunita Rao", "Arjun Mehta"}


def test_relation_prefix_names() -> None:
    assert "Marimuthu" in _names("S/O: Marimuthu, 57, Some Street")
    assert "John Smith" in _names("D/O John Smith")


def test_salutation_names() -> None:
    assert "Anand Krishnan" in _names("Dear Mr. Anand Krishnan, welcome.")
    assert "Latha" in _names("Contact Smt. Latha for details.")


def test_addressee_after_bare_to() -> None:
    assert "Makilesh M" in _names("To\nMakilesh M\nS/O: someone")


def test_addressee_skips_non_latin_line() -> None:
    # Mirrors the Aadhaar: a Tamil name precedes the romanized addressee.
    text = "To\nமகிலேஷ் மா\nMakilesh M\n123 Street"
    assert "Makilesh M" in _names(text)


def test_addressee_inline_to() -> None:
    assert "Jane Doe" in _names("Bill To: Jane Doe")


def test_stoplist_blocks_non_names() -> None:
    # A structure word right after "To" must not be captured as a person.
    assert _names("To\nState of Affairs Report") == set()


# --- occurrence-complete redaction --------------------------------------
def test_redact_all_occurrences_removes_every_hit() -> None:
    text = "Makilesh M lives here. Later, Makilesh M signed. VID 1111 2222."
    findings = [Finding(EntityType.PERSON, "M***", "Makilesh M", 0, 10, "name-addressee", 0.85)]
    out = redact_all_occurrences(text, findings, style="placeholder")
    assert "Makilesh M" not in out
    assert out.count("[REDACTED:PERSON]") == 2  # both occurrences redacted


def test_redaction_boundary_guard_no_substring_overmatch() -> None:
    # "John" must not redact the "John" inside "Johnson".
    text = "John met Johnson."
    findings = [Finding(EntityType.PERSON, "J***", "John", 0, 4, "name-label", 0.85)]
    out = redact_all_occurrences(text, findings, style="placeholder")
    assert "Johnson" in out  # untouched
    assert out.startswith("[REDACTED:PERSON] met")
