"""Per-model rate-limit tracking for the Gemini rotation client.

Tracks three independent limits per model:

* **RPM** — requests in a trailing 60-second sliding window.
* **TPM** — tokens (prompt + response) in a trailing 60-second window.
* **RPD** — requests per calendar day, persisted to a small JSON file so the
  count survives process restarts within the same day (resets at midnight).

All mutation is guarded by a lock so ``can_use`` → ``record`` sequences are
atomic and cannot overshoot a limit under concurrency (mirrors the reference
repo's atomic-budget pattern). The clock is injectable for deterministic tests.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.config import ModelSpec


@dataclass
class _ModelWindow:
    """Mutable in-memory sliding-window state for one model."""

    request_times: deque[float] = field(default_factory=deque)
    token_events: deque[tuple[float, int]] = field(default_factory=deque)
    cooldown_until: float = 0.0


@dataclass
class ModelUsage:
    """Read-only snapshot of a model's usage for the UI."""

    name: str
    provider: str
    rpm_used: int
    rpm_limit: int
    tpm_used: int
    tpm_limit: int
    rpd_used: int
    rpd_limit: int
    cooling_down: bool
    available: bool


class RateLimiter:
    """Thread-safe RPM/TPM/RPD accounting across a set of models."""

    _WINDOW_SECONDS = 60.0

    def __init__(
        self,
        models: list[ModelSpec],
        state_file: str,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._models = {m.name: m for m in models}
        self._windows: dict[str, _ModelWindow] = {m.name: _ModelWindow() for m in models}
        self._state_file = Path(state_file)
        self._now = now or time.time
        self._lock = threading.Lock()
        self._rpd_date: str = ""
        self._rpd: dict[str, int] = {m.name: 0 for m in models}
        self._load_rpd()

    # --- persistence -----------------------------------------------------
    def _today(self) -> str:
        return datetime.fromtimestamp(self._now()).strftime("%Y-%m-%d")

    def _load_rpd(self) -> None:
        today = self._today()
        if self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                if data.get("date") == today:
                    self._rpd_date = today
                    stored = data.get("rpd", {})
                    for name in self._rpd:
                        self._rpd[name] = int(stored.get(name, 0))
                    return
            except (ValueError, OSError):
                pass
        self._rpd_date = today  # new/other day → fresh counts

    def _persist_rpd(self) -> None:
        try:
            self._state_file.write_text(
                json.dumps({"date": self._rpd_date, "rpd": self._rpd}),
                encoding="utf-8",
            )
        except OSError:
            pass  # persistence is best-effort; never break a request over it

    def _roll_day_if_needed(self) -> None:
        today = self._today()
        if today != self._rpd_date:
            self._rpd_date = today
            self._rpd = dict.fromkeys(self._rpd, 0)
            self._persist_rpd()

    # --- window maintenance ---------------------------------------------
    def _prune(self, window: _ModelWindow, now: float) -> None:
        cutoff = now - self._WINDOW_SECONDS
        while window.request_times and window.request_times[0] <= cutoff:
            window.request_times.popleft()
        while window.token_events and window.token_events[0][0] <= cutoff:
            window.token_events.popleft()

    # --- public API ------------------------------------------------------
    def can_use(self, model_name: str) -> bool:
        """Return True if a request to ``model_name`` would not breach a limit."""
        with self._lock:
            return self._can_use_locked(model_name)

    def _can_use_locked(self, model_name: str) -> bool:
        spec = self._models.get(model_name)
        if spec is None:
            return False
        self._roll_day_if_needed()
        now = self._now()
        window = self._windows[model_name]
        self._prune(window, now)
        if window.cooldown_until > now:
            return False
        if len(window.request_times) >= spec.rpm:
            return False
        if sum(tok for _, tok in window.token_events) >= spec.tpm:
            return False
        if self._rpd[model_name] >= spec.rpd:
            return False
        return True

    def record(self, model_name: str, tokens: int) -> None:
        """Record one successful request of ``tokens`` against ``model_name``."""
        with self._lock:
            if model_name not in self._models:
                return
            self._roll_day_if_needed()
            now = self._now()
            window = self._windows[model_name]
            window.request_times.append(now)
            window.token_events.append((now, max(tokens, 0)))
            self._rpd[model_name] += 1
            self._persist_rpd()

    def mark_cooldown(self, model_name: str, seconds: float) -> None:
        """Cool a model down (e.g. after a 429) so rotation skips it briefly."""
        with self._lock:
            if model_name in self._windows:
                self._windows[model_name].cooldown_until = self._now() + seconds

    def seconds_until_available(self, model_name: str) -> float:
        """Estimate seconds until ``model_name`` frees up (for short waits)."""
        with self._lock:
            spec = self._models.get(model_name)
            if spec is None:
                return float("inf")
            now = self._now()
            window = self._windows[model_name]
            self._prune(window, now)
            if self._rpd[model_name] >= spec.rpd:
                return float("inf")  # only a day roll frees it
            waits = [max(0.0, window.cooldown_until - now)]
            if len(window.request_times) >= spec.rpm and window.request_times:
                waits.append(self._WINDOW_SECONDS - (now - window.request_times[0]))
            return max(waits)

    def snapshot(self) -> list[ModelUsage]:
        """Return a UI-friendly usage snapshot for every model."""
        with self._lock:
            now = self._now()
            self._roll_day_if_needed()
            out: list[ModelUsage] = []
            for name, spec in self._models.items():
                window = self._windows[name]
                self._prune(window, now)
                out.append(
                    ModelUsage(
                        name=name,
                        provider=spec.provider,
                        rpm_used=len(window.request_times),
                        rpm_limit=spec.rpm,
                        tpm_used=sum(tok for _, tok in window.token_events),
                        tpm_limit=spec.tpm,
                        rpd_used=self._rpd[name],
                        rpd_limit=spec.rpd,
                        cooling_down=window.cooldown_until > now,
                        available=self._can_use_locked(name),
                    )
                )
            return out
