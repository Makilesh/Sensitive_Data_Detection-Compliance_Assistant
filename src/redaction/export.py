"""Sanitized document export in TXT / PDF / CSV.

Builds a shareable copy of a document with every detected sensitive span removed.
Redacted TXT is always available; PDFs use PyMuPDF redaction annotations that
delete the underlying text (not just cover it); CSVs mask the offending cells.
All exporters build on the single ``redact_text`` / ``replacement_for`` primitives
in :mod:`src.redaction.masker`.
"""

from __future__ import annotations

import io

from src.config import Settings, get_settings
from src.models import Document, Finding
from src.redaction.masker import redact_all_occurrences, replacement_for


def _style(settings: Settings | None) -> str:
    return (settings or get_settings()).redaction_style


def redact_txt(document: Document, findings: list[Finding], settings: Settings | None = None) -> str:
    """Return the full document text with every occurrence of each value redacted."""
    return redact_all_occurrences(document.text, findings, style=_style(settings))


def redact_csv(
    document: Document, findings: list[Finding], settings: Settings | None = None
) -> bytes:
    """Return CSV bytes with sensitive cell values masked.

    Uses the retained DataFrame; each cell containing a detected raw value has that
    value replaced by its redaction rendering.
    """
    style = _style(settings)
    df = document.metadata.get("dataframe")
    if df is None:
        return redact_txt(document, findings, settings).encode("utf-8")

    replacements = [(f.value_raw, replacement_for(f, style)) for f in findings if f.value_raw]
    redacted = df.copy()

    def _clean(cell: object) -> object:
        text = str(cell)
        for raw, repl in replacements:
            if raw and raw in text:
                text = text.replace(raw, repl)
        return text

    for col in redacted.columns:
        redacted[col] = redacted[col].map(_clean)

    buffer = io.StringIO()
    redacted.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")


def redact_pdf(raw_bytes: bytes, findings: list[Finding], settings: Settings | None = None) -> bytes:
    """Return PDF bytes with sensitive text redacted via PyMuPDF.

    Redaction annotations remove the underlying glyphs on apply, so redacted values
    are not merely visually covered. Values whose coordinates cannot be located
    (e.g. OCR-only pages) are handled by the always-safe TXT export instead.
    """
    import fitz

    style = _style(settings)
    raw_values = sorted({f.value_raw for f in findings if f.value_raw}, key=len, reverse=True)

    with fitz.open(stream=raw_bytes, filetype="pdf") as pdf:
        for page in pdf:
            for value in raw_values:
                for rect in page.search_for(value):
                    page.add_redact_annot(rect, fill=(0, 0, 0))
            page.apply_redactions()
        out = io.BytesIO()
        pdf.save(out)
    _ = style  # style is reflected in the TXT/CSV exports; PDF uses black boxes
    return out.getvalue()
