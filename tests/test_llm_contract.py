"""Provider contract suite (ADR-0020 test plan, slice G6; D-092). No network, no key.

One shape contract is applied to every provider that can answer: the offline fake and the
Anthropic adapter over a fake SDK client. The error mapping and the never-sent parameters are
adapter-only, since the fake has no wire and no stop reasons other than ``end_turn``.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

from cv_agent.llm.anthropic_provider import AnthropicProvider
from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.errors import LLMEmptyResponseError, LLMRefusalError, LLMTruncatedError
from cv_agent.llm.mock import FakeLLMProvider
from tests.llm_fakes import FakeAnthropicClient, FakeMessage, FakeTextBlock, FakeThinkingBlock, text_message

_MODEL = "claude-haiku-5-5"
_NEVER_SENT = ("temperature", "top_p", "top_k", "tools", "tool_choice")


def _fake() -> LLMProvider:
    return FakeLLMProvider()


def _anthropic() -> LLMProvider:
    return AnthropicProvider(_MODEL, client=FakeAnthropicClient(response=text_message("hello")))


_FACTORIES: list[Callable[[], LLMProvider]] = [_fake, _anthropic]


@pytest.fixture(params=_FACTORIES, ids=["fake", "anthropic-fake-client"])
def provider(request: pytest.FixtureRequest) -> LLMProvider:
    factory: Callable[[], LLMProvider] = request.param
    return factory()


def test_returns_a_complete_response(provider: LLMProvider) -> None:
    response = provider.complete(LLMRequest(prompt="Say hi.", max_tokens=64))
    assert isinstance(response, LLMResponse)
    assert isinstance(response.content, str) and response.content.strip()
    assert response.stop_reason == "end_turn"
    assert response.provider == provider.provider_name
    assert response.model == provider.model_name
    assert {"prompt_tokens", "completion_tokens", "total_tokens"} <= set(response.usage)
    assert all(isinstance(v, int) for v in response.usage.values())


def _adapter(message: Any) -> tuple[AnthropicProvider, FakeAnthropicClient]:
    client = FakeAnthropicClient(response=message)
    return AnthropicProvider(_MODEL, client=client), client


def _call(p: AnthropicProvider) -> LLMResponse:
    return p.complete(LLMRequest(prompt="q", max_tokens=64))


def test_adapter_truncation_raises_and_discards_partial_text() -> None:
    p, _ = _adapter(FakeMessage([FakeTextBlock("partial")], stop_reason="max_tokens"))
    with pytest.raises(LLMTruncatedError):
        _call(p)


def test_adapter_thinking_only_truncation_is_flagged() -> None:
    p, _ = _adapter(FakeMessage([FakeThinkingBlock()], stop_reason="max_tokens"))
    with pytest.raises(LLMTruncatedError) as info:
        _call(p)
    assert info.value.thinking_only is True


def test_adapter_refusal_raises() -> None:
    p, _ = _adapter(FakeMessage([FakeTextBlock("no")], stop_reason="refusal"))
    with pytest.raises(LLMRefusalError):
        _call(p)


@pytest.mark.parametrize("blocks", [[], [FakeTextBlock("  ")], [FakeThinkingBlock()]])
def test_adapter_empty_answer_raises(blocks: list[Any]) -> None:
    p, _ = _adapter(FakeMessage(blocks, stop_reason="end_turn"))
    with pytest.raises(LLMEmptyResponseError):
        _call(p)


@pytest.mark.parametrize("kwargs", [{}, {"thinking": "disabled"}, {"thinking": "adaptive", "effort": "low"}])
def test_adapter_never_sends_sampling_or_tool_parameters(kwargs: dict[str, Any]) -> None:
    client = FakeAnthropicClient(response=text_message("ok"))
    AnthropicProvider(_MODEL, client=client, **kwargs).complete(
        LLMRequest(prompt="q", system="s", max_tokens=64)
    )
    sent = client.messages.calls[0]
    assert not set(_NEVER_SENT) & set(sent)
    assert "budget_tokens" not in str(sent.get("thinking", ""))
