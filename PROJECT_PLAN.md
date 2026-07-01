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
| 4 | Sensitive data detection engine | ✅ done |
| 5 | Risk classification | ⏳ pending |
| 6 | RAG Q&A over the document | ⏳ pending |
| 7 | AI compliance summary | ⏳ pending |
| 8 | Redaction / masking & sanitized export | ⏳ pending |
| 9 | Audit logging & multi-document support | ⏳ pending |
| 10 | Dockerization, deployment & documentation | ⏳ pending |

## Current State
Phases 1–4 complete. Skeleton/config/models (P1); ingestion + OCR (P2); Gemini
rotation client (P3); detection engine (P4) — deterministic regex + Verhoeff/Luhn
checksums + IFSC + provider key patterns, spaCy NER, LLM contextual pass (with
verbatim-snippet hallucination guard), orchestrator with span→page/line mapping,
overlap dedupe, and immediate masking; Findings tab with per-type chart, masked
table, and explicit reveal toggle. 32 tests green, `ruff` clean.

## Next Task
Phase 5 — risk classification: `classification/risk.py` weighted scoring over
findings (severity weights + counts + density) → Low/Med/High with an explainable
contributor breakdown; Risk tab with badge + bar chart.
