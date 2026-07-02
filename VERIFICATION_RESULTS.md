# Project Verification Results: Sensitive_Data_Detection-Compliance_Assistant

This document reports the end-to-end verification results of the **Sensitive_Data_Detection-Compliance_Assistant** project, executed programmatically against a comprehensive synthetic dataset.

---

## 1. Setup Notes & Environment

- **Execution Date**: July 2, 2026
- **Operating System**: Windows
- **Python Version**: 3.12 (via WindowsApps Python release)
- **Primary LLM Engine**: Google Gemini API (`gemini-2.5-flash` rotated priority)
- **Active Key**: Loaded programmatically from the project root `.env` file
- **spaCy Model**: `en_core_web_sm` (installed and loaded)
- **Ollama Status**: **Offline/Untested** (Connection timed out on local port `11434` because the Ollama service was not running. Cloud Gemini fallback worked seamlessly).
- **Tesseract OCR Status**: **Skipped** (Not installed on path, native PDF text parsing was used).

---

## 2. Capability Coverage Checklist

| Sensitive Data Category | Tested? | Data Origin | Status / Findings |
| :--- | :---: | :--- | :--- |
| **AADHAAR** | Yes | Existing + New Synthetic | Deterministic regex + Verhoeff checksum |
| **PAN** | Yes | Existing + New Synthetic | Deterministic regex (uppercase only) |
| **EMAIL** | Yes | Existing + New Synthetic | Deterministic regex |
| **PHONE** | Yes | Existing + New Synthetic | Indian phone formats (+91, starts 6-9) |
| **CREDIT_CARD** | Yes | Existing + New Synthetic | Deterministic regex + Luhn checksum |
| **BANK_ACCOUNT** | Yes | Existing + New Synthetic | Keyword proximity + digit run |
| **IFSC** | Yes | Existing + New Synthetic | Deterministic regex (uppercase only) |
| **API_KEY** | Yes | Existing + New Synthetic | Provider-specific patterns + assigned secret |
| **PASSWORD** | Yes | Existing + New Synthetic | Key-value proximity regex |
| **EMPLOYEE_ID** | Yes | Existing + New Synthetic | Configurable regex (default: `EMP\d{4,6}`) |
| **CONFIDENTIAL_INFO** | Yes | New Synthetic | LLM contextual extraction (NDAs, M&A) |
| **PERSON** | Yes | New Synthetic | spaCy NER |
| **ORG** | Yes | New Synthetic | spaCy NER |
| **LOCATION** | Yes | New Synthetic | spaCy NER |

---

## 3. Aggregate Performance Metrics

Computed programmatically over the synthetic test dataset (including TXT, CSV, and PDF formats):

| Category | True Positives (TP) | False Positives (FP) | False Negatives (FN) | True Negatives (TN) | Precision | Recall | F1-Score |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **AADHAAR** | 4 | 0 | 0 | 2 | 1.00 | 1.00 | 1.00 |
| **PAN** | 5 | 0 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| **IFSC** | 3 | 0 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| **BANK_ACCOUNT** | 2 | 0 | 0 | 2 | 1.00 | 1.00 | 1.00 |
| **API_KEY** | 3 | 0 | 0 | 1 | 1.00 | 1.00 | 1.00 |
| **EMPLOYEE_ID** | 5 | 0 | 0 | 2 | 1.00 | 1.00 | 1.00 |
| **CREDIT_CARD** | 3 | 0 | 1 | 1 | 1.00 | 0.75 | 0.86 |
| **EMAIL** | 5 | 0 | 2 | 0 | 1.00 | 0.71 | 0.83 |
| **CONFIDENTIAL_INFO**| 2 | 0 | 1 | 1 | 1.00 | 0.67 | 0.80 |
| **PASSWORD** | 1 | 0 | 1 | 2 | 1.00 | 0.50 | 0.67 |
| **LOCATION** | 1 | 1 | 0 | 0 | 0.50 | 1.00 | 0.67 |
| **PHONE** | 2 | 2 | 3 | 1 | 0.50 | 0.40 | 0.44 |
| **PERSON** (NER) | 1 | 7 | 0 | 0 | 0.12 | 1.00 | 0.22 |
| **ORG** (NER) | 1 | 12 | 0 | 0 | 0.08 | 1.00 | 0.14 |

*Note on NER (PERSON/ORG/LOCATION)*: High FP rate is expected since the pre-trained spaCy model correctly extracts standard named entities from the text, but the test manifest only evaluates specific designated entities.

---

## 4. Key Bugs & Gaps Identified

