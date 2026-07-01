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
| 3 | Gemini model-rotation client (rate-limit engine) | ✅ done |
| 4 | Sensitive data detection engine | ⏳ pending |
| 5 | Risk classification | ⏳ pending |
| 6 | RAG Q&A over the document | ⏳ pending |
| 7 | AI compliance summary | ⏳ pending |
| 8 | Redaction / masking & sanitized export | ⏳ pending |
| 9 | Audit logging & multi-document support | ⏳ pending |
| 10 | Dockerization, deployment & documentation | ⏳ pending |

## Current State
Phases 1–3 complete. Skeleton + config + models (P1); multi-format ingestion +
OCR (P2); rate-limit-aware Gemini rotation client — `RateLimiter` (sliding-window
RPM/TPM + persisted daily RPD, injectable clock, atomic) and `GeminiClient`
(429 failover, 5xx backoff, `AllModelsExhausted`), with a live sidebar quota
panel (P3). 22 tests green, `ruff` clean.

## Next Task
Phase 4 — sensitive data detection engine: `detection/patterns.py` (regex +
Verhoeff/Luhn/IFSC validators), `detection/ner.py` (spaCy), `detection/
llm_contextual.py` (Gemini JSON pass), `detection/engine.py` (orchestrate +
dedupe + mask), Findings tab in the UI.
