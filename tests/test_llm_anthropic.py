"""Tests for cv_agent.llm.anthropic_provider (ADR-0002, ADR-0020 §3.8 adapter v2).

No test in this file makes a real network call or requires a real API key —
every completion path is exercised against an injected fake client. Tests that
build the real ``anthropic.Anthropic`` use a dummy key and never call it. The
stop-reason policy lives in tests/test_llm_stop_reason.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anthropic
import httpx
import pytest

from cv_agent.llm import anthropic_provider
from cv_agent.llm.anthropic_provider import (
    ADAPTER_VERSION,
    AnthropicConfigError,
    AnthropicProvider,
    AnthropicRequestError,
)
from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.errors import LLMConfigError, LLMCredentialError
from cv_agent.llm.registry import get_provider, list_providers
from tests.llm_fakes import (
    FakeAnthropicClient,
    FakeMessage,
    FakeTextBlock,
    FakeThinkingBlock,
    FakeUsage,
    text_message,
)

_ENV_VAR = "CV_AGENT_ANTHROPIC_API_KEY"
_MODEL = "claude-opus-5-5"


def _http_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(status_code=status_code, request=request)


def _sent(provider_kwargs: dict[str, Any] | None = None, **req: Any) -> dict[str, Any]:
    """Run one complete() against a fake client and return the kwargs the SDK received."""
    client = FakeAnthropicClient(response=text_message("ok"))
    p = AnthropicProvider(_MODEL, client=client, **(provider_kwargs or {}))
    p.complete(LLMRequest(prompt="q", max_tokens=256, **req))
    return client.messages.calls[0]


# ── Construction / credential handling ─────────────────────────────────────


class TestAnthropicProviderConstruction:
    def test_is_llm_provider_subclass(self) -> None:
        assert issubclass(AnthropicProvider, LLMProvider)

    def test_names_and_versions(self) -> None:
        p = AnthropicProvider(_MODEL, client=FakeAnthropicClient())
        assert p.provider_name == "anthropic"
        assert p.model_name == _MODEL
        assert ADAPTER_VERSION == "anthropic/2"
        assert p.adapter_version == "anthropic/2"
        assert p.sdk_version == anthropic.__version__

    def test_error_classes_are_rebased_on_the_gateway_errors(self) -> None:
        assert issubclass(AnthropicConfigError, LLMConfigError)

    def test_missing_api_key_still_raises_credential_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_ENV_VAR, raising=False)
        with pytest.raises(LLMCredentialError, match=_ENV_VAR):
            AnthropicProvider(_MODEL)

    def test_explicit_api_key_overrides_missing_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_ENV_VAR, raising=False)
        p = AnthropicProvider(_MODEL, api_key="sk-ant-test-not-real")
        assert p.model_name == _MODEL

    def test_env_var_supplies_key_when_no_override_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_ENV_VAR, "sk-ant-test-not-real")
        assert AnthropicProvider(_MODEL).model_name == _MODEL

    def test_injected_client_bypasses_credential_check_entirely(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_ENV_VAR, raising=False)
        assert AnthropicProvider(_MODEL, client=FakeAnthropicClient()).model_name == _MODEL

    def test_sdk_client_is_built_with_zero_retries_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        def fake_ctor(**kwargs: Any) -> object:
            seen.update(kwargs)
            return object()

        monkeypatch.setattr(anthropic_provider.anthropic, "Anthropic", fake_ctor)
        AnthropicProvider(_MODEL, api_key="sk-ant-test-not-real")
        assert seen["max_retries"] == 0
        assert seen["timeout"] == 60.0

    @pytest.mark.parametrize(
        "kwargs", [{"thinking": "enabled"}, {"thinking": "bogus"}, {"effort": "extreme"}]
    )
    def test_invalid_thinking_or_effort_is_a_config_error(self, kwargs: dict[str, str]) -> None:
        with pytest.raises(AnthropicConfigError):
            AnthropicProvider(_MODEL, client=FakeAnthropicClient(), **kwargs)  # type: ignore[arg-type]


# ── Request shape ──────────────────────────────────────────────────────────


class TestRequestShape:
    def test_prompt_system_model_and_max_tokens_are_passed(self) -> None:
        call = _sent(system="You are a CV assistant.")
        assert call["messages"] == [{"role": "user", "content": "q"}]
        assert call["system"] == "You are a CV assistant."
        assert call["model"] == _MODEL
        assert call["max_tokens"] == 256

    def test_system_omitted_when_not_given(self) -> None:
        assert "system" not in _sent()

    @pytest.mark.parametrize("opts", [None, {"thinking": "adaptive", "effort": "high"}])
    def test_forbidden_parameters_are_never_sent(self, opts: dict[str, str] | None) -> None:
        call = _sent(opts)
        for name in ("temperature", "top_p", "top_k", "tools", "tool_choice", "budget_tokens"):
            assert name not in call

    def test_thinking_and_effort_are_omitted_unless_set(self) -> None:
        call = _sent()
        assert "thinking" not in call
        assert "output_config" not in call

    def test_thinking_and_effort_are_sent_when_set(self) -> None:
        call = _sent({"thinking": "disabled", "effort": "low"})
        assert call["thinking"] == {"type": "disabled"}
        assert call["output_config"] == {"effort": "low"}

    def test_max_tokens_none_is_a_config_error_and_sends_nothing(self) -> None:
        client = FakeAnthropicClient(response=text_message("ok"))
        p = AnthropicProvider(_MODEL, client=client)
        with pytest.raises(LLMConfigError):
            p.complete(LLMRequest(prompt="q"))
        assert client.messages.calls == []


# ── Response mapping ───────────────────────────────────────────────────────


class TestResponseMapping:
    def test_complete_returns_mapped_response(self) -> None:
        msg = text_message(
            "Hello from Claude.", usage=FakeUsage(12, 4), request_id="req_1", stop_reason="end_turn"
        )
        p = AnthropicProvider(_MODEL, client=FakeAnthropicClient(response=msg))

        resp = p.complete(LLMRequest(prompt="hi", max_tokens=64))

        assert isinstance(resp, LLMResponse)
        assert resp.content == "Hello from Claude."
        assert resp.model == _MODEL
        assert resp.provider == "anthropic"
        assert resp.stop_reason == "end_turn"
        assert resp.request_id == "req_1"
        assert resp.call_id is None

    def test_thinking_blocks_never_appear_in_content(self) -> None:
        msg = FakeMessage(
            [FakeThinkingBlock("SECRET-REASONING"), FakeTextBlock("kept"), FakeTextBlock(" too")]
        )
        p = AnthropicProvider(_MODEL, client=FakeAnthropicClient(response=msg))
        resp = p.complete(LLMRequest(prompt="q", max_tokens=64))
        assert resp.content == "kept too"
        assert "SECRET-REASONING" not in repr(resp)

    def test_usage_reports_every_counter(self) -> None:
        usage = FakeUsage(
            12, 40, cache_creation_input_tokens=3, cache_read_input_tokens=5, thinking_tokens=30
        )
        p = AnthropicProvider(
            _MODEL, client=FakeAnthropicClient(response=text_message("ok", usage=usage))
        )
        resp = p.complete(LLMRequest(prompt="q", max_tokens=64))
        assert resp.usage == {
            "prompt_tokens": 12,
            "completion_tokens": 40,
            "cache_creation_input_tokens": 3,
            "cache_read_input_tokens": 5,
            "thinking_tokens": 30,
            "total_tokens": 52,
        }

    def test_usage_counters_absent_from_the_sdk_are_zero(self) -> None:
        p = AnthropicProvider(
            _MODEL, client=FakeAnthropicClient(response=text_message("ok", usage=FakeUsage(12, 4)))
        )
        usage = p.complete(LLMRequest(prompt="q", max_tokens=64)).usage
        assert usage["cache_creation_input_tokens"] == 0
        assert usage["cache_read_input_tokens"] == 0
        assert usage["thinking_tokens"] == 0
        assert usage["total_tokens"] == 16

    def test_request_id_is_none_when_the_sdk_gives_none(self) -> None:
        p = AnthropicProvider(_MODEL, client=FakeAnthropicClient(response=text_message("ok")))
        assert p.complete(LLMRequest(prompt="q", max_tokens=64)).request_id is None


# ── complete() — error mapping ───────────────────────────────────────────────


class TestAnthropicProviderErrorHandling:
    def _raises(self, exc: BaseException, match: str) -> None:
        p = AnthropicProvider(_MODEL, client=FakeAnthropicClient(exc=exc))
        with pytest.raises(AnthropicRequestError, match=match):
            p.complete(LLMRequest(prompt="q", max_tokens=64))

    def test_authentication_error_is_wrapped(self) -> None:
        self._raises(
            anthropic.AuthenticationError("bad key", response=_http_response(401), body=None),
            "authentication failed",
        )

    def test_rate_limit_error_is_wrapped(self) -> None:
        self._raises(
            anthropic.RateLimitError("slow down", response=_http_response(429), body=None),
            "rate limit",
        )

    def test_connection_error_is_wrapped(self) -> None:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        self._raises(
            anthropic.APIConnectionError(message="connection failed", request=request),
            "connection failed",
        )

    def test_generic_status_error_is_wrapped(self) -> None:
        self._raises(
            anthropic.InternalServerError("boom", response=_http_response(500), body=None),
            "status 500",
        )

    def test_generic_api_error_is_wrapped(self) -> None:
        self._raises(
            anthropic.APIResponseValidationError(
                response=_http_response(200), body=None, message="schema mismatch"
            ),
            "Anthropic API error",
        )

    def test_error_message_never_contains_env_var_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_ENV_VAR, "sk-ant-super-secret-value")
        exc = anthropic.AuthenticationError("bad key", response=_http_response(401), body=None)
        p = AnthropicProvider(_MODEL, client=FakeAnthropicClient(exc=exc))
        with pytest.raises(AnthropicRequestError) as exc_info:
            p.complete(LLMRequest(prompt="q", max_tokens=64))
        assert "sk-ant-super-secret-value" not in str(exc_info.value)


# ── Registry integration ────────────────────────────────────────────────────


class TestAnthropicRegistryIntegration:
    def test_anthropic_listed_as_a_known_provider(self) -> None:
        assert "anthropic" in list_providers()

    def test_mock_provider_unaffected(self) -> None:
        assert get_provider("mock", "fake-1").provider_name == "mock"

    def test_get_provider_constructs_a_real_anthropic_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Builds an anthropic.Anthropic() object only; no network request.
        monkeypatch.setenv(_ENV_VAR, "sk-ant-test-not-real")
        p = get_provider("anthropic", _MODEL)
        assert isinstance(p, AnthropicProvider)
        assert p.model_name == _MODEL

    def test_get_provider_reports_missing_credentials_clearly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(_ENV_VAR, raising=False)
        with pytest.raises(LLMCredentialError, match=_ENV_VAR):
            get_provider("anthropic", _MODEL)


# ── Architecture boundary ───────────────────────────────────────────────────


class TestArchitectureBoundary:
    def test_anthropic_sdk_import_is_confined_to_anthropic_provider_module(self) -> None:
        """ADR-0002: only cv_agent/llm/anthropic_provider.py may import `anthropic`."""
        import cv_agent

        package_root = Path(cv_agent.__file__).parent
        offenders = [
            str(f.relative_to(package_root))
            for f in package_root.rglob("*.py")
            if f.name != "anthropic_provider.py" and "import anthropic" in f.read_text(encoding="utf-8")
        ]
        assert offenders == [], f"anthropic imported outside anthropic_provider.py: {offenders}"
