"""Run programmatic verification of the sensitive data detection pipeline.

Loads the synthetic dataset and manifest, runs the detection and classification,
compares actual outputs to expected labels, and calculates performance metrics.
"""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv

# Load env variables before importing codebase
load_dotenv()

from src.classification.risk import classify_risk
from src.compliance import generate_summary
from src.config import get_settings
from src.detection.engine import run_detection
from src.ingestion.loaders import load_document
from src.llm.gemini_client import GeminiClient
from src.models import EntityType


def load_file_bytes(path: Path) -> bytes:
    return path.read_bytes()

def run_verification():
    settings = get_settings()
    client = GeminiClient(settings=settings)

    synthetic_dir = Path("test_data/synthetic")
    manifest_path = synthetic_dir / "manifest.json"

    if not manifest_path.exists():
        print(f"Error: Manifest file {manifest_path} does not exist. Run generate_synthetic_data.py first.")
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    txt_path = synthetic_dir / "synthetic_data.txt"
    csv_path = synthetic_dir / "synthetic_data.csv"
    pdf_path = synthetic_dir / "synthetic_data.pdf"

    # We will accumulate results for metrics calculation
    # Result maps: category -> {'tp': 0, 'fp': 0, 'fn': 0, 'tn': 0}
    metrics = {}
    for et in EntityType:
        metrics[et.value] = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}

    detailed_results = []

    # -------------------------------------------------------------------------
    # 1. Verify Plain Text Cases
    # -------------------------------------------------------------------------
    txt_bytes = load_file_bytes(txt_path)
    txt_doc = load_document("synthetic_data.txt", txt_bytes, settings)

    print("\n--- Running detection on Plain Text (TXT) ---")
    txt_findings = run_detection(txt_doc, client, settings)
    print(f"Found {len(txt_findings)} findings in TXT.")

    # Match findings by line
    txt_cases = manifest["txt_cases"]
    for i, case in enumerate(txt_cases):
        line_num = i + 1
        expected_list = case["expected"]
        case_id = case["id"]
        bucket = case["bucket"]

        # Get actual findings for this line
        actual_line_findings = [f for f in txt_findings if f.line == line_num]

        # Check expected vs actual
        # Match matches by type & value (or fuzzy match for CONFIDENTIAL_INFO)
        matched_actual = []
        for exp in expected_list:
            exp_type = exp["type"]
            exp_val = exp["value"]

            # Find a matching finding
            match_found = None
            for f in actual_line_findings:
                if f.entity_type.value == exp_type:
                    # For spaCy or LLM, do fuzzy check
                    if exp_type in {"CONFIDENTIAL_INFO", "PERSON", "ORG", "LOCATION"}:
                        if exp_val.lower() in f.value_raw.lower() or f.value_raw.lower() in exp_val.lower():
                            match_found = f
                            break
                    else:
                        # For deterministic patterns, exact match
                        if f.value_raw == exp_val:
                            match_found = f
                            break

            if match_found:
                metrics[exp_type]["tp"] += 1
                matched_actual.append(match_found)
                detailed_results.append({
                    "case_id": case_id,
                    "file": "synthetic_data.txt",
                    "bucket": bucket,
                    "expected": f"{exp_type}: {exp_val}",
                    "actual": f"{match_found.entity_type.value}: {match_found.value_raw}",
                    "status": "PASS"
                })
            else:
                metrics[exp_type]["fn"] += 1
                detailed_results.append({
                    "case_id": case_id,
                    "file": "synthetic_data.txt",
                    "bucket": bucket,
                    "expected": f"{exp_type}: {exp_val}",
                    "actual": "None",
                    "status": "FAIL (Missed)"
                })

        # Count false positives for unexpected findings
        for f in actual_line_findings:
            if f not in matched_actual:
                metrics[f.entity_type.value]["fp"] += 1
                detailed_results.append({
                    "case_id": case_id,
                    "file": "synthetic_data.txt",
                    "bucket": bucket,
                    "expected": "None",
                    "actual": f"{f.entity_type.value}: {f.value_raw}",
                    "status": "FAIL (False Positive)"
                })

        # True Negatives count: if expected is empty and actual is empty
        if not expected_list and not actual_line_findings:
            # We increment TN for the category that this case was testing (extracted from case_id prefix)
            test_cat = case_id.split("_")[0].upper()
            # map prefix to EntityType if needed
            cat_map = {
                "AADHAAR": "AADHAAR", "CC": "CREDIT_CARD", "PAN": "PAN", "IFSC": "IFSC",
                "EMAIL": "EMAIL", "PHONE": "PHONE", "BANK": "BANK_ACCOUNT", "API": "API_KEY",
                "PWD": "PASSWORD", "EMP": "EMPLOYEE_ID", "CONF": "CONFIDENTIAL_INFO"
            }
            mapped_cat = cat_map.get(test_cat)
            if mapped_cat:
                metrics[mapped_cat]["tn"] += 1
            detailed_results.append({
                "case_id": case_id,
                "file": "synthetic_data.txt",
                "bucket": bucket,
                "expected": "None",
                "actual": "None",
                "status": "PASS"
            })

    # -------------------------------------------------------------------------
    # 2. Verify CSV Dataset
    # -------------------------------------------------------------------------
    csv_bytes = load_file_bytes(csv_path)
    csv_doc = load_document("synthetic_data.csv", csv_bytes, settings)

    print("\n--- Running detection on CSV ---")
    csv_findings = run_detection(csv_doc, client, settings)
    print(f"Found {len(csv_findings)} findings in CSV.")

    csv_expected = manifest["csv_expected"]
    # Check if expected PII values were found in CSV
    for email in csv_expected["emails"]:
        matches = [f for f in csv_findings if f.entity_type == EntityType.EMAIL and f.value_raw == email]
        if matches:
            metrics["EMAIL"]["tp"] += 1
            detailed_results.append({"case_id": "csv_email", "file": "synthetic_data.csv", "bucket": "csv_row", "expected": f"EMAIL: {email}", "actual": f"EMAIL: {email}", "status": "PASS"})
        else:
            metrics["EMAIL"]["fn"] += 1
            detailed_results.append({"case_id": "csv_email", "file": "synthetic_data.csv", "bucket": "csv_row", "expected": f"EMAIL: {email}", "actual": "None", "status": "FAIL"})

    for phone in csv_expected["phones"]:
        matches = [f for f in csv_findings if f.entity_type == EntityType.PHONE and f.value_raw == phone]
        if matches:
            metrics["PHONE"]["tp"] += 1
            detailed_results.append({"case_id": "csv_phone", "file": "synthetic_data.csv", "bucket": "csv_row", "expected": f"PHONE: {phone}", "actual": f"PHONE: {phone}", "status": "PASS"})
        else:
            metrics["PHONE"]["fn"] += 1
            detailed_results.append({"case_id": "csv_phone", "file": "synthetic_data.csv", "bucket": "csv_row", "expected": f"PHONE: {phone}", "actual": "None", "status": "FAIL"})

    for pan in csv_expected["pans"]:
        matches = [f for f in csv_findings if f.entity_type == EntityType.PAN and f.value_raw == pan]
        if matches:
            metrics["PAN"]["tp"] += 1
            detailed_results.append({"case_id": "csv_pan", "file": "synthetic_data.csv", "bucket": "csv_row", "expected": f"PAN: {pan}", "actual": f"PAN: {pan}", "status": "PASS"})
        else:
            metrics["PAN"]["fn"] += 1
            detailed_results.append({"case_id": "csv_pan", "file": "synthetic_data.csv", "bucket": "csv_row", "expected": f"PAN: {pan}", "actual": "None", "status": "FAIL"})

    for aadhaar in csv_expected["aadhaars"]:
        matches = [f for f in csv_findings if f.entity_type == EntityType.AADHAAR and f.value_raw == aadhaar]
        if matches:
            metrics["AADHAAR"]["tp"] += 1
            detailed_results.append({"case_id": "csv_aadhaar", "file": "synthetic_data.csv", "bucket": "csv_row", "expected": f"AADHAAR: {aadhaar}", "actual": f"AADHAAR: {aadhaar}", "status": "PASS"})
        else:
            metrics["AADHAAR"]["fn"] += 1
            detailed_results.append({"case_id": "csv_aadhaar", "file": "synthetic_data.csv", "bucket": "csv_row", "expected": f"AADHAAR: {aadhaar}", "actual": "None", "status": "FAIL"})

    for emp_id in csv_expected["emp_ids"]:
        matches = [f for f in csv_findings if f.entity_type == EntityType.EMPLOYEE_ID and f.value_raw == emp_id]
        if matches:
            metrics["EMPLOYEE_ID"]["tp"] += 1
            detailed_results.append({"case_id": "csv_emp_id", "file": "synthetic_data.csv", "bucket": "csv_row", "expected": f"EMPLOYEE_ID: {emp_id}", "actual": f"EMPLOYEE_ID: {emp_id}", "status": "PASS"})
        else:
            metrics["EMPLOYEE_ID"]["fn"] += 1
            detailed_results.append({"case_id": "csv_emp_id", "file": "synthetic_data.csv", "bucket": "csv_row", "expected": f"EMPLOYEE_ID: {emp_id}", "actual": "None", "status": "FAIL"})

    # -------------------------------------------------------------------------
    # 3. Verify PDF Dataset
    # -------------------------------------------------------------------------
    pdf_bytes = load_file_bytes(pdf_path)
    pdf_doc = load_document("synthetic_data.pdf", pdf_bytes, settings)

    print("\n--- Running detection on PDF ---")
    pdf_findings = run_detection(pdf_doc, client, settings)
    print(f"Found {len(pdf_findings)} findings in PDF.")

    pdf_expected = manifest["pdf_expected"]
    # Check page 1 findings
    p1_findings = [f for f in pdf_findings if f.page == 1]

    p1_checks = [
        ("EMAIL", pdf_expected["email"]),
        ("PAN", pdf_expected["pan"]),
        ("AADHAAR", pdf_expected["aadhaar"]),
        ("CREDIT_CARD", pdf_expected["cc"]),
        ("IFSC", pdf_expected["ifsc"]),
        ("EMPLOYEE_ID", pdf_expected["emp_id"])
    ]

    for etype, val in p1_checks:
        matches = [f for f in p1_findings if f.entity_type.value == etype and f.value_raw == val]
        if matches:
            metrics[etype]["tp"] += 1
            detailed_results.append({"case_id": f"pdf_p1_{etype.lower()}", "file": "synthetic_data.pdf", "bucket": "pdf_page_1", "expected": f"{etype}: {val}", "actual": f"{etype}: {val}", "status": "PASS"})
        else:
            metrics[etype]["fn"] += 1
            detailed_results.append({"case_id": f"pdf_p1_{etype.lower()}", "file": "synthetic_data.pdf", "bucket": "pdf_page_1", "expected": f"{etype}: {val}", "actual": "None", "status": "FAIL"})

    # Check page 2 findings (Confidential Info)
    p2_findings = [f for f in pdf_findings if f.page == 2]
    conf_findings = [f for f in p2_findings if f.entity_type == EntityType.CONFIDENTIAL_INFO]
    if conf_findings:
        metrics["CONFIDENTIAL_INFO"]["tp"] += 1
        detailed_results.append({"case_id": "pdf_p2_confidential", "file": "synthetic_data.pdf", "bucket": "pdf_page_2", "expected": "CONFIDENTIAL_INFO: NDA/M&A references", "actual": f"CONFIDENTIAL_INFO: {conf_findings[0].value_raw}", "status": "PASS"})
    else:
        metrics["CONFIDENTIAL_INFO"]["fn"] += 1
        detailed_results.append({"case_id": "pdf_p2_confidential", "file": "synthetic_data.pdf", "bucket": "pdf_page_2", "expected": "CONFIDENTIAL_INFO: NDA/M&A references", "actual": "None", "status": "FAIL"})

    # -------------------------------------------------------------------------
    # 4. Generate Overall Reports, Risk & Compliance Summary
    # -------------------------------------------------------------------------
    print("\n--- Running Risk Classification and Compliance Summary ---")
    # Run risk classification on the combined findings of PDF
    risk_report = classify_risk(pdf_findings, pdf_doc.page_count, settings)
    print(f"PDF Risk Level: {risk_report.level.value} (Score: {risk_report.score})")

    summary_result = generate_summary(pdf_doc, pdf_findings, risk_report, client, settings)
    print(
        f"Compliance Summary generated (length: {len(summary_result.text)} chars, "
        f"model: {summary_result.model_used or 'template fallback'})."
    )

    # -------------------------------------------------------------------------
    # 5. Compile Metrics and Generate Verification Report
    # -------------------------------------------------------------------------
    print("\n================== METRICS SUMMARY ==================")
    print(f"{'Category':<20} | {'TP':<4} | {'FP':<4} | {'FN':<4} | {'TN':<4} | {'Precision':<10} | {'Recall':<10} | {'F1-Score':<10}")
    print("-" * 80)

    markdown_metrics_rows = []

    for cat, counts in sorted(metrics.items()):
        tp, fp, fn, tn = counts["tp"], counts["fp"], counts["fn"], counts["tn"]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        print(f"{cat:<20} | {tp:<4} | {fp:<4} | {fn:<4} | {tn:<4} | {precision:<10.2f} | {recall:<10.2f} | {f1:<10.2f}")
        markdown_metrics_rows.append(
            f"| {cat} | {tp} | {fp} | {fn} | {tn} | {precision:.2f} | {recall:.2f} | {f1:.2f} |"
        )

    # Write details to structured results log in scratch directory
    scratch_dir = Path("test_data/scratch")
    scratch_dir.mkdir(parents=True, exist_ok=True)

    log_file = scratch_dir / "verification_log.json"
    log_data = {
        "metrics": metrics,
        "detailed_results": detailed_results,
        "risk_report": {
            "level": risk_report.level.value,
            "score": risk_report.score,
            "summary": risk_report.summary
        },
        "compliance_summary": summary_result.text,
        "compliance_summary_model": summary_result.model_used
    }
    log_file.write_text(json.dumps(log_data, indent=2), encoding="utf-8")
    print(f"\nVerification details written to: {log_file}")

if __name__ == "__main__":
    run_verification()
