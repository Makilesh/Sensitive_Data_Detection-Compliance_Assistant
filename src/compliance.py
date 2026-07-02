"""AI compliance summary generation.

Builds a *masked* structured brief from the detection findings and risk report and
asks Gemini for a compliance report (observations, security risks, remediation),
referencing GDPR / India DPDP Act / PCI-DSS where the detected data types make
them relevant. If the LLM is unavailable (no key / all models exhausted), a
deterministic template summary is produced from the same brief so the feature
never hard-fails. No raw sensitive values are ever included.
"""

from __future__ import annotations

from src.config import Settings, get_settings
from src.detection.engine import summarize_counts
from src.llm.gemini_client import GeminiClient
from src.llm.prompts import build_compliance_prompt
from src.models import Document, Finding, RiskReport, SummaryResult

# Regulation hints + remediation guidance per entity type (single source).
_REMEDIATION: dict[str, tuple[str, str]] = {
    "AADHAAR": ("India DPDP Act 2023", "Mask/tokenize Aadhaar; restrict access; avoid storage."),
    "VID": ("India DPDP Act 2023", "Treat Aadhaar VID as Aadhaar; mask and restrict access."),
    "DOB": ("GDPR / DPDP", "Date of birth is personal data; minimize and restrict access."),
    "PAN": ("India DPDP Act 2023", "Encrypt PAN at rest; limit to authorized processing."),
    "CREDIT_CARD": ("PCI-DSS", "Never store PANs in clear text; tokenize; scope PCI environment."),
    "BANK_ACCOUNT": ("PCI-DSS / DPDP", "Encrypt account numbers; enforce least-privilege access."),
    "IFSC": ("India DPDP Act 2023", "Treat with bank details; avoid exposing in shared docs."),
    "API_KEY": ("Security best practice", "Rotate keys immediately; move to a secrets manager."),
    "PASSWORD": ("Security best practice", "Rotate credentials; never store plaintext passwords."),
    "EMAIL": ("GDPR / DPDP", "Minimize retention; obtain consent; support erasure requests."),
    "PHONE": ("GDPR / DPDP", "Minimize retention; restrict access to phone numbers."),
    "EMPLOYEE_ID": ("GDPR / DPDP", "Limit internal identifiers to need-to-know systems."),
    "CONFIDENTIAL_INFO": ("Confidentiality/NDA", "Apply access controls; label and track distribution."),
    "PERSON": ("GDPR / DPDP", "Treat personal names as personal data; minimize exposure."),
    "ORG": ("Confidentiality", "Review whether organization references are sensitive."),
    "LOCATION": ("GDPR / DPDP", "Assess whether location data is personally identifying."),
}


def _build_brief(findings: list[Finding], risk: RiskReport) -> str:
    """A compact, PII-free brief the LLM (or template) reasons over."""
    counts = summarize_counts(findings)
    lines = [f"Overall risk: {risk.level.value} (score {risk.score})."]
    if counts:
        lines.append("Detected sensitive data types and counts:")
        for entity, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {entity}: {count}")
    else:
        lines.append("No sensitive data detected.")
    return "\n".join(lines)


def generate_summary(
    document: Document,
    findings: list[Finding],
    risk: RiskReport,
    client: GeminiClient | None,
    settings: Settings | None = None,
) -> SummaryResult:
    """Return a Markdown compliance summary grounded in the findings.

    ``SummaryResult.model_used`` is ``None`` when the deterministic template
    fallback served the summary, so the UI can show which model (if any)
    generated it.
    """
    settings = settings or get_settings()
    brief = _build_brief(findings, risk)

    if client is not None and client.is_configured:
        try:
            result = client.generate(build_compliance_prompt(brief), max_output_tokens=1024)
            if result.text.strip():
                return SummaryResult(text=result.text.strip(), model_used=result.model_used)
        except Exception:  # noqa: BLE001 - AllModelsExhausted / SDK errors → template
            pass
    return SummaryResult(text=_template_summary(findings, risk), model_used=None)


def _template_summary(findings: list[Finding], risk: RiskReport) -> str:
    """Deterministic fallback summary built entirely from the findings."""
    counts = summarize_counts(findings)
    out: list[str] = [
        "# Compliance Summary (template)",
        "",
        f"**Overall risk:** {risk.level.value} (score {risk.score})",
        "",
        "## Compliance Observations",
    ]
    if not counts:
        out.append("- No sensitive data was detected in this document.")
        return "\n".join(out)

    regs = sorted({_REMEDIATION.get(t, ("", ""))[0] for t in counts if _REMEDIATION.get(t, ("",))[0]})
    out.append(
        "- Detected data types trigger these frameworks: " + ", ".join(regs) + "."
        if regs
        else "- Review detected data types against applicable frameworks."
    )
    for entity, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        reg = _REMEDIATION.get(entity, ("General", ""))[0]
        out.append(f"- **{entity}** ({count}) — relevant to {reg}.")

    out += ["", "## Security Risks"]
    out.append(f"- Overall exposure is rated **{risk.level.value}**.")
    for contributor in risk.contributors[:5]:
        out.append(
            f"- {contributor.entity_type.value}: {contributor.count} occurrence(s) "
            f"contributing {contributor.contribution:.0f} to the risk score."
        )

    out += ["", "## Recommended Remediation"]
    for entity, _ in sorted(counts.items(), key=lambda kv: -kv[1]):
        step = _REMEDIATION.get(entity, ("", "Review and protect this data."))[1]
        out.append(f"- **{entity}:** {step}")
    return "\n".join(out)
