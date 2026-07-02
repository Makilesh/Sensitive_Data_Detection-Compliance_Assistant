"""LLM contextual pass for confidential business information.

Finds fuzzy, non-structured sensitive content the regexes cannot — NDAs,
financials, M&A / change-of-control language, litigation, trade secrets. The LLM
returns structured findings and MUST quote text that actually appears in the
document; every returned snippet is verified against the source text and dropped
if it cannot be located (anti-hallucination guard). If the LLM is unavailable
(all models exhausted or no API key), the pass returns an empty list rather than
failing the pipeline.
"""

from __future__ import annotations

import json

from src.llm.gemini_client import GeminiClient
from src.llm.prompts import with_preamble
from src.models import EntityType, Finding
from src.redaction.masker import mask_value

_MAX_CHARS = 12_000

_PROMPT_TEMPLATE = """Identify CONFIDENTIAL BUSINESS INFORMATION in the document \
below. Look for: NDAs / confidentiality clauses, financial figures and \
projections, M&A / change-of-control terms, litigation, and trade secrets.

Rules:
- Only report text that is literally present in the document.
- Quote the exact snippet (verbatim) as it appears.
- Do NOT invent, paraphrase, or infer values that are not written.
- If nothing qualifies, return an empty list.

Return ONLY valid JSON of the form:
{{"findings": [{{"snippet": "<verbatim quote>", "rationale": "<why sensitive>"}}]}}

DOCUMENT:
\"\"\"
{document}
\"\"\""""


def detect_contextual(
    text: str,
    client: GeminiClient | None,
    max_chars: int = _MAX_CHARS,
) -> list[Finding]:
    """Return LLM-detected confidential-info findings, verified against ``text``."""
    if client is None or not client.is_configured:
        return []

    prompt = with_preamble(_PROMPT_TEMPLATE.format(document=text[:max_chars]))
    try:
        result = client.generate(prompt, json_mode=True, max_output_tokens=1024)
    except Exception:  # noqa: BLE001 - AllModelsExhausted / SDK errors → skip
        return []

    items = _parse_findings(result.text)
    findings: list[Finding] = []
    for item in items:
        snippet = (item.get("snippet") or "").strip()
        if not snippet:
            continue
        idx = text.find(snippet)
        if idx == -1:  # hallucination guard: snippet must exist verbatim
            continue
        findings.append(
            Finding(
                entity_type=EntityType.CONFIDENTIAL_INFO,
                value_masked=mask_value(EntityType.CONFIDENTIAL_INFO, snippet),
                value_raw=snippet,
                start=idx,
                end=idx + len(snippet),
                detector="llm",
                confidence=0.7,
                rationale=(item.get("rationale") or "").strip() or None,
            )
        )
    return findings


def _parse_findings(raw: str) -> list[dict]:
    """Best-effort parse of the model's JSON, tolerant of code fences."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        return []
    try:
        # strict=False tolerates literal control chars (newlines/tabs) inside
        # string values — LLMs frequently emit multi-line snippets verbatim,
        # which strict JSON would reject and silently drop.
        data = json.loads(cleaned[start : end + 1], strict=False)
    except ValueError:
        return []
    findings = data.get("findings", [])
    return findings if isinstance(findings, list) else []
