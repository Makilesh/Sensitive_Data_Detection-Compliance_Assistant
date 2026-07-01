"""Phase 3 tests: RPM/TPM/RPD windowing with a fake clock."""

from __future__ import annotations

from src.config import ModelSpec
from src.llm.rate_limiter import RateLimiter


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _limiter(tmp_path, rpm=2, rpd=5, tpm=1000):
    clock = FakeClock()
    models = [ModelSpec(name="m1", rpm=rpm, rpd=rpd, tpm=tpm)]
    rl = RateLimiter(models, str(tmp_path / "rl.json"), now=clock)
    return rl, clock


def test_rpm_blocks_then_frees_after_window(tmp_path) -> None:
    rl, clock = _limiter(tmp_path, rpm=2)
    assert rl.can_use("m1")
    rl.record("m1", 10)
    rl.record("m1", 10)
    assert not rl.can_use("m1"), "RPM cap of 2 should block the 3rd request"
    clock.advance(61)
    assert rl.can_use("m1"), "window should free after 60s"


def test_rpd_blocks_and_persists(tmp_path) -> None:
    state = tmp_path / "rl.json"
    clock = FakeClock()
    models = [ModelSpec(name="m1", rpm=100, rpd=3, tpm=10_000)]
    rl = RateLimiter(models, str(state), now=clock)
    for _ in range(3):
        assert rl.can_use("m1")
        rl.record("m1", 5)
    assert not rl.can_use("m1"), "RPD cap reached"

    # A fresh limiter on the same day reloads the daily count from disk.
    rl2 = RateLimiter(models, str(state), now=clock)
    assert not rl2.can_use("m1"), "RPD count must persist within the day"


def test_rpd_resets_next_day(tmp_path) -> None:
    rl, clock = _limiter(tmp_path, rpm=100, rpd=2)
    rl.record("m1", 5)
    rl.record("m1", 5)
    assert not rl.can_use("m1")
    clock.advance(24 * 3600)  # next day
    assert rl.can_use("m1"), "daily counter should reset at midnight roll"


def test_tpm_blocks_when_token_budget_spent(tmp_path) -> None:
    rl, clock = _limiter(tmp_path, rpm=100, tpm=100)
    rl.record("m1", 100)
    assert not rl.can_use("m1"), "TPM budget exhausted"
    clock.advance(61)
    assert rl.can_use("m1")


def test_cooldown_and_snapshot(tmp_path) -> None:
    rl, clock = _limiter(tmp_path)
    rl.mark_cooldown("m1", 30)
    assert not rl.can_use("m1")
    snap = {u.name: u for u in rl.snapshot()}
    assert snap["m1"].cooling_down is True
    clock.advance(31)
    assert rl.can_use("m1")
