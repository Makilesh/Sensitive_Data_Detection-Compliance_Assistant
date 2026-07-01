"""Phase 5 tests: deterministic Low/Medium/High classification + breakdown."""

from __future__ import annotations

from src.classification.risk import classify_risk
from src.models import EntityType, Finding, RiskLevel


def _f(entity: EntityType) -> Finding:
    return Finding(entity, "***", "raw", 0, 3, "regex", 1.0)


def test_empty_is_low() -> None:
    report = classify_risk([], page_count=1)
    assert report.level is RiskLevel.LOW
    assert report.score == 0.0
    assert "No sensitive data" in report.summary


def test_low_risk_single_email() -> None:
    report = classify_risk([_f(EntityType.EMAIL)], page_count=1)
    assert report.level is RiskLevel.LOW  # weight 4 < 10


def test_medium_risk_single_aadhaar() -> None:
    report = classify_risk([_f(EntityType.AADHAAR)], page_count=1)
    assert report.level is RiskLevel.MEDIUM  # weight 10 == medium threshold


def test_high_risk_multiple_criticals() -> None:
    findings = [
        _f(EntityType.AADHAAR),
        _f(EntityType.CREDIT_CARD),
        _f(EntityType.API_KEY),
    ]
    report = classify_risk(findings, page_count=1)
    assert report.level is RiskLevel.HIGH  # 30 >= high threshold


def test_contributors_sorted_and_top_is_highest() -> None:
    findings = [
        _f(EntityType.EMAIL),
        _f(EntityType.EMAIL),
        _f(EntityType.CREDIT_CARD),
    ]
    report = classify_risk(findings, page_count=1)
    assert report.contributors[0].entity_type is EntityType.CREDIT_CARD
    contribs = [c.contribution for c in report.contributors]
    assert contribs == sorted(contribs, reverse=True)


def test_density_factor_bumps_dense_documents() -> None:
    # 6 emails on a single page → concentration 6 → factor 1.3.
    findings = [_f(EntityType.EMAIL) for _ in range(6)]
    dense = classify_risk(findings, page_count=1)
    spread = classify_risk(findings, page_count=10)
    assert dense.score > spread.score
