# MASTER BUILD PROMPT — Sensitive Data Detection & Compliance Assistant

> Paste this whole document to your AI coding agent (Claude Code / Cursor / etc.) at the start.
> Build **one phase at a time**, in order. Do not begin a phase until the previous phase's
> "Definition of Done" checklist passes. After each phase, commit to git with the stated message.

---

## 0. ROLE & GROUND RULES

You are a **senior AI/ML engineer**. Build a production-quality **Sensitive Data Detection &
Compliance Assistant** as a **Streamlit** web app. The app ingests a document (PDF / TXT / CSV),
detects sensitive/confidential information, classifies overall risk, generates a compliance
summary, and answers user questions about the document via RAG.

**Hard constraints & conventions**

- **Language:** Python 3.11+.
- **UI:** Streamlit (single app, multi-section layout with tabs/sidebar).
- **LLM:** Google **Gemini** free tier ONLY. Use the `google-generativeai` SDK.
- **Rate-limit resilience is a first-class feature.** We are on the free tier where each model has
  its own RPM (requests/min), TPM (tokens/min), and RPD (requests/day) limits. Build a **model
  rotation layer** that automatically fails over from one Gemini model to the next when a model is
  rate-limited (HTTP 429 / `ResourceExhausted`) or its daily quota is exhausted. See Phase 3.
- **Secrets:** never hardcode keys. Read `GEMINI_API_KEY` from `.env` (via `python-dotenv`) locally
  and from `st.secrets` when deployed. Provide `.env.example`.
- **Code quality:** type hints everywhere, docstrings on public functions, module-level separation
  of concerns (no giant single file), `ruff`/`black` clean, meaningful names.
- **Determinism where it matters:** detection of structured PII (Aadhaar, PAN, card, etc.) MUST be
  regex/validator-based and deterministic — never rely on the LLM to "find" these. The LLM is used
  only for narrative summaries, contextual/confidential-info detection, and Q&A synthesis.
- **Never fabricate.** In Q&A, if retrieved context is insufficient, the assistant must say so
  rather than guess. Ground every answer in retrieved chunks and cite them.
- **Privacy:** sensitive values are masked by default anywhere they surface in the UI, logs, or the
  vector store. Raw values are only shown when the user explicitly toggles "reveal".
