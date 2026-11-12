"""
cv_agent.llm.errors — exception types for the LLM gateway.

Responsibility: name the gateway's failure modes so callers can catch them without
importing a provider module. Credential failures come from ADR-0021; configuration and
after-send call failures from ADR-0020 slice G1, the call-log store failure from G2. Budget,
privacy and clock-skew errors arrive with their own slices (G3 onward).
"""

from __future__ import annotations

from typing import Any, Literal, Optional


class LLMError(RuntimeError):
    """Base class for every error raised by the LLM gateway."""


class LLMCredentialError(LLMError):
    """A credential is missing, unreadable or malformed. Never carries a secret value."""


class LLMConfigError(LLMError):
    """An adapter or gateway setting is invalid. Raised before any request is sent."""


class LLMStoreError(LLMError):
    """The call log is missing, corrupt, busy, of a foreign schema version, or a write failed.

    The gateway fails closed on it: a call that cannot be logged is not handed out.
    """


class LLMCallError(LLMError):
    """Base for failures after a request was sent (or attempted).

    Carries diagnostics only: never the key, the prompt or any model output text.
    ``call_id`` and ``tier`` stay None until a governed provider (G4) fills them in.
    """

    def __init__(
        self,
        message: str,
        *,
        model: Optional[str] = None,
        stop_reason: Optional[str] = None,
        usage: Optional[dict[str, int]] = None,
        request_id: Optional[str] = None,
        call_id: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.model = model
        self.stop_reason = stop_reason
        self.usage: dict[str, int] = usage or {}
        self.request_id = request_id
        self.call_id = call_id
        self.tier = tier


class LLMRequestError(LLMCallError):
    """The provider request failed at the transport or HTTP level."""

    def __init__(
        self, message: str, *, status_code: Optional[int] = None, **kwargs: Any
    ) -> None:
        super().__init__(message, **kwargs)
        self.status_code = status_code


class LLMTruncatedError(LLMCallError):
    """The output was cut off (token cap or context window); partial text is never returned."""

    def __init__(
        self,
        message: str,
        *,
        thinking_only: bool,
        reason: Literal["max_tokens", "context_window"],
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.thinking_only = thinking_only
        self.reason = reason


class LLMRefusalError(LLMCallError):
    """The model refused to answer (stop reason ``refusal``)."""


class LLMEmptyResponseError(LLMCallError):
    """The call ended normally but produced no text."""


class LLMUnexpectedStopError(LLMCallError):
    """The stop reason is not one this gateway accepts (tool use, pause, unknown)."""
