"""Detection orchestrator: run all detectors → deduped, located ``Finding[]``.

This is the single entry point the UI and later phases use. It composes the
deterministic pattern detectors, the spaCy NER pass, and the LLM contextual pass,
attaches page/line/column provenance by mapping character spans back to document
segments, and de-duplicates overlapping spans (preferring the longer span, then
the more trustworthy detector). Values are already masked by the individual
detectors.
"""

from __future__ import annotations

from src.config import Settings, get_settings
from src.detection.llm_contextual import detect_contextual
from src.detection.ner import detect_ner
from src.detection.patterns import detect_patterns
from src.llm.gemini_client import GeminiClient
from src.models import Document, Finding, Segment

# Detector trust ranking used to break ties when spans overlap.
_DETECTOR_RANK = {
    "verhoeff": 5,
    "luhn": 5,
    "aws-key": 5,
    "github-token": 5,
    "regex": 4,
    "keyword-proximity": 4,
    "vid-keyword": 4,
    "dob-keyword": 4,
    "openai-key": 4,
    "jwt": 4,
    "assigned-secret": 4,
    "assigned-password": 4,
    "spacy": 2,
    "llm": 1,
}


def run_detection(
    document: Document,
    client: GeminiClient | None = None,
    settings: Settings | None = None,
    *,
    enable_ner: bool | None = None,
    enable_llm: bool | None = None,
) -> list[Finding]:
    """Detect all sensitive entities in ``document`` and return located findings."""
    settings = settings or get_settings()
    use_ner = settings.enable_ner if enable_ner is None else enable_ner
    use_llm = settings.enable_llm_contextual if enable_llm is None else enable_llm

    findings: list[Finding] = detect_patterns(document.text, settings)
    if use_ner:
        findings.extend(_dedupe_ner_by_value(detect_ner(document.text)))
    if use_llm:
        findings.extend(detect_contextual(document.text, client))

    findings = _dedupe(findings)
    _locate(findings, document.segments)
    findings.sort(key=lambda f: (f.start, f.entity_type.value))
    return findings


def _dedupe_ner_by_value(ner_findings: list[Finding]) -> list[Finding]:
    """Collapse repeated NER hits for the same (type, value) to the first one.

    spaCy re-tags the same token wherever it recurs (common in addresses — e.g. a
    town name repeated across an Aadhaar), which floods the findings list and
    inflates the risk score. Keeping one occurrence per distinct value keeps the
    signal without the noise.
    """
    seen: set[tuple[str, str]] = set()
    kept: list[Finding] = []
    for finding in ner_findings:
        key = (finding.entity_type.value, finding.value_raw.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        kept.append(finding)
    return kept


def _rank(finding: Finding) -> int:
    return _DETECTOR_RANK.get(finding.detector, 3)


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """Drop findings whose span overlaps a stronger kept finding.

    Preference order for overlaps: higher detector **trust rank** first, then
    longer span, then higher confidence. Ranking before span length ensures a
    deterministic detector (e.g. an EMAIL/CREDIT_CARD regex) always wins over a
    lower-trust spaCy/LLM span that merely happens to be longer — e.g. spaCy
    tagging ``email=alice@example.com`` as ORG must not evict the inner EMAIL.
    Equal-rank overlaps (e.g. CREDIT_CARD vs AADHAAR) still fall back to the
    longer span, so the card wins over a coincidental inner Aadhaar match.
    """
    ordered = sorted(
        findings,
        key=lambda f: (_rank(f), f.end - f.start, f.confidence),
        reverse=True,
    )
    kept: list[Finding] = []
    for candidate in ordered:
        if any(_overlaps(candidate, k) for k in kept):
            continue
        kept.append(candidate)
    return kept


def _overlaps(a: Finding, b: Finding) -> bool:
    return a.start < b.end and b.start < a.end


def _locate(findings: list[Finding], segments: list[Segment]) -> None:
    """Attach page/line/column to each finding from the containing segment."""
    if not segments:
        return
    ordered = sorted(segments, key=lambda s: s.char_offset)
    for finding in findings:
        seg = _segment_for(finding.start, ordered)
        if seg is not None:
            finding.page = seg.page
            finding.line = seg.line
            finding.column = seg.column


def _segment_for(offset: int, ordered: list[Segment]) -> Segment | None:
    """Return the segment whose char range contains ``offset`` (linear scan)."""
    best: Segment | None = None
    for seg in ordered:
        if seg.char_offset <= offset:
            best = seg
        else:
            break
    return best


def summarize_counts(findings: list[Finding]) -> dict[str, int]:
    """Return a count of findings per entity type (for UI + counting Q&A)."""
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.entity_type.value] = counts.get(f.entity_type.value, 0) + 1
    return counts