- **Tests:** each phase adds unit tests. Use `pytest`. Keep a growing suite that stays green.
- **Docs:** maintain **living documentation** — keep `PROJECT_PLAN.md`, `ARCHITECTURE.md`,
  `PROGRESS.md`, `DECISIONS_LOG.md`, and `README.md` continuously updated (see "Living
  Documentation" below).

**Architectural consistency rules (enforce throughout the entire project)**

- **Never duplicate business logic.** If the same logic is needed twice, extract it into one shared
  function/module and call it from both places.
- **Single source of truth per feature.** Each concern (detection patterns, risk thresholds, model
  registry, masking rules, prompts) lives in exactly one place — never re-declared or forked.
- **Keep modules loosely coupled.** Depend on small interfaces/data models (`src/models.py`), not on
  another module's internals. Ingestion, detection, classification, RAG, LLM, and UI must be
  swappable in isolation.
- **Separate responsibilities clearly.** `app.py` stays thin (UI only) and delegates; no business
  logic in the UI layer; no UI concerns inside `src/`.
- **Prefer composition over inheritance.** Compose small helpers/strategies; avoid deep class
  hierarchies unless a genuine is-a relationship exists.
- **Consistent naming conventions across the whole project.** `snake_case` for functions/vars/
  modules, `PascalCase` for classes, `UPPER_SNAKE` for constants; verbs for functions, nouns for
  data. Detectors, findings, and config keys use the same vocabulary everywhere.

**Challenge the specification when there is a materially better solution**

- Do **not** blindly follow every instruction if a significantly better engineering approach exists.
  When you spot one: (1) explain the issue, (2) explain why your proposal is better, (3) describe the
  trade-offs.
- If the change **significantly alters the architecture**, present the reasoning and **wait for
  approval** before implementing.
- **Minor** implementation improvements (better data structure, cleaner API, safer default) may be
  applied automatically — but always note what you changed and why in `DECISIONS_LOG.md`.

**Design patterns to borrow from the reference project**
(`github.com/Makilesh/ma-diligence-rag-engine` — an M&A due-diligence RAG engine):

- Deterministic numeric/structured verification instead of trusting the LLM.
- Graceful degradation & fallback layers (there: Qdrant→local disk, Postgres→in-memory; here:
  model rotation + regex fallback when LLM is unavailable).
- Token-budget / rate-limit governance per model with atomic accounting.
- Hallucination guarding: answer "I don't know" over confident guessing; cite sources.
- Structured, cited answer synthesis; clean separation of ingestion / processing / retrieval / UI.
- Honest reporting of limitations in the README.

---

## 0.5 MANDATORY PER-PHASE WORKFLOW (applies to EVERY phase below)

Every phase in this document must follow this exact workflow. **Never jump straight into writing
code.** The "Do" steps inside each phase are the *implementation* portion — they come only after the
reasoning gate below.

**A. Reason before coding.** Before writing any code for a phase, produce a short design brief:
1. **Goal** — restate what this phase must achieve.
2. **Architecture** — the modules, data flow, and interfaces you will introduce or touch, and how
   they fit the existing structure without violating the architectural consistency rules.
3. **Why this approach** — the reasoning behind the chosen design.
4. **Alternatives considered** — at least one or two other viable approaches.
5. **Why alternatives were rejected** — the concrete trade-offs that made you choose your design.

If this reasoning surfaces a materially better approach than the spec prescribes, invoke the
"Challenge the specification" rule from Section 0 before proceeding.

**B. Implement** — carry out the phase's "Do" steps and tests.

**C. Mandatory self code review (before declaring the phase complete).** Perform a structured
engineering review of everything you wrote in the phase, covering: **code quality, maintainability,
performance, security, error handling, edge cases, potential bugs, and refactoring opportunities.**
If the review identifies improvements, **apply them before marking the phase done** — do not defer.
Summarize the review outcome (issues found + fixes applied) in `PROGRESS.md`.

**D. Close out** — confirm the phase's "Definition of Done" checklist passes, update the living
documentation (Section 0.7), then commit with the stated message.

Only after D is complete may you begin the next phase.

---

## 0.6 LIVING DOCUMENTATION (keep current after every phase)

Maintain these four documents so they always reflect the **current** implementation state — update
them at the close of every phase, not at the end of the project:

- **`PROJECT_PLAN.md`** — the phase roadmap, scope, and status of each phase (done / in progress /
  pending). The authoritative plan of record.
- **`ARCHITECTURE.md`** — the live architecture: module responsibilities, data flow, interfaces,
  the current folder structure, and the target diagram. Update whenever a module or contract changes.
- **`PROGRESS.md`** — running log of what was completed each phase, the self-review outcome, and
  what's next.
- **`DECISIONS_LOG.md`** — every significant engineering decision and trade-off, including any spec
  challenges and any auto-applied minor improvements (with rationale).

`RESULTS.md` and `README.md` are produced/finalized in Phase 10 but may be started earlier.

---

## 0.7 LONG-CONVERSATION & CONTEXT MANAGEMENT (global)

This project will likely exceed a single conversation's context window. Manage context continuously
so work can resume seamlessly across conversations:

- **Track state as you go:** which phases are complete, what remains, the architecture decisions
  made, and the current folder structure — all reflected in the living docs (Section 0.6), which act
  as your durable memory.
- **Do not regenerate previously completed code** unless explicitly asked. Reuse existing
  implementations; extend rather than rewrite. Before writing new code, check whether a module/
  function already exists (single-source-of-truth rule).
- **When the conversation approaches the context limit,** automatically produce a **Continuation
  Summary** containing: completed phases, remaining phases, current architecture, key engineering
  decisions, current folder structure, outstanding TODOs, current implementation status, and the
  next recommended task.
- **Then emit a ready-to-paste Continuation Prompt** — a self-contained block the user can paste into
  a fresh Claude conversation to resume work with full context (it should reference the living docs
  as the source of truth and state exactly which phase/task to pick up next).

---

## 1. TARGET ARCHITECTURE (build toward this)

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
│  PDF/TXT/CSV    │            │  Regex validators +  │          │  chunk → embed →      │
│  + OCR fallback │──text──▶   │  spaCy NER + LLM      │          │  FAISS/Chroma →       │
│  (PyMuPDF,      │            │  contextual pass      │          │  retrieve → Gemini    │
│  pdfplumber,    │            │  → findings[]         │          │  synthesize + cite    │
│  Tesseract)     │            └──────────┬───────────┘          └───────────┬──────────┘
└─────────────────┘                       │                                  │
                                ┌──────────▼───────────┐                     │
                                │  Risk Classifier      │                     │
                                │  weighted scoring →   │                     │
                                │  Low / Medium / High  │                     │
                                └──────────┬───────────┘                     │
                                           │                                  │
                                ┌──────────▼──────────────────────────────────▼─────────┐
                                │      Gemini Model-Rotation Client (rate-limit aware)   │
                                │  registry of free-tier models · RPM/RPD tracker ·      │
                                │  429 failover · retry/backoff · local regex fallback   │
                                └──────────┬─────────────────────────────────────────────┘
                                           │
                                ┌──────────▼──────────┐
                                │  Audit Log (JSONL)   │  every detection & query, masked
                                └─────────────────────┘
```

**Suggested repo layout** (create in Phase 1, fill in over later phases):

```
sensitive-data-assistant/
├── app.py                     # Streamlit entrypoint (thin; delegates to src/)
├── src/
│   ├── config.py              # settings, model registry, thresholds (pydantic-settings)
│   ├── ingestion/
│   │   ├── loaders.py         # pdf/txt/csv loaders → normalized Document
│   │   └── ocr.py             # Tesseract OCR fallback for scanned PDFs/images
│   ├── detection/
│   │   ├── patterns.py        # regex + checksum validators (Aadhaar Verhoeff, PAN, Luhn…)
│   │   ├── ner.py             # spaCy NER pass (names, orgs, locations)
│   │   ├── llm_contextual.py  # LLM pass for confidential business info
│   │   └── engine.py          # orchestrates all detectors → Finding[]
│   ├── classification/
│   │   └── risk.py            # weighted risk scoring → Low/Medium/High
│   ├── redaction/
│   │   └── masker.py          # mask/redact + export sanitized copy
│   ├── rag/
│   │   ├── chunker.py         # text splitting
│   │   ├── embeddings.py      # embedding model wrapper
│   │   ├── store.py           # FAISS or Chroma index
│   │   └── qa.py              # retrieve + Gemini synthesis + citations
│   ├── llm/
│   │   ├── gemini_client.py   # model-rotation, rate-limit-aware client
│   │   ├── rate_limiter.py    # RPM/RPD tracking per model
│   │   └── prompts.py         # prompt templates
│   ├── models.py              # dataclasses/pydantic: Document, Finding, RiskReport…
│   └── audit.py               # JSONL audit logger (masked)
├── tests/
├── data/samples/              # sample docs with fake PII for demo/tests
├── .env.example
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── README.md
├── PROJECT_PLAN.md            # phase roadmap + status (living doc)
├── ARCHITECTURE.md            # live architecture, module map, folder structure (living doc)
├── DECISIONS_LOG.md           # engineering decisions & trade-offs (living doc)
└── PROGRESS.md                # per-phase progress + self-review outcomes (living doc)
```

---

## PHASE 1 — Project Scaffold & Config

**Goal:** runnable skeleton, dependency management, config, and a "hello" Streamlit app.

**Do:**
1. Create the repo layout above (empty modules with docstrings + `TODO`).
2. `requirements.txt` with pinned versions: `streamlit`, `google-generativeai`, `python-dotenv`,
   `pydantic`, `pydantic-settings`, `pandas`, `pymupdf`, `pdfplumber`, `spacy`, `pytesseract`,
   `pillow`, `faiss-cpu` (or `chromadb`), `sentence-transformers`, `tiktoken`, `pytest`, `ruff`,
   `black`. Add `python -m spacy download en_core_web_sm` to setup docs.
3. `src/config.py`: `Settings` via `pydantic-settings` — reads `GEMINI_API_KEY`, thresholds, the
   **model registry** (list of Gemini models with per-model RPM/RPD placeholders), embedding model
   name, chunk sizes, redaction defaults.
4. `src/models.py`: define `Document`, `Finding` (type, value_masked, value_raw, span, page,
   confidence, detector), `RiskReport`, `QAResult` (answer, citations[], grounded: bool).
5. `.env.example` with `GEMINI_API_KEY=`.
6. `app.py`: minimal Streamlit with title, sidebar, and a file-uploader stub (no processing yet).
7. Init git; add `.gitignore` (`.env`, `__pycache__`, index files, `*.jsonl`).
8. Scaffold the living docs: `PROJECT_PLAN.md` (the 10-phase roadmap with statuses),
   `ARCHITECTURE.md` (initial module map + folder structure + target diagram), `PROGRESS.md`, and
   `DECISIONS_LOG.md`. These must be updated at the close of every subsequent phase.

**Definition of Done:** `streamlit run app.py` launches; `pytest` runs (even if 0 tests);
`ruff check .` clean; the four living docs exist and reflect the current state. **Commit:**
`chore: project scaffold and config`.

---

## PHASE 2 — Document Ingestion (PDF / TXT / CSV + OCR)

**Goal:** turn any supported upload into normalized text with page/line metadata.

**Do:**
1. `ingestion/loaders.py`:
   - **PDF:** stream pages with **PyMuPDF** (memory-flat, page-by-page); capture per-page text and
     page numbers. Use **pdfplumber** as a secondary path for tables (CSV-like content in PDFs).
   - **TXT:** read with encoding detection (`chardet`/`charset-normalizer`); keep line numbers.
   - **CSV:** load with **pandas**; expose both a text serialization (for detection/RAG) and the
     DataFrame (so column-level detection can name the offending column).
   - Return a normalized `Document` (full text + list of segments with `{page/line/col, text}`).
2. `ingestion/ocr.py`: if a PDF page yields little/no extractable text (scanned), render the page to
   an image (PyMuPDF) and OCR with **pytesseract**. Make OCR a toggle in config (needs Tesseract
   installed — document it).
3. Wire uploader in `app.py` to call the loader and show extracted text length, page count, and a
   preview.

**Tests:** put 3 tiny sample files in `data/samples/` (a text PDF, a scanned-image PDF, a CSV with
fake PII). Assert each loads, page/line metadata present, OCR path triggers on the scanned PDF.

**DoD:** all three formats load and preview in the UI; OCR fallback works on the scanned sample.
**Commit:** `feat: multi-format ingestion with OCR fallback`.

---

## PHASE 3 — Gemini Model-Rotation Client (rate-limit engine) ★ core differentiator

**Goal:** a single client that transparently rotates across free-tier Gemini models to survive RPM /
TPM / RPD limits. This is the feature the user specifically asked for — make it robust and visible.

**Do:**
1. `llm/rate_limiter.py`:
   - Track per-model usage: a **sliding-window RPM** counter (timestamps in the last 60s), a **TPM**
     estimate (sum of prompt+response tokens in the last 60s, tokens via `tiktoken` or the SDK's
     `count_tokens`), and a **daily RPD** counter that resets at midnight (store counts in a small
     JSON file so they survive restarts within a day).
   - `can_use(model) -> bool` and `record(model, tokens)`; make increments atomic (threading lock)
     to avoid TOCTOU overshoot (mirror the reference repo's atomic budget pattern).
2. `llm/gemini_client.py`:
   - Read the **model registry** from config: an ordered list, e.g.
     `[gemini-2.5-flash, gemini-2.5-flash-lite, gemini-2.0-flash, gemini-2.0-flash-lite,
       gemini-1.5-flash, gemini-1.5-flash-8b]` — each with its own RPM/RPD from config.
     **IMPORTANT:** free-tier model names and limits change often; do NOT hardcode numbers in code —
     put them in `config.py`/YAML and tell me to verify current values at
     `https://ai.google.dev/gemini-api/docs/rate-limits`. Treat the list as the priority order:
     highest-capability model first, cheapest/most-generous quota as later fallbacks.
   - `generate(prompt, *, json=False, max_tokens=...)`:
     1. Pick the first model where `rate_limiter.can_use(model)` is true.
     2. Call it. On `429`/`ResourceExhausted`/quota errors, mark that model cooling-down and move to
        the next model. On transient 5xx, retry with exponential backoff (e.g. 3 tries) before
        rotating.
     3. If **all** models are exhausted, either wait for the soonest RPM window to free up (short
        waits only) or raise a typed `AllModelsExhausted` error the callers can degrade on.
   - Record token usage after each successful call.
   - Optional embeddings via Gemini too, but prefer a **local** `sentence-transformers` embedder
     (Phase 6) so RAG indexing doesn't burn LLM quota.
3. Surface state in the UI: a sidebar panel showing each model's remaining RPM/RPD and which model
   served the last call (great for the demo video).

**Tests:** simulate 429s (monkeypatch the SDK call) and assert the client rotates to the next model;
assert RPM window blocks a model after N calls and frees after 60s (use a fake clock); assert
`AllModelsExhausted` raised when everything is capped.

**DoD:** forced-429 test rotates correctly; UI shows live per-model quota. **Commit:**
`feat: rate-limit-aware Gemini model rotation client`.

---

## PHASE 4 — Sensitive Data Detection Engine

**Goal:** detect every required entity type deterministically first, LLM only for fuzzy/contextual.

**Required entity types & method:**

| Entity | Method |
|---|---|
| Aadhaar number | Regex `\b\d{4}\s?\d{4}\s?\d{4}\b` + **Verhoeff checksum** validation to cut false positives |
| PAN number | Regex `\b[A-Z]{5}[0-9]{4}[A-Z]\b` + structural rules |
| Email | Regex (RFC-ish) |
| Phone (India + intl) | Regex with country-code handling; validate length |
| Credit card | Regex + **Luhn** checksum; identify network (Visa/MC/Amex) |
| Bank details | IFSC regex `^[A-Z]{4}0[A-Z0-9]{6}$`, account-number heuristics, keyword proximity ("A/C", "IFSC") |
| API keys / passwords | High-entropy string detection + provider patterns (AWS `AKIA…`, `sk-…`, `ghp_…`, JWT, `password=…`) |
| Employee IDs | Configurable pattern (e.g. `EMP\d{4,6}`); make the pattern set config-driven |
| Confidential business info | **LLM contextual pass** (via Phase 3 client) — flags NDAs, financials, M&A/change-of-control, litigation, trade secrets; returns spans + rationale |

**Do:**
1. `detection/patterns.py`: all regexes + checksum validators (Verhoeff, Luhn) as pure, tested
   functions returning `Finding` objects with character spans, page/line, and a confidence.
2. `detection/ner.py`: spaCy `en_core_web_sm` pass for PERSON / ORG / GPE names (context for
   confidential info + risk). Keep it optional/fast.
3. `detection/llm_contextual.py`: prompt Gemini (JSON-mode) to find confidential business info the
   regexes can't; **strictly** return structured findings, and never invent values — must quote text
   actually present. If the LLM is unavailable (all models exhausted), skip gracefully and note it.
4. `detection/engine.py`: run all detectors, de-duplicate overlapping spans (prefer
   deterministic > LLM when they overlap), attach detector provenance, mask values immediately.
5. UI "Findings" tab: table grouped by entity type with counts, page/line, masked value, detector,
   confidence; a per-row "reveal" toggle.

**Tests:** golden file with known planted PII → assert exact counts per type; assert Verhoeff/Luhn
reject invalid numbers; assert overlapping-span dedupe; assert graceful skip when LLM is down.

**DoD:** all 9 categories detected on the sample; deterministic ones have checksum validation;
counts are exact on the golden file. **Commit:** `feat: deterministic + contextual detection engine`.

---

## PHASE 5 — Risk Classification

**Goal:** map findings to an overall **Low / Medium / High** risk with an explainable score.

**Do:**
1. `classification/risk.py`: weighted scoring. Assign per-type severity weights (e.g. Aadhaar/card/
   bank/API-key = high; email/phone/employee-id = medium; names alone = low) and combine with counts
   and density (per-page concentration). Produce: overall label, numeric score, and a **breakdown**
   explaining what drove the level (top contributors).
2. Thresholds live in `config.py` (tunable). Keep the mapping deterministic and documented.
3. UI "Risk" tab: big Low/Med/High badge (color-coded), the score, and the contributor breakdown
   as a small bar chart.

**Tests:** craft finding sets that must yield each level; assert thresholds and that the breakdown
lists correct top contributors.

**DoD:** three synthetic docs produce Low/Med/High deterministically with explanations.
**Commit:** `feat: explainable risk classification`.

---

## PHASE 6 — RAG Q&A over the document

**Goal:** grounded, cited question answering. No hallucination.

**Do:**
1. `rag/chunker.py`: sentence-boundary-aware splitting (~500 tokens, ~10% overlap); carry
   page/line metadata into each chunk. For CSV, chunk by row-groups keeping headers.
2. `rag/embeddings.py`: local `sentence-transformers` (e.g. `all-MiniLM-L6-v2` or `bge-small`) so
   indexing doesn't consume Gemini quota. **Embed the MASKED text** (never store raw PII in the
   vector index).
