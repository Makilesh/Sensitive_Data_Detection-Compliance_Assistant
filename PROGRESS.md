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

## Phase 4 — Sensitive Data Detection Engine ✅

**Completed**
- `redaction/masker.py`: `mask_value()` — single masking source (email partial,
  last-4 for numeric IDs, full mask for keys/passwords), used at detection time.
- `detection/patterns.py`: Verhoeff (Aadhaar) + Luhn (card) validators, card
  network id, and a `PATTERN_SPECS` registry covering Email, Aadhaar, PAN, Phone,
  Credit Card, IFSC, Bank Account (keyword-proximity), API keys (AWS/OpenAI/
  GitHub/JWT/assigned-secret), Password, and config-driven Employee ID.
- `detection/ner.py`: lazy-cached spaCy `en_core_web_sm` → PERSON/ORG/LOCATION,
  degrades to `[]` if the model is missing.
- `detection/llm_contextual.py`: Gemini JSON pass for confidential business info;
  every returned snippet must exist verbatim in the text or is dropped
  (hallucination guard); skips cleanly when unconfigured/exhausted.
- `detection/engine.py`: `run_detection()` composes all detectors, maps char
  spans → page/line/column via segments, dedupes overlaps (longer span, then
  detector trust rank, then confidence), `summarize_counts()`.
- `data/samples/golden.txt`: planted PII incl. a checksum-INVALID Aadhaar.
- UI: tabbed layout (Overview + Findings); per-type bar chart, masked table,
  explicit "reveal raw values" checkbox; findings cached per doc_id.
- Tests (`test_detection.py`, 10): checksum accept/reject, exact golden counts,
  invalid-Aadhaar rejection, masking, overlap dedupe, line metadata, NER,
  contextual verify-vs-drop, unconfigured skip.

**Self code review outcome**
- Verified checksums prevent cross-matches: 12-digit account# is not matched by
  the card regex (needs ≥13 digits) and the invalid Aadhaar is checksum-rejected.
- Confirmed raw values live only in `Finding.value_raw`; all default UI/table
  surfaces use `value_masked`; reveal is an explicit opt-in.
- Minor UX decision: global "reveal" checkbox instead of per-row toggle (cleaner
  in Streamlit, same privacy guarantee) — logged in DECISIONS_LOG (D16).
- `ruff` clean; 32 tests green; app launches with Findings tab.

**Definition of Done:** ✅ all 9 categories detected (8 deterministic + LLM
contextual); checksum validation on Aadhaar/card; exact golden counts.

**Next:** Phase 5 — explainable risk classification.

## Phase 5 — Risk Classification ✅

**Completed**
- `classification/risk.py`: `classify_risk(findings, page_count, settings)` →
  `RiskReport`. Score = Σ(severity_weight×count) × density_factor
  (`1 + 0.1·max(0, findings_per_page−3)`), banded by config thresholds
  (Medium ≥ 10, High ≥ 30). Sorted `RiskContributor` breakdown + human summary.
- Recalibrated thresholds (Medium 10 / High 30) so a single critical entity
  (e.g. one Aadhaar) lands at ≥ Medium while a lone email stays Low.
- UI Risk tab: colored badge (green/orange/red), score metric, summary, and a
  contributor bar chart. Risk cached per doc_id.
- Tests (`test_risk.py`, 6): empty→Low, email→Low, Aadhaar→Medium, three
  criticals→High, contributor sort order, density bump on dense docs.

**Self code review outcome**
- Confirmed determinism: same findings always yield the same level; all thresholds
  and weights sourced from `config.py` (single source).
- Density factor calibrated to not disturb small test sets (kicks in only at
  concentration > 3) — logged as D19.
- `ruff` clean; 38 tests green; app launches with the Risk tab.

**Definition of Done:** ✅ synthetic sets yield Low/Med/High deterministically with
explanations.

**Next:** Phase 6 — cited RAG question answering.

