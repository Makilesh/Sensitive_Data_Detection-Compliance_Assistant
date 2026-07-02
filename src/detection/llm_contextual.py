"""LLM verification pass — the final, model-driven sweep for sensitive data.

Catches what regex + spaCy cannot: fuzzy confidential business content (NDAs,
financials, M&A, trade secrets) AND personal data in *any language or script*
(e.g. a Tamil/Hindi name or place-name the English NER model mislabels or misses).
Gemini returns typed, verbatim snippets; every snippet is verified against the
source text and dropped if it cannot be located (anti-hallucination guard). If the
LLM is unavailable (exhausted / no key), the pass returns an empty list so the
deterministic pipeline still works.
"""

from __future__ import annotations

import json
import re

from src.llm.gemini_client import GeminiClient
from src.llm.prompts import with_preamble
from src.models import EntityType, Finding
from src.redaction.masker import mask_value

_MAX_CHARS = 12_000

# LLM type string → our entity vocabulary. Unknown types fall back to
# CONFIDENTIAL_INFO so nothing sensitive is silently dropped.
_TYPE_MAP = {
    "PERSON": EntityType.PERSON,
    "NAME": EntityType.PERSON,
    "LOCATION": EntityType.LOCATION,
    "ADDRESS": EntityType.LOCATION,
    "PLACE": EntityType.LOCATION,
    "ORG": EntityType.ORG,
    "ORGANIZATION": EntityType.ORG,
    "DOB": EntityType.DOB,
    "DATE_OF_BIRTH": EntityType.DOB,
    "CONFIDENTIAL_INFO": EntityType.CONFIDENTIAL_INFO,
}

_PROMPT_TEMPLATE = """You are the final verification step of a PII redaction tool. \
Identify EVERY piece of sensitive or personal data in the document below that must \
be redacted before sharing. This includes:
- Person names in ANY language or script (English, Tamil, Hindi, etc.).
- Postal addresses and place / locality names.
- Dates of birth.
- Organizations.
- Confidential business information (NDAs, financials, M&A, trade secrets).

Rules:
- Only report text that is literally present in the document (quote it verbatim,
  in its original script).
- Do NOT invent, translate, paraphrase, or infer anything not written.
- Classify each with a "type" from: PERSON, LOCATION, ORG, DOB, CONFIDENTIAL_INFO.
- If nothing qualifies, return an empty list.

Return ONLY valid JSON:
{{"findings": [{{"snippet": "<verbatim quote>", "type": "PERSON", "rationale": "<why>"}}]}}

DOCUMENT:
\"\"\"
{document}
\"\"\""""


def detect_contextual(
    text: str,
    client: GeminiClient | None,
    max_chars: int = _MAX_CHARS,
) -> list[Finding]:
    """Return LLM-verified sensitive-data findings, each located in ``text``."""
    if client is None or not client.is_configured:
        return []

    prompt = with_preamble(_PROMPT_TEMPLATE.format(document=text[:max_chars]))
    try:
        result = client.generate(prompt, json_mode=True, max_output_tokens=2048)
    except Exception:  # noqa: BLE001 - AllModelsExhausted / SDK errors → skip
        return []

    findings: list[Finding] = []
    for item in _parse_findings(result.text):
        snippet = (item.get("snippet") or "").strip()
        if not snippet:
            continue
        start, end = _locate_snippet(text, snippet)
        if start == -1:  # hallucination guard: snippet must exist in the source
            continue
        actual = text[start:end]  # the real substring, with its original whitespace
        entity = _TYPE_MAP.get(str(item.get("type", "")).upper(), EntityType.CONFIDENTIAL_INFO)
        findings.append(
            Finding(
                entity_type=entity,
                value_masked=mask_value(entity, actual),
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
