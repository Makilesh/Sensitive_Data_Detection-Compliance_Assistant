"""Streamlit entrypoint.

Thin UI layer only — all business logic lives in ``src/``. This module wires
user interactions to the ingestion/detection/RAG services, caches per-document
results in session state, and renders them across tabs.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.classification.risk import classify_risk
from src.compliance import generate_summary
from src.config import Settings, get_settings
from src.detection.engine import run_detection, summarize_counts
from src.ingestion.loaders import UnsupportedFileTypeError, load_document
from src.llm.gemini_client import GeminiClient
from src.models import Document, Finding, RiskLevel, RiskReport
from src.rag.qa import answer_question, build_index
from src.redaction.export import redact_csv, redact_pdf, redact_txt

_RISK_COLORS = {RiskLevel.LOW: "green", RiskLevel.MEDIUM: "orange", RiskLevel.HIGH: "red"}


def get_client() -> GeminiClient:
    """Return the session-scoped Gemini client (persists quota across reruns)."""
    if "gemini_client" not in st.session_state:
        st.session_state["gemini_client"] = GeminiClient()
    return st.session_state["gemini_client"]


def get_findings(document: Document, settings: Settings) -> list[Finding]:
    """Detect (once per doc_id) and cache findings in session state."""
    cache = st.session_state.setdefault("findings_cache", {})
    if document.doc_id not in cache:
        with st.spinner("Detecting sensitive data…"):
            cache[document.doc_id] = run_detection(document, get_client(), settings)
    return cache[document.doc_id]


def get_risk(document: Document, findings: list[Finding], settings: Settings) -> RiskReport:
    """Classify (once per doc_id) and cache the risk report."""
    cache = st.session_state.setdefault("risk_cache", {})
    if document.doc_id not in cache:
        cache[document.doc_id] = classify_risk(findings, document.page_count, settings)
    return cache[document.doc_id]


def render_risk(report: RiskReport) -> None:
    color = _RISK_COLORS[report.level]
    st.markdown(f"### Overall risk: :{color}[{report.level.value}]")
    st.metric("Risk score", report.score)
    st.write(report.summary)
    if report.contributors:
        st.write("**Contributor breakdown**")
        data = {c.entity_type.value: c.contribution for c in report.contributors}
        st.bar_chart(pd.Series(data, name="contribution"))


def render_redaction(
    document: Document, findings: list[Finding], raw_bytes: bytes, settings: Settings
) -> None:
    st.caption(
        f"Redaction style: **{settings.redaction_style}**. Download a sanitized copy "
        "with all detected sensitive values removed."
    )
    redacted_text = redact_txt(document, findings, settings)
    left, right = st.columns(2)
    with left:
        st.write("**Original (masked preview)**")
        st.text(document.text[:1500])
    with right:
        st.write("**Redacted**")
        st.text(redacted_text[:1500])

    st.download_button(
        "⬇️ Download redacted TXT",
        data=redacted_text,
        file_name=f"redacted_{document.filename}.txt",
        mime="text/plain",
    )
    if document.file_type == "pdf":
        st.download_button(
            "⬇️ Download redacted PDF",
            data=redact_pdf(raw_bytes, findings, settings),
            file_name=f"redacted_{document.filename}",
            mime="application/pdf",
        )
    if document.file_type == "csv":
        st.download_button(
            "⬇️ Download redacted CSV",
            data=redact_csv(document, findings, settings),
            file_name=f"redacted_{document.filename}",
            mime="text/csv",
        )


def render_summary(document: Document, findings: list[Finding], risk: RiskReport, settings: Settings) -> None:
    cache = st.session_state.setdefault("summary_cache", {})
    if st.button("Generate compliance summary", type="primary") or document.doc_id in cache:
        if document.doc_id not in cache:
            with st.spinner("Generating compliance summary…"):
                cache[document.doc_id] = generate_summary(
                    document, findings, risk, get_client(), settings
                )
        summary = cache[document.doc_id]
        st.markdown(summary)
        st.download_button(
            "⬇️ Download report (Markdown)",
            data=summary,
            file_name=f"compliance_report_{document.doc_id}.md",
            mime="text/markdown",
        )
    else:
        st.info("Click to generate a grounded compliance summary with remediation steps.")


def get_store(document: Document, findings: list[Finding], settings: Settings):
    """Build/load and cache the RAG index for the document."""
    cache = st.session_state.setdefault("store_cache", {})
    if document.doc_id not in cache:
        with st.spinner("Building search index…"):
            cache[document.doc_id] = build_index(document, findings, settings=settings)
    return cache[document.doc_id]


def render_chat(document: Document, findings: list[Finding], settings: Settings) -> None:
    st.caption(
        "Ask about the document. Answers are grounded in retrieved context and "
        "cite their sources; counting questions use the deterministic findings."
    )
    histories = st.session_state.setdefault("chat_histories", {})
    history = histories.setdefault(document.doc_id, [])

    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    question = st.chat_input("e.g. What sensitive data exists in the document?")
    if not question:
        return

    history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    store = get_store(document, findings, settings)
    with st.chat_message("assistant"), st.spinner("Thinking…"):
        result = answer_question(question, document, findings, get_client(), store, settings=settings)
        if result.model_used:
            st.session_state["last_model_used"] = result.model_used
        st.markdown(result.answer)
        if not result.grounded:
            st.caption("⚠️ Not grounded — insufficient supporting context.")
        if result.citations:
            with st.expander(f"Citations ({len(result.citations)})"):
                for cit in result.citations:
                    loc = f"page {cit.page}, line {cit.line}"
                    st.markdown(f"- **[{cit.chunk_id}]** ({loc}) — {cit.snippet}")
    history.append({"role": "assistant", "content": result.answer})


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


def render_overview(document: Document, findings: list[Finding]) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Format", document.file_type.upper())
    col2.metric("Pages / segments", document.page_count)
    col3.metric("Characters", f"{len(document.text):,}")
    col4.metric("Sensitive findings", len(findings))
    if document.used_ocr:
        st.caption("ℹ️ OCR was used to extract text from a scanned page.")
    with st.expander("Text preview", expanded=False):
        st.text(document.text[:2000] + ("…" if len(document.text) > 2000 else ""))


def render_findings(findings: list[Finding]) -> None:
    if not findings:
        st.success("No sensitive data detected.")
        return

    counts = summarize_counts(findings)
    st.write("**Findings by type**")
    st.bar_chart(pd.Series(counts, name="count"))

    reveal = st.checkbox("Reveal raw values (handle with care)", value=False)
    rows = [
        {
            "Type": f.entity_type.value,
            "Value": f.value_raw if reveal else f.value_masked,
            "Detector": f.detector,
            "Confidence": round(f.confidence, 2),
            "Page": f.page,
            "Line": f.line,
            "Column": f.column,
            "Rationale": f.rationale or "",
        }
        for f in findings
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


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
            st.warning("GEMINI_API_KEY not set — LLM contextual detection disabled.")
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

    raw_bytes = uploaded.getvalue()
    try:
        document = load_document(uploaded.name, raw_bytes, settings)
    except UnsupportedFileTypeError as exc:
        st.error(str(exc))
        return

    st.success(f"Loaded **{document.filename}** — `{document.doc_id}`")
    findings = get_findings(document, settings)
    risk = get_risk(document, findings, settings)

    overview_tab, findings_tab, risk_tab, summary_tab, chat_tab = st.tabs(
        ["📄 Overview", "🔍 Findings", "⚠️ Risk", "📋 Summary", "💬 Chat"]
    )
    with overview_tab:
        render_overview(document, findings)
    with findings_tab:
        render_findings(findings)
    with risk_tab:
        render_risk(risk)
    with summary_tab:
        render_summary(document, findings, risk, settings)
    with chat_tab:
        render_chat(document, findings, settings)


if __name__ == "__main__":
    main()