## Phase 6 — RAG Q&A ✅

**Completed**
- `redaction/masker.redact_text()`: single document-level span-redaction primitive
  (reused by RAG + P8 export).
- `rag/chunker.py`: sentence-unit splitting preserving page/line, greedy packing
  to ~500 tokens with ~10% overlap; each chunk redacted before emission.
- `rag/embeddings.py`: cached `LocalEmbedder` (MiniLM, normalized) — indexing uses
  no Gemini quota; `get_embedder()` shared singleton.
- `rag/store.py`: `FaissStore` IndexFlatIP over masked chunks, persisted per
  doc_id (`.faiss` + `.json`) so re-uploads are instant.
- `rag/qa.py`: `build_index()` and `answer_question()`. Counting questions answered
  from deterministic findings; free-text retrieves top-k, refuses below cosine
  floor (`rag_min_score`), else grounded Gemini synthesis with page/line citations;
  degrades to surfacing masked context when the LLM is unavailable/exhausted.
- `prompts.build_qa_prompt` + config `rag_min_score`.
- UI Chat tab: chat history per doc, answer + citations expander + non-grounded
  warning; records last model used into the sidebar panel.
- Tests (`test_rag.py`, 5): chunks contain no raw PII, counting via findings,
  out-of-scope refusal, grounded answer has citations, index persist+reload.

**Self code review outcome**
- Verified no raw values reach chunks/index (asserted on AWS key + email).
- Refusal path returns `grounded=False` and drops citations; degrade path keeps
  masked context only. Index cached on disk by doc hash (deterministic findings).
- `ruff` clean; 43 tests green; app launches with the Chat tab.

**Definition of Done:** ✅ grounded cited answers; refuses when unsupported;
counting matches the detector.

**Next:** Phase 7 — AI compliance summary with remediation.

## Phase 7 — AI Compliance Summary ✅

**Completed**
- `src/compliance.py`: `generate_summary()` builds a masked, PII-free brief (type
  counts + risk) and asks Gemini for a 3-section Markdown report (Compliance
  Observations w/ GDPR·DPDP·PCI-DSS, Security Risks, Recommended Remediation).
  `_template_summary()` deterministic fallback with a per-type regulation +
  remediation map so the feature never hard-fails.
- `prompts.build_compliance_prompt` grounded on the brief only.
- UI Summary tab: generate button, rendered markdown, Markdown download button;
  cached per doc_id.
- Tests (`test_compliance.py`, 5): template fallback structure, regulation
  references (PCI-DSS/DPDP), empty findings, LLM-used path with masked brief
  assertion, LLM-error → template fallback.

**Self code review outcome**
- Verified the brief passed to the LLM contains no raw values (asserted on a raw
  card number); summary grounded strictly in detected type counts.
- Fallback path exercised on both "no key" and "LLM raises" branches.
- `ruff` clean; 48 tests green; app launches with the Summary tab.

**Definition of Done:** ✅ one-click grounded summary referencing found types, with
downloadable report and working template fallback.

**Next:** Phase 8 — redaction & sanitized export.

## Phase 8 — Redaction & Sanitized Export ✅

**Completed**
- `redaction/masker.py`: generalized `redact_text(..., style)` + `replacement_for`
  supporting "mask" (partial value; used by RAG) and "placeholder"
  (`[REDACTED:TYPE]`); RAG path unchanged (default "mask").
- `redaction/export.py`: `redact_txt` (always), `redact_csv` (masks offending
  cells via the retained DataFrame), `redact_pdf` (PyMuPDF redaction annotations +
  `apply_redactions` — deletes underlying glyphs, not just covers them).
- UI Redaction tab: side-by-side original/redacted preview + per-format download
  buttons (TXT always; PDF/CSV when applicable).
- Tests (`test_redaction.py`, 4): TXT leaks no raw value + uses placeholder,
  mask/placeholder styles, CSV cell masking with header preserved, PDF underlying
  text truly removed (email + PAN gone after re-extraction).

