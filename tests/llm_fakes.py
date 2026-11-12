"""Fake Anthropic SDK objects shared by the adapter tests (no network, no real types).

The adapter reads only attributes (``content``, ``usage``, ``stop_reason``,
``_request_id``), so plain objects stand in for the SDK's response models.
"""

from __future__ import annotations

from typing import Any, Optional


class FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class FakeThinkingBlock:
    def __init__(self, thinking: str = "internal reasoning") -> None:
        self.type = "thinking"
        self.thinking = thinking
        self.signature = "sig"


class FakeThinkingDetails:
    def __init__(self, thinking_tokens: int) -> None:
        self.thinking_tokens = thinking_tokens


class FakeUsage:
    """Only the counters the SDK reports; absent ones stay absent (not zero)."""

    def __init__(
        self,
        input_tokens: int = 10,
        output_tokens: int = 5,
        *,
        cache_creation_input_tokens: Optional[int] = None,
        cache_read_input_tokens: Optional[int] = None,
        thinking_tokens: Optional[int] = None,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        if cache_creation_input_tokens is not None:
            self.cache_creation_input_tokens = cache_creation_input_tokens
        if cache_read_input_tokens is not None:
            self.cache_read_input_tokens = cache_read_input_tokens
        if thinking_tokens is not None:
            self.output_tokens_details = FakeThinkingDetails(thinking_tokens)


class FakeMessage:
    def __init__(
        self,
        blocks: list[Any],
        *,
        stop_reason: Optional[str] = "end_turn",
        usage: Optional[FakeUsage] = None,
        request_id: Optional[str] = None,
    ) -> None:
        self.content = blocks
        self.usage = usage if usage is not None else FakeUsage()
        self.stop_reason = stop_reason
        if request_id is not None:
            self._request_id = request_id


def text_message(text: str, **kwargs: Any) -> FakeMessage:
    return FakeMessage([FakeTextBlock(text)], **kwargs)


class FakeMessagesResource:
    def __init__(self, *, response: Any = None, exc: Optional[BaseException] = None) -> None:
        self._response = response
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._response


class FakeAnthropicClient:
    def __init__(self, *, response: Any = None, exc: Optional[BaseException] = None) -> None:
        self.messages = FakeMessagesResource(response=response, exc=exc)
