"""FAISS vector store, built and persisted per document.

Stores masked chunk text plus page/line metadata alongside a FAISS inner-product
index (cosine similarity over normalized vectors). Indexes are persisted to disk
keyed by document hash so re-uploading the same document is instant. Only masked
text is ever written — raw PII never touches disk here.
"""

from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np

from src.models import Chunk
from src.rag.lexical import BM25, reciprocal_rank_fusion, tokenize


class FaissStore:
    """A per-document hybrid store: FAISS dense index + BM25 sparse index."""

    def __init__(self, doc_id: str, index_dir: str) -> None:
        self._doc_id = doc_id
        self._dir = Path(index_dir)
        self._index: faiss.Index | None = None
        self._chunks: list[Chunk] = []
        self._bm25: BM25 | None = None

    def _build_bm25(self) -> None:
        self._bm25 = BM25([tokenize(c.text) for c in self._chunks])

    # --- paths -----------------------------------------------------------
    @property
    def _index_path(self) -> Path:
        return self._dir / f"{self._doc_id}.faiss"

    @property
    def _meta_path(self) -> Path:
        return self._dir / f"{self._doc_id}.json"

    def exists(self) -> bool:
        return self._index_path.exists() and self._meta_path.exists()

    # --- build / persist -------------------------------------------------
    def build(self, chunks: list[Chunk], embeddings: np.ndarray) -> None:
        """Build the index from chunks and their embeddings, then persist."""
        self._chunks = chunks
        dim = embeddings.shape[1] if embeddings.size else 1
        index = faiss.IndexFlatIP(dim)
        if embeddings.size:
            index.add(embeddings)
        self._index = index
        self._build_bm25()
        self._persist()

    def _persist(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self._index_path))
        meta = [
            {"chunk_id": c.chunk_id, "text": c.text, "page": c.page, "line": c.line}
            for c in self._chunks
        ]
        self._meta_path.write_text(json.dumps(meta), encoding="utf-8")

    def load(self) -> None:
        """Load a previously persisted index and its chunk metadata."""
        self._index = faiss.read_index(str(self._index_path))
        meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
        self._chunks = [
            Chunk(chunk_id=m["chunk_id"], text=m["text"], page=m["page"], line=m["line"])
            for m in meta
        ]
        self._build_bm25()  # rebuilt from persisted chunk text (no extra files)

    # --- query -----------------------------------------------------------
    def _dense_ranked(self, query: np.ndarray, pool: int) -> list[tuple[int, float]]:
        """Dense candidates as (chunk_index, cosine) pairs, best first."""
        scores, indices = self._index.search(query, min(pool, len(self._chunks)))
        return [
            (int(i), float(s))
            for i, s in zip(indices[0], scores[0], strict=False)
            if 0 <= i < len(self._chunks)
        ]

    def _cosine(self, idx: int, query: np.ndarray) -> float:
        """Cosine of a chunk against the query (vectors are normalized)."""
        vec = self._index.reconstruct(int(idx))
        return float(np.dot(query.reshape(-1), vec))

    def search(self, query_embedding: np.ndarray, k: int = 5) -> list[tuple[Chunk, float]]:
        """Dense-only search: up to ``k`` (chunk, cosine) pairs, best first."""
        if self._index is None or not self._chunks:
            return []
        query = np.asarray(query_embedding, dtype=np.float32).reshape(1, -1)
        return [(self._chunks[i], s) for i, s in self._dense_ranked(query, k)]

    def search_hybrid(
        self,
        query_text: str,
        query_embedding: np.ndarray,
        k: int = 5,
        pool: int = 20,
        rrf_k: int = 60,
    ) -> list[tuple[Chunk, float]]:
        """Fuse dense + BM25 candidates via RRF; score is the dense cosine.

        Ordering reflects the RRF fusion (improved recall for exact-term queries),
        while the returned score stays the absolute cosine so the caller's
        grounding/refusal threshold keeps its meaning.
        """
        if self._index is None or not self._chunks:
            return []
        query = np.asarray(query_embedding, dtype=np.float32).reshape(1, -1)

        dense = self._dense_ranked(query, pool)
        dense_order = [i for i, _ in dense]

        lex_order: list[int] = []
        if self._bm25 is not None:
            lex_scores = self._bm25.scores(tokenize(query_text))
            ranked = sorted(range(len(lex_scores)), key=lambda i: lex_scores[i], reverse=True)
            lex_order = [i for i in ranked if lex_scores[i] > 0][:pool]

        fused = reciprocal_rank_fusion([dense_order, lex_order], rrf_k)[:k]
        dense_lookup = dict(dense)
        return [
            (self._chunks[i], dense_lookup.get(i) if i in dense_lookup else self._cosine(i, query))
            for i in fused
        ]
