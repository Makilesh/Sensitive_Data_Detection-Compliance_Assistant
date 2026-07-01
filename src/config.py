"""Central configuration — the single source of truth for settings.

Everything tunable in the app lives here: the Gemini model registry with
per-model rate limits, risk-scoring thresholds and severity weights, embedding
and chunking parameters, and redaction defaults. No other module may redeclare
these values.

Values are read from environment variables (prefix ``SDA_``) / ``.env`` locally
and can be overridden by ``st.secrets`` when deployed. ``GEMINI_API_KEY`` is read
without the prefix so it matches the conventional name.

NOTE: Gemini free-tier model names and limits change often. The registry below
is seeded with reasonable defaults but MUST be verified against
https://ai.google.dev/gemini-api/docs/rate-limits before finalizing. Limits are
data (here), never hardcoded in business logic.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelSpec(BaseModel):
    """One entry in the Gemini model-rotation registry.

    Attributes:
        name: The Gemini model identifier passed to the SDK.
        rpm: Requests-per-minute cap on the free tier.
        rpd: Requests-per-day cap on the free tier.
        tpm: Tokens-per-minute cap on the free tier.
    """

    name: str
    rpm: int = Field(gt=0)
    rpd: int = Field(gt=0)
    tpm: int = Field(gt=0)


# Priority order: highest-capability first, most-generous quota as later
# fallbacks. VERIFY current values at the rate-limits URL above.
DEFAULT_MODEL_REGISTRY: list[ModelSpec] = [
    ModelSpec(name="gemini-2.5-flash", rpm=10, rpd=250, tpm=250_000),
    ModelSpec(name="gemini-2.5-flash-lite", rpm=15, rpd=1_000, tpm=250_000),
    ModelSpec(name="gemini-2.0-flash", rpm=15, rpd=200, tpm=1_000_000),
    ModelSpec(name="gemini-2.0-flash-lite", rpm=30, rpd=200, tpm=1_000_000),
    ModelSpec(name="gemini-1.5-flash", rpm=15, rpd=50, tpm=250_000),
    ModelSpec(name="gemini-1.5-flash-8b", rpm=15, rpd=50, tpm=250_000),
]

# Per-entity-type severity weights driving risk classification (Phase 5).
DEFAULT_SEVERITY_WEIGHTS: dict[str, int] = {
    "AADHAAR": 10,
    "CREDIT_CARD": 10,
    "BANK_ACCOUNT": 9,
    "IFSC": 7,
    "API_KEY": 10,
    "PASSWORD": 10,
    "PAN": 8,
    "PHONE": 4,
    "EMAIL": 4,
    "EMPLOYEE_ID": 4,
    "CONFIDENTIAL_INFO": 6,
    "PERSON": 1,
    "ORG": 1,
    "LOCATION": 1,
}


class Settings(BaseSettings):
    """Application settings, validated and typed."""

    model_config = SettingsConfigDict(
        env_prefix="SDA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- Secrets ---
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")

    # --- LLM / rotation ---
    model_registry: list[ModelSpec] = Field(default_factory=lambda: list(DEFAULT_MODEL_REGISTRY))
    llm_max_retries: int = 3
    llm_backoff_seconds: float = 1.0
    rate_limit_state_file: str = ".rate_limits.json"

    # --- Detection ---
    enable_ner: bool = True
    enable_llm_contextual: bool = True
    employee_id_pattern: str = r"\bEMP\d{4,6}\b"

    # --- Risk classification ---
    severity_weights: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_SEVERITY_WEIGHTS))
    risk_medium_threshold: float = 10.0
    risk_high_threshold: float = 30.0

    # --- RAG ---
    embedding_model: str = "all-MiniLM-L6-v2"
    chunk_size_tokens: int = 500
    chunk_overlap_ratio: float = 0.1
    retrieval_top_k: int = 5
    index_dir: str = "data/indexes"

    # --- Ingestion ---
    enable_ocr: bool = False
    ocr_min_chars_per_page: int = 20

    # --- Redaction ---
    redaction_style: str = "placeholder"  # "placeholder" | "partial"

    # --- Audit ---
    audit_log_file: str = "audit_log.jsonl"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
