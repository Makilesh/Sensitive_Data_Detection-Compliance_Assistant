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
