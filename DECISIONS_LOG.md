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