3. `rag/store.py`: **FAISS** (or Chroma) index built per uploaded document; store chunk text +
   metadata; persist to disk keyed by a document hash so re-uploads are instant.
4. `rag/qa.py`: retrieve top-k → build a grounded prompt → call the Phase 3 Gemini client →
   return `QAResult` with the answer, **citations** (page/line of source chunks), and a `grounded`
   flag. If retrieval is weak/empty, return an honest "I don't have enough information in this
   document" refusal. For counting questions ("how many emails?"), answer from the **deterministic
   findings**, not the LLM, then let the LLM phrase it.
5. UI "Chat" tab: chat interface; show answer + expandable citations; show which Gemini model
   answered. Support the sample questions from the assignment
   ("What sensitive data exists?", "How many email addresses?", "Summarize this document",
   "What compliance risks are identified?").

**Tests:** ask a question whose answer is in the doc → assert citation points to correct page;
ask an out-of-scope question → assert refusal; assert counting questions match Phase-4 counts.

**DoD:** grounded answers with citations; refuses when unsupported; counts match the detector.
**Commit:** `feat: cited RAG question answering`.

---

## PHASE 7 — AI Compliance Summary

**Goal:** the assignment's required summary: compliance observations, security risks, remediation.

**Do:**
1. Add a summary generator (in `rag/qa.py` or `detection/`) that feeds the LLM a **structured brief**
   built from findings + risk report (masked), and asks for: (a) compliance observations
   (reference GDPR / India DPDP Act / PCI-DSS where relevant), (b) concrete security risks,
   (c) prioritized remediation steps. Output structured markdown.
