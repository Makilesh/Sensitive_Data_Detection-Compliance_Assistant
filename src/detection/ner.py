"""spaCy named-entity pass for PERSON / ORG / LOCATION.

Provides contextual entities (names, organizations, places) that help the risk
model and the confidential-info pass. The spaCy model is loaded lazily and cached;
if it is not installed, detection degrades gracefully to an empty result so the
pipeline never hard-fails.
"""

from __future__ import annotations

from src.models import EntityType, Finding
from src.redaction.masker import mask_value

_MODEL_NAME = "en_core_web_sm"
_LABEL_MAP = {
    "PERSON": EntityType.PERSON,
    "ORG": EntityType.ORG,
    "GPE": EntityType.LOCATION,
    "LOC": EntityType.LOCATION,
}

_nlp = None
_load_failed = False


def _get_nlp():
    """Lazily load and cache the spaCy pipeline; return None if unavailable."""
    global _nlp, _load_failed
    if _nlp is not None or _load_failed:
        return _nlp
    try:
        import spacy

        _nlp = spacy.load(_MODEL_NAME, disable=["lemmatizer"])
    except Exception:  # noqa: BLE001 - model missing or load error → degrade
        _load_failed = True
        _nlp = None
    return _nlp


def detect_ner(text: str, max_chars: int = 100_000) -> list[Finding]:
    """Return PERSON/ORG/LOCATION findings; empty if spaCy is unavailable."""
    nlp = _get_nlp()
    if nlp is None:
        return []

    doc = nlp(text[:max_chars])
    findings: list[Finding] = []
    for ent in doc.ents:
        entity_type = _LABEL_MAP.get(ent.label_)
        if entity_type is None:
            continue
        findings.append(
            Finding(
                entity_type=entity_type,
                value_masked=mask_value(entity_type, ent.text),
                value_raw=ent.text,
                start=ent.start_char,
                end=ent.end_char,
                detector="spacy",
                confidence=0.6,
            )
        )
    return findings
