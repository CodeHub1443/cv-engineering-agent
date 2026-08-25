"""
cv_agent.llm.registry — Provider factory and registration.

Real provider adapters (e.g. AnthropicProvider, OpenAIProvider) register
themselves here in their own modules.  Graph and runtime code only calls
get_provider(); it never imports a concrete adapter directly.
"""

from __future__ import annotations

from typing import Type

from cv_agent.llm.base import LLMProvider
from cv_agent.llm.mock import FakeLLMProvider

# Internal registry: provider name → concrete class
_REGISTRY: dict[str, Type[LLMProvider]] = {
    FakeLLMProvider.PROVIDER_NAME: FakeLLMProvider,
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
        ValueError: If the provider name is not registered.
    """
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY))
        raise ValueError(
            f"Unknown LLM provider {name!r}. "
            f"Registered providers: {available}"
        )
    cls = _REGISTRY[name]
    return cls(model=model)


def list_providers() -> list[str]:
    """Return sorted list of registered provider names."""
    return sorted(_REGISTRY)
