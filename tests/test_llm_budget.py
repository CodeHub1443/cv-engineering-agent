"""Slice G3 acceptance tests: daily budget, call limit, length caps and prices.

ADR-0020 §3 item 5(2-3), §3 item 6 and §7 "G3"; D-092; issue #93. No network, no real key,
no real state root: every store lives under ``tmp_path``, every adapter is a fake and the
clock is injected.
"""

from __future__ import annotations

import logging
import multiprocessing
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.catalog import PriceStep, load_catalog, parse_catalog, price_for
from cv_agent.llm.errors import (
    LLMBudgetExceededError,
    LLMCallLimitError,
    LLMClockSkewError,
    LLMConfigError,
    LLMCredentialError,
    LLMInputTooLargeError,
    LLMRequestError,
    LLMStoreError,
    LLMTruncatedError,
)
from cv_agent.llm.governed import (
    GovernedProvider,
    LLMBudgetConfig,
    actual_cost_usd,
    day_key_for,
    worst_case_usd,
)
from cv_agent.llm.sqlite_store import SCHEMA_VERSION, LLMCallStore

OPUS = "claude-opus-5-5"
HAIKU = "claude-haiku-5-5"
T0 = datetime(2026, 11, 12, 9, 30, 0, tzinfo=timezone.utc)  # 15:30 at UTC+06:00
DAY = "2026-11-12+06:00"
RESETS = "2026-11-12T18:00:00+00:00"
SECRET = "TOPSECRET-PROMPT-TEXT"
CATALOG = load_catalog()


class FakeClock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now
        self._mono = 0.0

    def now_utc(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        self._mono += 0.1
        return self._mono


class FakeAdapter(LLMProvider):
    """Counts how many times the 'network' was reached."""

    def __init__(
        self,
        model: str = OPUS,
        *,
        usage: Optional[dict[str, int]] = None,
        exc: Optional[BaseException] = None,
    ) -> None:
        self._model = model
        self._usage = usage if usage is not None else _usage(10, 5)
        self._exc = exc
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return "fakeprovider"

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return LLMResponse(
            content="ok",
            model=self._model,
            provider="fakeprovider",
            usage=dict(self._usage),
            stop_reason="end_turn",
        )


def _usage(prompt: int, completion: int, cache_creation: int = 0, cache_read: int = 0) -> dict[str, int]:
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "thinking_tokens": 0,
        "total_tokens": prompt + completion,
    }


def _store(tmp_path: Path) -> LLMCallStore:
    path = tmp_path / "llm_calls.sqlite"
    LLMCallStore.initialise(path)
    return LLMCallStore(path)


def _governed(
    store: LLMCallStore,
    adapter: LLMProvider,
    clock: Optional[FakeClock] = None,
    budget: Optional[LLMBudgetConfig] = None,
) -> GovernedProvider:
    return GovernedProvider(
        hosted=False,
        task_class="extraction",
        tier="fast",
        adapter=adapter,
        store=store,
        clock=clock or FakeClock(),
        budget=budget or LLMBudgetConfig(),
        catalog=CATALOG,
    )


def _spend(store: LLMCallStore, usd: float, *, call_id: str = "seed", now: datetime = T0) -> None:
    """Put ``usd`` on today's books without going through a provider."""
    store.reserve(
        call_id=call_id,
        now_utc=now,
        day_key=day_key_for(now, "+06:00"),
        worst_usd=usd,
        ceiling_usd=5.0,
        call_limit=100,
        skew_tolerance_s=300.0,
        prices_as_of="2026-11-12",
        resets_at_utc=RESETS,
    )


def _request(prompt: str = "hello", max_tokens: Optional[int] = 100, system: Optional[str] = None) -> LLMRequest:
    return LLMRequest(prompt=prompt, system=system, max_tokens=max_tokens)


# ── Prices and the catalog ───────────────────────────────────────────────────


def test_catalog_loads_from_the_installed_package_with_as_of_and_source() -> None:
    catalog = load_catalog()
    assert set(catalog.models) >= {OPUS, HAIKU}
    for facts in catalog.models.values():
        assert facts.prices_as_of == "2026-11-12"
        assert facts.prices_source == "https://docs.claude.com/en/docs/about-claude/pricing"
        assert facts.provider


