# RESULTS — Honest Evaluation

This document reports measured behavior on the bundled samples and states known
limitations candidly.

## Test Suite
- **57 tests, all green** (`pytest`), `ruff check .` clean.
- Coverage spans: config/models, ingestion (+OCR trigger), rate limiter &
  rotation, detection (checksums, golden counts, dedupe, NER, contextual),
  risk classification, RAG (chunking/store/QA/corpus), compliance summary,
  redaction export, and audit logging.

## Detection Accuracy — Golden File
`data/samples/golden.txt` contains 10 planted valid entities (one per required
deterministic category) plus **one intentionally invalid Aadhaar** (fails
Verhoeff) that must be rejected.

| Metric | Value |
|--------|-------|
| Entities planted (valid) | 10 |
| True positives | 10 |
| False positives | 0 |
| False negatives | 0 |
| Invalid Aadhaar correctly rejected | ✅ |
| **Precision** | **1.00** |
| **Recall** | **1.00** |

All nine required categories are detected; deterministic PII is validated by
checksum (Verhoeff/Luhn). These numbers reflect a small, curated golden file —
they demonstrate correctness of the detectors, not population-level accuracy.

## Ingestion
- Text PDF (2 pages), scanned image-only PDF, and a CSV with fake PII all load
  with page/line/column metadata.
- The scanned PDF yields 0 extractable characters and triggers the OCR fallback
  (verified via a mocked Tesseract call; a real binary is installed in Docker).

## RAG Q&A
- Counting questions match the deterministic detector exactly.
- Out-of-scope questions are refused (no hallucination) below the cosine floor.
- Grounded answers carry page/line citations; chunks contain **no raw PII**
  (asserted on an AWS key and an email).

## Rate-Limit Rotation
- Simulated 429s rotate to the next model; RPM/TPM/RPD windows block and free
  correctly under a fake clock; `AllModelsExhausted` is raised when all capped.

## Redaction
- TXT/CSV/PDF exports contain zero raw sensitive values; PDF redaction removes the
  underlying glyphs (verified by re-extracting text from the redacted PDF).

## Known Limitations
- **Model registry values are placeholders.** Free-tier RPM/TPM/RPD change often;
  verify at the Google rate-limits page before relying on them.
- **Phone/name detection is heuristic.** International phone formats and
  NER-derived names can miss or over-match; treat NER findings as low confidence.
- **Contextual (LLM) detection depends on quota.** When all models are exhausted
  or no key is set, the contextual pass and LLM answers degrade gracefully but are
  skipped/limited.
- **Golden-file metrics are illustrative**, not a benchmark over diverse
  real-world documents.
- **OCR quality** depends on scan resolution; low-DPI scans reduce recall.
