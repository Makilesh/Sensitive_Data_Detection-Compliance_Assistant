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
| 5 | Risk classification | ✅ done |
| 6 | RAG Q&A over the document | ✅ done |
| 7 | AI compliance summary | ✅ done |
| 8 | Redaction / masking & sanitized export | ✅ done |
| 9 | Audit logging & multi-document support | ✅ done |
| 10 | Dockerization, deployment & documentation | ✅ done |

## Current State
Phases 1–4 complete. Skeleton/config/models (P1); ingestion + OCR (P2); Gemini
rotation client (P3); detection engine (P4) — deterministic regex + Verhoeff/Luhn
checksums + IFSC + provider key patterns, spaCy NER, LLM contextual pass (with
verbatim-snippet hallucination guard), orchestrator with span→page/line mapping,
overlap dedupe, and immediate masking; Findings tab with per-type chart, masked
table, and explicit reveal toggle. Risk classification (P5) — weighted score ×
density → Low/Med/High with contributor breakdown; Risk tab with colored badge +
chart. RAG Q&A (P6) — masked sentence-aware chunking, local MiniLM embeddings,
persisted FAISS per doc, grounded cited synthesis with refusal + deterministic
counting; Chat tab. Compliance summary (P7) — masked brief → GDPR/DPDP/PCI-DSS
observations + risks + remediation, deterministic template fallback; Summary tab +
Markdown download. Redaction (P8) — TXT/PDF/CSV sanitized export (PyMuPDF true
redaction) with zero leaked values; Redaction tab. Audit + multi-doc (P9) —
append-only PII-free JSONL (hashed questions), multi-file upload + document
switcher + corpus mode + Audit expander. Dockerization + docs (P10) — Dockerfile,
compose, packages.txt, README (all 5 mandatory sections), RESULTS, demo script.
57 tests green, `ruff` clean. **Shipped.**

## Next Task
All 10 phases complete. Remaining external steps (require the user): run
`docker compose up --build` to confirm the image, deploy to Streamlit Community
Cloud and fill in the live URL, record the demo video, and verify current Gemini
free-tier limits at the rate-limits URL. `git push` when ready.
