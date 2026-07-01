"""Lexical (sparse) retrieval: in-house BM25 + Reciprocal Rank Fusion.

Complements the dense FAISS index so exact-token queries (field labels like
"IFSC", "employee id", "password") are matched by BM25 while semantic queries are
matched by embeddings. Results from both are merged with Reciprocal Rank Fusion
(RRF), a rank-based combiner that needs no score normalization. Pure standard
library — no extra dependency.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokenization shared by indexing and querying."""
    return _TOKEN.findall(text.lower())


class BM25:
    """Okapi BM25 over a small in-memory corpus of pre-tokenized documents."""

    def __init__(self, corpus_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.n = len(corpus_tokens)
        self.doc_len = [len(doc) for doc in corpus_tokens]
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0
        self.tf = [Counter(doc) for doc in corpus_tokens]

        df: Counter[str] = Counter()
        for doc in corpus_tokens:
            df.update(set(doc))
        self.idf = {
            term: math.log(1 + (self.n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }
        # Inverted index: term -> list of (doc_index, term_frequency).
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, counts in enumerate(self.tf):
            for term, freq in counts.items():
                self.postings[term].append((i, freq))

    def scores(self, query_tokens: list[str]) -> list[float]:
        """Return a BM25 score per document for the query."""
        out = [0.0] * self.n
        if not self.avgdl:
            return out
        for term in set(query_tokens):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, freq in self.postings.get(term, ()):
                denom = freq + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                out[i] += idf * (freq * (self.k1 + 1)) / denom
        return out


def reciprocal_rank_fusion(rank_lists: list[list[int]], k: int = 60) -> list[int]:
    """Fuse several ranked id-lists into one order via RRF (best first)."""
    scores: dict[int, float] = defaultdict(float)
    for ranks in rank_lists:
        for position, idx in enumerate(ranks):
            scores[idx] += 1.0 / (k + position + 1)
    return sorted(scores, key=lambda i: scores[i], reverse=True)