def test_catalog_prices_match_the_owner_supplied_table() -> None:
    opus = CATALOG.facts_for(OPUS)
    assert [(s.up_to_input_tokens, s.input_usd_per_mtok, s.output_usd_per_mtok) for s in opus.price_steps] == [
        (None, 4.0, 20.0)
    ]
    haiku = CATALOG.facts_for(HAIKU)
    assert [(s.up_to_input_tokens, s.input_usd_per_mtok, s.output_usd_per_mtok) for s in haiku.price_steps] == [
        (100_000, 0.10, 0.50),
        (None, 0.50, 2.50),
    ]


def test_unknown_model_is_a_config_error() -> None:
    with pytest.raises(LLMConfigError, match="mystery-model"):
        CATALOG.facts_for("mystery-model")


def test_governed_provider_with_an_unknown_model_is_a_config_error_and_never_calls(tmp_path: Path) -> None:
    adapter = FakeAdapter("mystery-model")
    with pytest.raises(LLMConfigError, match="mystery-model"):
        _governed(_store(tmp_path), adapter)
    assert adapter.calls == 0


_VALID = """
[models."m"]
provider = "p"
prices_as_of = "2026-11-12"
prices_source = "https://example.invalid/pricing"
[[models."m".price_steps]]
up_to_input_tokens = 100
input_usd_per_mtok = 1.0
output_usd_per_mtok = 2.0
[[models."m".price_steps]]
input_usd_per_mtok = 3.0
output_usd_per_mtok = 4.0
"""


def test_parse_catalog_accepts_a_valid_file() -> None:
    assert len(parse_catalog(_VALID).facts_for("m").price_steps) == 2


@pytest.mark.parametrize(
    "mutation",
    [
        lambda t: t.replace('prices_as_of = "2026-11-12"\n', ""),
        lambda t: t.replace('prices_source = "https://example.invalid/pricing"\n', ""),
        lambda t: t.replace('prices_as_of = "2026-11-12"', 'prices_as_of = "yesterday"'),
        lambda t: t.replace("up_to_input_tokens = 100\n", ""),  # first step unbounded, then another step
        lambda t: t.replace("input_usd_per_mtok = 1.0", "input_usd_per_mtok = -1.0"),
        lambda t: t.replace('provider = "p"\n', ""),
    ],
)
def test_parse_catalog_rejects_malformed_files(mutation: Any) -> None:
    with pytest.raises(LLMConfigError):
        parse_catalog(mutation(_VALID))


def test_price_for_boundary_is_inclusive_of_the_first_step() -> None:
    haiku = CATALOG.facts_for(HAIKU)
    assert price_for(haiku, 100_000).input_usd_per_mtok == 0.10
    assert price_for(haiku, 100_001).input_usd_per_mtok == 0.50
    assert isinstance(price_for(haiku, 1), PriceStep)


# ── worst_case_usd, actual_cost_usd, day_key_for ─────────────────────────────


def test_worst_case_worked_example_opus_1000_chars_4000_tokens() -> None:
    # (1000 bytes + 512) x $4/MTok + 4000 x $20/MTok = 0.006048 + 0.08
    cost = worst_case_usd(CATALOG.facts_for(OPUS), system=None, prompt="a" * 1000, max_tokens=4000)
    assert cost == pytest.approx(0.086048)


def test_worst_case_counts_utf8_bytes_of_system_and_prompt() -> None:
    facts = CATALOG.facts_for(OPUS)
    ascii_cost = worst_case_usd(facts, system="ab", prompt="cd", max_tokens=0)
    assert ascii_cost == pytest.approx((4 + 512) * 4.0 / 1e6)
    bengali = worst_case_usd(facts, system=None, prompt="ক", max_tokens=0)  # 3 bytes, 1 char
    assert bengali == pytest.approx((3 + 512) * 4.0 / 1e6)


def test_haiku_worst_case_above_100k_input_tokens_uses_the_higher_step() -> None:
    facts = CATALOG.facts_for(HAIKU)
    low = worst_case_usd(facts, system=None, prompt="x" * (100_000 - 512), max_tokens=1000)
    assert low == pytest.approx(100_000 * 0.10 / 1e6 + 1000 * 0.50 / 1e6)
    high = worst_case_usd(facts, system=None, prompt="x" * (100_000 - 512 + 1), max_tokens=1000)
    assert high == pytest.approx(100_001 * 0.50 / 1e6 + 1000 * 2.50 / 1e6)


