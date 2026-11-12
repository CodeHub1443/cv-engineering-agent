"""
cv_agent.llm.base — Abstract LLM provider interface.

All provider adapters (Anthropic, OpenAI, Google, local, mock, …)
must implement LLMProvider.  Graph logic depends only on this interface;
no provider name is ever hard-coded outside the registry module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LLMRequest:
    """Input to an LLM completion call."""

    prompt: str
    system: Optional[str] = None
    max_tokens: Optional[int] = None  # None is legal here; adapters require an int
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
    stop_reason: Optional[str] = None
    request_id: Optional[str] = None  # the provider's request ID, when it gave one
    call_id: Optional[str] = None  # set by the governed provider (G4), never by an adapter


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

    @property
    def adapter_version(self) -> Optional[str]:
        """Adapter contract version (e.g. 'anthropic/2'); None when not applicable."""
        return None

    @property
    def sdk_version(self) -> Optional[str]:
        """Version of the provider SDK in use; None when not applicable."""
        return None

    @property
    def local_model_digest(self) -> Optional[str]:
        """Digest of a locally served model; None for hosted providers."""
        return None

    @property
    def local_quantization(self) -> Optional[str]:
        """Quantization of a locally served model; None for hosted providers."""
        return None

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"provider={self.provider_name!r}, "
            f"model={self.model_name!r})"
        )
