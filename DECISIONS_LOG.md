# DECISIONS LOG

Significant engineering decisions, trade-offs, spec challenges, and auto-applied
minor improvements — with rationale.

## Phase 1

- **D1 — Config via `pydantic-settings` as single source of truth.** All tunables
  (model registry, thresholds, weights, chunking, redaction) live in `config.py`,
  never redeclared. Rationale: enforces the single-source-of-truth rule and gives
  typed validation. Trade-off: a small amount of boilerplate vs. plain dicts.

- **D2 — Model registry as data, not code.** Free-tier model names/limits change
  often, so they live in `DEFAULT_MODEL_REGISTRY` (config) with a `ModelSpec`
  type, and business logic reads them. **Action required:** verify current values
  at https://ai.google.dev/gemini-api/docs/rate-limits before finalizing.

- **D3 — Dataclasses (not pydantic) for `Finding`/`Document`.** These are hot,
  in-memory transfer objects; stdlib dataclasses are lighter and need no
  validation overhead. Pydantic is reserved for settings/boundary validation.

- **D4 (minor, auto-applied) — `StrEnum` instead of `(str, Enum)`.** Ruff UP042.
  Cleaner string semantics for JSON/logging/UI; requires Python 3.11+, which the
  project already targets.

- **D5 — `Finding.value_raw` kept in-memory only.** Privacy rule: raw values never
  reach logs, the vector index, or the UI unless explicitly revealed. Masking is
  applied at detection time; surfaces use `value_masked`.

- **D6 — Env prefix `SDA_` with `GEMINI_API_KEY` aliased.** Namespaces our own
  settings while keeping the conventional secret name. Verified the alias reads
  the unprefixed variable.

## Phase 2

- **D7 — Single `load_document()` dispatch by extension.** One ingestion entry
  point returning `Document`; UI/detection depend only on that contract.
- **D8 — Retain the CSV DataFrame in `Document.metadata`.** Enables column-level
  detection (naming the offending column) without re-parsing. Trade-off: keeps a
  DataFrame in memory; acceptable for single-doc processing.
- **D9 — OCR isolated + config-gated, replaces text only if it yields more.**
  Ingestion degrades gracefully when Tesseract is absent (local env has no
  binary); Docker image installs it (P10).

## Phase 3

- **D10 — Sliding-window RPM/TPM in memory, RPD persisted.** 60s windows are
  ephemeral (safe to lose on restart); the daily counter must survive restarts so
  it is written to a small JSON keyed by date. Rationale: correctness of the daily
  cap without a database.
- **D11 — Injectable clock + isolated `_invoke_sdk`.** Makes the entire rotation
  engine deterministically testable (fake clock, simulated 429/5xx) with no
  network or SDK dependency in tests.
- **D12 — Raise `AllModelsExhausted` instead of long blocking waits.** Predictable
  behavior and lets callers degrade to deterministic fallbacks; `seconds_until_
  available` is exposed for optional short waits/UI but not used to block.
- **D13 — Error classification by status code + class name + message.** Robust to
  the SDK not being importable in tests and to message-only rate-limit signals.

## Phase 4

- **D14 — Masking centralized in `redaction/masker.mask_value`.** Detection imports
  it so masking rules exist in exactly one place (reused by P8 export). Coupling
  detection→redaction is acceptable; both only depend on `models`.
- **D15 — Low base confidence + checksum boost for Aadhaar/card.** Regex-only
  matches score 0.4; a passing Verhoeff/Luhn raises to 0.99. Encodes that the
  checksum, not the regex, is what makes these trustworthy.
- **D16 (minor, auto-applied) — Global "reveal" checkbox instead of per-row
  toggle.** Cleaner in Streamlit and identical privacy guarantee (masked by
  default, explicit opt-in). Spec suggested per-row; deviation noted here.
- **D17 — Overlap dedupe by (span length, detector trust, confidence).** Ensures a
  real card is not shadowed by a coincidental Aadhaar/LLM span; deterministic
  detectors outrank NER/LLM on ties.
- **D18 — LLM snippets verified verbatim against source text.** Any snippet not
  found by exact substring match is discarded — concrete anti-hallucination guard.

## Phase 8

- **D24 — True PDF redaction via `apply_redactions()`.** Redaction annotations
  remove the underlying glyphs, so exported PDFs cannot leak values by copy-paste
  or re-extraction (verified by test). OCR-only pages fall back to the safe TXT
  export since coordinates are unavailable.
- **D25 — Exporters in `redaction/export.py`, primitives in `masker.py`.** Keeps
  masking rules single-sourced while isolating heavy `fitz`/`pandas` usage (lazy
  imports) from the detection path that only needs `mask_value`/`redact_text`.

## Phase 6

- **D20 — Embed MASKED text only.** Chunks are redacted before embedding so raw
  PII never enters the vector store or disk. Segment-level redaction preserves
  page/line metadata for citations.
- **D21 — Local sentence-transformers for embeddings.** Keeps RAG indexing off the
  Gemini free-tier quota (which is reserved for synthesis/contextual detection).
- **D22 — Counting questions answered from deterministic findings.** "How many
  emails?" must equal the detector, so it bypasses the LLM entirely; the LLM only
  phrases free-text answers.
- **D23 — Cosine-floor refusal + persisted FAISS keyed by doc hash.** Retrieval
  below `rag_min_score` triggers an explicit "not enough information" refusal
  (no guessing); indexes persist per doc_id for instant re-uploads.

## Phase 5

- **D19 — Mild, thresholded density factor.** `1 + 0.1·max(0, findings/pages − 3)`
  so concentration only raises risk for genuinely dense documents and never
  destabilizes the base weighted score. Thresholds recalibrated to Medium 10 /
  High 30 so a single critical entity is at least Medium.
