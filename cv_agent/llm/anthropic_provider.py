"""
cv_agent.llm.anthropic_provider — Anthropic Claude adapter for the LLM gateway.

This is the ONLY module in cv_agent that may import the `anthropic` SDK
(enforced by tests/test_llm_anthropic.py's structural test) — no skill,
workflow, or graph node may call Anthropic directly [P§20]. It registers
itself in cv_agent.llm.registry on import; the registry imports this module
lazily, only when the "anthropic" provider name is actually requested, so no
other module pays for this dependency by merely importing cv_agent.llm.

Credentials: ANTHROPIC_API_KEY is read from the process environment, never
from AgentConfig/TOML (docs/APPROVALS.md's data/privacy rule; CLAUDE.md's
"no hard-coded API keys or secrets"). See ADR-0002.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import anthropic

from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.registry import register_provider

_API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"

_logger = logging.getLogger(__name__)


class AnthropicConfigError(RuntimeError):
    """Raised when AnthropicProvider cannot be constructed (missing/invalid config)."""


class AnthropicRequestError(RuntimeError):
    """Raised when a completion request to the Anthropic API fails."""


class AnthropicProvider(LLMProvider):
    """
    Real LLMProvider adapter backed by the Anthropic Messages API.

    Args:
        model:       Anthropic model identifier (e.g. "claude-sonnet-4-5").
        api_key:     Explicit API key override. Not read from AgentConfig —
                     the default (None) reads ANTHROPIC_API_KEY from the
                     environment. Provided only for direct construction/tests.
        client:      Pre-built client for dependency injection in tests. When
                     given, api_key/max_retries/timeout are ignored entirely
                     and no credential check is performed — the caller owns
                     the client's configuration.
        max_retries: Passed to anthropic.Anthropic() when no client is given.
        timeout:     Passed to anthropic.Anthropic() when no client is given.

    Raises:
        AnthropicConfigError: no client was given and no API key is available
            from either `api_key` or the ANTHROPIC_API_KEY environment
            variable.
    """

    PROVIDER_NAME: str = "anthropic"

    def __init__(
        self,
        model: str,
        *,
        api_key: Optional[str] = None,
        client: Optional[Any] = None,
        max_retries: int = 2,
        timeout: float = 60.0,
    ) -> None:
        self._model = model
        if client is not None:
            self._client = client
            return

        key = api_key if api_key is not None else os.environ.get(_API_KEY_ENV_VAR)
        if not key:
            raise AnthropicConfigError(
                f"Anthropic provider requires an API key: set the {_API_KEY_ENV_VAR} "
                "environment variable. Credentials are never read from AgentConfig "
                "or a TOML config file (docs/APPROVALS.md)."
            )
        self._client = anthropic.Anthropic(
            api_key=key, max_retries=max_retries, timeout=timeout
        )

    # ── LLMProvider interface ─────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, request: LLMRequest) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system:
            kwargs["system"] = request.system

        try:
            response = self._client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise AnthropicRequestError(
                "Anthropic authentication failed (invalid or revoked API key)."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise AnthropicRequestError(
                f"Anthropic API rate limit exceeded: {exc.message}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise AnthropicRequestError(
                f"Anthropic API connection failed: {exc}"
            ) from exc
        except anthropic.APIStatusError as exc:
            raise AnthropicRequestError(
                f"Anthropic API returned an error (status {exc.status_code}): "
                f"{exc.message}"
            ) from exc
        except anthropic.APIError as exc:
            raise AnthropicRequestError(f"Anthropic API error: {exc}") from exc

        content = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }
        _logger.debug(
            "anthropic completion: model=%s prompt_tokens=%d completion_tokens=%d stop_reason=%s",
            self._model,
            usage["prompt_tokens"],
            usage["completion_tokens"],
            response.stop_reason,
        )
        return LLMResponse(
            content=content,
            model=self._model,
            provider=self.PROVIDER_NAME,
            usage=usage,
            metadata={"stop_reason": response.stop_reason},
        )


register_provider(AnthropicProvider.PROVIDER_NAME, AnthropicProvider)
