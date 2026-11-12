"""Adapter-level stop-reason and error policy for AnthropicProvider (ADR-0020 §3.5/§3.8, Q35).

Only ``end_turn`` / ``stop_sequence`` with text is an answer. Everything else raises a
typed error and never returns partial or empty text. Uses a fake client; no network.
"""

from __future__ import annotations

import anthropic
import httpx
import pytest

from cv_agent.llm.anthropic_provider import AnthropicProvider, AnthropicRequestError
from cv_agent.llm.base import LLMRequest
from cv_agent.llm.errors import (
    LLMCallError,
    LLMEmptyResponseError,
    LLMRefusalError,
    LLMRequestError,
    LLMTruncatedError,
    LLMUnexpectedStopError,
)
from tests.llm_fakes import (
    FakeAnthropicClient,
    FakeMessage,
    FakeTextBlock,
    FakeThinkingBlock,
    FakeUsage,
    text_message,
)

_REQ = LLMRequest(prompt="SECRET-PROMPT-TEXT", max_tokens=64)


def _provider(response: object = None, exc: BaseException | None = None) -> AnthropicProvider:
    return AnthropicProvider(
        "claude-opus-5-5", client=FakeAnthropicClient(response=response, exc=exc)
    )


@pytest.mark.parametrize("stop", ["end_turn", "stop_sequence"])
def test_normal_stop_with_text_returns_response(stop: str) -> None:
    resp = _provider(text_message("answer", stop_reason=stop)).complete(_REQ)
    assert resp.content == "answer"
    assert resp.stop_reason == stop


def test_max_tokens_with_only_thinking_raises_thinking_only() -> None:
    msg = FakeMessage([FakeThinkingBlock()], stop_reason="max_tokens")
    with pytest.raises(LLMTruncatedError) as ei:
        _provider(msg).complete(_REQ)
    assert ei.value.thinking_only is True
    assert ei.value.reason == "max_tokens"
    assert ei.value.stop_reason == "max_tokens"
    assert isinstance(ei.value, LLMCallError)


def test_max_tokens_with_some_text_still_raises_q35() -> None:
    msg = FakeMessage(
        [FakeThinkingBlock(), FakeTextBlock('{"partial": ')], stop_reason="max_tokens"
    )
    with pytest.raises(LLMTruncatedError) as ei:
        _provider(msg).complete(_REQ)
    assert ei.value.thinking_only is False
    assert ei.value.reason == "max_tokens"


def test_context_window_exceeded_raises_truncated_context_window() -> None:
    msg = FakeMessage([FakeTextBlock("x")], stop_reason="model_context_window_exceeded")
    with pytest.raises(LLMTruncatedError) as ei:
        _provider(msg).complete(_REQ)
    assert ei.value.reason == "context_window"


def test_refusal_raises_refusal_error() -> None:
    msg = FakeMessage([], stop_reason="refusal")
    with pytest.raises(LLMRefusalError):
        _provider(msg).complete(_REQ)


@pytest.mark.parametrize("blocks", [[], [FakeTextBlock("")], [FakeTextBlock("  \n")], [FakeThinkingBlock()]])
def test_end_turn_without_text_raises_empty_response(blocks: list[object]) -> None:
    with pytest.raises(LLMEmptyResponseError):
        _provider(FakeMessage(blocks, stop_reason="end_turn")).complete(_REQ)


@pytest.mark.parametrize("stop", ["tool_use", "pause_turn", "something_new", None])
def test_any_other_stop_reason_raises_unexpected_stop(stop: str | None) -> None:
    with pytest.raises(LLMUnexpectedStopError) as ei:
        _provider(text_message("text", stop_reason=stop)).complete(_REQ)
    assert ei.value.stop_reason == stop


def test_call_errors_carry_model_usage_and_request_id_but_not_the_prompt() -> None:
    msg = FakeMessage(
        [FakeThinkingBlock("SECRET-REASONING")],
        stop_reason="max_tokens",
        usage=FakeUsage(7, 64, thinking_tokens=64),
        request_id="req_trunc",
    )
    with pytest.raises(LLMTruncatedError) as ei:
        _provider(msg).complete(_REQ)
    err = ei.value
    assert err.model == "claude-opus-5-5"
    assert err.request_id == "req_trunc"
    assert err.usage["completion_tokens"] == 64
    assert "SECRET-PROMPT-TEXT" not in str(err)
    assert "SECRET-REASONING" not in str(err)


# ── SDK transport / HTTP failures ─────────────────────────────────────────────


def _http_response(status: int, request_id: str | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    headers = {"request-id": request_id} if request_id else {}
    return httpx.Response(status_code=status, request=request, headers=headers)


def test_http_error_is_llm_request_error_with_status_and_request_id() -> None:
    exc = anthropic.BadRequestError(
        "`temperature` is deprecated for this model.",
        response=_http_response(400, "req_abc123"),
        body=None,
    )
    with pytest.raises(LLMRequestError) as ei:
        _provider(exc=exc).complete(_REQ)
    err = ei.value
    assert isinstance(err, AnthropicRequestError)
    assert err.status_code == 400
    assert err.request_id == "req_abc123"
    assert "400" in str(err)
    assert "req_abc123" in str(err)


def test_transport_error_is_llm_request_error_without_key_or_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_AGENT_ANTHROPIC_API_KEY", "sk-ant-super-secret-value")
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    exc = anthropic.APIConnectionError(message="connection failed", request=request)
    with pytest.raises(LLMRequestError) as ei:
        _provider(exc=exc).complete(_REQ)
    assert "sk-ant-super-secret-value" not in str(ei.value)
    assert "SECRET-PROMPT-TEXT" not in str(ei.value)