2. Ground it in the actual findings (pass counts/types), and require it to avoid inventing data.
   If LLM unavailable, produce a deterministic template summary from findings so the feature never
   hard-fails.
3. UI "Summary" tab: render the markdown; add a "Download report" button (markdown/PDF).

**Tests:** assert the summary references the entity types actually found; assert template fallback
works with LLM disabled.

**DoD:** one-click compliance summary grounded in findings, with a downloadable report.
**Commit:** `feat: AI compliance summary with remediation`.

---

## PHASE 8 — Redaction / Masking & Sanitized Export

**Goal:** produce a safe, shareable copy of the document with sensitive data removed.

**Do:**
1. `redaction/masker.py`: given findings + original text, replace each sensitive span with a
   placeholder (`[REDACTED:AADHAAR]`) or partial mask (`XXXX-XXXX-1234`), configurable.
2. Export sanitized outputs: redacted **TXT** always; redacted **PDF** (draw black boxes over spans
   using PyMuPDF where coordinates are known, else regenerate text PDF); redacted **CSV** (mask
   offending cells).
3. UI "Redaction" tab: preview redacted text side-by-side and download the sanitized file.

**Tests:** assert no raw sensitive value survives in the redacted output; assert partial-mask format.

**DoD:** downloadable sanitized copy for each format with zero leaked values.
**Commit:** `feat: redaction and sanitized export`.