**Self code review outcome**
- Confirmed true redaction (re-extracted PDF text contains no raw values).
- CSV masking operates per-cell on raw values; header row preserved.
- Exporters isolated in `export.py` with lazy `fitz` import so the detection path
  stays light; all build on the single masker primitives.
- `ruff` clean; 52 tests green; app launches with the Redaction tab.

**Definition of Done:** ✅ downloadable sanitized copy per format with zero leaked
values.

**Next:** Phase 9 — audit logging & multi-document support.

## Phase 9 — Audit Logging & Multi-Document Support ✅

**Completed**
- `src/audit.py`: append-only JSONL. `log_detection` (doc_id, type counts, risk
  level, model, latency), `log_query` (question hashed + length, grounded flag,
  model, latency), `read_recent`. Lock-guarded, best-effort writes; only masked
  metadata — never raw values or verbatim questions.
- `rag/qa.py`: extracted shared `_synthesize()`; added `answer_corpus()` merging
  retrieval across multiple document stores.
- UI multi-doc: `accept_multiple_files=True`, per-doc caches keyed by doc_id,
  sidebar document switcher, corpus-mode checkbox in Chat, sidebar Audit expander.
  Detection logged once per doc; each query logged with latency.
- Tests (`test_audit.py`, 4): detection event written, question hashed (no raw
  text), no raw values in detection log, recent limit + order; plus corpus
  counting test in `test_rag.py`.

**Self code review outcome**
- Verified no raw PII or verbatim questions reach the log (asserted email + card).
- Per-doc_id caches make document switching correct by construction; audit
  de-duped via an `audited_docs` set so re-render doesn't double-log.
- Audit file (`*.jsonl`) is gitignored. `ruff` clean; 57 tests green; app launches.

**Definition of Done:** ✅ audit populated & PII-free; multiple documents handled in
one session with a switcher + corpus mode.

**Next:** Phase 10 — Docker, deployment & documentation.

## Phase 10 — Dockerization, Deployment & Documentation ✅

**Completed**
- `Dockerfile` (python:3.11-slim, installs `tesseract-ocr`, deps, spaCy model,
  healthcheck, headless Streamlit on 8501); `docker-compose.yml` (port map, env,
  single `./runtime` volume for indexes+audit+quota state); `.dockerignore`;
  `packages.txt` (`tesseract-ocr`) for Streamlit Cloud; `.streamlit/config.toml`.
- `README.md` with all five MANDATORY sections: Setup, Architecture overview
  (diagram), AI/ML approach, Challenges faced, Future improvements — plus Docker,
  Streamlit Cloud deploy steps, and demo/deploy link placeholders.
- `RESULTS.md`: honest evaluation — 57 tests green, golden-file precision/recall
  1.00, invalid-Aadhaar rejection, and candid limitations.
- `DEMO_SCRIPT.md`: 2–5 min walkthrough script.

**Self code review outcome**
- `docker compose config` validates; env vars (`SDA_INDEX_DIR`,
  `SDA_AUDIT_LOG_FILE`, `SDA_RATE_LIMIT_STATE_FILE`) confirmed to map to settings.
- Fixed a volume pitfall (mounting a non-existent file → dir) by routing all
  runtime artifacts under one mounted `runtime/` directory.
- **Honest caveat:** a full `docker build`/`compose up` could not be executed here
  because the Docker daemon was not running; documented in RESULTS.md. Local app
  run, tests, and lint all verified.

**Definition of Done:** ⚠️ Docker/compose files complete & config-validated (build
not run — daemon down); README has all mandatory sections; tests green, ruff clean.
Deployment URL + demo video are user follow-ups.

**Project shipped.** Remaining external steps: local docker build verification,
Streamlit Cloud deploy + URL, demo video, verify live Gemini limits, `git push`.
