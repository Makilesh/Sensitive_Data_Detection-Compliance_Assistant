"""Phase 1 smoke tests: config and data models load and are well-formed."""

from __future__ import annotations

from src.config import get_settings
from src.models import (
    Document,
    EntityType,
    Finding,
    QAResult,
    RiskLevel,
    RiskReport,
)


def test_settings_load_with_defaults() -> None:
    settings = get_settings()
    assert settings.model_registry, "model registry must not be empty"
    assert settings.risk_high_threshold > settings.risk_medium_threshold
    assert 0.0 < settings.chunk_overlap_ratio < 1.0


def test_model_registry_priority_order_is_unique() -> None:
    names = [m.name for m in get_settings().model_registry]
    assert len(names) == len(set(names)), "model names must be unique"


def test_severity_weights_cover_all_entity_types() -> None:
    weights = get_settings().severity_weights
    for entity in EntityType:
        assert entity.value in weights, f"missing weight for {entity.value}"


def test_data_models_construct() -> None:
    doc = Document(doc_id="abc", filename="f.txt", file_type="txt", text="hi")
    assert doc.doc_id == "abc"

    finding = Finding(
        entity_type=EntityType.EMAIL,
        value_masked="j***@e***.com",
        value_raw="john@example.com",
        start=0,
        end=16,
        detector="regex",
    )
    assert finding.entity_type is EntityType.EMAIL

    report = RiskReport(level=RiskLevel.LOW, score=0.0)
    assert report.level is RiskLevel.LOW

    qa = QAResult(answer="I don't know", grounded=False)
    assert qa.grounded is False