def test_governed_reservation_for_a_huge_haiku_input_uses_the_higher_step(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _spend(store, 4.9999)
    adapter = FakeAdapter(HAIKU)
    governed = _governed(store, adapter, budget=LLMBudgetConfig(max_input_chars=500_000))
    with pytest.raises(LLMBudgetExceededError) as info:
        governed.complete(_request("x" * 150_000, max_tokens=1000))
    assert info.value.call_worst_usd == pytest.approx(150_512 * 0.50 / 1e6 + 1000 * 2.50 / 1e6)
    assert adapter.calls == 0


def test_actual_cost_prices_cache_tokens_at_the_full_input_rate_and_never_double_counts_thinking() -> None:
    facts = CATALOG.facts_for(OPUS)
    usage = _usage(10, 20, cache_creation=5, cache_read=3)
    usage["thinking_tokens"] = 15  # already inside completion_tokens
    assert actual_cost_usd(facts, usage) == pytest.approx((10 + 5 + 3) * 4.0 / 1e6 + 20 * 20.0 / 1e6)


def test_actual_cost_picks_the_haiku_step_from_total_input_tokens() -> None:
    facts = CATALOG.facts_for(HAIKU)
    cost = actual_cost_usd(facts, _usage(60_000, 100, cache_read=40_001))
    assert cost == pytest.approx(100_001 * 0.50 / 1e6 + 100 * 2.50 / 1e6)


def test_day_key_uses_a_fixed_utc_plus_6_day() -> None:
    assert day_key_for(datetime(2026, 11, 12, 17, 59, 59, tzinfo=timezone.utc), "+06:00") == "2026-11-12+06:00"
    assert day_key_for(datetime(2026, 11, 12, 18, 0, 0, tzinfo=timezone.utc), "+06:00") == "2026-11-13+06:00"
    assert day_key_for(datetime(2026, 11, 12, 0, 0, 0, tzinfo=timezone.utc), "+06:00") == "2026-11-12+06:00"


def test_day_key_rejects_naive_datetimes_and_bad_offsets() -> None:
    with pytest.raises(ValueError):
        day_key_for(datetime(2026, 11, 12, 9, 30), "+06:00")
    with pytest.raises(ValueError):
        day_key_for(T0, "six hours")


def test_budget_config_defaults_are_the_d092_values() -> None:
    cfg = LLMBudgetConfig()
    assert (cfg.daily_usd_ceiling, cfg.daily_call_limit) == (5.0, 100)
    assert (cfg.max_input_chars, cfg.max_output_tokens) == (24_000, 4_000)
    assert cfg.day_boundary_utc_offset == "+06:00"


# ── Budget: refuse before the network ────────────────────────────────────────


def test_over_budget_call_is_refused_with_zero_adapter_calls_and_no_prompt_text(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _spend(store, 4.95)
    adapter = FakeAdapter(OPUS)
    governed = _governed(store, adapter)
    request = _request(SECRET * 100, max_tokens=4000)  # worst case ~ $0.08

    with pytest.raises(LLMBudgetExceededError) as info:
        governed.complete(request)

    assert adapter.calls == 0
    err = info.value
    assert err.day_key == DAY
    assert err.ceiling_usd == 5.0
    assert err.spent_usd == pytest.approx(4.95)
    assert err.call_worst_usd == pytest.approx(
        worst_case_usd(CATALOG.facts_for(OPUS), system=None, prompt=SECRET * 100, max_tokens=4000)
    )
    assert err.resets_at_utc == RESETS
    assert SECRET not in str(err)
    assert store.spent_today(DAY)[1] == 1  # the refusal reserved nothing


def test_a_call_that_just_fits_is_allowed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    worst = worst_case_usd(CATALOG.facts_for(OPUS), system=None, prompt="hello", max_tokens=100)
    _spend(store, 5.0 - worst - 1e-6)
    adapter = FakeAdapter(OPUS)
    _governed(store, adapter).complete(_request())
    assert adapter.calls == 1


def test_the_101st_call_of_the_day_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    adapter = FakeAdapter(HAIKU, usage=_usage(5, 5))
    governed = _governed(store, adapter)
    for _ in range(100):
        governed.complete(_request(max_tokens=10))
    assert adapter.calls == 100
    with pytest.raises(LLMCallLimitError) as info:
        governed.complete(_request(SECRET, max_tokens=10))
    assert adapter.calls == 100
    assert SECRET not in str(info.value)
    assert info.value.day_key == DAY
    assert info.value.limit == 100
    assert info.value.resets_at_utc == RESETS


def test_day_rollover_at_18_00_utc_resets_spend_and_call_count(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 11, 12, 17, 59, 0, tzinfo=timezone.utc))
    store = _store(tmp_path)
    _spend(store, 4.99, now=clock.now)
    adapter = FakeAdapter(OPUS)
    governed = _governed(store, adapter, clock)
    with pytest.raises(LLMBudgetExceededError):
        governed.complete(_request(max_tokens=4000))
    assert adapter.calls == 0

    clock.now = datetime(2026, 11, 12, 18, 0, 0, tzinfo=timezone.utc)
    governed.complete(_request(max_tokens=4000))
    assert adapter.calls == 1
    assert store.spent_today("2026-11-12+06:00")[0] == pytest.approx(4.99)
    assert store.spent_today("2026-11-13+06:00")[1] == 1


def test_budget_error_resets_at_the_next_local_midnight(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 11, 12, 20, 0, 0, tzinfo=timezone.utc))  # 02:00 next local day
    store = _store(tmp_path)
    _spend(store, 4.99, now=clock.now)
    with pytest.raises(LLMBudgetExceededError) as info:
        _governed(store, FakeAdapter(OPUS), clock).complete(_request(max_tokens=4000))
    assert info.value.day_key == "2026-11-13+06:00"
    assert info.value.resets_at_utc == "2026-11-13T18:00:00+00:00"


