"""Tesseract OCR fallback for scanned PDFs / image-only pages.

OCR is a config toggle (``Settings.enable_ocr``) because it requires the native
Tesseract binary to be installed on the host. The trigger heuristic
(``needs_ocr``) is pure and independently testable; the actual OCR call is
isolated in ``ocr_pdf_page`` so ingestion degrades gracefully when Tesseract is
unavailable.
"""

from __future__ import annotations

import io


class OcrUnavailableError(RuntimeError):
    """Raised when OCR is requested but cannot be performed."""


def needs_ocr(extracted_text: str, min_chars: int) -> bool:
    """Return True if a page's extractable text is too sparse to trust.

    A scanned/image-only page typically yields little or no selectable text, so
    when the character count falls below ``min_chars`` we fall back to OCR.
    """
    return len(extracted_text.strip()) < min_chars


def ocr_pdf_page(page: object, dpi: int = 200) -> str:
    """Render a PyMuPDF page to an image and OCR it with pytesseract.

    Imports are performed lazily so importing this module never hard-requires the
    native Tesseract binary. Raises ``OcrUnavailableError`` if OCR cannot run.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise OcrUnavailableError("pytesseract/Pillow not installed") from exc

    pix = page.get_pixmap(dpi=dpi)  # type: ignore[attr-defined]
    image = Image.open(io.BytesIO(pix.tobytes("png")))
    try:
        return pytesseract.image_to_string(image)
    except Exception as exc:  # tesseract binary missing or failed
        raise OcrUnavailableError(str(exc)) from exc
