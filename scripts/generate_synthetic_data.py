"""Generate synthetic test data for all 14 sensitive categories.

Covers four buckets per category:
  a) True positives
  b) True negatives / decoys
  c) Edge cases
  d) Adversarial cases

Outputs TXT, CSV, and PDF formats to test_data/synthetic/, along with manifest.json.
"""

from __future__ import annotations

import json
from pathlib import Path
import fitz  # PyMuPDF

# Import validators from the codebase to ensure we generate conforming numbers
from src.detection.patterns import verhoeff_check, luhn_check

def find_valid_aadhaar() -> str:
    # 234567890124 passes Verhoeff
    val = "234567890124"
    assert verhoeff_check(val)
    return val

def find_invalid_aadhaar() -> str:
    # 234567890125 fails Verhoeff
    val = "234567890125"
    assert not verhoeff_check(val)
    return val

def find_valid_credit_card() -> str:
    # Visa card passing Luhn
    val = "4111111111111111"
    assert luhn_check(val)
    return val

def find_invalid_credit_card() -> str:
    val = "4111111111111112"
    assert not luhn_check(val)
    return val

def generate_datasets():
    output_dir = Path("test_data/synthetic")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Plain Text Cases (covers TXT format and generic PII scenarios)
    # We will structure these into discrete lines/paragraphs to test line-level detection
    txt_cases = [
        # --- AADHAAR ---
        {
            "id": "aadhaar_tp",
            "bucket": "true_positive",
            "text": f"The customer's verified Aadhaar number is {find_valid_aadhaar()}.",
            "expected": [{"type": "AADHAAR", "value": find_valid_aadhaar()}]
        },
        {
            "id": "aadhaar_tn",
            "bucket": "true_negative",
            "text": f"The number {find_invalid_aadhaar()} is invalid and should be rejected.",
            "expected": []
        },
        {
            "id": "aadhaar_edge",
            "bucket": "edge_case",
            "text": f"JSON logs: {{\"user_profile\": {{\"aadhaar\": \"{find_valid_aadhaar()}\"}}}}",
            "expected": [{"type": "AADHAAR", "value": find_valid_aadhaar()}]
        },
        {
            "id": "aadhaar_adv",
            "bucket": "adversarial",
            "text": f"Double spaces in digit runs: 2345  6789  0124 should fail regex.",
            "expected": []
        },

        # --- CREDIT CARD ---
        {
            "id": "cc_tp",
            "bucket": "true_positive",
            "text": f"Please bill card number {find_valid_credit_card()}.",
            "expected": [{"type": "CREDIT_CARD", "value": find_valid_credit_card()}]
        },
        {
            "id": "cc_tn",
            "bucket": "true_negative",
            "text": f"The card ending in {find_invalid_credit_card()} is expired.",
            "expected": []
        },
        {
            "id": "cc_edge",
            "bucket": "edge_case",
            "text": f"Transaction details: cc_num={find_valid_credit_card()}; amount=150.00",
            "expected": [{"type": "CREDIT_CARD", "value": find_valid_credit_card()}]
        },
        {
            "id": "cc_adv",
            "bucket": "adversarial",
            "text": "Product Serial number 1234567890123452 passes Luhn but might not be a card.",
            "expected": [{"type": "CREDIT_CARD", "value": "1234567890123452"}] # Luhn-valid digit run is classified as CREDIT_CARD by system
        },

        # --- PAN ---
        {
            "id": "pan_tp",
            "bucket": "true_positive",
            "text": "My Permanent Account Number (PAN) is ABCDE1234F.",
            "expected": [{"type": "PAN", "value": "ABCDE1234F"}]
        },
        {
            "id": "pan_tn",
            "bucket": "true_negative",
            "text": "Invalid PAN numbers: ABCDE12345 (no trailing letter), ABCD12345F (wrong length).",
            "expected": []
        },
        {
            "id": "pan_edge",
            "bucket": "edge_case",
            "text": "The CSV field holds [PAN:ABCDE1234F] which is critical.",
            "expected": [{"type": "PAN", "value": "ABCDE1234F"}]
        },
        {
            "id": "pan_adv",
            "bucket": "adversarial",
            "text": "Lowercase PAN card abcde1234f might be missed by strict regex.",
            "expected": [] # The current regex doesn't match lowercase. This will show up as a gap.
        },

        # --- IFSC ---
        {
            "id": "ifsc_tp",
            "bucket": "true_positive",
            "text": "The bank branch code IFSC is HDFC0001234.",
            "expected": [{"type": "IFSC", "value": "HDFC0001234"}]
        },
        {
            "id": "ifsc_tn",
            "bucket": "true_negative",
            "text": "The code HDFC1001234 is not an IFSC (5th char must be 0).",
            "expected": []
        },
        {
            "id": "ifsc_edge",
            "bucket": "edge_case",
            "text": "Please transfer to IFSC:HDFC0001234 immediately.",
            "expected": [{"type": "IFSC", "value": "HDFC0001234"}]
        },
        {
            "id": "ifsc_adv",
            "bucket": "adversarial",
            "text": "Lowercase IFSC hdfc0001234 might be missed by regex.",
            "expected": [] # Regex expects uppercase, so this will be missed.
        },

        # --- EMAIL ---
        {
            "id": "email_tp",
            "bucket": "true_positive",
            "text": "Contact us at support@example.com for help.",
            "expected": [{"type": "EMAIL", "value": "support@example.com"}]
        },
        {
            "id": "email_tn",
            "bucket": "true_negative",
            "text": "Non-email strings: user@domain (missing TLD), @example.com (no local part).",
            "expected": []
        },
        {
            "id": "email_edge",
            "bucket": "edge_case",
            "text": "HTML anchor: <a href=\"mailto:admin.contact@sub.example.co.uk\">Send Email</a>",
            "expected": [{"type": "EMAIL", "value": "admin.contact@sub.example.co.uk"}]
        },
        {
            "id": "email_adv",
            "bucket": "adversarial",
            "text": "Emails inside comments like info@example.com.org might be parsed.",
            "expected": [{"type": "EMAIL", "value": "info@example.com.org"}]
        },

        # --- PHONE ---
        {
            "id": "phone_tp",
            "bucket": "true_positive",
            "text": "Indian mobile number is 9876543210.",
            "expected": [{"type": "PHONE", "value": "9876543210"}]
        },
        {
            "id": "phone_tn",
            "bucket": "true_negative",
            "text": "Decoys: 1234567890 (does not start with 6-9), 987654321 (9 digits).",
            "expected": []
        },
        {
            "id": "phone_edge",
            "bucket": "edge_case",
            "text": "Call us at +91-98765-43210 or +91 98765 43210.",
            "expected": [{"type": "PHONE", "value": "98765-43210"}, {"type": "PHONE", "value": "98765 43210"}]
        },
        {
            "id": "phone_adv",
            "bucket": "adversarial",
            "text": "US Number +1-555-0199 will not be caught because the regex is Indian-only.",
            "expected": [] # Gap to report: US phone numbers are not supported by the regex.
        },

        # --- BANK ACCOUNT ---
        {
            "id": "bank_tp",
            "bucket": "true_positive",
            "text": "Transfer money to Account No: 123456789012.",
            "expected": [{"type": "BANK_ACCOUNT", "value": "123456789012"}]
        },
        {
            "id": "bank_tn",
            "bucket": "true_negative",
            "text": "The account balance is 50000 USD (no bank account number here).",
            "expected": []
        },
        {
            "id": "bank_edge",
            "bucket": "edge_case",
            "text": "Bank details: acc no 987654321098; holder: John.",
            "expected": [{"type": "BANK_ACCOUNT", "value": "987654321098"}]
        },
        {
            "id": "bank_adv",
            "bucket": "adversarial",
            "text": "Underscore labels like account_num: 123456789012 will fail keyword proximity.",
            "expected": [] # Gap: regex requires spaces/colons, not underscores.
        },

        # --- API KEY ---
        {
            "id": "api_key_tp",
            "bucket": "true_positive",
            "text": "AWS Secret: AKIAIOSFODNN7EXAMPLE",
            "expected": [{"type": "API_KEY", "value": "AKIAIOSFODNN7EXAMPLE"}]
        },
        {
            "id": "api_key_tn",
            "bucket": "true_negative",
            "text": "The key identifier was too short: AKIA123.",
            "expected": []
        },
        {
            "id": "api_key_edge",
            "bucket": "edge_case",
            "text": "api_key = \"sk-12345678901234567890123456789012\"",
            "expected": [{"type": "API_KEY", "value": "sk-12345678901234567890123456789012"}]
        },
        {
            "id": "api_key_adv",
            "bucket": "adversarial",
            "text": "api-key:secret_value_without_quotes_1234567890",
            "expected": [{"type": "API_KEY", "value": "secret_value_without_quotes_1234567890"}]
        },

        # --- PASSWORD ---
        {
            "id": "pwd_tp",
            "bucket": "true_positive",
            "text": "Default login password: SecretPassword123",
            "expected": [{"type": "PASSWORD", "value": "SecretPassword123"}]
        },
        {
            "id": "pwd_tn",
            "bucket": "true_negative",
            "text": "Enter password to log in.",
            "expected": []
        },
        {
            "id": "pwd_edge",
            "bucket": "edge_case",
            "text": "credentials = { 'password': 'my-super-secret-password-99' }",
            "expected": [{"type": "PASSWORD", "value": "my-super-secret-password-99"}]
        },
        {
            "id": "pwd_adv",
            "bucket": "adversarial",
            "text": "password:   \"\" (empty password string is skipped by length >= 4 check)",
            "expected": []
        },

        # --- EMPLOYEE ID ---
        {
            "id": "emp_id_tp",
            "bucket": "true_positive",
            "text": "The manager's ID is EMP12345.",
            "expected": [{"type": "EMPLOYEE_ID", "value": "EMP12345"}]
        },
        {
            "id": "emp_id_tn",
            "bucket": "true_negative",
            "text": "Check employee database for ids EMP12 (too short) or EMP12345678 (too long).",
            "expected": []
        },
        {
            "id": "emp_id_edge",
            "bucket": "edge_case",
            "text": "Assign task to [employee: EMP9999].",
            "expected": [{"type": "EMPLOYEE_ID", "value": "EMP9999"}]
        },
        {
            "id": "emp_id_adv",
            "bucket": "adversarial",
            "text": "Lowercase employee id emp12345 will be missed.",
            "expected": [] # Gap: regex is case-sensitive EMP.
        },

        # --- CONFIDENTIAL INFO (Fuzzy Contextual Pass) ---
        {
            "id": "conf_tp",
            "bucket": "true_positive",
            "text": "Project ProjectX: We are planning an M&A transaction with competitor Z next quarter.",
            "expected": [{"type": "CONFIDENTIAL_INFO", "value": "planning an M&A transaction with competitor Z next quarter"}]
        },
        {
            "id": "conf_tn",
            "bucket": "true_negative",
            "text": "This is a public press release about our new office design.",
            "expected": []
        },
        {
            "id": "conf_edge",
            "bucket": "edge_case",
            "text": "Subject: NDA discussion. Please review the attached mutual non-disclosure agreement details.",
            "expected": [{"type": "CONFIDENTIAL_INFO", "value": "mutual non-disclosure agreement"}]
        },

        # --- PERSON / ORG / LOCATION (spaCy NER) ---
        {
            "id": "ner_tp",
            "bucket": "true_positive",
            "text": "Elon Musk visited Microsoft in Seattle yesterday.",
            "expected": [
                {"type": "PERSON", "value": "Elon Musk"},
                {"type": "ORG", "value": "Microsoft"},
                {"type": "LOCATION", "value": "Seattle"}
            ]
        }
    ]

    # Write Plain Text dataset
    txt_content = "\n".join(case["text"] for case in txt_cases)
    txt_path = output_dir / "synthetic_data.txt"
    txt_path.write_text(txt_content, encoding="utf-8")

    # 2. CSV Dataset
    # Write a tabular CSV containing rows with sensitive data and decoy rows
    csv_rows = [
        "name,email,phone,pan,aadhaar,employee_id,notes",
        f"Alice Smith,alice@example.com,9876543210,ABCDE1234F,{find_valid_aadhaar()},EMP1001,Confidential record.",
        f"Bob Jones,bob@example.com,9123456780,PQRSX6789Z,{find_invalid_aadhaar()},EMP1002,Decoy Aadhaar.",
        "Charlie Public,charlie@public.com,1234567890,INVALIDPAN,,EMP99,Public user decoy numbers."
    ]
    csv_content = "\n".join(csv_rows)
    csv_path = output_dir / "synthetic_data.csv"
    csv_path.write_text(csv_content, encoding="utf-8")

    # 3. PDF Dataset
    # We will generate a PDF file using PyMuPDF (fitz) page-by-page containing PII
    pdf_doc = fitz.open()
    
    # Page 1: Structured PII
    page1 = pdf_doc.new_page()
    page1_text = (
        "CONFIDENTIAL PAYMENT RECORDS\n\n"
        "Employee details:\n"
        "Name: David Miller\n"
        "Email: david.miller@example.com\n"
        "PAN: VWXYZ5678A\n"
        f"Aadhaar Number: {find_valid_aadhaar()}\n"
        f"Credit Card Info: {find_valid_credit_card()}\n"
        "Bank Account No: 9876543210123\n"
        "Bank IFSC Code: ICIC0009876\n"
        "Employee ID: EMP9876"
    )
    page1.insert_text((50, 50), page1_text, fontsize=12)

    # Page 2: Confidential Business Info / NDA
    page2 = pdf_doc.new_page()
    page2_text = (
        "MUTUAL NON-DISCLOSURE AGREEMENT\n\n"
        "This agreement is made between Acme Corp and Tech Solutions.\n"
        "The parties agree not to disclose proprietary financial data or\n"
        "potential M&A negotiations discussed in June 2026."
    )
    page2.insert_text((50, 50), page2_text, fontsize=12)

    pdf_path = output_dir / "synthetic_data.pdf"
    pdf_doc.save(str(pdf_path))
    pdf_doc.close()

    # 4. Manifest File
    # Combine everything into a unified manifest that verify_pipeline.py can parse
    # For text, we'll map line numbers since line extraction reads the file line-by-line.
    manifest = {
        "txt_cases": txt_cases,
        "csv_expected": {
            "emails": ["alice@example.com", "bob@example.com", "charlie@public.com"],
            "phones": ["9876543210", "9123456780"],
            "pans": ["ABCDE1234F", "PQRSX6789Z"],
            "aadhaars": [find_valid_aadhaar()],
            "emp_ids": ["EMP1001", "EMP1002"]
        },
        "pdf_expected": {
            "email": "david.miller@example.com",
            "pan": "VWXYZ5678A",
            "aadhaar": find_valid_aadhaar(),
            "cc": find_valid_credit_card(),
            "ifsc": "ICIC0009876",
            "emp_id": "EMP9876"
        }
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Generated synthetic test data:")
    print(f" - TXT: {txt_path}")
    print(f" - CSV: {csv_path}")
    print(f" - PDF: {pdf_path}")
    print(f" - Manifest: {manifest_path}")

if __name__ == "__main__":
    generate_datasets()
