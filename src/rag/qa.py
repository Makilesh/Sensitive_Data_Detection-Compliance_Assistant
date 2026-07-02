"""Grounded, cited RAG question answering.

Builds (or loads) a per-document FAISS index over masked chunks and answers
questions with citations. Counting questions ("how many emails?") are answered
from the deterministic detector findings, not the LLM. Free-text questions are
answered by retrieving relevant chunks and asking Gemini to synthesize an answer
grounded strictly in that context; if retrieval is too weak, the assistant refuses
rather than guessing.
"""

from __future__ import annotations

import re

from src.config import Settings, get_settings
from src.detection.engine import summarize_counts
from src.llm.gemini_client import GeminiClient
from src.llm.prompts import build_qa_prompt
from src.models import Citation, Document, EntityType, Finding, QAResult
from src.rag.chunker import chunk_document
from src.rag.embeddings import LocalEmbedder, get_embedder
from src.rag.store import FaissStore

_REFUSAL = "I don't have enough information in this document to answer that."

# Keyword → entity type for counting questions (checked in order; longest first).
_COUNT_KEYWORDS: list[tuple[str, EntityType]] = [
    ("credit card", EntityType.CREDIT_CARD),
    ("api key", EntityType.API_KEY),
    ("employee id", EntityType.EMPLOYEE_ID),
    ("bank account", EntityType.BANK_ACCOUNT),
    ("aadhaar", EntityType.AADHAAR),
    ("password", EntityType.PASSWORD),
    ("email", EntityType.EMAIL),
    ("phone", EntityType.PHONE),
    ("ifsc", EntityType.IFSC),
    ("pan", EntityType.PAN),
]


def build_index(
    document: Document,
    findings: list[Finding],
    embedder: LocalEmbedder | None = None,
    settings: Settings | None = None,
) -> FaissStore:
    """Build or load the FAISS index for ``document`` (keyed by doc hash)."""
    settings = settings or get_settings()
    embedder = embedder or get_embedder()
    store = FaissStore(document.doc_id, settings.index_dir)
    if store.exists():
        store.load()
        return store
    chunks = chunk_document(document, findings, settings)
    embeddings = embedder.embed([c.text for c in chunks])
    store.build(chunks, embeddings)
    return store


def answer_question(
    question: str,
    document: Document,
    findings: list[Finding],
    client: GeminiClient | None,
    store: FaissStore,
    embedder: LocalEmbedder | None = None,
    settings: Settings | None = None,
) -> QAResult:
    """Answer ``question`` about ``document`` with grounding and citations."""
    settings = settings or get_settings()
    embedder = embedder or get_embedder()

    deterministic = _try_counting(question, findings) or _try_inventory(question, findings)
    if deterministic is not None:
        return deterministic

    hits = _retrieve(question, store, embedder, settings)
    strong = [(c, s) for c, s in hits if s >= settings.rag_min_score]
    if strong:
        return _answer_from(question, strong, client, settings)
    # Small-document fallback: if retrieval returned the whole document (few
    # chunks) but nothing cleared the similarity floor, let the LLM answer from the
    # full (masked) content instead of wrongly refusing a valid question about it.
    # Only when an LLM is available to judge relevance (it refuses out-of-scope via
    # the QA prompt); without one, the cosine floor is the only refusal signal.
    small_doc = hits and store.chunk_count <= settings.retrieval_top_k
    if small_doc and client is not None and client.is_configured:
        return _answer_from(question, hits, client, settings)
    return QAResult(answer=_REFUSAL, citations=[], grounded=False)


def _retrieve(question, store, embedder, settings):
    """Retrieve hits from one store: hybrid fusion, then optional reranking."""
    query_vec = embedder.embed_one(question)
    # When reranking, pull a larger pool first, then let the cross-encoder pick.
    top_k = settings.rerank_pool if settings.enable_reranker else settings.retrieval_top_k

    if settings.enable_hybrid_search:
        hits = store.search_hybrid(
            question, query_vec, top_k, settings.retrieval_pool, settings.rrf_k
        )
    else:
        hits = store.search(query_vec, top_k)

    if settings.enable_reranker:
        from src.rag.reranker import get_reranker

        hits = get_reranker().rerank(question, hits)[: settings.retrieval_top_k]
    return hits


