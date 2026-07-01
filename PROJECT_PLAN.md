# PROJECT PLAN — Sensitive Data Detection & Compliance Assistant

Authoritative plan of record. Status legend: ✅ done · 🚧 in progress · ⏳ pending.

## Scope
A Streamlit app that ingests a PDF/TXT/CSV document, deterministically detects
sensitive/confidential information, classifies overall risk, generates a grounded
compliance summary, redacts, and answers cited questions via RAG — all on the
Gemini free tier with a rate-limit-aware model-rotation client.

## Phase Roadmap

| Phase | Title | Status |
|------:|-------|--------|
| 1 | Project scaffold & config | ✅ done |
| 2 | Document ingestion (PDF/TXT/CSV + OCR) | ✅ done |
| 3 | Gemini model-rotation client (rate-limit engine) | ⏳ pending |
| 4 | Sensitive data detection engine | ⏳ pending |
| 5 | Risk classification | ⏳ pending |
| 6 | RAG Q&A over the document | ⏳ pending |
| 7 | AI compliance summary | ⏳ pending |
| 8 | Redaction / masking & sanitized export | ⏳ pending |
| 9 | Audit logging & multi-document support | ⏳ pending |
| 10 | Dockerization, deployment & documentation | ⏳ pending |

## Current State
Phases 1–2 complete. Runnable skeleton + typed config + shared models (P1);
multi-format ingestion (PDF via PyMuPDF, TXT with charset detection, CSV via
pandas) with a config-gated Tesseract OCR fallback, normalized `Document` with
page/line/column metadata, wired into the uploader with a preview (P2). 12 tests
green, `ruff` clean.

## Next Task
Phase 3 — the Gemini model-rotation client: `llm/rate_limiter.py` (sliding-window
RPM, TPM estimate, daily RPD with persistence) and `llm/gemini_client.py`
(429 failover across the registry, backoff, `AllModelsExhausted`), plus a sidebar
quota panel.
