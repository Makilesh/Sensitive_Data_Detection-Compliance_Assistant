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
| `src/detection/patterns.py` | Regex + Verhoeff/Luhn/IFSC validators → `Finding`. | stub (P4) |
| `src/detection/ner.py` | spaCy NER pass. | stub (P4) |
| `src/detection/llm_contextual.py` | LLM confidential-info pass. | stub (P4) |
| `src/detection/engine.py` | Orchestrate detectors, dedupe, mask. | stub (P4) |
| `src/classification/risk.py` | Weighted risk scoring. | stub (P5) |
| `src/redaction/masker.py` | Mask/redact + sanitized export. | stub (P8) |
| `src/rag/chunker.py` | Sentence-aware chunking. | stub (P6) |
| `src/rag/embeddings.py` | Local sentence-transformers embedder. | stub (P6) |
| `src/rag/store.py` | FAISS per-document index. | stub (P6) |
| `src/rag/qa.py` | Retrieve + synthesize + cite. | stub (P6) |
| `src/llm/gemini_client.py` | Rate-limit-aware rotation client. | stub (P3) |
| `src/llm/rate_limiter.py` | RPM/TPM/RPD tracking. | stub (P3) |
| `src/llm/prompts.py` | Prompt templates. | stub (P3) |
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
