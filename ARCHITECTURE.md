# ARCHITECTURE — live

Reflects the **current** implementation. Updated at the close of every phase.

## Target Diagram

```
                          ┌─────────────────────────────┐
                          │        Streamlit UI          │
                          │  Upload · Findings · Risk ·  │
                          │  Summary · Chat · Redaction  │
                          └──────────────┬──────────────┘
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        │                                │                                 │
┌───────▼────────┐            ┌──────────▼──────────┐          ┌───────────▼──────────┐
│  Ingestion      │            │  Detection Engine    │          │  RAG / Q&A            │
│  PDF/TXT/CSV    │──text──▶   │  Regex validators +  │          │  chunk → embed →      │
│  + OCR fallback │            │  spaCy NER + LLM      │          │  FAISS → retrieve →   │
└─────────────────┘            │  contextual pass      │          │  Gemini synth + cite  │
                               └──────────┬───────────┘          └───────────┬──────────┘
                               ┌──────────▼───────────┐                      │
                               │  Risk Classifier      │                      │
                               │  weighted → L/M/H     │                      │
                               └──────────┬───────────┘                      │
                               ┌──────────▼──────────────────────────────────▼─────────┐
                               │   Gemini Model-Rotation Client (rate-limit aware)      │
                               └──────────┬─────────────────────────────────────────────┘
                               ┌──────────▼──────────┐
                               │  Audit Log (JSONL)   │ masked
                               └─────────────────────┘
```

## Module Responsibilities (current)

| Module | Responsibility | Status |
|--------|----------------|--------|
| `app.py` | Thin Streamlit UI; delegates to `src/`. | skeleton |
| `src/config.py` | Single source of truth: settings, model registry, thresholds, weights. | ✅ |
| `src/models.py` | Shared data contracts: `Document`, `Segment`, `Finding`, `RiskReport`, `RiskContributor`, `Citation`, `QAResult`, `EntityType`, `RiskLevel`. | ✅ |
| `src/ingestion/loaders.py` | `load_document()` dispatch: PDF (PyMuPDF page-by-page), TXT (charset-normalizer, per-line), CSV (pandas, row segments + DataFrame in metadata). | ✅ |
| `src/ingestion/ocr.py` | `needs_ocr()` heuristic + `ocr_pdf_page()` (lazy pytesseract). | ✅ |
| `src/detection/patterns.py` | Verhoeff/Luhn/IFSC + `PATTERN_SPECS` registry → `detect_patterns()`; card-network id; config-driven employee-id pattern. | ✅ |
| `src/detection/ner.py` | Lazy spaCy PERSON/ORG/LOCATION, graceful `[]`. | ✅ |
| `src/detection/llm_contextual.py` | `detect_contextual()` JSON pass with verbatim-snippet hallucination guard; skips when unconfigured/exhausted. | ✅ |
| `src/detection/engine.py` | `run_detection()` orchestrator: compose detectors, span→page/line/column, overlap dedupe (longer+trust rank), `summarize_counts()`. | ✅ |
| `src/classification/risk.py` | `classify_risk()`: Σ(weight×count)×density → Low/Med/High + sorted `RiskContributor` breakdown + summary. | ✅ |
| `src/redaction/masker.py` | `mask_value()`, `redact_text()`, `replacement_for()` — single source of masking/redaction primitives. | ✅ |
| `src/redaction/export.py` | `redact_txt()` / `redact_csv()` / `redact_pdf()` sanitized exporters (PyMuPDF true redaction). | ✅ |
| `src/rag/chunker.py` | `chunk_document()`: sentence units → masked, overlapping `Chunk[]` with page/line. | ✅ |
| `src/rag/embeddings.py` | `LocalEmbedder` (cached MiniLM, normalized vectors); `get_embedder()`. | ✅ |
| `src/rag/store.py` | `FaissStore`: IndexFlatIP over masked chunks, persisted per doc_id. | ✅ |
| `src/rag/qa.py` | `build_index()` + `answer_question()`: counting via findings, retrieve+refuse+grounded synthesis, citations. | ✅ |
| `src/llm/gemini_client.py` | `GeminiClient.generate()`: rotation, 429 failover, 5xx backoff, `AllModelsExhausted`, `LLMResult`. SDK call isolated in `_invoke_sdk`. | ✅ |
| `src/llm/rate_limiter.py` | `RateLimiter`: sliding-window RPM/TPM + persisted daily RPD, atomic, injectable clock, `snapshot()` for UI. | ✅ |
| `src/llm/prompts.py` | Shared `SYSTEM_PREAMBLE` + `with_preamble()`; task templates grow per phase. | ✅ |
| `src/compliance.py` | `generate_summary()`: masked brief → GDPR/DPDP/PCI-DSS observations + risks + remediation; deterministic `_template_summary` fallback. | ✅ |
| `src/audit.py` | JSONL masked audit log. | stub (P9) |

## Interfaces / Contracts
All layers communicate via `src/models.py` dataclasses only — no module reaches
into another's internals. `config.get_settings()` is the sole configuration entry
point. Raw sensitive values (`Finding.value_raw`) never leave memory into logs,
the vector store, or the UI unless explicitly revealed.

## Folder Structure (current)

```
app.py · pyproject.toml · requirements.txt · .env.example · .gitignore
src/
  config.py · models.py · audit.py
  ingestion/{loaders,ocr}.py
  detection/{patterns,ner,llm_contextual,engine}.py
  classification/risk.py
  redaction/masker.py
  rag/{chunker,embeddings,store,qa}.py
  llm/{gemini_client,rate_limiter,prompts}.py
tests/  ·  data/samples/
PROJECT_PLAN.md · ARCHITECTURE.md · PROGRESS.md · DECISIONS_LOG.md
```
