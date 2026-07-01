"""Prompt templates — the single source of truth for all LLM instructions.

Every prompt sent to Gemini is built here so wording, grounding rules, and the
"never fabricate" guardrails live in exactly one place. Later phases (contextual
detection, RAG Q&A, compliance summary) add their templates alongside these.
"""

from __future__ import annotations

# Shared system preamble injected before task-specific instructions. Enforces the
# project-wide anti-hallucination and privacy rules on every LLM call.
SYSTEM_PREAMBLE = (
    "You are a careful compliance assistant. Ground every statement in the text "
    "you are given. Never invent values, names, or facts. If the provided context "
    "is insufficient, say so explicitly rather than guessing. Sensitive values are "
    "already masked; do not attempt to reconstruct them."
)


def with_preamble(task_prompt: str) -> str:
    """Prepend the shared system preamble to a task-specific prompt."""
    return f"{SYSTEM_PREAMBLE}\n\n{task_prompt}"


# RAG Q&A: answer strictly from numbered context chunks; cite them; refuse when
# the answer is not supported.
QA_PROMPT_TEMPLATE = """Answer the question using ONLY the numbered context below.

Rules:
- Ground every claim in the context. Cite the chunk numbers you used like [1], [2].
- If the context does not contain the answer, reply exactly:
  "I don't have enough information in this document to answer that."
- Do not use outside knowledge. Do not reveal or guess masked values.

Context:
{context}

Question: {question}

Answer:"""


def build_qa_prompt(question: str, context: str) -> str:
    return with_preamble(QA_PROMPT_TEMPLATE.format(context=context, question=question))


# Compliance summary: grounded in the provided (masked) findings brief only.
COMPLIANCE_PROMPT_TEMPLATE = """You are given a masked summary of sensitive data \
detected in a document. Produce a concise compliance report in Markdown with \
exactly these three sections:

## Compliance Observations
Reference relevant regulations (GDPR, India DPDP Act 2023, PCI-DSS) only where the \
detected data types make them applicable.

## Security Risks
Concrete risks implied by the detected data.

## Recommended Remediation
Prioritized, actionable steps (most critical first).

Rules:
- Use ONLY the detected types and counts below. Do not invent specific values,
  names, or numbers beyond what is provided.
- If a data type is not listed, do not claim it was found.

DETECTION BRIEF:
{brief}"""


def build_compliance_prompt(brief: str) -> str:
    return with_preamble(COMPLIANCE_PROMPT_TEMPLATE.format(brief=brief))
