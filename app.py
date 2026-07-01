"""Streamlit entrypoint.

Thin UI layer only — all business logic lives in ``src/``. This module wires
user interactions to the ingestion/detection/RAG services and renders results.
Phase 1 ships a skeleton: title, sidebar, and a file-uploader stub (no
processing yet).
"""

from __future__ import annotations

import streamlit as st

from src.config import get_settings
from src.ingestion.loaders import UnsupportedFileTypeError, load_document
from src.llm.gemini_client import GeminiClient


def get_client() -> GeminiClient:
    """Return the session-scoped Gemini client (persists quota across reruns)."""
    if "gemini_client" not in st.session_state:
        st.session_state["gemini_client"] = GeminiClient()
    return st.session_state["gemini_client"]


def render_quota_panel(client: GeminiClient) -> None:
    """Render live per-model RPM/RPD usage in the sidebar."""
    st.subheader("Gemini model rotation")
    last = st.session_state.get("last_model_used")
    if last:
        st.caption(f"Last call served by **{last}**")
    for usage in client.rate_limiter.snapshot():
        status = "🟢" if usage.available else ("🟡" if usage.cooling_down else "🔴")
        st.write(
            f"{status} `{usage.name}` — RPM {usage.rpm_used}/{usage.rpm_limit} · "
            f"RPD {usage.rpd_used}/{usage.rpd_limit}"
        )


def main() -> None:
    """Render the Streamlit application shell."""
    settings = get_settings()

    st.set_page_config(
        page_title="Sensitive Data Detection & Compliance Assistant",
        page_icon="🛡️",
        layout="wide",
    )

    st.title("🛡️ Sensitive Data Detection & Compliance Assistant")
    st.caption(
        "Upload a document to detect sensitive data, classify risk, generate a "
        "compliance summary, and ask grounded questions."
    )

    with st.sidebar:
        st.header("Configuration")
        st.write(f"**Embedding model:** `{settings.embedding_model}`")
        st.write(f"**OCR enabled:** {settings.enable_ocr}")
        st.write(f"**Models in rotation:** {len(settings.model_registry)}")
        if not settings.gemini_api_key:
            st.warning("GEMINI_API_KEY not set — LLM features will be disabled.")
        st.divider()
        render_quota_panel(get_client())

    uploaded = st.file_uploader(
        "Upload a document",
        type=["pdf", "txt", "csv"],
        help="Supported formats: PDF, TXT, CSV.",
    )

    if uploaded is None:
        st.info("👆 Upload a PDF, TXT, or CSV file to begin.")
        return

    try:
        document = load_document(uploaded.name, uploaded.getvalue(), settings)
    except UnsupportedFileTypeError as exc:
        st.error(str(exc))
        return

    st.success(f"Loaded **{document.filename}** — `{document.doc_id}`")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Format", document.file_type.upper())
    col2.metric("Pages / segments", document.page_count)
    col3.metric("Characters", f"{len(document.text):,}")
    col4.metric("OCR used", "Yes" if document.used_ocr else "No")

    with st.expander("Text preview", expanded=True):
        st.text(document.text[:2000] + ("…" if len(document.text) > 2000 else ""))

    st.info("Detection, risk, summary, chat, and redaction arrive in later phases.")


if __name__ == "__main__":
    main()
