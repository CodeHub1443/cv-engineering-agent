"""
cv_agent.llm.mock — Deterministic fake LLM provider for tests and offline use.

FakeLLMProvider requires no API keys, no network access, and returns
predictable responses.  It is the default provider in config/default.toml.
"""

from __future__ import annotations

from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse


class FakeLLMProvider(LLMProvider):
    """Deterministic fake LLM provider."""

    PROVIDER_NAME: str = "mock"

    def __init__(
        self,
        model: str = "fake-1",
        fixed_response: str | None = None,
    ) -> None:
        self._model = model
        self._fixed_response = fixed_response
        self._call_count: int = 0

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, request: LLMRequest) -> LLMResponse:
        self._call_count += 1
        prompt_preview = request.prompt[:60].replace("\n", " ")
        content = (
            self._fixed_response
            if self._fixed_response is not None
            else f"[FakeLLM:{self._model}] Response #{self._call_count} to: {prompt_preview!r}"
        )
        prompt_tokens = len(request.prompt.split())
        completion_tokens = len(content.split())
        return LLMResponse(
            content=content,
            model=self._model,
            provider=self.PROVIDER_NAME,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )

    @property
    def call_count(self) -> int:
        return self._call_count

    def reset(self) -> None:
        self._call_count = 0
