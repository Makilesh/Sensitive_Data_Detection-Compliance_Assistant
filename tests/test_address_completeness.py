"""Regression tests: PIN codes and address house/age numbers must not leak.

A real Aadhaar PDF showed the postal PIN code and the age/house-number sitting
right after "S/O: <father>," surviving redaction while everything else around
them was masked. These tests cover both deterministic fixes.
"""

from __future__ import annotations

from src.detection.engine import _detect_trailing_address_numbers
from src.detection.patterns import detect_patterns
from src.models import EntityType, Finding
from src.redaction.masker import redact_all_occurrences


# --- PIN code: labeled field ---------------------------------------------
def test_pincode_labeled_field_detected() -> None:
    text = "City: Kolkata\nPIN Code: 700016,\nCountry: India"
    pins = [f for f in detect_patterns(text) if f.value_raw == "700016"]
    assert len(pins) == 1
    assert pins[0].entity_type is EntityType.LOCATION
    assert pins[0].detector == "pincode-keyword"


def test_pincode_alt_labels() -> None:
    for text in ["Pincode: 630302", "Pin: 630302", "PIN 630302"]:
        assert any(f.value_raw == "630302" for f in detect_patterns(text)), text


# --- PIN code: "<State> - NNNNNN" line-ending idiom -----------------------
def test_pincode_state_dash_suffix_detected() -> None:
    text = "Address:\nTamil Nadu - 630302\nNext line unrelated"
    hits = [f for f in detect_patterns(text) if f.value_raw == "630302"]
    assert any(f.detector == "pincode-suffix" for f in hits)


def test_pincode_suffix_does_not_match_short_dash_numbers() -> None:
    # Card-style groups and short reference codes must not false-positive.
    text = "Authorization Code: AUTH-8829\nInvoice: INV-2026-4482"
    assert not any(f.detector == "pincode-suffix" for f in detect_patterns(text))


def test_pincode_not_falsely_matched_in_unrelated_text() -> None:
    text = "The population grew by 123456 people this year."  # no PIN/dash context
    assert not any(f.value_raw == "123456" for f in detect_patterns(text))


# --- Address house/age number right after a PERSON name -------------------
def test_address_number_after_latin_name_same_line() -> None:
    findings = [Finding(EntityType.PERSON, "M**u", "Marimuthu", 0, 9, "name-relation", 0.85)]
    text = "Marimuthu, 57, REGUNATHA PURAM EAST,"
    extra = _detect_trailing_address_numbers(text, findings)
    assert len(extra) == 1
    assert extra[0].value_raw == "57"
    assert extra[0].entity_type is EntityType.LOCATION


def test_address_number_after_name_across_newlines() -> None:
    # PDF text extraction often puts each comma-separated field on its own line.
    findings = [Finding(EntityType.PERSON, "M**u", "Marimuthu", 0, 9, "name-relation", 0.85)]
    text = "Marimuthu,\n57,\nREGUNATHA PURAM EAST,"
    extra = _detect_trailing_address_numbers(text, findings)
    assert len(extra) == 1 and extra[0].value_raw == "57"


def test_address_number_after_non_latin_person_name() -> None:
    # Positional, not language-specific: works even when the PERSON finding
    # itself came from the (Tamil-capable) LLM pass, not a Latin-only regex.
    name = "மாரிமுத்து"
    findings = [Finding(EntityType.PERSON, "***", name, 0, len(name), "llm", 0.7)]
    text = f"{name}, 57,\nரெகுநாதபுரம்"
    extra = _detect_trailing_address_numbers(text, findings)
    assert len(extra) == 1 and extra[0].value_raw == "57"


def test_no_address_number_without_trailing_comma() -> None:
    # "John met 12 friends." — a number after a name with no comma-comma
    # bracketing is not an address/age field; must not be flagged.
    findings = [Finding(EntityType.PERSON, "J***", "John", 0, 4, "name-label", 0.85)]
    text = "John met 12 friends."
    assert _detect_trailing_address_numbers(text, findings) == []


# --- End-to-end: nothing leaks in the redacted output ----------------------
def test_end_to_end_no_pin_or_address_number_leak() -> None:
    text = (
        "Name: Rajesh Kumar\n"
        "S/O: Madan Lal Kumar,\n"
        "57,\n"
        "Flat 4B, Sunflower Apartments,\n"
        "City: Kolkata\n"
        "PIN Code: 700016\n"
        "West Bengal - 700016\n"
    )
    from src.detection.names import detect_names

    findings = list(detect_patterns(text)) + detect_names(text)
    findings += _detect_trailing_address_numbers(text, findings)
    redacted = redact_all_occurrences(text, findings, style="placeholder")
    assert "700016" not in redacted
    assert "\n57,\n" not in redacted and ", 57," not in redacted
