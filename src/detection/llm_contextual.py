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
import re

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
        result = client.generate(prompt, json_mode=True, max_output_tokens=2048)
    except Exception:  # noqa: BLE001 - AllModelsExhausted / SDK errors → skip
        return []

    items = _parse_findings(result.text)
    findings: list[Finding] = []
    for item in items:
        snippet = (item.get("snippet") or "").strip()
        if not snippet:
            continue
        start, end = _locate_snippet(text, snippet)
        if start == -1:  # hallucination guard: snippet must exist in the source
            continue
        actual = text[start:end]  # the real substring, with its original whitespace
        findings.append(
            Finding(
                entity_type=EntityType.CONFIDENTIAL_INFO,
                value_masked=mask_value(EntityType.CONFIDENTIAL_INFO, actual),
                value_raw=actual,
                start=start,
                end=end,
                detector="llm",
                confidence=0.7,
                rationale=(item.get("rationale") or "").strip() or None,
            )
        )
    return findings


def _locate_snippet(text: str, snippet: str) -> tuple[int, int]:
    """Find ``snippet`` in ``text``, tolerating whitespace/newline differences.

    LLMs frequently normalize a document's internal line breaks when quoting, so a
    strict ``str.find`` wrongly rejects real snippets. This still requires the
    snippet to exist in the source (anti-hallucination) but ignores differences in
    runs of whitespace, mapping the match back to the original character offsets.
    """
    exact = text.find(snippet)
    if exact != -1:
        return exact, exact + len(snippet)

    norm_chars: list[str] = []
    norm_to_orig: list[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if prev_space:
                continue
            norm_chars.append(" ")
            norm_to_orig.append(i)
            prev_space = True
        else:
            norm_chars.append(ch)
            norm_to_orig.append(i)
            prev_space = False
    norm_text = "".join(norm_chars)
    norm_snippet = re.sub(r"\s+", " ", snippet).strip()
    if not norm_snippet:
        return -1, -1
    j = norm_text.find(norm_snippet)
    if j == -1:
        return -1, -1
    start = norm_to_orig[j]
    end = norm_to_orig[j + len(norm_snippet) - 1] + 1
    return start, end


def _parse_findings(raw: str) -> list[dict]:
    """Best-effort parse of the model's JSON, tolerant of fences and truncation."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]

    # Preferred path: a complete, well-formed object. strict=False tolerates
    # literal control chars (newlines/tabs) inside string values.
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1], strict=False)
            findings = data.get("findings", [])
            if isinstance(findings, list):
                return findings
        except ValueError:
            pass

    # Salvage path: the response was truncated (max tokens) → the outer array is
    # unterminated. Recover every complete flat {snippet, rationale} object.
    salvaged: list[dict] = []
    for match in re.finditer(r"\{[^{}]*\}", cleaned):
        try:
            obj = json.loads(match.group(0), strict=False)
        except ValueError:
            continue
        if isinstance(obj, dict) and "snippet" in obj:
            salvaged.append(obj)
    return salvaged