---

## PHASE 9 — Audit Logging & Multi-Document Support

**Goal:** traceability + handle more than one document.

**Do:**
1. `audit.py`: append-only **JSONL** log of every detection run and every Q&A query — timestamp,
   doc hash, entity-type counts (NOT raw values), risk level, model used, latency. Masked only.
2. Multi-document: let the user upload several docs in a session; keep a per-doc index and findings;
   add a document selector; optionally a "corpus" mode that queries across all docs (retrieve from
   each index and merge). Persist indexes keyed by doc hash.
3. UI: a small "Audit" expander showing recent runs; a document switcher in the sidebar.

**Tests:** assert audit entries are written and contain no raw PII; assert switching documents
swaps findings/index correctly.

**DoD:** audit log populated & PII-free; multiple documents handled in one session.
**Commit:** `feat: audit logging and multi-document support`.

---

## PHASE 10 — Dockerization, Deployment & Documentation (submission-ready)

**Goal:** meet every MANDATORY submission requirement.

**Do:**
1. `Dockerfile` (install Tesseract + spaCy model in the image) and `docker-compose.yml`
   (`streamlit run app.py` on 8501; mount a volume for indexes/audit). Verify `docker compose up`
   serves the app.
2. **Deploy** to **Streamlit Community Cloud** (free) — set `GEMINI_API_KEY` in app secrets; ensure
   `packages.txt` installs `tesseract-ocr` if OCR is enabled on the host. Provide the live URL.
