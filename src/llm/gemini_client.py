"""Rate-limit-aware Gemini model-rotation client.

Presents a single ``generate()`` method that transparently rotates across the
free-tier Gemini models declared in the config registry. On a rate-limit error
(HTTP 429 / ``ResourceExhausted`` / quota exhaustion) the offending model is put
on a short cooldown and the client moves to the next model. Transient 5xx errors
are retried with exponential backoff before rotating. When every model is capped
it raises the typed :class:`AllModelsExhausted` so callers can degrade gracefully
(e.g. fall back to deterministic behavior).

The real SDK call is isolated in ``_invoke_sdk`` so the rotation logic is fully
unit-testable with a fake clock and simulated failures — no network required.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from src.config import Settings, get_settings
from src.llm.rate_limiter import RateLimiter


class AllModelsExhausted(RuntimeError):
    """Raised when no model in the registry can currently serve a request."""


class LLMUnavailableError(RuntimeError):
    """Raised when the client is used without a configured API key."""


@dataclass
class LLMResult:
    """Result of a successful generation."""

    text: str
    model_used: str
    prompt_tokens: int
    response_tokens: int


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token) used for TPM accounting."""
    return max(1, len(text) // 4)


def _status_of(exc: BaseException) -> int | None:
    for attr in ("status_code", "code", "grpc_status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def _is_rate_limit_error(exc: BaseException) -> bool:
    if _status_of(exc) == 429:
        return True
    name = type(exc).__name__
    if name in {"ResourceExhausted", "TooManyRequests"}:
        return True
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "quota" in msg or "exhausted" in msg


def _is_transient_error(exc: BaseException) -> bool:
    status = _status_of(exc)
    if status is not None and 500 <= status < 600:
        return True
    return type(exc).__name__ in {
        "ServiceUnavailable",
        "InternalServerError",
        "DeadlineExceeded",
        "Aborted",
    }


class GeminiClient:
    """Rate-limit-aware rotation client over the configured model registry."""

    def __init__(
        self,
        settings: Settings | None = None,
        rate_limiter: RateLimiter | None = None,
        now: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._now = now or time.time
        self._sleep = sleep or time.sleep
        self._rate_limiter = rate_limiter or RateLimiter(
            self._settings.model_registry,
            self._settings.rate_limit_state_file,
            now=self._now,
        )
        self._cooldown_seconds = 60.0
        self._sdk_configured = False

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._rate_limiter

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.gemini_api_key)

    def generate(
        self,
        prompt: str,
        *,
        json_mode: bool = False,
        max_output_tokens: int = 1024,
    ) -> LLMResult:
        """Generate text, rotating across models on rate-limit / transient errors."""
        if not self.is_configured:
            raise LLMUnavailableError("GEMINI_API_KEY is not set")

        prompt_tokens = estimate_tokens(prompt)
        last_error: BaseException | None = None

        for spec in self._settings.model_registry:
            if not self._rate_limiter.can_use(spec.name):
                continue
            result = self._try_model(
                spec.name, prompt, json_mode, max_output_tokens, prompt_tokens
            )
            if result is not None:
                return result
            # rotation was triggered (rate-limit or retries exhausted)

        # Nothing served the request.
        raise AllModelsExhausted(
            "All Gemini models are rate-limited or exhausted; try again later."
        ) from last_error

    def _try_model(
        self,
        model_name: str,
        prompt: str,
        json_mode: bool,
        max_output_tokens: int,
        prompt_tokens: int,
    ) -> LLMResult | None:
        """Attempt one model with retry/backoff. Returns None to rotate onward."""
        for attempt in range(self._settings.llm_max_retries):
            try:
                text, response_tokens = self._invoke_sdk(
                    model_name, prompt, json_mode, max_output_tokens
                )
            except Exception as exc:  # noqa: BLE001 - classified below
                if _is_rate_limit_error(exc):
                    self._rate_limiter.mark_cooldown(model_name, self._cooldown_seconds)
                    return None  # rotate to next model
                if _is_transient_error(exc) and attempt < self._settings.llm_max_retries - 1:
                    self._sleep(self._settings.llm_backoff_seconds * (2**attempt))
                    continue  # retry same model
                return None  # non-retryable or retries exhausted → rotate
            self._rate_limiter.record(model_name, prompt_tokens + response_tokens)
            return LLMResult(
                text=text,
                model_used=model_name,
                prompt_tokens=prompt_tokens,
                response_tokens=response_tokens,
            )
        return None

    def _invoke_sdk(
        self,
        model_name: str,
        prompt: str,
        json_mode: bool,
        max_output_tokens: int,
    ) -> tuple[str, int]:
        """Perform the real Gemini SDK call. Isolated for testability."""
        import google.generativeai as genai  # lazy: avoids import cost in tests

        if not self._sdk_configured:
            genai.configure(api_key=self._settings.gemini_api_key)
            self._sdk_configured = True

        generation_config: dict = {"max_output_tokens": max_output_tokens}
        if json_mode:
            generation_config["response_mime_type"] = "application/json"

        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt, generation_config=generation_config)
        text = response.text or ""

        response_tokens = estimate_tokens(text)
        usage = getattr(response, "usage_metadata", None)
        if usage is not None and getattr(usage, "candidates_token_count", None):
            response_tokens = int(usage.candidates_token_count)
        return text, response_tokens
