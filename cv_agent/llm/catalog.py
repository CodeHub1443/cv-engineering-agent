"""
cv_agent.llm.catalog — gateway-owned model facts and prices (ADR-0020 §3 item 2, slice G3).

Responsibility: load and validate ``catalog.toml`` (shipped inside the package, read through
``importlib.resources``): the tiers (which provider and model serve a tier, whether it leaves this
machine, its output cap and thinking setting), each model's capability facts, and "what does this
model cost for this many input tokens". A tier that breaks a model's facts, an unknown model and
any unknown key are ``LLMConfigError`` at load.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from typing import Any, Literal, Mapping, Optional

from cv_agent.llm.errors import LLMConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10 only
    import tomli as tomllib

CATALOG_FILENAME = "catalog.toml"

ThinkingMode = Literal["adaptive", "disabled"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
THINKING_MODES: tuple[str, ...] = ("adaptive", "disabled")  # "enabled" is not a legal tier value
EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")  # ascending
_TIER_KEYS = ("provider", "model", "hosted", "max_tokens", "thinking", "effort")


@dataclass(frozen=True)
class PriceStep:
    """USD per million tokens while total input tokens <= ``up_to_input_tokens`` (None = no bound)."""

    up_to_input_tokens: Optional[int]
    input_usd_per_mtok: float
    output_usd_per_mtok: float


@dataclass(frozen=True)
class ModelFacts:
    model: str
    provider: str
    price_steps: tuple[PriceStep, ...]
    prices_as_of: str
    prices_source: str
    thinking_can_disable: bool = False
    thinking_disable_max_effort: Optional[str] = None  # highest effort at which "disabled" is accepted
    max_output_tokens: Optional[int] = None  # None: no model maximum is known


@dataclass(frozen=True)
class TierSpec:
    """What a tier name means: a provider and model, whether the call leaves this machine, the output
    cap (thinking included) and the thinking setting. ``None`` means the provider default."""

    name: str
    provider: str
    model: str
    hosted: bool
    max_tokens: int
    thinking: Optional[str] = None
    effort: Optional[str] = None


@dataclass(frozen=True)
class Catalog:
    models: Mapping[str, ModelFacts]
    tiers: Mapping[str, TierSpec] = field(default_factory=dict)

    def facts_for(self, model: str) -> ModelFacts:
        try:
            return self.models[model]
        except KeyError:
            raise LLMConfigError(f"model {model!r} is not in the LLM catalog; add it to catalog.toml.") from None


def price_for(facts: ModelFacts, input_tokens: int) -> PriceStep:
    """The price step that ``input_tokens`` total input tokens fall into."""
    for step in facts.price_steps:
        if step.up_to_input_tokens is None or input_tokens <= step.up_to_input_tokens:
            return step
    raise LLMConfigError(f"model {facts.model!r} has no price step for {input_tokens} input tokens.")


def load_catalog() -> Catalog:
    """Read ``catalog.toml`` from the installed package and validate it."""
    text = resources.files("cv_agent.llm").joinpath(CATALOG_FILENAME).read_text(encoding="utf-8")
    return parse_catalog(text)


def parse_catalog(text: str) -> Catalog:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise LLMConfigError(f"catalog.toml is not valid TOML: {exc}") from exc
    models = raw.get("models")
    if not isinstance(models, dict) or not models:
        raise LLMConfigError("catalog.toml defines no [models.*] table.")
    facts = {name: _model(name, body) for name, body in models.items()}
    raw_tiers = raw.get("tiers", {})
    if not isinstance(raw_tiers, dict):
        raise LLMConfigError("catalog.toml: [tiers] must be a table of tiers.")
    return Catalog(facts, {name: _tier(name, body, facts) for name, body in raw_tiers.items()})


def _model(name: str, body: Any) -> ModelFacts:
    def text(key: str) -> str:
        value = body.get(key) if isinstance(body, dict) else None
        if not isinstance(value, str) or not value:
            raise LLMConfigError(f"catalog model {name!r}: {key} must be a non-empty string.")
        return value

    as_of = text("prices_as_of")
    try:
        date.fromisoformat(as_of)
    except ValueError:
        raise LLMConfigError(f"catalog model {name!r}: prices_as_of {as_of!r} is not an ISO date.") from None
    raw_steps = body.get("price_steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise LLMConfigError(f"catalog model {name!r}: price_steps must list at least one step.")
    steps = tuple(_step(name, s) for s in raw_steps)
    bounds = [s.up_to_input_tokens for s in steps]
    finite = [b for b in bounds[:-1] if b is not None]
    if bounds[-1] is not None or len(finite) != len(bounds) - 1 or finite != sorted(set(finite)):
        raise LLMConfigError(
            f"catalog model {name!r}: price_steps need strictly ascending bounds and an unbounded last step."
        )
    can_disable = body.get("thinking_can_disable", False)
    if not isinstance(can_disable, bool):
        raise LLMConfigError(f"catalog model {name!r}: thinking_can_disable must be true or false.")
    max_effort = body.get("thinking_disable_max_effort")
    if max_effort is not None and max_effort not in EFFORTS:
        raise LLMConfigError(f"catalog model {name!r}: thinking_disable_max_effort must be one of {EFFORTS}.")
    max_output = body.get("max_output_tokens")
    if max_output is not None and (not isinstance(max_output, int) or isinstance(max_output, bool) or max_output < 1):
        raise LLMConfigError(f"catalog model {name!r}: max_output_tokens must be a positive integer.")
    return ModelFacts(
        name, text("provider"), steps, as_of, text("prices_source"), can_disable, max_effort, max_output
    )


def _tier(name: str, body: Any, models: Mapping[str, ModelFacts]) -> TierSpec:
    def fail(why: str) -> LLMConfigError:
        return LLMConfigError(f"catalog tier {name!r}: {why}")

    if not isinstance(body, dict):
        raise fail("must be a table.")
    unknown = sorted(set(body) - set(_TIER_KEYS))
    if unknown:
        raise fail(f"unknown key(s) {unknown}; allowed: {list(_TIER_KEYS)}.")
    provider, model = body.get("provider"), body.get("model")
    if not isinstance(provider, str) or not provider or not isinstance(model, str) or not model:
        raise fail("provider and model must be non-empty strings.")
    hosted, max_tokens = body.get("hosted"), body.get("max_tokens")
    if not isinstance(hosted, bool):
        raise fail("hosted must be true or false.")
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
        raise fail("max_tokens must be a positive integer.")
    thinking, effort = body.get("thinking"), body.get("effort")
    if thinking is not None and thinking not in THINKING_MODES:
        raise fail(f"thinking must be one of {THINKING_MODES} or omitted, got {thinking!r}.")
    if effort is not None and effort not in EFFORTS:
        raise fail(f"effort must be one of {EFFORTS} or omitted, got {effort!r}.")
    facts = models.get(model)
    if facts is None:
        if hosted:
            raise fail(f"hosted model {model!r} has no [models.*] entry (prices and capability facts).")
    else:
        if facts.provider != provider:
            raise fail(f"provider {provider!r} does not match the catalog's {facts.provider!r} for {model!r}.")
        if facts.max_output_tokens is not None and max_tokens > facts.max_output_tokens:
            raise fail(f"max_tokens {max_tokens} is above {model!r}'s maximum output {facts.max_output_tokens}.")
        if thinking == "disabled" and not facts.thinking_can_disable:
            raise fail(f"{model!r} cannot disable thinking.")
        if thinking == "disabled" and effort is not None and facts.thinking_disable_max_effort is not None:
            if EFFORTS.index(effort) > EFFORTS.index(facts.thinking_disable_max_effort):
                raise fail(
                    f"effort {effort!r} is above {facts.thinking_disable_max_effort!r}, "
                    f"the highest effort at which {model!r} accepts thinking disabled."
                )
    return TierSpec(name, provider, model, hosted, max_tokens, thinking, effort)


def _step(name: str, raw: Any) -> PriceStep:
    if not isinstance(raw, dict):
        raise LLMConfigError(f"catalog model {name!r}: a price step must be a table.")
    bound = raw.get("up_to_input_tokens")
    if bound is not None and (not isinstance(bound, int) or isinstance(bound, bool) or bound <= 0):
        raise LLMConfigError(f"catalog model {name!r}: up_to_input_tokens must be a positive integer.")
    prices = []
    for key in ("input_usd_per_mtok", "output_usd_per_mtok"):
        value = raw.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise LLMConfigError(f"catalog model {name!r}: {key} must be a non-negative number.")
        prices.append(float(value))
    return PriceStep(bound, prices[0], prices[1])