# ── Length caps ──────────────────────────────────────────────────────────────


def test_input_of_24001_chars_is_refused_and_24000_is_allowed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    adapter = FakeAdapter(HAIKU)
    governed = _governed(store, adapter)
    with pytest.raises(LLMInputTooLargeError) as info:
        governed.complete(_request("a" * 24_001))
    assert adapter.calls == 0
    assert store.spent_today(DAY) == (0.0, 0)
    governed.complete(_request("a" * 24_000))
    assert adapter.calls == 1
    assert "a" * 50 not in str(info.value)


def test_input_cap_counts_system_plus_prompt_in_characters_not_bytes(tmp_path: Path) -> None:
    adapter = FakeAdapter(HAIKU)
    governed = _governed(_store(tmp_path), adapter)
    governed.complete(_request("ক" * 12_000, system="খ" * 12_000))  # 24,000 chars, 72,000 bytes
    with pytest.raises(LLMInputTooLargeError):
        governed.complete(_request("ক" * 12_000, system="খ" * 12_001))
    with pytest.raises(LLMInputTooLargeError):
        governed.complete(_request("a" * 24_000, system="b"))  # system counts
    assert adapter.calls == 1


def test_max_tokens_4001_is_refused_and_4000_is_allowed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    adapter = FakeAdapter(OPUS)
    governed = _governed(store, adapter)
    with pytest.raises(LLMConfigError, match="4000"):
        governed.complete(_request(max_tokens=4001))
    assert adapter.calls == 0
    assert store.spent_today(DAY) == (0.0, 0)
    governed.complete(_request(max_tokens=4000))
    assert adapter.calls == 1


def test_missing_max_tokens_is_a_config_error_until_tiers_supply_a_default(tmp_path: Path) -> None:
    adapter = FakeAdapter(OPUS)
    with pytest.raises(LLMConfigError, match="max_tokens"):
        _governed(_store(tmp_path), adapter).complete(_request(max_tokens=None))
    assert adapter.calls == 0


def test_non_positive_max_tokens_is_a_config_error(tmp_path: Path) -> None:
    adapter = FakeAdapter(OPUS)
    with pytest.raises(LLMConfigError):
        _governed(_store(tmp_path), adapter).complete(_request(max_tokens=0))
    assert adapter.calls == 0


