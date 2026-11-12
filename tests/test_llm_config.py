"""Slice G5 acceptance tests: tiers, task-class routing, [llm] config and the router.

ADR-0020 §3 items 2-4, 10, 11 and §7 "G5"; D-089, D-092; issue #97. No network, no real key,
no real state root: stores live under ``tmp_path``, the API key (when needed) is a placeholder
set on the test's own environment, and nothing here sends a request.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from cv_agent.config.settings import AgentConfig, LLMConfig, load_config
from cv_agent.llm import catalog as catalog_module
from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.catalog import load_catalog, parse_catalog
from cv_agent.llm.errors import (
    LLMConfigError,
    LLMCredentialError,
    LLMDataClassNotAllowedError,
    LLMStoreError,
)
from cv_agent.llm.governed import GovernedProvider
from cv_agent.llm.mock import FakeLLMProvider
from cv_agent.llm.policy import DataClass, TaskClass
from cv_agent.llm.registry import get_provider
from cv_agent.llm.router import LLMRouter, RouteInfo, build_router
from cv_agent.llm.sqlite_store import LLMCallStore
from tests.llm_fakes import FakeAnthropicClient, text_message

OPUS = "claude-opus-5-5"
HAIKU = "claude-haiku-5-5"
KEY_VAR = "CV_AGENT_ANTHROPIC_API_KEY"
CATALOG_TEXT = (
    Path(catalog_module.__file__).with_name(catalog_module.CATALOG_FILENAME).read_text(encoding="utf-8")
)


def _config(tmp_path: Path, body: str) -> LLMConfig:
    path = tmp_path / "cfg.toml"
    path.write_text(body, encoding="utf-8")
    return load_config(path).llm


def _router(tmp_path: Path, routing: Optional[dict[str, str]] = None, **kwargs: Any) -> LLMRouter:
    cfg = LLMConfig()
    if routing:
        cfg.routing.update(routing)
    return build_router(cfg, state_dir=tmp_path, **kwargs)


# ── The shipped defaults ─────────────────────────────────────────────────────


def test_default_config_loads_with_documented_values() -> None:
    llm = load_config().llm
    assert llm.routing == {"extraction": "offline", "selection": "offline", "narrative": "offline"}
    assert llm.budget.daily_usd_ceiling == 5.0
    assert llm.budget.daily_call_limit == 100
    assert llm.budget.max_input_chars == 24_000
    assert llm.budget.max_output_tokens == 4_000
    assert llm.budget.day_boundary_utc_offset == "+06:00"
    assert llm.privacy.hosted_allowed_data_classes == ("PUBLIC_WEB", "PROJECT_METADATA")
    assert llm.log.store_text is False


def test_missing_config_file_gives_the_same_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "missing.toml").llm == load_config().llm == LLMConfig()


def test_legacy_provider_model_and_overrides_are_gone() -> None:
    llm = LLMConfig()
    assert not hasattr(llm, "provider") and not hasattr(llm, "model") and not hasattr(llm, "overrides")
    with pytest.raises(ImportError):
        from cv_agent.config.settings import LLMOverride  # noqa: F401


def test_every_default_route_is_offline_and_ungoverned(tmp_path: Path) -> None:
    router = build_router(load_config().llm, state_dir=tmp_path)
    assert router.routes() == tuple(
        RouteInfo(tc, "offline", "mock", "fake-1", False) for tc in TaskClass
    )
    for tc in TaskClass:
        provider = router.for_task(tc)
        assert type(provider) is FakeLLMProvider
        assert not isinstance(provider, GovernedProvider)
    assert list(tmp_path.iterdir()) == []  # offline use creates nothing


# ── Config validation (load time, no network) ───────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        '[llm]\nprovider = "mock"\n',
        '[llm]\nmodel = "fake-1"\n',
        '[llm.overrides.planner]\nprovider = "anthropic"\nmodel = "x"\n',
        "[llm.extra]\nx = 1\n",
        '[llm.routing]\nbogus = "offline"\n',  # unknown task class
        '[llm.routing]\nextraction = 3\n',
        "[llm.budget]\ntemperature = 0.0\n",
        "[llm.budget]\ntop_p = 1\n",
        "[llm.budget]\nbudget_tokens = 10\n",
        "[llm.privacy]\ntool_choice = 1\n",
        "[llm.log]\nkeep_days = 3\n",
        "[llm]\nrouting = 3\n",
    ],
)
def test_keys_outside_the_four_sections_are_rejected(tmp_path: Path, body: str) -> None:
    with pytest.raises(LLMConfigError):
        _config(tmp_path, body)


@pytest.mark.parametrize(
    "body",
    [
        '[llm.privacy]\nhosted_allowed_data_classes = ["PUBLIC_WEB", "SECRET_STUFF"]\n',
        '[llm.privacy]\nhosted_allowed_data_classes = ["public_web"]\n',
        '[llm.privacy]\nhosted_allowed_data_classes = "PUBLIC_WEB"\n',
        '[llm.budget]\nday_boundary_utc_offset = "6:00"\n',
        '[llm.budget]\nday_boundary_utc_offset = "UTC+6"\n',
        '[llm.budget]\nday_boundary_utc_offset = "+25:00"\n',
        '[llm.budget]\nday_boundary_utc_offset = 6\n',
        "[llm.budget]\ndaily_usd_ceiling = 0\n",
        "[llm.budget]\ndaily_usd_ceiling = -1.5\n",
        '[llm.budget]\ndaily_usd_ceiling = "5"\n',
        "[llm.budget]\ndaily_call_limit = 0\n",
        "[llm.budget]\ndaily_call_limit = -3\n",
        "[llm.budget]\ndaily_call_limit = 2.5\n",
        "[llm.budget]\nmax_input_chars = 0\n",
        "[llm.budget]\nmax_output_tokens = 0\n",
        '[llm.log]\nstore_text = "yes"\n',
    ],
)
def test_bad_values_are_rejected_at_load(tmp_path: Path, body: str) -> None:
    with pytest.raises(LLMConfigError):
        _config(tmp_path, body)


def test_a_valid_partial_config_keeps_defaults_for_the_rest(tmp_path: Path) -> None:
    llm = _config(
        tmp_path,
        '[llm.routing]\nextraction = "fast"\n[llm.budget]\ndaily_usd_ceiling = 1.25\n'
        '[llm.privacy]\nhosted_allowed_data_classes = ["PUBLIC_WEB"]\n[llm.log]\nstore_text = true\n',
    )
    assert llm.routing == {"extraction": "fast", "selection": "offline", "narrative": "offline"}
    assert llm.budget.daily_usd_ceiling == 1.25 and llm.budget.daily_call_limit == 100
    assert llm.privacy.hosted_allowed_data_classes == ("PUBLIC_WEB",)
    assert llm.log.store_text is True


def test_unknown_tier_name_is_rejected_by_build_router(tmp_path: Path) -> None:
    llm = _config(tmp_path, '[llm.routing]\nextraction = "turbo"\n')  # shape is fine; the catalog decides
    with pytest.raises(LLMConfigError, match="turbo"):
        build_router(llm, state_dir=tmp_path)


def test_tier_max_tokens_above_the_budget_cap_is_rejected(tmp_path: Path) -> None:
    llm = _config(tmp_path, "[llm.budget]\nmax_output_tokens = 2000\n")  # strong tier is 4000
    with pytest.raises(LLMConfigError, match="max_tokens"):
        build_router(llm, state_dir=tmp_path)


def test_a_budget_cap_that_covers_every_tier_is_accepted(tmp_path: Path) -> None:
    llm = _config(tmp_path, "[llm.budget]\nmax_output_tokens = 4000\n")
    assert len(build_router(llm, state_dir=tmp_path).routes()) == len(TaskClass)


def test_haiku_price_step_guard_rejects_an_input_cap_that_can_cross_the_step(tmp_path: Path) -> None:
    # 30,000 chars x 4 bytes + 512 > 100,000 input tokens (the first Haiku price step).
    llm = _config(tmp_path, "[llm.budget]\nmax_input_chars = 30000\n")
    with pytest.raises(LLMConfigError, match="price step"):
        build_router(llm, state_dir=tmp_path)


def _catalog_with(old: str, new: str) -> str:
    assert old in CATALOG_TEXT, old
    return CATALOG_TEXT.replace(old, new, 1)


def test_tier_max_tokens_above_the_model_maximum_is_rejected() -> None:
    text = _catalog_with("max_tokens = 4000", "max_tokens = 4000000")
    with pytest.raises(LLMConfigError, match="max_tokens"):
        parse_catalog(text)


def test_opus_with_thinking_disabled_is_rejected() -> None:
    text = _catalog_with("max_tokens = 4000", 'max_tokens = 4000\nthinking = "disabled"')
    with pytest.raises(LLMConfigError, match="cannot disable"):
        parse_catalog(text)


@pytest.mark.parametrize("effort", ["xhigh", "max"])
def test_haiku_disabled_with_xhigh_or_max_is_rejected(effort: str) -> None:
    text = _catalog_with('thinking = "disabled"', f'thinking = "disabled"\neffort = "{effort}"')
    with pytest.raises(LLMConfigError, match="effort"):
        parse_catalog(text)


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_haiku_disabled_with_effort_up_to_high_is_accepted(effort: str) -> None:
    text = _catalog_with('thinking = "disabled"', f'thinking = "disabled"\neffort = "{effort}"')
    assert parse_catalog(text).tiers["fast"].effort == effort


def test_opus_effort_is_accepted_when_thinking_is_adaptive() -> None:
    text = _catalog_with("max_tokens = 4000", 'max_tokens = 4000\neffort = "max"')
    assert parse_catalog(text).tiers["strong"].effort == "max"


@pytest.mark.parametrize(
    "old,new",
    [
        ("max_tokens = 4000", 'max_tokens = 4000\nthinking = "enabled"'),
        ("max_tokens = 4000", 'max_tokens = 4000\ntemperature = 0.0'),
        ("max_tokens = 4000", 'max_tokens = 4000\nbudget_tokens = 100'),
        ("max_tokens = 4000", 'max_tokens = 4000\neffort = "ludicrous"'),
        ('model = "claude-opus-5-5"\nhosted = true', 'model = "claude-opus-9-9"\nhosted = true'),
        ('provider = "anthropic"\nmodel = "claude-opus-5-5"', 'provider = "openai"\nmodel = "claude-opus-5-5"'),
        ("max_tokens = 4000", "max_tokens = 0"),
        ("hosted = true\nmax_tokens = 4000", 'hosted = "yes"\nmax_tokens = 4000'),
    ],
)
def test_malformed_tiers_are_rejected(old: str, new: str) -> None:
    with pytest.raises(LLMConfigError):
        parse_catalog(_catalog_with(old, new))


# ── The shipped catalog ──────────────────────────────────────────────────────


def test_shipped_tiers_match_d089_and_d092() -> None:
    cat = load_catalog()
    assert set(cat.tiers) == {"offline", "fast", "strong"}
    offline, fast, strong = cat.tiers["offline"], cat.tiers["fast"], cat.tiers["strong"]
    assert (offline.provider, offline.model, offline.hosted, offline.max_tokens) == ("mock", "fake-1", False, 1024)
    assert (fast.provider, fast.model, fast.hosted, fast.max_tokens) == ("anthropic", HAIKU, True, 1024)
    assert fast.thinking == "disabled" and fast.effort is None
    assert (strong.provider, strong.model, strong.hosted, strong.max_tokens) == ("anthropic", OPUS, True, 4000)
    assert strong.thinking is None and strong.effort is None  # adaptive, provider default effort


def test_shipped_capability_facts() -> None:
    cat = load_catalog()
    opus, haiku = cat.facts_for(OPUS), cat.facts_for(HAIKU)
    assert opus.thinking_can_disable is False and opus.thinking_disable_max_effort is None
    assert haiku.thinking_can_disable is True and haiku.thinking_disable_max_effort == "high"
    assert opus.max_output_tokens and haiku.max_output_tokens


# ── Routes, lazy hosted tiers, no fallback ───────────────────────────────────


def test_routes_report_tier_provider_model_and_hosted_without_building_anything(tmp_path: Path) -> None:
    router = _router(tmp_path, {"extraction": "fast", "selection": "strong"})
    assert router.routes() == (
        RouteInfo(TaskClass.EXTRACTION, "fast", "anthropic", HAIKU, True),
        RouteInfo(TaskClass.SELECTION, "strong", "anthropic", OPUS, True),
        RouteInfo(TaskClass.NARRATIVE, "offline", "mock", "fake-1", False),
    )
    assert list(tmp_path.iterdir()) == []  # no store created, no key read


def test_hosted_route_does_not_break_startup_or_offline_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(KEY_VAR, raising=False)
    router = _router(tmp_path / "no-store-here", {"extraction": "fast"})  # build is fine: no key, no store
    assert type(router.for_task(TaskClass.NARRATIVE)) is FakeLLMProvider  # offline still works


def test_missing_key_surfaces_as_credential_error_only_on_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(KEY_VAR, raising=False)
    router = _router(tmp_path, {"extraction": "fast"})
    with pytest.raises(LLMCredentialError):
        router.for_task(TaskClass.EXTRACTION)


def test_missing_store_surfaces_as_store_error_and_never_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(KEY_VAR, "placeholder-not-a-real-key")
    router = _router(tmp_path, {"extraction": "fast"})  # no store was initialised
    with pytest.raises(LLMStoreError, match="llm-log init"):
        router.for_task(TaskClass.EXTRACTION)
    assert type(router.for_task(TaskClass.SELECTION)) is FakeLLMProvider  # other routes unaffected


def test_hosted_route_is_a_governed_provider_built_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_VAR, "placeholder-not-a-real-key")
    LLMCallStore.initialise(tmp_path / "llm_calls.sqlite")
    router = _router(tmp_path, {"extraction": "fast", "narrative": "strong"})
    fast = router.for_task(TaskClass.EXTRACTION)
    assert isinstance(fast, GovernedProvider)
    assert (fast.provider_name, fast.model_name, fast.tier_name, fast.task_class) == (
        "anthropic",
        HAIKU,
        "fast",
        "extraction",
    )
    assert router.for_task(TaskClass.EXTRACTION) is fast
    strong = router.for_task(TaskClass.NARRATIVE)
    assert isinstance(strong, GovernedProvider) and strong.model_name == OPUS and strong is not fast


def test_a_hosted_route_refuses_project_data_by_default_before_any_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(KEY_VAR, "placeholder-not-a-real-key")
    LLMCallStore.initialise(tmp_path / "llm_calls.sqlite")
    narrative = _router(tmp_path, {"narrative": "fast"}).for_task(TaskClass.NARRATIVE)
    with pytest.raises(LLMDataClassNotAllowedError):
        narrative.complete(LLMRequest(prompt="a request", data_classes=frozenset({DataClass.PROJECT_DATA})))
    with pytest.raises(LLMDataClassNotAllowedError):
        narrative.complete(LLMRequest(prompt="declares nothing"))


def test_the_privacy_allow_set_comes_from_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_VAR, "placeholder-not-a-real-key")
    LLMCallStore.initialise(tmp_path / "llm_calls.sqlite")
    llm = _config(tmp_path, '[llm.routing]\nextraction = "fast"\n[llm.privacy]\nhosted_allowed_data_classes = ["PUBLIC_WEB"]\n')
    provider = build_router(llm, state_dir=tmp_path).for_task(TaskClass.EXTRACTION)
    with pytest.raises(LLMDataClassNotAllowedError):  # PROJECT_METADATA is no longer allowed
        provider.complete(LLMRequest(prompt="x", data_classes=frozenset({DataClass.PROJECT_METADATA})))


# ── GovernedProvider tier default for max_tokens ─────────────────────────────


class _Recorder(LLMProvider):
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    provider_name = "anthropic"  # type: ignore[assignment]
    model_name = HAIKU  # type: ignore[assignment]

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            content="ok", model=HAIKU, provider="anthropic", usage={"prompt_tokens": 1, "completion_tokens": 1},
            stop_reason="end_turn",
        )


class _Clock:
    def now_utc(self) -> datetime:
        return datetime(2026, 11, 12, 9, 30, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        return 0.0


def _governed(tmp_path: Path, tier_max_tokens: Optional[int]) -> tuple[GovernedProvider, _Recorder]:
    LLMCallStore.initialise(tmp_path / "llm_calls.sqlite")
    adapter = _Recorder()
    provider = GovernedProvider(
        hosted=False,
        task_class="extraction",
        tier="fast",
        adapter=adapter,
        store=LLMCallStore(tmp_path / "llm_calls.sqlite"),
        clock=_Clock(),
        tier_max_tokens=tier_max_tokens,
    )
    return provider, adapter


def test_request_without_max_tokens_gets_the_tier_value(tmp_path: Path) -> None:
    provider, adapter = _governed(tmp_path, 1024)
    provider.complete(LLMRequest(prompt="hi"))
    assert adapter.requests[0].max_tokens == 1024


def test_explicit_max_tokens_above_the_tier_raises_with_no_silent_clamp(tmp_path: Path) -> None:
    provider, adapter = _governed(tmp_path, 1024)
    with pytest.raises(LLMConfigError, match="1024"):
        provider.complete(LLMRequest(prompt="hi", max_tokens=2000))
    assert adapter.requests == []
    provider.complete(LLMRequest(prompt="hi", max_tokens=300))
    assert adapter.requests[0].max_tokens == 300


def test_without_a_tier_value_max_tokens_is_still_required(tmp_path: Path) -> None:
    provider, adapter = _governed(tmp_path, None)
    with pytest.raises(LLMConfigError):
        provider.complete(LLMRequest(prompt="hi"))
    assert adapter.requests == []


# ── Registry passes adapter options ──────────────────────────────────────────


def test_get_provider_passes_thinking_and_effort_to_the_adapter() -> None:
    client = FakeAnthropicClient(response=text_message("ok"))
    provider = get_provider("anthropic", HAIKU, thinking="disabled", effort="high", client=client)
    provider.complete(LLMRequest(prompt="hi", max_tokens=50))
    sent = client.messages.calls[0]
    assert sent["thinking"] == {"type": "disabled"}
    assert sent["output_config"] == {"effort": "high"}


def test_get_provider_still_works_without_options() -> None:
    assert type(get_provider("mock", "fake-1")) is FakeLLMProvider
    assert get_provider("mock", "fake-9", fixed_response="x").complete(LLMRequest(prompt="p")).content == "x"


def test_agent_config_carries_only_the_llm_sections() -> None:
    cfg = AgentConfig()
    assert set(vars(cfg.llm)) == {"routing", "budget", "privacy", "log"}
