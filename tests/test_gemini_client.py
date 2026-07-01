"""Phase 3 tests: model rotation, retry/backoff, and exhaustion."""

from __future__ import annotations

import pytest

from src.config import ModelSpec, Settings
from src.llm.gemini_client import AllModelsExhausted, GeminiClient, LLMUnavailableError
from src.llm.rate_limiter import RateLimiter
from tests.test_rate_limiter import FakeClock


class RateLimit429(Exception):
    status_code = 429


class ServerError503(Exception):
    status_code = 503


def _client(tmp_path, clock, models=None):
    models = models or [
        ModelSpec(name="m1", rpm=5, rpd=100, tpm=100_000),
        ModelSpec(name="m2", rpm=5, rpd=100, tpm=100_000),
    ]
    settings = Settings(
        gemini_api_key="test-key",
        model_registry=models,
        llm_backoff_seconds=0.0,
        enable_ollama=False,  # keep these unit tests Gemini-only + deterministic
    )
    rl = RateLimiter(settings.model_registry, str(tmp_path / "rl.json"), now=clock)
    client = GeminiClient(settings=settings, rate_limiter=rl, now=clock, sleep=lambda _s: None)
    return client, rl


def test_rotates_to_next_model_on_429(tmp_path) -> None:
    clock = FakeClock()
    client, rl = _client(tmp_path, clock)

    def fake_sdk(model_name, prompt, json_mode, max_output_tokens):
        if model_name == "m1":
            raise RateLimit429("429 quota")
        return "hello from m2", 3

    client._invoke_sdk = fake_sdk  # type: ignore[assignment]
    result = client.generate("hi")
    assert result.model_used == "m2"
    assert result.text == "hello from m2"
    assert not rl.can_use("m1"), "m1 should be cooling down after the 429"


def test_retries_transient_then_succeeds(tmp_path) -> None:
    clock = FakeClock()
    client, _ = _client(tmp_path, clock)
    attempts = {"n": 0}

    def fake_sdk(model_name, prompt, json_mode, max_output_tokens):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ServerError503("503 transient")
        return "recovered", 2

    client._invoke_sdk = fake_sdk  # type: ignore[assignment]
    result = client.generate("hi")
    assert result.text == "recovered"
    assert attempts["n"] == 2, "should retry the same model once before succeeding"


def test_all_models_exhausted_raises(tmp_path) -> None:
    clock = FakeClock()
    client, _ = _client(tmp_path, clock)

    def always_429(model_name, prompt, json_mode, max_output_tokens):
        raise RateLimit429("429")

    client._invoke_sdk = always_429  # type: ignore[assignment]
    with pytest.raises(AllModelsExhausted):
        client.generate("hi")


def test_unconfigured_client_raises() -> None:
    settings = Settings(gemini_api_key="", enable_ollama=False)
    client = GeminiClient(settings=settings)
    with pytest.raises(LLMUnavailableError):
        client.generate("hi")


def test_ollama_backup_used_when_gemini_exhausted(tmp_path) -> None:
    """With Gemini 429'd, rotation falls through to the local Ollama backup."""
    clock = FakeClock()
    models = [ModelSpec(name="m1", rpm=5, rpd=100, tpm=100_000)]
    settings = Settings(
        gemini_api_key="test-key",
        model_registry=models,
        llm_backoff_seconds=0.0,
        enable_ollama=True,
        ollama_model="qwen2.5:14b",
    )
    rl = RateLimiter(settings.model_registry, str(tmp_path / "rl.json"), now=clock)
    client = GeminiClient(settings=settings, rate_limiter=rl, now=clock, sleep=lambda _s: None)

    client._invoke_sdk = lambda *a: (_ for _ in ()).throw(RateLimit429("429"))  # type: ignore
    client._invoke_ollama = lambda *a: ("local answer", 7)  # type: ignore[assignment]

    result = client.generate("hi")
    assert result.text == "local answer"
    assert result.model_used == "qwen2.5:14b"


def test_ollama_only_configuration() -> None:
    """No Gemini key but Ollama enabled → client is configured via the local model."""
    settings = Settings(gemini_api_key="", enable_ollama=True, ollama_model="qwen2.5:14b")
    client = GeminiClient(settings=settings)
    assert client.is_configured
    assert any(m.provider == "ollama" for m in settings.model_registry)


def test_successful_call_records_usage(tmp_path) -> None:
    clock = FakeClock()
    client, rl = _client(tmp_path, clock)
    client._invoke_sdk = lambda *a: ("ok", 5)  # type: ignore[assignment]
    client.generate("some prompt text")
    snap = {u.name: u for u in rl.snapshot()}
    assert snap["m1"].rpm_used == 1
    assert snap["m1"].tpm_used > 0