def test_length_caps_are_checked_before_the_budget(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _spend(store, 5.0)
    adapter = FakeAdapter(OPUS)
    with pytest.raises(LLMInputTooLargeError):
        _governed(store, adapter).complete(_request("a" * 24_001))
    with pytest.raises(LLMConfigError):
        _governed(store, adapter).complete(_request(max_tokens=4001))
    assert adapter.calls == 0


# ── Settle ───────────────────────────────────────────────────────────────────


def test_settle_replaces_the_reservation_with_the_actual_cost(tmp_path: Path) -> None:
    store = _store(tmp_path)
    adapter = FakeAdapter(OPUS, usage=_usage(10, 20, cache_creation=5, cache_read=3))
    governed = _governed(store, adapter)
    worst = worst_case_usd(CATALOG.facts_for(OPUS), system=None, prompt="hi", max_tokens=4000)

    response = governed.complete(_request("hi", max_tokens=4000))

    spent, calls = store.spent_today(DAY)
    assert calls == 1
    assert spent == pytest.approx(18 * 4.0 / 1e6 + 20 * 20.0 / 1e6)
    assert spent < worst
    assert response.call_id
    conn = sqlite3.connect(store.path)
    try:
        row = conn.execute("SELECT call_id, reserved_usd, spent_usd, settled FROM llm_budget").fetchone()
        n_calls = conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0]
    finally:
        conn.close()
    assert row[0] == response.call_id  # budget row and call row share the call id
    assert row[1] == pytest.approx(worst)
    assert row[2] == pytest.approx(spent)
    assert row[3] == 1
    assert n_calls == 1


@pytest.mark.parametrize(
    "error",
    [
        LLMRequestError("503", status_code=503),
        LLMTruncatedError(
            "cut", thinking_only=True, reason="max_tokens", stop_reason="max_tokens", usage=_usage(10, 4000)
        ),
    ],
)
def test_a_call_that_errors_after_send_keeps_its_full_reservation(tmp_path: Path, error: Any) -> None:
    store = _store(tmp_path)
    adapter = FakeAdapter(OPUS, exc=error)
    worst = worst_case_usd(CATALOG.facts_for(OPUS), system=None, prompt="hi", max_tokens=4000)
    with pytest.raises(type(error)):
        _governed(store, adapter).complete(_request("hi", max_tokens=4000))
    assert adapter.calls == 1
    spent, calls = store.spent_today(DAY)
    assert (spent, calls) == (pytest.approx(worst), 1)
    conn = sqlite3.connect(store.path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 1  # still logged (G2)
        assert conn.execute("SELECT settled FROM llm_budget").fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.parametrize("error", [LLMConfigError("bad"), LLMCredentialError("no key")])
def test_errors_raised_before_a_request_leaves_the_process_release_the_reservation(
    tmp_path: Path, error: Any
) -> None:
    store = _store(tmp_path)
    with pytest.raises(type(error)):
        _governed(store, FakeAdapter(OPUS, exc=error)).complete(_request())
    assert store.spent_today(DAY) == (0.0, 0)


def test_actual_above_the_reservation_is_recorded_and_logged_as_an_overshoot(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = _store(tmp_path)
    adapter = FakeAdapter(OPUS, usage=_usage(100_000, 10))  # far more than bytes + 512 allowed for
    with caplog.at_level(logging.WARNING, logger="cv_agent.llm.governed"):
        _governed(store, adapter).complete(_request(SECRET, max_tokens=10))
    spent, _ = store.spent_today(DAY)
    assert spent == pytest.approx(100_000 * 4.0 / 1e6 + 10 * 20.0 / 1e6)
    assert any("overshoot" in r.getMessage().lower() for r in caplog.records)
    assert SECRET not in caplog.text


def test_a_response_without_usage_keeps_the_reservation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    worst = worst_case_usd(CATALOG.facts_for(OPUS), system=None, prompt="hello", max_tokens=100)
    _governed(store, FakeAdapter(OPUS, usage={})).complete(_request())
    assert store.spent_today(DAY)[0] == pytest.approx(worst)


# ── Clock ────────────────────────────────────────────────────────────────────


def test_clock_moved_back_more_than_300_seconds_fails_closed(tmp_path: Path) -> None:
    clock = FakeClock()
    store = _store(tmp_path)
    adapter = FakeAdapter(HAIKU)
    governed = _governed(store, adapter, clock)
    governed.complete(_request())
    clock.now = T0 - timedelta(seconds=301)
    with pytest.raises(LLMClockSkewError):
        governed.complete(_request())
    assert adapter.calls == 1


def test_clock_moved_back_exactly_300_seconds_is_tolerated(tmp_path: Path) -> None:
    clock = FakeClock()
    adapter = FakeAdapter(HAIKU)
    governed = _governed(_store(tmp_path), adapter, clock)
    governed.complete(_request())
    clock.now = T0 - timedelta(seconds=300)
    governed.complete(_request())
    assert adapter.calls == 2


def test_clock_skew_also_blocks_a_backward_jump_across_a_day_boundary(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 11, 12, 18, 0, 5, tzinfo=timezone.utc))  # new day
    store = _store(tmp_path)
    _spend(store, 4.99, now=clock.now)
    adapter = FakeAdapter(OPUS)
    clock.now = datetime(2026, 11, 12, 17, 0, 0, tzinfo=timezone.utc)  # back into the old day
    with pytest.raises(LLMClockSkewError):
        _governed(store, adapter, clock).complete(_request())
    assert adapter.calls == 0


# ── Concurrency ──────────────────────────────────────────────────────────────


def _reserve_worker(path: str, worker: int, worst_usd: float) -> None:
    store = LLMCallStore(Path(path), busy_timeout_s=30.0)
    try:
        store.reserve(
            call_id=f"proc-{worker}",
            now_utc=T0,
            day_key=DAY,
            worst_usd=worst_usd,
            ceiling_usd=5.0,
            call_limit=100,
            skew_tolerance_s=300.0,
            prices_as_of="2026-11-12",
            resets_at_utc=RESETS,
        )
    except LLMBudgetExceededError:
        sys.exit(3)
    sys.exit(0)


def test_two_processes_racing_near_the_ceiling_never_both_pass(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_reserve_worker, args=(str(store.path), w, 3.0)) for w in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=120)
    codes = sorted(p.exitcode for p in procs)  # type: ignore[type-var]
    assert codes == [0, 3, 3, 3]  # exactly one reserved; 3.0 + 3.0 > 5.0 for everyone else
    assert store.spent_today(DAY) == (pytest.approx(3.0), 1)


