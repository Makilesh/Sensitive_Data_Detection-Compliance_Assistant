# 🛡️ Sensitive Data Detection & Compliance Assistant

An AI-powered Streamlit application that ingests a document (PDF / TXT / CSV),
**detects sensitive & confidential information**, **classifies risk**, generates a
**compliance summary**, produces a **redacted copy**, and answers **grounded,
cited questions** about the document via RAG — all on the **Google Gemini free
tier** with a rate-limit-aware model-rotation engine.

> **Live demo:** _<add your Streamlit Community Cloud URL here>_
> **Demo video (2–5 min):** _<add your video link here>_

---

## Setup Instructions

### Prerequisites
- Python 3.11+
- A free Gemini API key — https://aistudio.google.com/app/apikey
- (Optional) Tesseract OCR for scanned PDFs — https://github.com/tesseract-ocr/tesseract
- (Optional) [Ollama](https://ollama.com) for the local LLM fallback:
  ```bash
  ollama pull qwen2.5:14b     # ~9GB, fits a 12GB-VRAM GPU; strong at JSON/extraction
  ```
  Toggle/point it via `SDA_ENABLE_OLLAMA`, `SDA_OLLAMA_MODEL`, `SDA_OLLAMA_HOST`.
  With Ollama enabled you can run the app **without** a Gemini key.
- (Optional) GPU reranker: the auto-upgrade to `bge-reranker-v2-m3` requires a
  **CUDA-enabled PyTorch** build (the default `pip` torch on Windows is CPU-only);
  install the CUDA wheel from https://pytorch.org if you want GPU reranking.

### Local install
```bash
# 1. Clone and enter the project
git clone <your-repo-url>
cd Sensitive_Data_Detection_Compliance_Assistant

# 2. Install dependencies
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# 3. Configure secrets
cp .env.example .env
# edit .env and set GEMINI_API_KEY=...

# 4. Run
streamlit run app.py
```
Open http://localhost:8501.

### Run with Docker
```bash
export GEMINI_API_KEY=your_key_here   # or put it in a .env file
docker compose up --build
```
The app is served on http://localhost:8501 with Tesseract and the spaCy model
pre-installed. RAG indexes and the audit log are persisted via mounted volumes.

### Tests & linting
```bash
pytest          # 57 tests
ruff check .    # lint
```

### Deploy to Streamlit Community Cloud (free)
1. Push this repo to GitHub.
2. On https://share.streamlit.io create an app pointing at `app.py`.
3. In **App settings → Secrets**, add:
   ```toml
   GEMINI_API_KEY = "your_key_here"
   ```
4. `packages.txt` (already included) installs `tesseract-ocr` on the host so the
   OCR fallback works.

---

## Architecture Overview

```
                          ┌─────────────────────────────┐
                          │        Streamlit UI          │
                          │ Overview·Findings·Risk·      │
                          │ Summary·Chat·Redaction·Audit │
                          └──────────────┬──────────────┘
        ┌────────────────────────────────┼────────────────────────────────┐
┌───────▼────────┐            ┌──────────▼──────────┐          ┌───────────▼──────────┐
│  Ingestion      │            │  Detection Engine    │          │  RAG / Q&A            │
│  PDF/TXT/CSV    │──text──▶   │  Regex + checksums + │          │  chunk(mask)→embed→   │
│  + OCR fallback │            │  spaCy NER + LLM      │          │  FAISS→retrieve→      │
│  (PyMuPDF,      │            │  contextual pass      │          │  Gemini synth + cite  │
│   pdfplumber,   │            │  → Finding[]          │          │  (or refuse)          │
│   Tesseract)    │            └──────────┬───────────┘          └───────────┬──────────┘
└─────────────────┘            ┌──────────▼───────────┐                      │
                               │  Risk Classifier      │                      │
                               │  weighted → L/M/H     │                      │
                               └──────────┬───────────┘                      │
                               ┌──────────▼──────────────────────────────────▼─────────┐
                               │   Gemini Model-Rotation Client (rate-limit aware)      │
                               │   registry · RPM/TPM/RPD tracker · 429 failover ·      │
                               │   retry/backoff · graceful degradation                 │
                               └──────────┬─────────────────────────────────────────────┘
                               ┌──────────▼──────────┐
                               │  Audit Log (JSONL)   │  masked, PII-free
                               └─────────────────────┘
```

- **`app.py`** — thin Streamlit UI; delegates everything to `src/`.
- **`src/config.py`** — single source of truth: model registry, thresholds,
  weights, chunking, redaction settings.
- **`src/models.py`** — shared dataclasses (`Document`, `Finding`, `RiskReport`,
  `Chunk`, `QAResult`, …) that keep the layers loosely coupled.
- **`src/ingestion/`** — `loaders.py` (PDF/TXT/CSV → `Document`), `ocr.py`
  (Tesseract fallback).
- **`src/detection/`** — `patterns.py` (regex + Verhoeff/Luhn/IFSC), `ner.py`
  (spaCy), `llm_contextual.py` (Gemini, hallucination-guarded), `engine.py`
  (orchestrate + dedupe + mask).
- **`src/classification/risk.py`** — explainable weighted risk scoring.
- **`src/rag/`** — `chunker.py`, `embeddings.py` (local MiniLM), `store.py`
  (FAISS), `qa.py` (grounded, cited answers).
- **`src/llm/`** — `gemini_client.py` (rotation), `rate_limiter.py`, `prompts.py`.
- **`src/redaction/`** — `masker.py` (masking primitives), `export.py`
  (sanitized TXT/PDF/CSV).
- **`src/compliance.py`** — GDPR/DPDP/PCI-DSS compliance summary.
- **`src/audit.py`** — append-only, PII-free JSONL audit log.

See `ARCHITECTURE.md` for the live module map and `DECISIONS_LOG.md` for the
engineering rationale behind each choice.

---

## AI/ML Approach Used

The design deliberately separates **deterministic** detection from **probabilistic**
AI, using each where it is strongest:

1. **Deterministic structured-PII detection** — Aadhaar (regex + **Verhoeff**
   checksum), PAN, credit cards (regex + **Luhn** + network id), IFSC, phone,
   bank accounts (keyword proximity), and provider API-key patterns
   (AWS/OpenAI/GitHub/JWT). Checksums cut false positives; the LLM is never
   trusted to "find" these.
2. **spaCy NER** — PERSON / ORG / LOCATION context for risk and confidential-info
   detection.
3. **Gemini contextual pass** — flags fuzzy confidential business information
   (NDAs, financials, M&A, litigation) in strict JSON, with every returned
   snippet **verified verbatim** against the source (hallucination guard).
4. **Explainable risk scoring** — `Σ(severity_weight × count) × density` → Low /
   Medium / High with a contributor breakdown.
5. **Hybrid local-embedding RAG** — `sentence-transformers` (all-MiniLM-L6-v2)
   over **masked** chunks in FAISS, **fused with an in-house BM25 sparse index via
   Reciprocal Rank Fusion** so exact-token queries (e.g. "IFSC", "employee id")
   are recalled alongside semantic ones. Gemini synthesizes a grounded, cited
   answer or **refuses** when retrieval is weak (absolute cosine floor). Counting
   questions ("how many emails?") are answered from the deterministic findings,
   not the LLM. (Hybrid toggle: `SDA_ENABLE_HYBRID_SEARCH`.)
   - **Optional cross-encoder reranker** (`SDA_ENABLE_RERANKER`) for large/noisy
     documents: reranks a larger candidate pool with cross-attention. GPU-aware —
     loads lightweight `ms-marco-MiniLM-L-6-v2` on CPU, auto-upgrades to
     `bge-reranker-v2-m3` when a CUDA GPU is available. Off by default.
   - **Privacy local-only mode** (`SDA_LOCAL_ONLY_MODE`, or the sidebar toggle):
     forces the local Ollama backend so **no document text — even masked — leaves
     the machine**. Ideal for the most sensitive documents.
6. **Rate-limit-aware model rotation + local fallback** — a registry of free-tier
   Gemini models (led by high-throughput flash tiers) with per-model RPM/TPM/RPD
   tracking; on a 429 the client cools that model down and rotates to the next,
   retrying transient 5xx with backoff. When all cloud models are exhausted it
   falls through to a **local Ollama model** (default `qwen2.5:14b`), so the app
   keeps working with **zero quota** — and runs fully offline if no key is set.

**Privacy by default:** raw sensitive values never enter logs, the vector index,
or the UI unless the user explicitly clicks "reveal".

---

## Challenges Faced

- **Free-tier rate limits.** Any single Gemini free model exhausts quickly. The
  **model-rotation client** (`src/llm/`) with sliding-window RPM/TPM + persisted
  daily RPD and 429 failover keeps the app usable, and degrades gracefully to
  deterministic behavior (template summary, masked-context answers) when *all*
  models are exhausted.
- **Checksum false positives.** Naïve regex flags any 12/16-digit run. Verhoeff
  (Aadhaar) and Luhn (card) validation eliminate lookalikes — verified by a
  golden file containing an intentionally invalid Aadhaar that is rejected.
- **OCR on scanned PDFs.** Image-only pages yield no text; a per-page heuristic
  triggers a Tesseract fallback, isolated so the app still runs where Tesseract
  is absent.
- **Grounding / hallucination.** RAG refuses below a cosine floor, cites page/line
  sources, and the contextual detector drops any snippet not present verbatim.
- **Keeping PII out of the pipeline.** Chunks are masked before embedding; the
  audit log stores counts and a hashed question, never raw values.

---

## Future Improvements

- Coordinate-level PDF redaction for OCR-only pages (currently TXT fallback).
- Configurable, org-specific detector packs (custom employee-ID / project-code
  patterns) loaded from YAML.
- Precision/recall evaluation harness across a larger labeled corpus.
- Streaming LLM responses and per-answer token/cost accounting in the UI.
- Optional cloud vector store (Qdrant/Chroma) with the same interface for scale.
- Role-based reveal permissions and encrypted at-rest index storage.

---

## Project Status & Docs
- `PROJECT_PLAN.md` — phase roadmap & status
- `ARCHITECTURE.md` — live architecture
- `PROGRESS.md` — per-phase progress + self-reviews
- `DECISIONS_LOG.md` — engineering decisions & trade-offs
- `RESULTS.md` — honest evaluation & limitations

> ⚠️ Verify current Gemini free-tier model names/limits at
> https://ai.google.dev/gemini-api/docs/rate-limits and update
> `DEFAULT_MODEL_REGISTRY` in `src/config.py` — limits change often.
