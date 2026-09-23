"""
cv_agent.llm.registry — Provider factory and registration.

Real provider adapters (e.g. AnthropicProvider, OpenAIProvider) register
themselves here in their own modules.  Graph and runtime code only calls
get_provider(); it never imports a concrete adapter directly.
"""

from __future__ import annotations

import importlib
from typing import Type

from cv_agent.llm.base import LLMProvider
from cv_agent.llm.mock import FakeLLMProvider

# Internal registry: provider name → concrete class
_REGISTRY: dict[str, Type[LLMProvider]] = {
    FakeLLMProvider.PROVIDER_NAME: FakeLLMProvider,
}

# Provider name -> adapter module to import lazily on first request. The
# adapter module registers itself (register_provider()) as a side effect of
# being imported. Kept as a plain literal map, not a discovery mechanism —
# adding a provider means adding one entry here and one new module (ADR-0002
# §4: a generic plugin-scanner was rejected as speculative with only one
# real adapter to justify it).
_LAZY_ADAPTERS: dict[str, str] = {
    "anthropic": "cv_agent.llm.anthropic_provider",
}


def register_provider(name: str, cls: Type[LLMProvider]) -> None:
    """
    Register a new LLM provider adapter.

    Call this from the adapter's own module at import time so that the
    registry stays the single source of truth:

        from cv_agent.llm.registry import register_provider
        register_provider("anthropic", AnthropicProvider)
    """
    if not issubclass(cls, LLMProvider):
        raise TypeError(f"{cls!r} must be a subclass of LLMProvider")
    _REGISTRY[name] = cls


def get_provider(name: str, model: str) -> LLMProvider:
    """
    Instantiate a provider by name and model.

    Args:
        name:  Provider identifier (e.g. 'mock', 'anthropic', 'openai').
        model: Model identifier passed to the provider constructor.

    Returns:
        Configured LLMProvider instance.

    Raises:
        ValueError: If the provider name is not registered and has no known
            adapter module, or its adapter module failed to import (e.g. the
            provider's optional dependency is not installed).
    """
    if name not in _REGISTRY and name in _LAZY_ADAPTERS:
        module_name = _LAZY_ADAPTERS[name]
        try:
            importlib.import_module(module_name)
        except ImportError as exc:
            raise ValueError(
                f"LLM provider {name!r} is known but its adapter module "
                f"{module_name!r} failed to import (its optional dependency "
                f"may not be installed): {exc}"
            ) from exc

    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY))
        raise ValueError(
            f"Unknown LLM provider {name!r}. "
            f"Registered providers: {available}"
        )
    cls = _REGISTRY[name]
    # `LLMProvider` (the ABC) declares no __init__, since its only concrete
    # subclasses today are free to accept whatever their own adapter needs
    # (API keys, timeouts, ...) — `register_provider()` enforces `issubclass
    # (cls, LLMProvider)` but not a constructor signature. Every provider
    # actually registered is required, by this function's own contract
    # above ("model: Model identifier passed to the provider constructor"),
    # to accept `model` as shown; mypy cannot verify that through a bare
    # `Type[LLMProvider]`, so this is a real, load-bearing runtime contract,
    # not a bug — a provider that violates it fails loudly here, uncaught.
    return cls(model=model)  # type: ignore[call-arg]


def list_providers() -> list[str]:
    """Return sorted list of provider names, registered or known-lazy.

    Includes names in `_LAZY_ADAPTERS` that have not been imported yet, so a
    caller can discover "anthropic" is available without first triggering
    get_provider() — importing its adapter module may still fail later (e.g.
    a missing optional dependency), which get_provider() reports at that
    point, not here.
    """
    return sorted(set(_REGISTRY) | set(_LAZY_ADAPTERS))
