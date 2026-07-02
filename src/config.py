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

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelSpec(BaseModel):
    """One entry in the Gemini model-rotation registry.

    Attributes:
        name: The model identifier passed to the backend SDK/API.
        rpm: Requests-per-minute cap on the free tier.
        rpd: Requests-per-day cap on the free tier.
        tpm: Tokens-per-minute cap on the free tier.
        provider: Which backend serves this model ("gemini" | "ollama").
    """

    name: str
    rpm: int = Field(gt=0)
    rpd: int = Field(gt=0)
    tpm: int = Field(gt=0)
    provider: str = "gemini"


# Priority order tuned for THIS workload (structured JSON extraction + RAG
# synthesis + summaries): lead with high-throughput flash models (survive rate
# limits), keep the pro tiers as mid fallbacks for harder synthesis, and a local
# Ollama model as the final, quota-free backup (appended by Settings when
# ``enable_ollama`` is on). VERIFY current values at the rate-limits URL above —
# free-tier names/limits change often.
DEFAULT_MODEL_REGISTRY: list[ModelSpec] = [
    ModelSpec(name="gemini-3.5-flash", rpm=10, rpd=1_500, tpm=250_000),
    ModelSpec(name="gemini-3.1-flash-lite", rpm=15, rpd=1_000, tpm=250_000),
    ModelSpec(name="gemini-2.5-flash", rpm=10, rpd=250, tpm=250_000),
    ModelSpec(name="gemini-3.1-pro-preview", rpm=5, rpd=100, tpm=250_000),
    ModelSpec(name="gemini-2.5-pro", rpm=5, rpd=100, tpm=250_000),
]

# Per-entity-type severity weights driving risk classification (Phase 5).
DEFAULT_SEVERITY_WEIGHTS: dict[str, int] = {
    "AADHAAR": 10,
    "VID": 10,
    "DOB": 6,
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
        protected_namespaces=(),  # allow `model_registry` without the model_ warning
    )

    # --- Secrets ---
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")

    # --- LLM / rotation ---
    model_registry: list[ModelSpec] = Field(default_factory=lambda: list(DEFAULT_MODEL_REGISTRY))
    llm_max_retries: int = 3
    llm_backoff_seconds: float = 1.0

    # --- Local Ollama backup (final, quota-free fallback) ---
    # qwen2.5:14b (~9GB Q4) fits a 12GB-VRAM GPU (e.g. RTX 5070 Ti) and is strong
    # at instruction-following / JSON — ideal for this extraction+RAG workload.
    # Lighter alternative: "llama3.1:8b". Reasoning models (deepseek-r1) and
    # >12GB models (gpt-oss:20b) are not recommended here.
    enable_ollama: bool = True
    ollama_model: str = "qwen2.5:14b"
    ollama_host: str = "http://localhost:11434"
    ollama_rpm: int = 1_000  # local: effectively unlimited
    ollama_rpd: int = 100_000
    ollama_tpm: int = 10_000_000
    ollama_timeout_seconds: float = 120.0

    # Privacy: when True, only the local Ollama backend is used — no document
    # text (even masked) is sent to the cloud.
    local_only_mode: bool = False
    rate_limit_state_file: str = ".rate_limits.json"

    # --- Detection ---
    enable_ner: bool = True
    enable_llm_contextual: bool = True
    employee_id_pattern: str = r"(?i)\bEMP\d{4,6}\b"  # case-insensitive by default

    # --- Risk classification ---
    severity_weights: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_SEVERITY_WEIGHTS))
    risk_medium_threshold: float = 10.0
    risk_high_threshold: float = 30.0

    # --- RAG ---
    embedding_model: str = "all-MiniLM-L6-v2"
    chunk_size_tokens: int = 500
    chunk_overlap_ratio: float = 0.1
    retrieval_top_k: int = 5
    rag_min_score: float = 0.25  # cosine floor below which Q&A refuses
    index_dir: str = "data/indexes"
    # Hybrid retrieval: fuse dense (FAISS) + sparse (BM25) via RRF.
    enable_hybrid_search: bool = True
    retrieval_pool: int = 20  # candidates pulled from each retriever before fusion
    rrf_k: int = 60  # RRF damping constant

    # Optional cross-encoder reranker (higher precision on large docs).
    enable_reranker: bool = False
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"  # light, CPU-ok
    reranker_model_gpu: str = "BAAI/bge-reranker-v2-m3"  # heavier, used if CUDA
    reranker_auto_upgrade_gpu: bool = True
    rerank_pool: int = 20  # candidates reranked before truncating to top_k

    # --- Ingestion ---
    enable_ocr: bool = False
    ocr_min_chars_per_page: int = 20

    # --- Redaction ---
    redaction_style: str = "placeholder"  # "placeholder" | "partial"

    # --- Audit ---
    audit_log_file: str = "audit_log.jsonl"

    @model_validator(mode="after")
    def _append_ollama_backup(self) -> Settings:
        """Append the local Ollama model as the final rotation fallback.

        Kept as data on the single ``model_registry`` so the rotation client has
        one uniform priority list (cloud Gemini first, local Ollama last).
        """
        if self.enable_ollama and not any(
            m.provider == "ollama" for m in self.model_registry
        ):
            self.model_registry.append(
                ModelSpec(
                    name=self.ollama_model,
                    rpm=self.ollama_rpm,
                    rpd=self.ollama_rpd,
                    tpm=self.ollama_tpm,
                    provider="ollama",
                )
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