def answer_corpus(
    question: str,
    findings_all: list[Finding],
    client: GeminiClient | None,
    stores: list[FaissStore],
    embedder: LocalEmbedder | None = None,
    settings: Settings | None = None,
) -> QAResult:
    """Answer a question across multiple documents by merging their retrievals."""
    settings = settings or get_settings()
    embedder = embedder or get_embedder()

    deterministic = _try_counting(question, findings_all) or _try_inventory(question, findings_all)
    if deterministic is not None:
        return deterministic

    merged: list[tuple] = []
    for store in stores:
        merged.extend(_retrieve(question, store, embedder, settings))
    merged.sort(key=lambda cs: cs[1], reverse=True)
    strong = [(c, s) for c, s in merged if s >= settings.rag_min_score]
    if not strong:
        return QAResult(answer=_REFUSAL, citations=[], grounded=False)
    return _answer_from(question, strong[: settings.retrieval_top_k], client, settings)


def _answer_from(question, chosen, client, settings) -> QAResult:
    """Synthesize a grounded, cited answer from the chosen (chunk, score) hits."""
    citations = [
        Citation(chunk_id=c.chunk_id, page=c.page, line=c.line, snippet=c.text[:200])
        for c, _ in chosen
    ]

    if client is None or not client.is_configured:
        joined = "\n".join(f"- {c.text}" for c, _ in chosen)
        return QAResult(
            answer=f"(LLM unavailable — most relevant context)\n{joined}",
            citations=citations,
            grounded=True,
        )

    context = "\n".join(
        f"[{i + 1}] (page {c.page}, line {c.line}) {c.text}" for i, (c, _) in enumerate(chosen)
    )
    try:
        result = client.generate(build_qa_prompt(question, context), max_output_tokens=768)
    except Exception:  # noqa: BLE001 - AllModelsExhausted / SDK errors → degrade
        joined = "\n".join(f"- {c.text}" for c, _ in chosen)
        return QAResult(
            answer=f"(LLM unavailable — most relevant context)\n{joined}",
            citations=citations,
            grounded=True,
        )

    grounded = _REFUSAL[:30].lower() not in result.text.lower()
    return QAResult(
        answer=result.text.strip(),
        citations=citations if grounded else [],
        grounded=grounded,
        model_used=result.model_used,
    )


def _try_counting(question: str, findings: list[Finding]) -> QAResult | None:
    """Answer 'how many X' from deterministic findings; None if not a count Q."""
    q = question.lower()
    if not re.search(r"how many|number of|count of", q):
        return None
    counts = summarize_counts(findings)
    for keyword, entity in _COUNT_KEYWORDS:
        if keyword in q:
            n = counts.get(entity.value, 0)
            return QAResult(
                answer=f"There {'is' if n == 1 else 'are'} {n} "
                f"{entity.value.replace('_', ' ').lower()} finding{'' if n == 1 else 's'} "
                "in this document.",
                citations=[],
                grounded=True,
            )
    total = sum(counts.values())
    return QAResult(
        answer=f"There are {total} sensitive-data findings in total across "
        f"{len(counts)} categories.",
        citations=[],
        grounded=True,
    )


def _try_inventory(question: str, findings: list[Finding]) -> QAResult | None:
    """Answer 'what sensitive data exists?' from findings; None if not that Q.

    Handles the assignment's sample question directly and deterministically so it
    never wrongly refuses just because the abstract question doesn't embed well
    against the (masked) document chunks.
    """
    q = question.lower()
    intent = re.search(r"\b(what|which|list|show|any|find)\b", q)
    topic = re.search(
        r"sensitive (data|info|information)|personal (data|info|information)"
        r"|confidential (data|info|information)|\bpii\b",
        q,
    )
    if not (intent and topic):
        return None

    counts = summarize_counts(findings)
    if not counts:
        return QAResult(
            answer="No sensitive data was detected in this document.",
            citations=[],
            grounded=True,
        )
    parts = [
        f"{entity.replace('_', ' ').title()} ({n})"
        for entity, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return QAResult(
        answer="This document contains the following detected sensitive data: "
        + ", ".join(parts)
        + ". (Counts are from deterministic detection; values are masked for privacy.)",
        citations=[],
        grounded=True,
    )
