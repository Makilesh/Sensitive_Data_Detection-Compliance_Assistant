"""Explainable weighted risk classification.

Maps a set of findings to an overall Low / Medium / High risk with a numeric
score and a breakdown of what drove the level. The mapping is fully deterministic
and documented:

    score = (Σ severity_weight[type] × count[type]) × density_factor
    density_factor = 1 + 0.1 × max(0, findings_per_page − 3)

Per-type severity weights and the Medium/High thresholds live in ``config.py`` so
tuning happens in one place.
"""

from __future__ import annotations

from src.config import Settings, get_settings
from src.models import EntityType, Finding, RiskContributor, RiskLevel, RiskReport


def classify_risk(
    findings: list[Finding],
    page_count: int = 1,
    settings: Settings | None = None,
) -> RiskReport:
    """Classify overall document risk from its findings."""
    settings = settings or get_settings()
    weights = settings.severity_weights

    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.entity_type.value] = counts.get(finding.entity_type.value, 0) + 1

    contributors: list[RiskContributor] = []
    base_score = 0.0
    for type_value, count in counts.items():
        weight = int(weights.get(type_value, 1))
        contribution = float(weight * count)
        base_score += contribution
        contributors.append(
            RiskContributor(
                entity_type=EntityType(type_value),
                count=count,
                weight=weight,
                contribution=contribution,
            )
        )

    density_factor = _density_factor(len(findings), page_count)
    score = round(base_score * density_factor, 2)
    level = _level_for(score, settings)
    contributors.sort(key=lambda c: c.contribution, reverse=True)

    return RiskReport(
        level=level,
        score=score,
        contributors=contributors,
        summary=_summarize(level, score, contributors, density_factor),
    )


def _density_factor(total_findings: int, page_count: int) -> float:
    """Mild multiplier that only rewards genuinely dense documents."""
    pages = max(page_count, 1)
    concentration = total_findings / pages
    return 1.0 + 0.1 * max(0.0, concentration - 3.0)


def _level_for(score: float, settings: Settings) -> RiskLevel:
    if score >= settings.risk_high_threshold:
        return RiskLevel.HIGH
    if score >= settings.risk_medium_threshold:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _summarize(
    level: RiskLevel,
    score: float,
    contributors: list[RiskContributor],
    density_factor: float,
) -> str:
    if not contributors:
        return "No sensitive data detected; risk is Low."
    top = ", ".join(
        f"{c.entity_type.value} (×{c.count}, weight {c.weight})" for c in contributors[:3]
    )
    density_note = (
        f" A density factor of {density_factor:.2f} was applied."
        if density_factor > 1.0
        else ""
    )
    return (
        f"{level.value} risk (score {score:.1f}). "
        f"Top contributors: {top}.{density_note}"
    )