# ── Schema v2 ────────────────────────────────────────────────────────────────


def test_schema_version_is_2_with_an_llm_budget_table(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert SCHEMA_VERSION == "2"
    conn = sqlite3.connect(store.path)
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        columns = [r[1] for r in conn.execute("PRAGMA table_info(llm_budget)")]
        version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    finally:
        conn.close()
    assert tables == {"llm_calls", "llm_budget", "meta"}
    assert columns == ["call_id", "day_key", "ts_utc", "reserved_usd", "spent_usd", "settled", "prices_as_of"]
    assert version == ("2",)


def test_a_version_1_store_is_refused_with_a_re_init_hint_and_not_migrated(tmp_path: Path) -> None:
    path = tmp_path / "llm_calls.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES ('schema_version', '1')")
    conn.commit()
    conn.close()
    before = path.read_bytes()
    with pytest.raises(LLMStoreError) as info:
        LLMCallStore(path)
    message = str(info.value)
    assert "'1'" in message and "llm-log init" in message and "migration" in message
    assert path.read_bytes() == before
    conn = sqlite3.connect(path)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()
    assert names == {"meta"}  # nothing was created or altered


def test_store_with_a_missing_budget_table_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    conn = sqlite3.connect(store.path)
    conn.execute("DROP TABLE llm_budget")
    conn.commit()
    conn.close()
    with pytest.raises(LLMStoreError):
        LLMCallStore(store.path)


def test_reserve_on_a_naive_timestamp_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _spend(_store(tmp_path), 0.1, now=datetime(2026, 11, 12, 9, 30))


def test_catalog_toml_is_listed_as_wheel_content() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert "cv_agent/llm/catalog.toml" in pyproject.read_text(encoding="utf-8")
