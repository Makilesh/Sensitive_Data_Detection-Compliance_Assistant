"""Tests for the BM25 sparse retriever and RRF fusion."""

from __future__ import annotations

from src.rag.lexical import BM25, reciprocal_rank_fusion, tokenize


def test_tokenize_lowercases_and_splits() -> None:
    assert tokenize("IFSC: HDFC0001234, email@x.com") == [
        "ifsc",
        "hdfc0001234",
        "email",
        "x",
        "com",
    ]


def test_bm25_ranks_matching_document_highest() -> None:
    corpus = [
        tokenize("bank ifsc code hdfc branch"),
        tokenize("employee salary and leave policy"),
        tokenize("credit card payment details"),
    ]
    bm25 = BM25(corpus)
    scores = bm25.scores(tokenize("ifsc code"))
    assert scores[0] == max(scores)
    assert scores[1] == 0.0  # no overlap


def test_bm25_empty_corpus() -> None:
    assert BM25([]).scores(["anything"]) == []


def test_rrf_merges_and_prefers_consensus() -> None:
    # Doc 2 is high in both lists → should win after fusion.
    fused = reciprocal_rank_fusion([[1, 2, 3], [2, 3, 1]], k=60)
    assert fused[0] == 2
    assert set(fused) == {1, 2, 3}
