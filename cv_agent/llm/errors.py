"""
cv_agent.llm.errors — exception types for the LLM gateway.

Responsibility: name the gateway's failure modes so callers can catch them without
importing a provider module. Credential failures come from ADR-0021; configuration and
after-send call failures from ADR-0020 slice G1, the call-log store failure from G2, budget,
call-limit, input-size and clock-skew refusals from G3, the data-class refusal from G4. None of
these messages ever carries prompt text.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from cv_agent.llm.policy import DataClass, TaskClass


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


class LLMClockSkewError(LLMError):
    """The clock reads earlier than the last recorded call by more than the tolerance."""


class LLMDataClassNotAllowedError(LLMError):
    """A hosted tier was asked to carry a data class it may not receive. Nothing was sent.

    The message names the task class, the tier and the blocked classes only, never prompt text.
    """

    def __init__(self, task_class: TaskClass | str, tier: str, blocked: frozenset[DataClass]) -> None:
        names = ", ".join(sorted(d.value for d in blocked))
        task = task_class.value if isinstance(task_class, TaskClass) else task_class
        super().__init__(f"LLM privacy refused: tier {tier!r} (task {task!r}) may not receive: {names}.")
        self.task_class = task_class
        self.tier = tier
        self.blocked = blocked


class LLMUnstructuredRequestError(LLMDataClassNotAllowedError):
    """A hosted SELECTION or NARRATIVE request carried no payload (ADR-0023 §3.2 rule 1). Nothing was sent.

    Free text on a structured-only route is a privacy refusal (it counts as ``PROJECT_DATA``), so this
    subclasses the data-class error: existing privacy handlers keep catching it. Never carries prompt text.
    """

    def __init__(self, task_class: TaskClass, tier: str) -> None:
        super().__init__(task_class, tier, frozenset({DataClass.PROJECT_DATA}))
        self.args = (
            f"LLM privacy refused: tier {tier!r} (task {task_class.value!r}) accepts structured payloads "
            "only; nothing was sent.",
        )


class LLMPayloadMisuseError(LLMError):
    """A payload came with prompt, system or data classes, or was not issued by the builder, or does not
    match the route's task class. Raised before any reservation or network I/O; never carries payload text."""


class PayloadFieldError(ValueError):
    """The payload builder or schema registry rejected a leaf, type or registration (ADR-0023 §3.2).

    Raised before any request exists. The message names the field path or vocabulary, never the value.
    """


class LLMInputTooLargeError(LLMError):
    """``len(system) + len(prompt)`` exceeds the input cap. Raised before any network I/O."""

    def __init__(self, *, chars: int, limit: int) -> None:
        super().__init__(f"LLM input is {chars} characters; the limit is {limit}.")
        self.chars = chars
        self.limit = limit


class LLMBudgetExceededError(LLMError):
    """Today's spend plus this call's worst case would pass the daily ceiling. Nothing was sent."""

    def __init__(
        self, *, day_key: str, ceiling_usd: float, spent_usd: float, call_worst_usd: float, resets_at_utc: str
    ) -> None:
        super().__init__(
            f"LLM daily budget refused: day {day_key}, spent ${spent_usd:.6f} of ${ceiling_usd:.2f}, "
            f"this call could cost up to ${call_worst_usd:.6f}; resets at {resets_at_utc}."
        )
        self.day_key = day_key
        self.ceiling_usd = ceiling_usd
        self.spent_usd = spent_usd
        self.call_worst_usd = call_worst_usd
        self.resets_at_utc = resets_at_utc


class LLMCallLimitError(LLMError):
    """The day's call limit is used up. Nothing was sent."""

    def __init__(self, *, day_key: str, limit: int, resets_at_utc: str) -> None:
        super().__init__(
            f"LLM daily call limit refused: day {day_key} has used {limit} of {limit} calls; "
            f"resets at {resets_at_utc}."
        )
        self.day_key = day_key
        self.limit = limit
        self.resets_at_utc = resets_at_utc


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
