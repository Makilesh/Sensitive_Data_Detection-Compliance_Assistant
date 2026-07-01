"""Local sentence-transformers embedding wrapper.

Embeddings are computed locally (no Gemini quota consumed for indexing) with a
cached SentenceTransformer. Vectors are L2-normalized so a FAISS inner-product
index yields cosine similarity. The model is loaded lazily on first use.
"""

from __future__ import annotations

import numpy as np

from src.config import get_settings


class LocalEmbedder:
    """Cached wrapper around a SentenceTransformer model."""

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or get_settings().embedding_model
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    @property
    def dimension(self) -> int:
        return int(self._load().get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an (n, dim) float32 array of normalized embeddings."""
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        vectors = self._load().encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


_default_embedder: LocalEmbedder | None = None


def get_embedder() -> LocalEmbedder:
    """Return a process-wide shared embedder (avoids reloading the model)."""
    global _default_embedder
    if _default_embedder is None:
        _default_embedder = LocalEmbedder()
    return _default_embedder
