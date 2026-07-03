# DECISIONS LOG

Significant engineering decisions, trade-offs, spec challenges, and auto-applied
minor improvements — with rationale.

## Post-build — Address completeness (PIN code + house/age number leaks)

A real Aadhaar showed the postal PIN code (`630302`) and the age/house-number
immediately after "S/O: <father>," surviving redaction — both **deterministic,
model-independent** fixes:

- **D48 — Two new PIN-code detectors.** `pincode-keyword` (`PIN Code:` / `Pincode:`
  / `Pin:` + 6 digits) and `pincode-suffix` (the `"<State> - NNNNNN"` idiom common
  at the end of an address line on Indian ID cards, anchored to end-of-line to
  avoid matching unrelated dash-separated numbers). Both classified `LOCATION`
  (no new entity type needed).
- **D49 — Positional address-number detector (`_detect_trailing_address_numbers`
  in engine.py).** A bare 1–3 digit number immediately followed by a comma, right
  after ANY detected PERSON finding — regardless of which detector found that
  person (regex, spaCy, or the multilingual LLM pass) or what script the name is
  in. This is why it's positional rather than a language-specific regex: it also
  catches the number following a Tamil name that only the LLM pass can read.
  Whitespace matching spans newlines, since PDF extraction often puts each
  comma-separated address field on its own line even though it renders as one
  visual line. Classified `LOCATION` (address component, not identity data alone).
  Runs after all PERSON-producing detectors, before dedupe.
- Both fixes are deterministic — they work identically whether or not an LLM call
  succeeds, unlike the multilingual place-name detection (D40–D43) which depends
  on the Gemini verification pass and can vary by which model in the rotation
  serves the call. Regression tests: `tests/test_address_completeness.py` (10).

## Post-verification bug fixes (from VERIFICATION_RESULTS.md §4)

- **D35 — Dedup ranks trust before span length (critical).** `engine._dedupe`
  sorted `(span_len, rank, conf)`, so a longer low-trust spaCy/LLM span could evict
  an inner deterministic finding (reproduced: spaCy tagged `email=alice@example.com`
  as ORG and dropped the EMAIL). Reordered to `(rank, span_len, conf)`. Equal-rank
  overlaps (CREDIT_CARD vs AADHAAR, both rank 5) still fall back to span length, so
  the card still wins. Regression tests added.
- **D36 — LLM JSON parsed with `strict=False` (high).** `_parse_findings` used
  strict `json.loads`, which rejects literal newlines/tabs inside string values and
  silently returned `[]` — dropping multi-line confidential snippets. `strict=False`
  tolerates control chars in strings (a safe superset).
- **D37 — Case-insensitive PAN / IFSC / EMPLOYEE_ID (medium).** Added
  `re.IGNORECASE` to the PAN/IFSC specs and `(?i)` to the default `employee_id_
  pattern` so lowercase occurrences are caught. `value_raw` preserves original case.
- **D38 — Password label may be quoted (medium).** Regex now allows optional quotes
  around the `password` label (`'password': '…'`), matching JSON/dict-style creds;
  the length≥4 guard still skips empty passwords.
- **D39 — Conservative international phone (low).** Added a second PHONE spec
  requiring a leading `+country` code (`\+\d{1,3}(?:[\s-]?\d){6,12}`); the mandatory
  `+` prefix keeps false positives low. Indian spec remains primary (higher rank).

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

## Post-build — Optional reranker + privacy local-only mode

- **D33 — Cross-encoder reranker as an opt-in, GPU-aware toggle.** Off by default so
  the fast path is unaffected. When on, `_retrieve()` pulls a larger pool then
  reranks with a `CrossEncoder`. Model choice is GPU-aware: lightweight
  `ms-marco-MiniLM-L-6-v2` on CPU, auto-upgrade to `bge-reranker-v2-m3` when CUDA is
  present (needs a CUDA torch build). Reranker only reorders — the returned score
  stays the dense cosine, so the `rag_min_score` refusal contract is preserved
  (verified). Loads lazily and degrades to unranked hits on any failure. No new
  dependency (`sentence-transformers` ships `CrossEncoder`).
- **D34 — Privacy local-only mode.** A config flag + runtime sidebar toggle that
  makes `_provider_available()` block all cloud Gemini models, forcing the local
  Ollama backend so no document-derived text (even masked) leaves the machine —
  a strong compliance option for the most sensitive documents. Reuses the existing
  provider-gating seam; `is_configured` degrades correctly if no local backend.

## Post-build — Real-document hardening (from a live Aadhaar test)

- **D40 — VID + DOB detectors + new entity types.** A real Aadhaar leaked its
  16-digit Virtual ID (survived redaction) and DOB. Added `EntityType.VID` /
  `EntityType.DOB`, keyword-anchored detectors (`\bVID\b`, `DOB:`), severity
  weights, masking (DOB fully masked), and compliance guidance. Keying on the
  label avoids card/date false positives.
- **D41 — Deterministic name detection (`detection/names.py`).** spaCy misses
  Indian/transliterated names ("Makilesh M") while mislabelling "Tamil Nadu" as a
  person. Rather than ship a heavy NER model (deploy memory), names are caught by
  document *structure* that generalizes across IDs, bank statements, HR records,
  invoices, and letters: field labels (`Name:`, `Account Holder:`), relation
  prefixes (`S/O`, `D/O`), salutations (`Mr.`, `Smt.`), and addressees (`To`). The
  addressee scan skips non-Latin lines so it reaches the romanized name on IDs.
