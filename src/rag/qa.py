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

    count_answer = _try_counting(question, findings)
    if count_answer is not None:
        return count_answer

    hits = store.search(embedder.embed_one(question), settings.retrieval_top_k)
    strong = [(c, s) for c, s in hits if s >= settings.rag_min_score]
    if not strong:
        return QAResult(answer=_REFUSAL, citations=[], grounded=False)

    citations = [
        Citation(chunk_id=c.chunk_id, page=c.page, line=c.line, snippet=c.text[:200])
        for c, _ in strong
    ]

    if client is None or not client.is_configured:
        # Degrade gracefully: surface the retrieved (masked) context itself.
        joined = "\n".join(f"- {c.text}" for c, _ in strong)
        return QAResult(
            answer=f"(LLM unavailable — most relevant context)\n{joined}",
            citations=citations,
            grounded=True,
            model_used=None,
        )

    context = "\n".join(
        f"[{i + 1}] (page {c.page}, line {c.line}) {c.text}" for i, (c, _) in enumerate(strong)
    )
    try:
        result = client.generate(build_qa_prompt(question, context), max_output_tokens=768)
    except Exception:  # noqa: BLE001 - AllModelsExhausted / SDK errors → degrade
        joined = "\n".join(f"- {c.text}" for c, _ in strong)
        return QAResult(
            answer=f"(LLM unavailable — most relevant context)\n{joined}",
            citations=citations,
            grounded=True,
            model_used=None,
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
