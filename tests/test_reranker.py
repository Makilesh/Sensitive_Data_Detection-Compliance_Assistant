"""Tests for the optional cross-encoder reranker."""

from __future__ import annotations

from pathlib import Path

from src.config import Settings
from src.detection.engine import run_detection
from src.ingestion.loaders import load_document
from src.models import Chunk
from src.rag import qa
from src.rag.reranker import CrossEncoderReranker

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
GOLDEN = (SAMPLES / "golden.txt").read_text(encoding="utf-8")


def _hits() -> list[tuple[Chunk, float]]:
    return [
        (Chunk(chunk_id="c0", text="unrelated policy text"), 0.40),
        (Chunk(chunk_id="c1", text="the IFSC bank code is here"), 0.35),
        (Chunk(chunk_id="c2", text="some other content"), 0.30),
    ]


class _StubModel:
    """Fake cross-encoder: scores by keyword presence in the chunk text."""

    def predict(self, pairs):
        return [2.0 if "ifsc" in text.lower() else 0.1 for _q, text in pairs]


def test_rerank_reorders_by_relevance() -> None:
    rr = CrossEncoderReranker()
    rr._model = _StubModel()  # bypass real model load
    reranked = rr.rerank("what is the IFSC code?", _hits())
    assert reranked[0][0].chunk_id == "c1"  # keyword chunk floated to the top
    # Scores (cosine) are preserved, not replaced by cross-encoder scores.
    assert reranked[0][1] == 0.35


def test_rerank_degrades_when_model_unavailable() -> None:
    rr = CrossEncoderReranker()
    rr._load_failed = True  # simulate load failure
    hits = _hits()
    assert rr.rerank("q", hits) == hits  # unchanged, no crash


def test_rerank_noop_on_single_hit() -> None:
    rr = CrossEncoderReranker()
    one = _hits()[:1]
    assert rr.rerank("q", one) == one


def test_reranker_enabled_still_refuses_out_of_scope(tmp_path, monkeypatch) -> None:
    doc = load_document("golden.txt", GOLDEN.encode("utf-8"))
    findings = run_detection(doc, enable_ner=False, enable_llm=False, client=None)
    settings = Settings(
        index_dir=str(tmp_path / "idx"), enable_reranker=True, rag_min_score=0.99
    )
    store = qa.build_index(doc, findings, settings=settings)

    # Stub the shared reranker so no heavy model loads during the test.
    from src.rag import reranker

    stub = CrossEncoderReranker()
    stub._model = _StubModel()
    monkeypatch.setattr(reranker, "get_reranker", lambda: stub)

    result = qa.answer_question(
        "What is the tallest mountain on Mars?", doc, findings, None, store, settings=settings
    )
    assert not result.grounded  # refusal contract preserved with reranker on