- **D42 — Occurrence-complete redaction (`masker.redact_all_occurrences`).**
  Detection may match a repeated value once, but a sanitized export must leave no
  occurrence. TXT export now replaces every occurrence of each detected value
  (longest-first, alphanumeric-boundary guarded to avoid substring over-redaction)
  — mirroring what the PDF export already does via `search_for`. Findings stay
  distinct (clean counts/table); redaction is exhaustive.
- **D43 — NER value-dedup + inventory intent.** Repeated spaCy tokens (a town
  printed 5× on an ID) collapse to one finding; "what sensitive data exists?" is
  answered deterministically from findings instead of wrongly refusing.
- **Known limitation:** spaCy `en_core_web_sm` still over-tags some geographic
  terms (over-redaction, never a leak). A transformer NER (`en_core_web_trf`) would
  fix precision but is too heavy for the free-tier deploy — logged as a future
  improvement.

## Post-build — Manual sample review (all 9 categories)

Ran 9 realistic sample docs (KYC, PAN form, emails, bank statement, invoice,
config file, payslip, NDA, CSV) through the full pipeline. Fixes:

- **D44 — DOB written forms.** "15 August 1985" / "Aug 15, 1985" now detected
  (previously only `DD/MM/YYYY`), keyed on the DOB label so other dates are safe.
- **D45 — First/Last/Given/Surname labels.** Added to the name detector so split
  name fields are caught, not just "Name:".
- **D46 — OpenAI project keys.** `sk-proj-…` (dashes) now matched by the dedicated
  `openai-key` detector (previously only caught via the `api_key:` label).
- **D47 — LLM contextual: truncation + whitespace tolerance (recall bug).** The
  NDA returned **zero** confidential findings because (a) the JSON was truncated at
  `max_output_tokens` → parse failed, and (b) the verbatim-snippet guard rejected
  snippets whose mid-sentence newlines the LLM had normalized. Fixed by raising the
  budget to 2048, salvaging complete objects from truncated JSON, and a
  whitespace-tolerant `_locate_snippet` that maps back to the original offsets.
  This also lifts the previously-low CONFIDENTIAL_INFO recall. Anti-hallucination
  guarantee preserved (snippet must still exist in the source modulo whitespace).
- Regression tests: `test_manual_samples.py` (per-file coverage + decoy rejection
  + redaction leak checks) and `test_llm_contextual.py` (parse/locate). 119 total.

## Post-build — Hybrid RAG (borrowed from ma-diligence-rag-engine)

- **D30 — Adopt hybrid dense+sparse retrieval with RRF.** The reference repo's
  flagship RAG technique. Added an in-house Okapi `BM25` + `reciprocal_rank_fusion`
  (`src/rag/lexical.py`, stdlib only — no new dependency) and `FaissStore.
  search_hybrid()`. Rationale: exact tokens (field labels like "IFSC", "employee
  id", "password") are matched by BM25 while embeddings handle semantics — directly
  relevant to sensitive-data docs. BM25 is rebuilt from persisted chunk text on
  load (no extra files). Toggle: `enable_hybrid_search`.
- **D31 — Preserve the cosine-based grounding contract under hybrid.** RRF sets the
  *ordering*, but the returned score stays the absolute dense cosine, so the
  `rag_min_score` refusal gate keeps its meaning and out-of-scope questions still
  refuse (verified by test).
- **D32 — Deliberately did NOT adopt** the reference's cross-encoder reranker
  (bge-reranker-v2-m3), bge-m3 1024-d embeddings, parent-child expansion, or the
  LangGraph/Qdrant/query-rewrite machinery. Rationale: heavy models + latency +
  VRAM for marginal gain on short compliance docs; MiniLM + hybrid + refusal is
  the right cost/quality point for this app. These remain easy future add-ons.

## Post-build — Model registry update + local Ollama fallback

- **D28 — Refreshed Gemini registry to user-provided current free-tier models.**
  Priority order tuned for this workload (JSON extraction + RAG synthesis):
  `gemini-3.5-flash` (10 RPM / 1500 RPD) → `gemini-3.1-flash-lite` (15/1000) →
  `gemini-2.5-flash` (10/250) → `gemini-3.1-pro-preview` (5/100) →
  `gemini-2.5-pro` (5/100). Lead with high-RPD flash tiers to survive limits; keep
  pro tiers as mid fallbacks. Values still to be re-verified at the rate-limits URL.
- **D29 — Local Ollama as the final, quota-free rotation fallback.** Added a
  `provider` field to `ModelSpec`; `Settings` appends an Ollama entry
  (default `qwen2.5:14b`) to the single `model_registry` so the rotation loop stays
  uniform (cloud first, local last). `ModelSpec` chosen for a 12GB-VRAM GPU
  (RTX 5070 Ti): qwen2.5:14b (~9GB Q4) has strong instruction-following/JSON;
  reasoning models (deepseek-r1) and >12GB models (gpt-oss:20b) were rejected as
  poorer fits for clean structured output / VRAM budget. The client dispatches by
  provider (`_invoke_ollama` uses stdlib `urllib`, no new dependency) and
  `is_configured` is true if *any* backend (Gemini key or Ollama) is available —
  so the app runs fully offline with no Gemini key.

## Phase 9

- **D26 — Hash questions in the audit log.** User questions may themselves contain
  PII, so only a sha256[:12] + length is stored, never the verbatim text — keeps
  the log PII-free while preserving de-dup/traceability.
- **D27 — Per-doc_id caches are the multi-doc mechanism.** Findings/risk/store/
  summary caches keyed by content hash mean switching documents is inherently
  correct and re-uploads are instant; corpus mode merges the per-doc stores.

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
