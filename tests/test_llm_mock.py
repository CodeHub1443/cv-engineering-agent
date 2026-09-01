"""Tests for cv_agent.llm (base, mock, registry)."""

from __future__ import annotations

import pytest

from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.mock import FakeLLMProvider
from cv_agent.llm.registry import get_provider, list_providers, register_provider


class TestLLMRequest:
    def test_defaults(self) -> None:
        req = LLMRequest(prompt="hello")
        assert req.prompt == "hello"
        assert req.system is None
        assert req.max_tokens == 1024
        assert req.temperature == 0.0
        assert req.metadata == {}

    def test_custom_values(self) -> None:
        req = LLMRequest(prompt="q", system="sys", max_tokens=512, temperature=0.7)
        assert req.system == "sys"
        assert req.max_tokens == 512
        assert req.temperature == 0.7


class TestFakeLLMProvider:
    def test_provider_name(self) -> None:
        p = FakeLLMProvider()
        assert p.provider_name == "mock"

    def test_default_model_name(self) -> None:
        p = FakeLLMProvider()
        assert p.model_name == "fake-1"

    def test_custom_model_name(self) -> None:
        p = FakeLLMProvider(model="fake-xl")
        assert p.model_name == "fake-xl"

    def test_complete_returns_response(self) -> None:
        p = FakeLLMProvider()
        resp = p.complete(LLMRequest(prompt="Analyse this image."))
        assert isinstance(resp, LLMResponse)

    def test_response_provider_and_model(self) -> None:
        p = FakeLLMProvider(model="fake-2")
        resp = p.complete(LLMRequest(prompt="test"))
        assert resp.provider == "mock"
        assert resp.model == "fake-2"

    def test_response_content_is_non_empty(self) -> None:
        p = FakeLLMProvider()
        resp = p.complete(LLMRequest(prompt="test"))
        assert resp.content

    def test_fixed_response(self) -> None:
        p = FakeLLMProvider(fixed_response="FIXED")
        resp = p.complete(LLMRequest(prompt="anything"))
        assert resp.content == "FIXED"

    def test_call_count_increments(self) -> None:
        p = FakeLLMProvider()
        assert p.call_count == 0
        p.complete(LLMRequest(prompt="a"))
        p.complete(LLMRequest(prompt="b"))
        assert p.call_count == 2

    def test_reset_call_count(self) -> None:
        p = FakeLLMProvider()
        p.complete(LLMRequest(prompt="a"))
        p.reset()
        assert p.call_count == 0

    def test_usage_keys_present(self) -> None:
        p = FakeLLMProvider()
        resp = p.complete(LLMRequest(prompt="detect objects in frame"))
        assert "prompt_tokens" in resp.usage
        assert "completion_tokens" in resp.usage
        assert "total_tokens" in resp.usage
        assert resp.usage["total_tokens"] == (
            resp.usage["prompt_tokens"] + resp.usage["completion_tokens"]
        )

    def test_is_llm_provider_subclass(self) -> None:
        assert issubclass(FakeLLMProvider, LLMProvider)

    def test_repr(self) -> None:
        p = FakeLLMProvider(model="fake-1")
        r = repr(p)
        assert "mock" in r
        assert "fake-1" in r


class TestProviderRegistry:
    def test_mock_is_registered(self) -> None:
        providers = list_providers()
        assert "mock" in providers

    def test_get_mock_provider(self) -> None:
        p = get_provider("mock", "fake-1")
        assert isinstance(p, FakeLLMProvider)
        assert p.model_name == "fake-1"

    def test_unknown_provider_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_provider("nonexistent_provider_xyz", "some-model")

    def test_register_custom_provider(self) -> None:
        class _DummyProvider(FakeLLMProvider):
            PROVIDER_NAME = "dummy-test"

            @property
            def provider_name(self) -> str:
                return self.PROVIDER_NAME

        register_provider("dummy-test", _DummyProvider)
        p = get_provider("dummy-test", "dummy-model")
        assert isinstance(p, _DummyProvider)
        assert "dummy-test" in list_providers()

    def test_register_non_provider_raises(self) -> None:
        with pytest.raises(TypeError):
            register_provider("bad", object)  # type: ignore[arg-type]
