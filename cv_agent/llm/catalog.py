"""
cv_agent.llm.catalog — gateway-owned model facts and prices (ADR-0020 §3 item 2, slice G3).

Responsibility: load and validate ``catalog.toml`` (shipped inside the package, read through
``importlib.resources``) and answer "what does this model cost for this many input tokens".
Tiers and capability facts are not here yet (G5). An unknown model is an ``LLMConfigError``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from importlib import resources
from typing import Any, Mapping, Optional

from cv_agent.llm.errors import LLMConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10 only
    import tomli as tomllib

CATALOG_FILENAME = "catalog.toml"


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


@dataclass(frozen=True)
class Catalog:
    models: Mapping[str, ModelFacts]

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
    return Catalog({name: _model(name, body) for name, body in models.items()})


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
    return ModelFacts(name, text("provider"), steps, as_of, text("prices_source"))


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
