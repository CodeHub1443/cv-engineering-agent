"""
cv_agent.llm.router — task class -> tier -> provider (ADR-0020 §3 items 3-4, slice G5).

Responsibility: validate the project ``[llm]`` config against the gateway catalog at startup
(``build_router``, no network) and hand call sites an ``LLMProvider`` for their task class.
The offline tier is a plain ``FakeLLMProvider`` (ungoverned: no store, no log, no key). Every
hosted tier is a ``GovernedProvider(hosted=True)`` over the adapter, built lazily on the first
``for_task`` call for that class and then reused, so a missing key or a missing call log never
breaks startup or offline use. There is no fallback: a route resolves or raises, and it never
turns into another tier, model or provider.

This module names no provider and no model: the catalog does.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from cv_agent.config.settings import LLMBudgetConfig, LLMConfig
from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.catalog import Catalog, TierSpec, load_catalog
from cv_agent.llm.clock import Clock, SystemClock
from cv_agent.llm.errors import LLMConfigError, LLMStoreError
from cv_agent.llm.governed import GovernedProvider
from cv_agent.llm.policy import DataClass, TaskClass
from cv_agent.llm.registry import get_provider
from cv_agent.llm.sqlite_store import LLM_CALLS_FILENAME, LLMCallStore

_WORST_BYTES_PER_CHAR = 4  # UTF-8
_FRAMING_RESERVE = 512  # tokens, the same reserve ``worst_case_usd`` uses


@dataclass(frozen=True)
class RouteInfo:
    """What a task class resolves to; reading it builds nothing and touches no key or store."""

    task_class: TaskClass
    tier: str
    provider: str
    model: str
    hosted: bool


def _validate(
    routing: Mapping[str, str], budget: LLMBudgetConfig, catalog: Catalog
) -> dict[TaskClass, TierSpec]:
    """Every check that needs the catalog; ``LLMConfigError`` on the first failure."""
    routes: dict[TaskClass, TierSpec] = {}
    for task_class in TaskClass:
        tier_name = routing.get(task_class.value, "offline")
        tier = catalog.tiers.get(tier_name)
        if tier is None:
            raise LLMConfigError(
                f"[llm.routing] {task_class.value} = {tier_name!r} is not a tier; known: {sorted(catalog.tiers)}."
            )
        routes[task_class] = tier
    unknown = sorted(set(routing) - {tc.value for tc in TaskClass})
    if unknown:
        raise LLMConfigError(f"[llm.routing]: unknown task class(es) {unknown}.")
    worst_input_tokens = budget.max_input_chars * _WORST_BYTES_PER_CHAR + _FRAMING_RESERVE
    for tier in catalog.tiers.values():
        if tier.max_tokens > budget.max_output_tokens:
            raise LLMConfigError(
                f"tier {tier.name!r}: max_tokens {tier.max_tokens} is above [llm.budget] "
                f"max_output_tokens {budget.max_output_tokens}."
            )
        facts = catalog.models.get(tier.model)
        if tier.hosted and facts is not None and len(facts.price_steps) > 1:
            first_step = facts.price_steps[0].up_to_input_tokens
            if first_step is not None and worst_input_tokens > first_step:
                raise LLMConfigError(
                    f"[llm.budget] max_input_chars {budget.max_input_chars} can reach {worst_input_tokens} input "
                    f"tokens, past the first price step ({first_step}) of {tier.model!r}; lower it."
                )
    return routes


class LLMRouter:
    """Resolves a task class to an ``LLMProvider``. Build it with ``build_router``."""

    def __init__(
        self,
        *,
        routes: Mapping[TaskClass, TierSpec],
        config: LLMConfig,
        catalog: Catalog,
        allowed_hosted: frozenset[DataClass],
        state_dir: Optional[Path],
        clock: Clock,
    ) -> None:
        self._routes = dict(routes)
        self._config = config
        self._catalog = catalog
        self._allowed_hosted = allowed_hosted
        self._state_dir = state_dir
        self._clock = clock
        self._built: dict[TaskClass, LLMProvider] = {}

    def routes(self) -> tuple[RouteInfo, ...]:
        """One entry per task class, in ``TaskClass`` order. Builds nothing."""
        return tuple(
            RouteInfo(tc, tier.name, tier.provider, tier.model, tier.hosted) for tc, tier in self._routes.items()
        )

    def for_task(self, task_class: TaskClass) -> LLMProvider:
        """The provider for ``task_class``, built on first use and then reused.

        Hosted tiers raise ``LLMCredentialError`` (no key) or ``LLMStoreError`` (no call log) here,
        never at startup, and never fall back to another tier.
        """
        if task_class not in self._built:
            self._built[task_class] = self._build(task_class, self._routes[task_class])
        return self._built[task_class]

    def lazy_for_task(self, task_class: TaskClass) -> LLMProvider:
        """A provider that calls ``for_task`` on its first ``complete()`` instead of now.

        For a caller that must be constructed at startup (``CVAgent``): its name and model come
        from the route, so nothing is built, and no key or store is needed, until a call is made.
        """
        tier = self._routes[task_class]
        return _RoutedProvider(self, task_class, tier.provider, tier.model)

    def _build(self, task_class: TaskClass, tier: TierSpec) -> LLMProvider:
        if not tier.hosted:
            return get_provider(tier.provider, tier.model)
        adapter = get_provider(tier.provider, tier.model, thinking=tier.thinking, effort=tier.effort)
        store = LLMCallStore(self._store_path())
        return GovernedProvider(
            hosted=True,
            task_class=task_class.value,
            tier=tier.name,
            adapter=adapter,
            store=store,
            store_text=self._config.log.store_text,
            clock=self._clock,
            thinking=tier.thinking,
            effort=tier.effort,
            budget=self._config.budget,
            catalog=self._catalog,
            allowed_hosted=self._allowed_hosted,
            tier_max_tokens=tier.max_tokens,
        )

    def _store_path(self) -> Path:
        if self._state_dir is not None:
            return self._state_dir / LLM_CALLS_FILENAME
        from cv_agent.experiments.provenance import ProvenanceError, repository_state_root

        try:  # the repository's .cv_agent/ (ADR-0011), found only when a hosted call needs it
            return repository_state_root() / LLM_CALLS_FILENAME
        except ProvenanceError as exc:
            raise LLMStoreError(f"cannot locate the LLM call log: {exc}") from exc


class _RoutedProvider(LLMProvider):
    """Defers ``LLMRouter.for_task`` to the first ``complete()``; see ``LLMRouter.lazy_for_task``."""

    def __init__(self, router: LLMRouter, task_class: TaskClass, provider: str, model: str) -> None:
        self._router = router
        self._task_class = task_class
        self._provider = provider
        self._model = model

    @property
    def provider_name(self) -> str:
        return self._provider

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, request: LLMRequest) -> LLMResponse:
        return self._router.for_task(self._task_class).complete(request)


def build_router(
    config: LLMConfig,
    state_dir: Optional[Path],
    clock: Optional[Clock] = None,
    catalog: Optional[Catalog] = None,
) -> LLMRouter:
    """Validate ``config`` against the catalog and return the router; ``LLMConfigError`` on any
    invalid setting. No network, no key read, no store opened.

    ``state_dir`` holds ``llm_calls.sqlite``; ``None`` means the repository's ``.cv_agent/``,
    looked up only when a hosted call first needs it.
    """
    catalog = catalog or load_catalog()
    routes = _validate(config.routing, config.budget, catalog)
    try:
        allowed = frozenset(DataClass[name] for name in config.privacy.hosted_allowed_data_classes)
    except KeyError as exc:
        raise LLMConfigError(f"[llm.privacy]: unknown data class {exc.args[0]!r}.") from None
    return LLMRouter(
        routes=routes,
        config=config,
        catalog=catalog,
        allowed_hosted=allowed,
        state_dir=state_dir,
        clock=clock or SystemClock(),
    )
