"""Optional cross-encoder reranker for higher-precision retrieval.

Bi-encoder cosine (dense) and BM25 (sparse) rank candidates cheaply, but on large
documents the top pool can be noisy. A cross-encoder scores each (query, chunk)
pair jointly with cross-attention, which reorders the pool more accurately at the
cost of a heavier model + latency. It is therefore **opt-in** (``enable_reranker``).

Model selection is GPU-aware: on a CUDA machine we load the stronger multilingual
``bge-reranker-v2-m3``; otherwise a lightweight, CPU-friendly MiniLM cross-encoder.
Loading is lazy and cached, and any failure degrades to the unranked hits so the
pipeline never breaks (mirrors ``ner.py``).
"""

from __future__ import annotations

from src.config import Settings, get_settings
from src.models import Chunk


class CrossEncoderReranker:
    """Lazy, cached cross-encoder that reorders retrieval hits by relevance."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._model = None
        self._load_failed = False
        self._model_name: str | None = None

    def _select_model(self) -> str:
        """Pick the GPU or CPU model name based on CUDA availability."""
        if self._settings.reranker_auto_upgrade_gpu:
            try:
                import torch

                if torch.cuda.is_available():
                    return self._settings.reranker_model_gpu
            except Exception:  # noqa: BLE001 - torch missing/broken → CPU model
                pass
        return self._settings.reranker_model

    def _load(self):
        if self._model is not None or self._load_failed:
            return self._model
        try:
            from sentence_transformers import CrossEncoder

            self._model_name = self._select_model()
            self._model = CrossEncoder(self._model_name)
        except Exception:  # noqa: BLE001 - model download/load failure → degrade
            self._load_failed = True
            self._model = None
        return self._model

    @property
    def active_model(self) -> str:
        """The model name that would be (or was) loaded — for UI display."""
        return self._model_name or self._select_model()

    def rerank(
        self, query: str, hits: list[tuple[Chunk, float]]
    ) -> list[tuple[Chunk, float]]:
        """Reorder ``hits`` by cross-encoder relevance, keeping their cosine score.

        The returned tuples preserve each chunk's original dense cosine as the
        score so the caller's grounding/refusal threshold keeps its meaning; only
        the ordering changes. Returns ``hits`` unchanged if the model is
        unavailable or there is nothing to reorder.
        """
        if len(hits) <= 1:
            return hits
        model = self._load()
        if model is None:
            return hits
        pairs = [[query, chunk.text] for chunk, _ in hits]
        try:
            scores = model.predict(pairs)
        except Exception:  # noqa: BLE001 - inference failure → keep original order
            return hits
        order = sorted(range(len(hits)), key=lambda i: float(scores[i]), reverse=True)
        return [hits[i] for i in order]


_default_reranker: CrossEncoderReranker | None = None


def get_reranker() -> CrossEncoderReranker:
    """Return a process-wide shared reranker (avoids reloading the model)."""
    global _default_reranker
    if _default_reranker is None:
        _default_reranker = CrossEncoderReranker()
    return _default_reranker
