"""Tests for cv_agent.llm.anthropic_provider (ADR-0002).

No test in this file makes a real network call or requires a real API key —
every completion path is exercised against an injected fake client. The one
test that constructs a real anthropic.Anthropic() client (via get_provider())
never calls .complete() on it, so no network request happens; a dummy,
obviously-fake key string is used to prove only that construction itself
requires *some* credential to be present.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import anthropic
import httpx
import pytest

from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.anthropic_provider import (
    AnthropicConfigError,
    AnthropicProvider,
    AnthropicRequestError,
)
from cv_agent.llm.registry import get_provider, list_providers

_ENV_VAR = "ANTHROPIC_API_KEY"


# ── Fake Anthropic SDK objects (no network, no real types) ────────────────


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeMessage:
    def __init__(
        self,
        text: str,
        *,
        input_tokens: int = 10,
        output_tokens: int = 5,
        stop_reason: str = "end_turn",
    ) -> None:
        self.content = [_FakeTextBlock(text)]
        self.usage = _FakeUsage(input_tokens, output_tokens)
        self.stop_reason = stop_reason


class _FakeMessagesResource:
    def __init__(self, *, response: Any = None, exc: Optional[BaseException] = None) -> None:
        self._response = response
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._response


class _FakeAnthropicClient:
    def __init__(self, *, response: Any = None, exc: Optional[BaseException] = None) -> None:
        self.messages = _FakeMessagesResource(response=response, exc=exc)


def _http_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(status_code=status_code, request=request)


# ── Construction / credential handling ─────────────────────────────────────


class TestAnthropicProviderConstruction:
    def test_is_llm_provider_subclass(self) -> None:
        assert issubclass(AnthropicProvider, LLMProvider)

    def test_provider_name(self) -> None:
        client = _FakeAnthropicClient()
        p = AnthropicProvider("claude-sonnet-5", client=client)
        assert p.provider_name == "anthropic"

    def test_model_name(self) -> None:
        client = _FakeAnthropicClient()
        p = AnthropicProvider("claude-sonnet-5", client=client)
        assert p.model_name == "claude-sonnet-5"

    def test_missing_api_key_raises_config_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_ENV_VAR, raising=False)
        with pytest.raises(AnthropicConfigError, match=_ENV_VAR):
            AnthropicProvider("claude-sonnet-5")

    def test_explicit_api_key_overrides_missing_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_ENV_VAR, raising=False)
        # Construction only builds the client; no network call is made here.
        p = AnthropicProvider("claude-sonnet-5", api_key="sk-ant-test-not-real")
        assert p.model_name == "claude-sonnet-5"

    def test_env_var_supplies_key_when_no_override_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_ENV_VAR, "sk-ant-test-not-real")
        p = AnthropicProvider("claude-sonnet-5")
        assert p.model_name == "claude-sonnet-5"

    def test_injected_client_bypasses_credential_check_entirely(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_ENV_VAR, raising=False)
        client = _FakeAnthropicClient()
        p = AnthropicProvider("claude-sonnet-5", client=client)
        assert p.model_name == "claude-sonnet-5"


# ── complete() — success path ───────────────────────────────────────────────


class TestAnthropicProviderComplete:
    def test_complete_returns_mapped_response(self) -> None:
        message = _FakeMessage("Hello from Claude.", input_tokens=12, output_tokens=4)
        client = _FakeAnthropicClient(response=message)
        p = AnthropicProvider("claude-sonnet-5", client=client)

        resp = p.complete(LLMRequest(prompt="hi"))

        assert isinstance(resp, LLMResponse)
        assert resp.content == "Hello from Claude."
        assert resp.model == "claude-sonnet-5"
        assert resp.provider == "anthropic"
        assert resp.usage == {
            "prompt_tokens": 12,
            "completion_tokens": 4,
            "total_tokens": 16,
        }
        assert resp.metadata == {"stop_reason": "end_turn"}

    def test_complete_passes_prompt_as_user_message(self) -> None:
        client = _FakeAnthropicClient(response=_FakeMessage("ok"))
        p = AnthropicProvider("claude-sonnet-5", client=client)

        p.complete(LLMRequest(prompt="describe this frame"))

        call = client.messages.calls[0]
        assert call["messages"] == [{"role": "user", "content": "describe this frame"}]
        assert call["model"] == "claude-sonnet-5"
        assert "system" not in call

    def test_complete_passes_system_prompt_when_given(self) -> None:
        client = _FakeAnthropicClient(response=_FakeMessage("ok"))
        p = AnthropicProvider("claude-sonnet-5", client=client)

        p.complete(LLMRequest(prompt="q", system="You are a CV assistant."))

        assert client.messages.calls[0]["system"] == "You are a CV assistant."

    def test_complete_passes_max_tokens_and_temperature(self) -> None:
        client = _FakeAnthropicClient(response=_FakeMessage("ok"))
        p = AnthropicProvider("claude-sonnet-5", client=client)

        p.complete(LLMRequest(prompt="q", max_tokens=256, temperature=0.5))

        call = client.messages.calls[0]
        assert call["max_tokens"] == 256
        assert call["temperature"] == 0.5

    def test_complete_ignores_non_text_content_blocks(self) -> None:
        message = _FakeMessage("kept")
        message.content.insert(0, type("ToolUseBlock", (), {"type": "tool_use"})())
        client = _FakeAnthropicClient(response=message)
        p = AnthropicProvider("claude-sonnet-5", client=client)

        resp = p.complete(LLMRequest(prompt="q"))

        assert resp.content == "kept"


# ── complete() — error mapping ───────────────────────────────────────────────


class TestAnthropicProviderErrorHandling:
    def test_authentication_error_is_wrapped(self) -> None:
        exc = anthropic.AuthenticationError(
            "invalid api key", response=_http_response(401), body=None
        )
        client = _FakeAnthropicClient(exc=exc)
        p = AnthropicProvider("claude-sonnet-5", client=client)

        with pytest.raises(AnthropicRequestError, match="authentication failed"):
            p.complete(LLMRequest(prompt="q"))

    def test_rate_limit_error_is_wrapped(self) -> None:
        exc = anthropic.RateLimitError(
            "rate limited", response=_http_response(429), body=None
        )
        client = _FakeAnthropicClient(exc=exc)
        p = AnthropicProvider("claude-sonnet-5", client=client)

        with pytest.raises(AnthropicRequestError, match="rate limit"):
            p.complete(LLMRequest(prompt="q"))

    def test_connection_error_is_wrapped(self) -> None:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        exc = anthropic.APIConnectionError(message="connection failed", request=request)
        client = _FakeAnthropicClient(exc=exc)
        p = AnthropicProvider("claude-sonnet-5", client=client)

        with pytest.raises(AnthropicRequestError, match="connection failed"):
            p.complete(LLMRequest(prompt="q"))

    def test_generic_status_error_is_wrapped(self) -> None:
        exc = anthropic.InternalServerError(
            "server exploded", response=_http_response(500), body=None
        )
        client = _FakeAnthropicClient(exc=exc)
        p = AnthropicProvider("claude-sonnet-5", client=client)

        with pytest.raises(AnthropicRequestError, match="status 500"):
            p.complete(LLMRequest(prompt="q"))

    def test_generic_api_error_is_wrapped(self) -> None:
        exc = anthropic.APIResponseValidationError(
            response=_http_response(200), body=None, message="schema mismatch"
        )
        client = _FakeAnthropicClient(exc=exc)
        p = AnthropicProvider("claude-sonnet-5", client=client)

        with pytest.raises(AnthropicRequestError, match="Anthropic API error"):
            p.complete(LLMRequest(prompt="q"))

    def test_error_message_never_contains_env_var_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_ENV_VAR, "sk-ant-super-secret-value")
        exc = anthropic.AuthenticationError(
            "invalid api key", response=_http_response(401), body=None
        )
        client = _FakeAnthropicClient(exc=exc)
        p = AnthropicProvider("claude-sonnet-5", client=client)

        with pytest.raises(AnthropicRequestError) as exc_info:
            p.complete(LLMRequest(prompt="q"))
        assert "sk-ant-super-secret-value" not in str(exc_info.value)


# ── Registry integration ────────────────────────────────────────────────────


class TestAnthropicRegistryIntegration:
    def test_anthropic_listed_as_a_known_provider(self) -> None:
        assert "anthropic" in list_providers()

    def test_mock_provider_unaffected(self) -> None:
        p = get_provider("mock", "fake-1")
        assert p.provider_name == "mock"

    def test_get_provider_constructs_a_real_anthropic_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Construction only builds an anthropic.Anthropic() client object; it
        # makes no network request. A dummy key proves only that the
        # registry -> lazy-import -> construction path works end to end.
        monkeypatch.setenv(_ENV_VAR, "sk-ant-test-not-real")
        p = get_provider("anthropic", "claude-sonnet-5")
        assert isinstance(p, AnthropicProvider)
        assert p.provider_name == "anthropic"
        assert p.model_name == "claude-sonnet-5"

    def test_get_provider_reports_missing_credentials_clearly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_ENV_VAR, raising=False)
        with pytest.raises(AnthropicConfigError, match=_ENV_VAR):
            get_provider("anthropic", "claude-sonnet-5")

    def test_no_automatic_fallback_to_mock_on_anthropic_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_ENV_VAR, raising=False)
        with pytest.raises(AnthropicConfigError):
            get_provider("anthropic", "claude-sonnet-5")
        # A failure to construct "anthropic" must not silently hand back a
        # mock/fake provider instead - the exception above is the entire
        # observable behavior; nothing else is returned.


# ── Architecture boundary ───────────────────────────────────────────────────


class TestArchitectureBoundary:
    def test_anthropic_sdk_import_is_confined_to_anthropic_provider_module(self) -> None:
        """ADR-0002 requirement: individual skills and workflows must not call
        Anthropic directly - only cv_agent/llm/anthropic_provider.py may import
        the `anthropic` package. Mirrors ADR-0004's sqlite3-confinement test."""
        import cv_agent

        package_root = Path(cv_agent.__file__).parent
        offenders = []
        for py_file in package_root.rglob("*.py"):
            if py_file.name == "anthropic_provider.py":
                continue
            text = py_file.read_text(encoding="utf-8")
            if "import anthropic" in text:
                offenders.append(str(py_file.relative_to(package_root)))
        assert offenders == [], f"anthropic imported outside anthropic_provider.py: {offenders}"
