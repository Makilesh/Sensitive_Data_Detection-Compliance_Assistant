"""Phase 6 tests: chunking (masked), FAISS store, and grounded/cited Q&A."""

from __future__ import annotations

from pathlib import Path

from src.config import Settings
from src.detection.engine import run_detection
from src.ingestion.loaders import load_document
from src.llm.gemini_client import LLMResult
from src.rag import qa
from src.rag.chunker import chunk_document
from src.rag.embeddings import get_embedder
from src.rag.store import FaissStore

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"
GOLDEN = (SAMPLES / "golden.txt").read_text(encoding="utf-8")


def _doc():
    return load_document("golden.txt", GOLDEN.encode("utf-8"))


def _findings(doc):
    return run_detection(doc, enable_ner=False, enable_llm=False, client=None)


class _FakeClient:
    def __init__(self, text: str, configured: bool = True) -> None:
        self._text = text
        self._configured = configured
        self.last_prompt = None

    @property
    def is_configured(self) -> bool:
        return self._configured

    def generate(self, prompt, *, json_mode=False, max_output_tokens=1024):
        self.last_prompt = prompt
        return LLMResult(text=self._text, model_used="fake-model", prompt_tokens=1, response_tokens=1)


def test_chunks_are_masked_no_raw_pii() -> None:
    doc = _doc()
    findings = _findings(doc)
    chunks = chunk_document(doc, findings)
    assert chunks
    blob = " ".join(c.text for c in chunks)
    # A raw detected value must not appear in any chunk.
    assert "AKIAIOSFODNN7EXAMPLE" not in blob
    assert "john.doe@example.com" not in blob


def test_counting_question_uses_findings(tmp_path) -> None:
    doc = _doc()
    findings = _findings(doc)
    settings = Settings(index_dir=str(tmp_path / "idx"))
    store = qa.build_index(doc, findings, settings=settings)
    result = qa.answer_question(
        "How many email addresses are present?", doc, findings, None, store, settings=settings
    )
    assert "1 email" in result.answer
    assert result.grounded


def test_out_of_scope_question_refuses(tmp_path) -> None:
    doc = _doc()
    findings = _findings(doc)
    settings = Settings(index_dir=str(tmp_path / "idx"), rag_min_score=0.99)
    store = qa.build_index(doc, findings, settings=settings)
    client = _FakeClient("some answer")
    result = qa.answer_question(
        "What is the capital of France?", doc, findings, client, store, settings=settings
    )
    assert not result.grounded
    assert "don't have enough information" in result.answer.lower()


def test_grounded_answer_has_citations(tmp_path) -> None:
    doc = _doc()
    findings = _findings(doc)
    settings = Settings(index_dir=str(tmp_path / "idx"), rag_min_score=0.0)
    store = qa.build_index(doc, findings, settings=settings)
    client = _FakeClient("The document contains employee and payment records [1].")
    result = qa.answer_question(
        "What kind of document is this?", doc, findings, client, store, settings=settings
    )
    assert result.grounded
    assert result.citations
    assert result.model_used == "fake-model"


def test_hybrid_search_surfaces_exact_term_chunk(tmp_path) -> None:
    doc = _doc()
    findings = _findings(doc)
    # Small chunks so entities land in separate chunks.
    settings = Settings(index_dir=str(tmp_path / "idx"), chunk_size_tokens=12)
    store = qa.build_index(doc, findings, settings=settings)
    embedder = get_embedder()
    hits = store.search_hybrid("IFSC bank code", embedder.embed_one("IFSC bank code"), k=3)
    assert hits, "hybrid search should return candidates"
    assert any("IFSC" in c.text for c, _ in hits), "BM25 should surface the IFSC chunk"


def test_hybrid_out_of_scope_still_refuses(tmp_path) -> None:
    doc = _doc()
    findings = _findings(doc)
    settings = Settings(
        index_dir=str(tmp_path / "idx"), rag_min_score=0.99, enable_hybrid_search=True
    )
    store = qa.build_index(doc, findings, settings=settings)
    result = qa.answer_question(
        "What is the boiling point of helium?", doc, findings, None, store, settings=settings
    )
    assert not result.grounded


def test_corpus_counting_sums_across_documents(tmp_path) -> None:
    doc = _doc()
    findings = _findings(doc)
    settings = Settings(index_dir=str(tmp_path / "idx"))
    store = qa.build_index(doc, findings, settings=settings)
    # Two "documents" worth of findings merged; corpus counting sums them.
    result = qa.answer_corpus(
        "How many emails in total?", findings + findings, None, [store, store], settings=settings
    )
    assert "2 email" in result.answer


def test_index_persists_and_reloads(tmp_path) -> None:
    doc = _doc()
    findings = _findings(doc)
    settings = Settings(index_dir=str(tmp_path / "idx"))
    qa.build_index(doc, findings, settings=settings)
    # A fresh store for the same doc_id should load from disk.
    store2 = FaissStore(doc.doc_id, str(tmp_path / "idx"))
    assert store2.exists()
    store2.load()
    hits = store2.search(get_embedder().embed_one("payment card"), 3)
    assert hits
