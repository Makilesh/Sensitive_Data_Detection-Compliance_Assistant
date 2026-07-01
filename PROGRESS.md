# PROGRESS LOG

Running log of per-phase completion + self-review outcomes.

## Phase 1 — Project Scaffold & Config ✅

**Completed**
- Repo layout created with `src/` subpackages and empty, docstringed stubs for
  all later phases.
- `requirements.txt` with pinned versions (Streamlit, google-generativeai,
  pydantic(-settings), pandas, pymupdf, pdfplumber, spacy, pytesseract, pillow,
  faiss-cpu, sentence-transformers, tiktoken, pytest, ruff, black).
- `src/config.py`: `Settings` (pydantic-settings) — reads `GEMINI_API_KEY`,
  Gemini model registry with per-model RPM/TPM/RPD, risk thresholds + severity
  weights, embedding/chunk/RAG params, OCR + redaction defaults.
- `src/models.py`: `EntityType`, `RiskLevel`, `Document`, `Segment`, `Finding`,
  `RiskContributor`, `RiskReport`, `Citation`, `QAResult`.
- `app.py`: thin Streamlit shell with title, sidebar config panel, uploader stub.
- `.env.example`, `.gitignore`, `pyproject.toml` (ruff/black/pytest config).
- Living docs scaffolded: PROJECT_PLAN, ARCHITECTURE, PROGRESS, DECISIONS_LOG.
- Tests: `tests/test_config.py` (settings load, registry uniqueness, weights
  cover all entity types, models construct).

**Self code review outcome**
- Issue: `EntityType`/`RiskLevel` used `(str, Enum)` → ruff UP042. **Fixed** by
  switching to `StrEnum` (Python 3.11+), which also gives clean value-based
  string behavior for JSON/logging.
- Verified `GEMINI_API_KEY` alias bypasses the `SDA_` env prefix (tested).
- Verified `streamlit run app.py` launches headless; `pytest` (4 passed);
  `ruff check .` clean.
- No secrets committed; `.env` gitignored.

**Definition of Done:** ✅ all criteria met.

**Next:** Phase 2 — multi-format ingestion with OCR fallback.

## Phase 2 — Document Ingestion (PDF/TXT/CSV + OCR) ✅

**Completed**
- `ingestion/loaders.py`: `load_document()` single entry point; PDF page-by-page
  (PyMuPDF), TXT with charset-normalizer + per-line segments, CSV via pandas with
  row segments and the DataFrame retained in `metadata` for column-level
  detection. Stable `doc_id` = sha256(bytes)[:16]. Char offsets validated to
  index back into full text.
- `ingestion/ocr.py`: pure `needs_ocr()` heuristic + isolated `ocr_pdf_page()`
  with lazy pytesseract import and `OcrUnavailableError` graceful degradation.
- Sample files in `data/samples/`: text PDF (2 pages), scanned image-only PDF
  (0 extractable chars), CSV with fake PII.
- Uploader wired in `app.py`: format/pages/chars/OCR metrics + text preview.
- Tests (`test_ingestion.py`, 8): all three formats, metadata, offset integrity,
  unsupported-type error, OCR trigger-on-scanned (mocked), OCR-disabled path.

**Self code review outcome**
- Confirmed OCR path degrades (keeps native text) when Tesseract absent — matches
  local env (no binary). OCR only replaces text if it yields *more* content.
- CSV loaded with `dtype=str, keep_default_na=False` to avoid NaN artifacts in
  detection. Empty-file invariant preserved (single empty segment).
- No raw values logged; ingestion emits only `Document`. `ruff` clean, 12 tests.

**Definition of Done:** ✅ all three formats load + preview; OCR fallback triggers
on the scanned sample.

**Next:** Phase 3 — rate-limit-aware Gemini model-rotation client.

## Phase 3 — Gemini Model-Rotation Client ✅

**Completed**
- `llm/rate_limiter.py`: `RateLimiter` with trailing-60s RPM + TPM sliding windows
  and daily RPD persisted to JSON (resets on day roll). Lock-guarded `can_use` /
  `record` for atomic accounting; injectable clock; `mark_cooldown`,
  `seconds_until_available`, and `snapshot()` (→ `ModelUsage`) for the UI.
- `llm/gemini_client.py`: `GeminiClient.generate()` rotates over the registry,
  cools down a model on 429/`ResourceExhausted`, retries 5xx with exponential
  backoff, records token usage, and raises `AllModelsExhausted` when all capped.
  Real SDK call isolated in `_invoke_sdk` (lazy import). Error classification via
  `_is_rate_limit_error` / `_is_transient_error`.
- `llm/prompts.py`: shared anti-hallucination `SYSTEM_PREAMBLE` + `with_preamble`.
- UI: sidebar quota panel (per-model RPM/RPD, availability, last model used).
- `config.py`: `populate_by_name=True` so settings can be built by field name.
- Tests: `test_rate_limiter.py` (5) + `test_gemini_client.py` (5) using a fake
  clock — RPM/TPM/RPD block+free, RPD persistence + day reset, cooldown, 429
  rotation, 5xx retry-then-succeed, `AllModelsExhausted`, unconfigured guard.

**Self code review outcome**
- Removed a dead `last_error` variable in `generate()` (was always `None`).
- Confirmed limits are data-only (config registry), never hardcoded in logic —
  values still need verifying at the rate-limits URL before final submission.
- `ruff` clean; 22 tests green; app launches with the live quota panel.

**Definition of Done:** ✅ forced-429 rotation verified by test; UI shows live
per-model quota.

**Next:** Phase 4 — deterministic + contextual detection engine.
