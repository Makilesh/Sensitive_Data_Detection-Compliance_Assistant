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


class FaissStore:
    """A per-document FAISS index over masked chunks."""

    def __init__(self, doc_id: str, index_dir: str) -> None:
        self._doc_id = doc_id
        self._dir = Path(index_dir)
        self._index: faiss.Index | None = None
        self._chunks: list[Chunk] = []

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

    # --- query -----------------------------------------------------------
    def search(self, query_embedding: np.ndarray, k: int = 5) -> list[tuple[Chunk, float]]:
        """Return up to ``k`` (chunk, score) pairs ranked by cosine similarity."""
        if self._index is None or not self._chunks:
            return []
        query = np.asarray(query_embedding, dtype=np.float32).reshape(1, -1)
        scores, indices = self._index.search(query, min(k, len(self._chunks)))
        results: list[tuple[Chunk, float]] = []
        for idx, score in zip(indices[0], scores[0], strict=False):
            if 0 <= idx < len(self._chunks):
                results.append((self._chunks[idx], float(score)))
        return results
