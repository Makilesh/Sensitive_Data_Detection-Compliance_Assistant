ROLE
You are verifying a real project end-to-end: Sensitive_Data_Detection-Compliance_Assistant.
Do not simulate or guess results. Only report what you actually ran and observed.

PHASE 1 — INVESTIGATE (do this before writing any test data)
1. Map the repo: entry points, core detection/classification modules, the compliance
   rule engine (if any), supported input formats (plain text, CSV, JSON, PDF, logs, etc.),
   and the output/report format (labels, risk score, redaction, structured JSON, etc.).
2. Read the README and any docstrings/comments for capability claims — list every
   sensitive data category the project claims to detect (e.g. SSN, credit card, email,
   phone, API keys/secrets, health records, IP addresses, addresses, financial account
   numbers, etc.). This claims list becomes the checklist you verify against later.
3. Check for existing test/sample data (test/, samples/, fixtures/, data/ dirs, etc.).
   List what's already covered. Do not duplicate it — you'll extend the gaps in Phase 2.

PHASE 2 — GENERATE SYNTHETIC TEST DATA
For every category from the claims checklist that lacks adequate coverage, generate
realistic but 100% fake data (no real PII, no real API keys/tokens — invalid but
correctly formatted, e.g. Luhn-invalid credit card numbers). Cover four buckets per
category, not just the happy path:
  a) True positives — clean, unambiguous instances of the category
  b) True negatives / decoys — values that look similar but aren't sensitive
     (e.g. order IDs vs SSNs, zip codes vs numeric IDs)
  c) Edge cases — sensitive values embedded in prose, logs, JSON payloads, or code;
     inconsistent formatting; multiple entity types in one document
  d) Adversarial cases — likely to trip false positives/negatives given how the
     detection logic actually works (base this on what you read in Phase 1, not guesses)
If the project supports multiple input formats, include at least one sample per format.
Save this dataset under a clearly labeled directory (e.g. test_data/synthetic/) with a
short manifest file mapping each sample to its expected classification/label.

PHASE 3 — EXECUTE
Run the actual detection/compliance pipeline against every sample programmatically.
Do not hand-summarize expected behavior — invoke the real code path exactly as a user
or API caller would. Capture raw output per sample.

PHASE 4 — REPORT (write to a NEW separate file: VERIFICATION_RESULTS.md — do not
edit README.md or existing docs)
Include:
  - Setup notes: how you ran it, any dependencies/config needed, anything you couldn't
    execute and why
  - Coverage table: claimed capability → tested? → existing sample or new synthetic?
  - Per-sample results table: input (truncated), expected label, actual output, pass/fail
  - Aggregate metrics where computable: precision, recall, F1, false positive rate,
    per-category breakdown
  - Bugs/gaps found — describe them, do NOT silently patch the code. Flag as
    "needs fix" and stop there unless I explicitly ask you to fix it.
  - Known limitations / untested paths (e.g. formats or categories you couldn't verify
    and why)

CONSTRAINTS
- Every number in the report must come from an actual execution, not an estimate.
- Keep synthetic data obviously fake — no real personal data, no working credentials.
- If existing test data already covers a category well, reuse it, note that you did,
  and don't regenerate it.
- If something in the pipeline can't be executed (missing API key, missing service,
  etc.), say so explicitly in the report instead of skipping it silently.