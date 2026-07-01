"""Multi-format document loaders.

Turn an uploaded file (PDF / TXT / CSV) into a normalized :class:`Document` with
per-page / per-line / per-column segments carrying character offsets into the
full text. This is the single ingestion entry point (``load_document``); the UI
and later phases depend only on the resulting ``Document``.
"""

from __future__ import annotations

import hashlib
import io

import fitz  # PyMuPDF
import pandas as pd
from charset_normalizer import from_bytes

from src.config import Settings, get_settings
from src.ingestion.ocr import OcrUnavailableError, needs_ocr, ocr_pdf_page
from src.models import Document, Segment


class UnsupportedFileTypeError(ValueError):
    """Raised when the uploaded file extension is not supported."""


def compute_doc_id(raw_bytes: bytes) -> str:
    """Stable content hash used to key indexes and audit records."""
    return hashlib.sha256(raw_bytes).hexdigest()[:16]


def load_document(
    filename: str,
    raw_bytes: bytes,
    settings: Settings | None = None,
) -> Document:
    """Dispatch on file extension and return a normalized ``Document``."""
    settings = settings or get_settings()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        return _load_pdf(filename, raw_bytes, settings)
    if ext == "txt":
        return _load_txt(filename, raw_bytes)
    if ext == "csv":
        return _load_csv(filename, raw_bytes)
    raise UnsupportedFileTypeError(f"Unsupported file type: {ext!r}")


def _assemble(
    doc_id: str,
    filename: str,
    file_type: str,
    segments: list[Segment],
    *,
    page_count: int = 0,
    used_ocr: bool = False,
    metadata: dict | None = None,
) -> Document:
    """Join segments into full text, fixing up each segment's char offset."""
    parts: list[str] = []
    offset = 0
    for seg in segments:
        seg.char_offset = offset
        parts.append(seg.text)
        offset += len(seg.text) + 1  # +1 for the joining newline
    return Document(
        doc_id=doc_id,
        filename=filename,
        file_type=file_type,
        text="\n".join(parts),
        segments=segments,
        page_count=page_count or len(segments),
        used_ocr=used_ocr,
        metadata=metadata or {},
    )


def _load_pdf(filename: str, raw_bytes: bytes, settings: Settings) -> Document:
    """Extract text page-by-page with PyMuPDF; OCR sparse pages when enabled."""
    segments: list[Segment] = []
    used_ocr = False
    with fitz.open(stream=raw_bytes, filetype="pdf") as pdf:
        page_count = pdf.page_count
        for page_index in range(page_count):
            page = pdf[page_index]
            text = page.get_text("text") or ""
            if settings.enable_ocr and needs_ocr(text, settings.ocr_min_chars_per_page):
                try:
                    ocr_text = ocr_pdf_page(page)
                    if len(ocr_text.strip()) > len(text.strip()):
                        text = ocr_text
                        used_ocr = True
                except OcrUnavailableError:
                    pass  # degrade gracefully: keep whatever native text exists
            segments.append(Segment(text=text, page=page_index + 1))
    return _assemble(
        compute_doc_id(raw_bytes),
        filename,
        "pdf",
        segments,
        page_count=page_count,
        used_ocr=used_ocr,
    )


def _decode_bytes(raw_bytes: bytes) -> str:
    """Decode raw bytes using charset detection, falling back to utf-8."""
    best = from_bytes(raw_bytes).best()
    if best is not None:
        return str(best)
    return raw_bytes.decode("utf-8", errors="replace")


def _load_txt(filename: str, raw_bytes: bytes) -> Document:
    """Decode text with encoding detection; one segment per line."""
    content = _decode_bytes(raw_bytes)
    segments = [
        Segment(text=line, line=i + 1)
        for i, line in enumerate(content.splitlines())
    ]
    if not segments:  # empty file → single empty segment keeps invariants
        segments = [Segment(text="", line=1)]
    return _assemble(compute_doc_id(raw_bytes), filename, "txt", segments)


def _load_csv(filename: str, raw_bytes: bytes) -> Document:
    """Load with pandas; serialize rows to text and retain the DataFrame.

    Each row becomes one segment (``line`` = 1-based row number) serialized as
    ``col=value`` pairs so downstream detection can name the offending column.
    The DataFrame is kept in ``metadata['dataframe']`` for column-level detection.
    """
    text = _decode_bytes(raw_bytes)
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    columns = list(df.columns)

    segments: list[Segment] = [Segment(text=" | ".join(columns), line=1, column="__header__")]
    for row_idx, row in df.iterrows():
        row_text = " | ".join(f"{col}={row[col]}" for col in columns)
        segments.append(Segment(text=row_text, line=int(row_idx) + 2))

    return _assemble(
        compute_doc_id(raw_bytes),
        filename,
        "csv",
        segments,
        metadata={"dataframe": df, "columns": columns, "row_count": len(df)},
    )
