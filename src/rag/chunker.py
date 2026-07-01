"""Sentence-aware chunking that carries page/line metadata and masks PII.

Splits a document into overlapping, retrieval-sized chunks. Each chunk's text is
redacted (via the masker) before it leaves this module, so raw sensitive values
never reach the embeddings or the vector store. Page/line metadata is preserved
from the source segments to support citations.
"""

from __future__ import annotations

import re

from src.config import Settings, get_settings
from src.llm.gemini_client import estimate_tokens
from src.models import Chunk, Document, Finding, Segment
from src.redaction.masker import redact_text

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _sentence_units(segments: list[Segment]) -> list[Segment]:
    """Break segments into sentence-level units, preserving page/line + offsets."""
    units: list[Segment] = []
    for seg in segments:
        if not seg.text.strip():
            continue
        cursor = 0
        for sentence in _SENTENCE_SPLIT.split(seg.text):
            if not sentence:
                continue
            local = seg.text.find(sentence, cursor)
            if local < 0:
                local = cursor
            units.append(
                Segment(
                    text=sentence,
                    page=seg.page,
                    line=seg.line,
                    column=seg.column,
                    char_offset=seg.char_offset + local,
                )
            )
            cursor = local + len(sentence)
    return units


def chunk_document(
    document: Document,
    findings: list[Finding],
    settings: Settings | None = None,
) -> list[Chunk]:
    """Split ``document`` into masked, metadata-carrying chunks."""
    settings = settings or get_settings()
    units = _sentence_units(document.segments)
    if not units:
        return []

    target = settings.chunk_size_tokens
    chunks: list[Chunk] = []
    i = 0
    n = len(units)
    while i < n:
        group: list[Segment] = []
        tokens = 0
        j = i
        while j < n and (tokens < target or not group):
            group.append(units[j])
            tokens += estimate_tokens(units[j].text)
            j += 1
        chunk = _build_chunk(len(chunks), group, findings)
        if chunk is not None:
            chunks.append(chunk)
        if j >= n:
            break
        # ~overlap_ratio of the group carried into the next chunk (≥1 sentence).
        overlap = max(1, round(len(group) * settings.chunk_overlap_ratio))
        i = max(i + 1, j - overlap)
    return chunks


def _build_chunk(index: int, group: list[Segment], findings: list[Finding]) -> Chunk | None:
    """Assemble one masked chunk from a group of sentence units."""
    if not group:
        return None
    masked_parts = [
        redact_text(unit.text, findings, base_offset=unit.char_offset) for unit in group
    ]
    text = " ".join(part.strip() for part in masked_parts if part.strip())
    if not text:
        return None
    first = group[0]
    return Chunk(chunk_id=f"c{index}", text=text, page=first.page, line=first.line)
