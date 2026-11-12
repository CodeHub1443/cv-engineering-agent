"""
cv_agent.llm.anthropic_provider — Anthropic Claude adapter for the LLM gateway (v2).

This is the ONLY module in cv_agent that may import the `anthropic` SDK
(enforced by tests/test_llm_anthropic.py's structural test) — no skill,
workflow, or graph node may call Anthropic directly [P§20]. It registers
itself in cv_agent.llm.registry on import; the registry imports this module
lazily, only when the "anthropic" provider name is actually requested, so no
other module pays for this dependency by merely importing cv_agent.llm.

Adapter v2 (ADR-0020 §3.8): never sends temperature, top_p, top_k, tools,
tool_choice or budget_tokens; sends `thinking` and `output_config.effort` only
when set on the constructor; returns text blocks only (thinking is never
returned); keeps the request ID; one complete() is one HTTP attempt
(max_retries=0). Only end_turn / stop_sequence with text is an answer; every
other stop reason raises a typed LLMCallError and no partial text is returned.

Credentials: CV_AGENT_ANTHROPIC_API_KEY, resolved by cv_agent.llm.credentials
(process environment, then the project .env loaded by the CLI), never from
AgentConfig/TOML. The generic Anthropic variable is not read (ADR-0021).
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

import anthropic

from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.catalog import EFFORTS, THINKING_MODES, Effort, ThinkingMode
from cv_agent.llm.credentials import get_credential
from cv_agent.llm.errors import (
    LLMConfigError,
    LLMEmptyResponseError,
    LLMRefusalError,
    LLMRequestError,
    LLMTruncatedError,
    LLMUnexpectedStopError,
)
from cv_agent.llm.registry import register_provider

ADAPTER_VERSION: str = "anthropic/2"

_API_KEY_ENV_VAR = "CV_AGENT_ANTHROPIC_API_KEY"
_THINKING_MODES = THINKING_MODES
_EFFORTS = EFFORTS
_NORMAL_STOPS = ("end_turn", "stop_sequence")

_logger = logging.getLogger(__name__)


class AnthropicConfigError(LLMConfigError):
    """Raised when AnthropicProvider cannot be constructed or called (invalid config)."""


class AnthropicRequestError(LLMRequestError):
    """Raised when a completion request to the Anthropic API fails."""


def _count(obj: Any, name: str) -> int:
    """An SDK token counter as a plain int; 0 when absent or not an int."""
    value = getattr(obj, name, None)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _usage(sdk_usage: Any) -> dict[str, int]:
    prompt = _count(sdk_usage, "input_tokens")
    completion = _count(sdk_usage, "output_tokens")
    details = getattr(sdk_usage, "output_tokens_details", None)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_creation_input_tokens": _count(sdk_usage, "cache_creation_input_tokens"),
        "cache_read_input_tokens": _count(sdk_usage, "cache_read_input_tokens"),
        # Thinking tokens are already inside output_tokens; reported separately only.
        "thinking_tokens": _count(details, "thinking_tokens"),
        "total_tokens": prompt + completion,
    }


class AnthropicProvider(LLMProvider):
    """
    Real LLMProvider adapter backed by the Anthropic Messages API.

    Args:
        model:       Anthropic model identifier (e.g. "claude-opus-5-5").
        thinking:    None (omit; provider default), "adaptive" or "disabled".
        effort:      None (omit; provider default) or low/medium/high/xhigh/max.
        api_key:     Explicit API key override. The default (None) resolves
                     CV_AGENT_ANTHROPIC_API_KEY via cv_agent.llm.credentials.
        client:      Pre-built client for dependency injection in tests. When
                     given, api_key/max_retries/timeout are ignored and no
                     credential check is performed.
        max_retries: Passed to anthropic.Anthropic() when no client is given.
                     0 means one complete() is one HTTP attempt.
        timeout:     Passed to anthropic.Anthropic() when no client is given.

    Raises:
        AnthropicConfigError: `thinking` or `effort` is not a legal value.
        LLMCredentialError: no client was given, `api_key` is None and the
            key is found neither in the process environment nor the project .env.
    """

    PROVIDER_NAME: str = "anthropic"

    def __init__(
        self,
        model: str,
        *,
        thinking: Optional[ThinkingMode] = None,
        effort: Optional[Effort] = None,
        api_key: Optional[str] = None,
        client: Optional[Any] = None,
        max_retries: int = 0,
        timeout: float = 60.0,
    ) -> None:
        if thinking is not None and thinking not in _THINKING_MODES:
            raise AnthropicConfigError(
                f"thinking must be None, 'adaptive' or 'disabled', got {thinking!r}."
            )
        if effort is not None and effort not in _EFFORTS:
            raise AnthropicConfigError(f"effort must be None or one of {_EFFORTS}, got {effort!r}.")
        self._model = model
        self._thinking = thinking
        self._effort = effort
        if client is not None:
            self._client = client
            return

        key = api_key if api_key is not None else get_credential(_API_KEY_ENV_VAR)
        self._client = anthropic.Anthropic(api_key=key, max_retries=max_retries, timeout=timeout)

    # ── LLMProvider interface ─────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def adapter_version(self) -> Optional[str]:
        return ADAPTER_VERSION

    @property
    def sdk_version(self) -> Optional[str]:
        return anthropic.__version__

    def complete(self, request: LLMRequest) -> LLMResponse:
        max_tokens = request.max_tokens
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool):
            raise AnthropicConfigError("LLMRequest.max_tokens must be an int for this adapter.")
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system:
            kwargs["system"] = request.system
        if self._thinking is not None:
            kwargs["thinking"] = {"type": self._thinking}
        if self._effort is not None:
            kwargs["output_config"] = {"effort": self._effort}

        try:
            response = self._client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise self._request_error(
                "Anthropic authentication failed (invalid or revoked API key)", exc
            ) from exc
        except anthropic.RateLimitError as exc:
            raise self._request_error(
                f"Anthropic API rate limit exceeded: {exc.message}", exc
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise self._request_error(f"Anthropic API connection failed: {exc}", exc) from exc
        except anthropic.APIStatusError as exc:
            raise self._request_error(
                f"Anthropic API returned an error (status {exc.status_code}): {exc.message}", exc
            ) from exc
        except anthropic.APIError as exc:
            raise self._request_error(f"Anthropic API error: {exc}", exc) from exc

        return self._to_response(response)

    # ── Internals ─────────────────────────────────────────────────────────

    def _request_error(self, message: str, exc: BaseException) -> AnthropicRequestError:
        """Wrapped error with status and request ID when the SDK has them; never the prompt."""
        status = getattr(exc, "status_code", None)
        request_id = getattr(exc, "request_id", None)
        if isinstance(request_id, str) and request_id:
            message = f"{message} [request id {request_id}]"
        else:
            request_id = None
        return AnthropicRequestError(
            message,
            status_code=status if isinstance(status, int) else None,
            request_id=request_id,
            model=self._model,
        )

    def _to_response(self, response: Any) -> LLMResponse:
        blocks = list(response.content)
        text = "".join(
            b.text for b in blocks if getattr(b, "type", None) == "text" and isinstance(b.text, str)
        )
        has_text = bool(text.strip())
        has_thinking = any(
            getattr(b, "type", None) in ("thinking", "redacted_thinking") for b in blocks
        )
        stop = response.stop_reason
        usage = _usage(response.usage)
        raw_id = getattr(response, "_request_id", None)
        request_id = raw_id if isinstance(raw_id, str) else None
        _logger.debug(
            "anthropic completion: model=%s prompt_tokens=%d completion_tokens=%d stop_reason=%s",
            self._model,
            usage["prompt_tokens"],
            usage["completion_tokens"],
            stop,
        )
        diag: dict[str, Any] = {
            "model": self._model,
            "stop_reason": stop,
            "usage": usage,
            "request_id": request_id,
        }

        if stop in _NORMAL_STOPS:
            if not has_text:
                raise LLMEmptyResponseError(
                    f"Anthropic call ended with stop_reason={stop!r} but returned no text.", **diag
                )
            return LLMResponse(
                content=text,
                model=self._model,
                provider=self.PROVIDER_NAME,
                usage=usage,
                stop_reason=stop,
                request_id=request_id,
            )
        if stop in ("max_tokens", "model_context_window_exceeded"):
            reason: Literal["max_tokens", "context_window"] = (
                "max_tokens" if stop == "max_tokens" else "context_window"
            )
            thinking_only = has_thinking and not has_text
            detail = "only thinking was produced" if thinking_only else "partial text discarded"
            raise LLMTruncatedError(
                f"Anthropic output truncated ({reason}); {detail}.",
                thinking_only=thinking_only,
                reason=reason,
                **diag,
            )
        if stop == "refusal":
            raise LLMRefusalError("Anthropic model refused to answer (stop_reason='refusal').", **diag)
        raise LLMUnexpectedStopError(f"Unexpected Anthropic stop_reason {stop!r}.", **diag)


register_provider(AnthropicProvider.PROVIDER_NAME, AnthropicProvider)