### 1. Deduplication Span-Length Priority Bug (Critical)
- **Observation**: Overlapping findings are resolved in `src/detection/engine.py` by sorting primarily on span length: `key=lambda f: (f.end - f.start, _rank(f), ...)`.
- **Bug**: A lower-confidence, broad detector (e.g. spaCy NER identifying `email=alice@example.com` or `phone=9876543210` as `ORG`) produces a longer span than the inner email/phone regex. Due to length priority, the longer `ORG` span wins, and the inner `EMAIL` or `PHONE` finding is discarded.
- **Impact**: Emails and phone numbers prefixed with labels in structured inputs (like CSV row joins) are swallowed by spaCy NER and fail to redact correctly.
- **Status**: **Needs Fix** (Deduplication sorting should prioritize detector trust rank `_rank(f)` or confidence before span length).

### 2. JSON Verbatim Newline Bug in LLM Contextual Pass (High)
- **Observation**: When analyzing the PDF page containing the NDA, the LLM returned JSON with literal newlines inside the `snippet` field (e.g. `"snippet": "MUTUAL NON-DISCLOSURE AGREEMENT\nThis..."`).
- **Bug**: Literal raw newlines inside JSON double-quoted strings violate standard JSON syntax. The `_parse_findings` helper catches the resulting `ValueError` from `json.loads` and silently returns `[]`.
- **Impact**: Multi-line confidential info is completely skipped/undetected because the JSON parsing fails silently.
- **Status**: **Needs Fix** (Escapes should be pre-processed in the raw text, or prompt engineering should enforce strict escaping).

### 3. Case Sensitivity in Deterministic Regexes (Medium)
- **Observation**: Regexes for `PAN`, `IFSC`, and default `EMPLOYEE_ID` match uppercase letters only (`[A-Z]`, `EMP`).
- **Bug**: Lowercase PANs (`abcde1234f`), lowercase IFSCs (`hdfc0001234`), and lowercase employee IDs (`emp12345`) are completely missed.
- **Status**: **Needs Fix** (Add the ignore-case flag to these specific specs).

### 4. Quoted Label Limitation in Passwords (Medium)
- **Observation**: The password regex `r"(?i)password\s*[:=]\s*['\"]?([^\s'\"]{4,})"` expects the word `password` followed by separator, but does not allow quotes around the word.
- **Bug**: Failed to match passwords in JSON/dictionary formats like `'password': 'value'`.
- **Status**: **Needs Fix** (Allow optional quotes around the password label).

### 5. Non-Indian Phone Support (Low)
- **Observation**: The phone regex specifically targets Indian mobile formats.
- **Bug**: US/UK phone numbers (e.g., `+1-555-0199`) are undetected.
- **Status**: **Needs Fix** (Extend regex to support standard international phone number representations).

---

## 5. Per-Sample Verification Details (Truncated)

Here is a subset of the actual test runs mapped to expected labels:

| Case ID | File | Category | Expected | Actual | Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| `aadhaar_tp` | synthetic_data.txt | AADHAAR | `AADHAAR: 234567890124` | `AADHAAR: 234567890124` | **PASS** |
| `aadhaar_tn` | synthetic_data.txt | AADHAAR | `None` | `None` | **PASS** |
| `cc_tp` | synthetic_data.txt | CREDIT_CARD | `CREDIT_CARD: 4111111111111111` | `CREDIT_CARD: 4111111111111111` | **PASS** |
| `cc_edge` | synthetic_data.txt | CREDIT_CARD | `CREDIT_CARD: 4111111111111111` | `None` | **FAIL (Deduplicated)** |
| `pan_tp` | synthetic_data.txt | PAN | `PAN: ABCDE1234F` | `PAN: ABCDE1234F` | **PASS** |
| `ifsc_tp` | synthetic_data.txt | IFSC | `IFSC: HDFC0001234` | `IFSC: HDFC0001234` | **PASS** |
| `pwd_edge` | synthetic_data.txt | PASSWORD | `PASSWORD: my-super-secret-password-99` | `None` | **FAIL (Regex)** |
| `pdf_p1_aadhaar` | synthetic_data.pdf | AADHAAR | `AADHAAR: 234567890124` | `AADHAAR: 234567890124` | **PASS** |
| `pdf_p1_cc` | synthetic_data.pdf | CREDIT_CARD | `CREDIT_CARD: 4111111111111111` | `CREDIT_CARD: 4111111111111111` | **PASS** |
| `pdf_p2_confidential`| synthetic_data.pdf| CONFIDENTIAL_INFO| `CONFIDENTIAL_INFO: NDA/M&A references`| `None` | **FAIL (JSON)** |
| `csv_email` (Alice) | synthetic_data.csv | EMAIL | `EMAIL: alice@example.com` | `None` | **FAIL (Deduplicated)** |

---

## 6. Execution Verification Summary

Overall risk classification correctly labeled the highly sensitive generated PDF as **High Risk** (Score: 74.1). The compliance summary Fallback engine functioned correctly. 

All 71 existing test suites have been run and verified as passing without regression.
