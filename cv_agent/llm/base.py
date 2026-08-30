"""
cv_agent.llm.base — Abstract LLM provider interface.

All provider adapters (Anthropic, OpenAI, Google, local, mock, …)
must implement LLMProvider.  Graph logic depends only on this interface;
no provider name is ever hard-coded outside the registry module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMRequest:
    """Input to an LLM completion call."""

    prompt: str
    system: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Output from an LLM completion call."""

    content: str
    model: str
    provider: str
    # Token counts — providers may return 0 if not available
    usage: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """
    Abstract base class for all LLM provider adapters.

    Implementations are registered in cv_agent.llm.registry and
    selected at runtime via configuration — never imported directly
    by graph or capability code.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable identifier for this provider (e.g. 'anthropic', 'openai', 'mock')."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier as accepted by the provider's API."""

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """
        Perform a completion and return the response.

        Implementations must be synchronous.  Async support will be
        added in a later step when streaming is required.
        """

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"provider={self.provider_name!r}, "
            f"model={self.model_name!r})"
        )