3. `README.md` covering all MANDATORY sections: **Setup instructions**, **Architecture overview**
   (include the diagram), **AI/ML approach used** (deterministic detection + spaCy NER + Gemini
   contextual + local-embedding RAG + rate-limit rotation), **Challenges faced** (free-tier rate
   limits & the rotation solution, checksum false positives, OCR on scans, grounding/refusal),
   **Future improvements**. Add a demo-video link placeholder.
4. Finalize the living docs: ensure `PROJECT_PLAN.md`, `ARCHITECTURE.md`, `DECISIONS_LOG.md`, and
   `PROGRESS.md` reflect the shipped implementation, and add `RESULTS.md` (honest evaluation: run the
   sample docs, report detection precision/recall on the golden file, note limitations — mirror the
   reference repo's honest-reporting style).
5. Record a **2–5 min demo video** script: upload → findings → risk → summary → chat (show a
   citation + a refusal) → redaction download → show the model-rotation sidebar under load.

**DoD:** `docker compose up` works; live deployment URL loads; README has all mandatory sections;
tests green. **Commit:** `docs: deployment, README, and submission materials`.

---

## FINAL VERIFICATION CHECKLIST (run before submitting)

- [ ] Upload works for PDF, TXT, CSV; OCR fallback works on a scanned PDF.
- [ ] All 9 sensitive-data categories detected; Aadhaar/card validated by checksum.
- [ ] Risk shows Low/Med/High with an explainable breakdown.
- [ ] Compliance summary lists observations, risks, remediation — grounded in findings.
- [ ] Q&A answers are cited and refuse when unsupported; counting questions match the detector.
- [ ] Redaction produces a sanitized file with zero leaked values.
- [ ] Model rotation demonstrably fails over on 429 and shows live per-model quota.
- [ ] Audit log is populated and contains no raw PII.
- [ ] Multi-document switching works.
- [ ] `pytest` green; `ruff` clean; Docker builds; live URL loads.
- [ ] README has all 5 mandatory sections + demo video link + deployment link.
- [ ] No secrets committed; `.env` gitignored.
- [ ] Every phase followed the reason-before-code workflow and passed a self code review.
- [ ] `PROJECT_PLAN.md`, `ARCHITECTURE.md`, `PROGRESS.md`, `DECISIONS_LOG.md` all reflect the final
      shipped state.

---

## NOTES YOU MUST HONOR

- Verify current Gemini free-tier model names & limits at
  `https://ai.google.dev/gemini-api/docs/rate-limits` before finalizing the model registry — do not
  trust hardcoded numbers.
- Keep raw sensitive values out of logs, the vector index, and the UI (unless explicitly revealed).
- Prefer "I don't know" over hallucination on every LLM path.
- Do not copy the reference repo wholesale — reuse *patterns*, write original code for this problem.
- Follow the Section 0.5 workflow for every phase (reason → implement → self-review → close out);
  never jump straight to code.
- Honor the architectural consistency rules (Section 0) on every change — no duplicated logic, one
  source of truth per feature, loose coupling, consistent naming.
- Update all four living docs (Section 0.6) at the close of each phase so they always reflect the
  current state.
- When nearing the context limit, emit the Continuation Summary + Continuation Prompt (Section 0.7)
  so work can resume in a fresh conversation without regenerating completed code.
```
