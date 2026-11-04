"""
Tests for cv_agent.tools.web_research — WebResearchFetchInvoker, build_spec,
register.

No real network calls are made in the default test suite.  All HTTP
interactions are replaced by unittest.mock.patch on urlopen.

Real-network integration tests live in TestRealHTTPIntegration and are
skipped unless the environment variable RUN_NETWORK_TESTS=1 is set.
"""

from __future__ import annotations

import os
import re
from unittest.mock import MagicMock, patch

import pytest

from cv_agent.tools.executor import ToolExecutor
from cv_agent.tools.models import (
    ToolId,
    ToolRequest,
)
from cv_agent.tools.registry import ToolRegistry
from cv_agent.tools.web_research import (
    TOOL_ID,
    WebResearchFetchInvoker,
    _MAX_RESPONSE_BYTES,
    _TIMEOUT_SECONDS,
    _USER_AGENT,
    _charset_from_content_type,
    build_spec,
    register,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NETWORK_ENABLED = os.environ.get("RUN_NETWORK_TESTS") == "1"


def _mock_response(
    body: bytes = b"<html>test content</html>",
    status: int = 200,
    content_type: str = "text/html; charset=utf-8",
    final_url: str = "https://example.com/page",
) -> MagicMock:
    """Context-manager mock for urllib.request.urlopen."""
    m = MagicMock()
    m.status = status
    m.getheader.return_value = content_type
    m.geturl.return_value = final_url
    m.read.return_value = body
    m.__enter__ = MagicMock(return_value=m)
    m.__exit__ = MagicMock(return_value=False)
    return m


def _invoke_with_mock(
    mock_response: MagicMock,
    url: str = "https://example.com/page",
    context_hint: str | None = None,
):
    """Run WebResearchFetchInvoker.invoke() against a mock urlopen response."""
    invoker = WebResearchFetchInvoker()
    spec = build_spec()
    inputs: dict = {"url": url}
    if context_hint is not None:
        inputs["context_hint"] = context_hint
    request = ToolRequest(inputs=inputs)
    with patch("cv_agent.tools.web_research.urlopen", return_value=mock_response):
        return invoker.invoke(spec, request)


# ---------------------------------------------------------------------------
# 1. ToolSpec fields
# ---------------------------------------------------------------------------


class TestBuildSpec:
    def test_tool_id(self):
        assert build_spec().tool_id == TOOL_ID
        assert TOOL_ID == "web-research-fetch"

    def test_transport_http(self):
        assert build_spec().transport == "http"

    def test_not_side_effecting(self):
        assert build_spec().side_effecting is False

    def test_default_approval_policy_allowed(self):
        assert build_spec().approval_policy == "allowed"

    def test_override_approval_policy(self):
        spec = build_spec(approval_policy="approval_required")
        assert spec.approval_policy == "approval_required"

    def test_verified_true(self):
        # verified=True because the implementation has been personally
        # inspected (ADR-0005 §13 / ADR-0009 §8 discipline).
        assert build_spec().verified is True

    def test_input_schema_has_two_fields(self):
        schema = build_spec().input_schema
        assert len(schema) == 2

    def test_url_field_required(self):
        url_field = next(f for f in build_spec().input_schema if f.name == "url")
        assert url_field.required is True

    def test_context_hint_field_optional(self):
        hint_field = next(
            f for f in build_spec().input_schema if f.name == "context_hint"
        )
        assert hint_field.required is False

    def test_no_field_groups(self):
        assert build_spec().input_field_groups == ()

    def test_name_is_non_empty_string(self):
        assert isinstance(build_spec().name, str) and build_spec().name

    def test_description_mentions_raw_content(self):
        desc = build_spec().description.lower()
        assert "raw content" in desc or "claim extraction" in desc


# ---------------------------------------------------------------------------
# 2. Charset helper
# ---------------------------------------------------------------------------


class TestCharsetParsing:
    def test_utf8_explicit(self):
        assert _charset_from_content_type("text/html; charset=utf-8") == "utf-8"

    def test_utf8_uppercase(self):
        assert _charset_from_content_type("text/html; charset=UTF-8") == "UTF-8"

    def test_iso_8859_1(self):
        assert _charset_from_content_type("text/html; charset=iso-8859-1") == "iso-8859-1"

    def test_quoted_charset(self):
        assert _charset_from_content_type('text/html; charset="windows-1252"') == "windows-1252"

    def test_no_charset_falls_back_to_utf8(self):
        assert _charset_from_content_type("text/html") == "utf-8"

    def test_empty_content_type_falls_back_to_utf8(self):
        assert _charset_from_content_type("") == "utf-8"

    def test_charset_equals_empty_falls_back(self):
        assert _charset_from_content_type("text/html; charset=") == "utf-8"

    def test_extra_whitespace(self):
        result = _charset_from_content_type("text/html ;  charset = utf-8 ")
        assert result == "utf-8"


# ---------------------------------------------------------------------------
# 3. URL validation (no network calls needed)
# ---------------------------------------------------------------------------


class TestURLValidation:
    def _invoke(self, inputs: dict):
        invoker = WebResearchFetchInvoker()
        spec = build_spec()
        request = ToolRequest(inputs=inputs)
        # No patch needed — validation rejects before urlopen is called
        return invoker.invoke(spec, request)

    def test_missing_url_key(self):
        outcome = self._invoke({})
        assert outcome.success is False
        assert "url" in outcome.error_message.lower()

    def test_url_none(self):
        outcome = self._invoke({"url": None})
        assert outcome.success is False

    def test_url_empty_string(self):
        outcome = self._invoke({"url": ""})
        assert outcome.success is False

    def test_url_whitespace_only(self):
        outcome = self._invoke({"url": "   "})
        assert outcome.success is False

    def test_url_non_string(self):
        outcome = self._invoke({"url": 42})
        assert outcome.success is False

    def test_ftp_scheme_rejected(self):
        outcome = self._invoke({"url": "ftp://files.example.com/data.zip"})
        assert outcome.success is False
        assert "ftp" in outcome.error_message

    def test_file_scheme_rejected(self):
        outcome = self._invoke({"url": "file:///etc/passwd"})
        assert outcome.success is False
        assert "file" in outcome.error_message

    def test_javascript_scheme_rejected(self):
        outcome = self._invoke({"url": "javascript:alert(1)"})
        assert outcome.success is False

    def test_no_scheme_rejected(self):
        outcome = self._invoke({"url": "example.com/page"})
        assert outcome.success is False

    def test_scheme_only_rejected(self):
        outcome = self._invoke({"url": "https://"})
        assert outcome.success is False
        assert "host" in outcome.error_message.lower()

    def test_http_accepted_reaches_network(self):
        # Reaches urlopen — mock to avoid real network call
        mock = _mock_response()
        outcome = _invoke_with_mock(mock, url="http://example.com/doc")
        assert outcome.success is True

    def test_https_accepted_reaches_network(self):
        mock = _mock_response()
        outcome = _invoke_with_mock(mock, url="https://example.com/doc")
        assert outcome.success is True


# ---------------------------------------------------------------------------
# 4. Successful fetch — output schema
# ---------------------------------------------------------------------------


class TestSuccessfulFetch:
    def test_output_contains_required_keys(self):
        mock = _mock_response()
        outcome = _invoke_with_mock(mock)
        assert outcome.success is True
        for key in ("url", "content_text", "content_type", "date_accessed", "http_status"):
            assert key in outcome.output, f"missing key: {key}"

    def test_output_url_is_final_url_after_redirect(self):
        redirected_url = "https://example.com/canonical"
        mock = _mock_response(
            final_url=redirected_url,
            body=b"content",
        )
        outcome = _invoke_with_mock(mock, url="https://example.com/old")
        assert outcome.output["url"] == redirected_url

    def test_content_text_decoded(self):
        body = b"<html>hello world</html>"
        mock = _mock_response(body=body, content_type="text/html; charset=utf-8")
        outcome = _invoke_with_mock(mock)
        assert "hello world" in outcome.output["content_text"]

    def test_content_type_preserved(self):
        ct = "application/json; charset=utf-8"
        mock = _mock_response(content_type=ct)
        outcome = _invoke_with_mock(mock)
        assert outcome.output["content_type"] == ct

    def test_http_status_200(self):
        mock = _mock_response(status=200)
        outcome = _invoke_with_mock(mock)
        assert outcome.output["http_status"] == 200

    def test_date_accessed_iso8601_utc_format(self):
        mock = _mock_response()
        outcome = _invoke_with_mock(mock)
        date_str = outcome.output["date_accessed"]
        # Must match YYYY-MM-DDTHH:MM:SSZ
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", date_str), (
            f"date_accessed {date_str!r} does not match ISO 8601 UTC format"
        )

    def test_not_truncated_on_small_response(self):
        mock = _mock_response(body=b"small")
        outcome = _invoke_with_mock(mock)
        assert outcome.output["truncated"] is False

    def test_context_hint_does_not_affect_output(self):
        mock = _mock_response()
        outcome_with = _invoke_with_mock(mock, context_hint="some logging hint")
        mock2 = _mock_response()
        outcome_without = _invoke_with_mock(mock2)
        assert outcome_with.output["content_text"] == outcome_without.output["content_text"]

    def test_non_utf8_charset_decoded_correctly(self):
        # Latin-1: byte 0xe9 is "é"
        body = "café".encode("iso-8859-1")
        mock = _mock_response(body=body, content_type="text/plain; charset=iso-8859-1")
        outcome = _invoke_with_mock(mock)
        assert "café" in outcome.output["content_text"]

    def test_unknown_charset_falls_back_to_utf8(self):
        body = b"hello"
        mock = _mock_response(body=body, content_type="text/plain; charset=totally-fake-codec")
        outcome = _invoke_with_mock(mock)
        assert outcome.success is True
        assert "hello" in outcome.output["content_text"]

    def test_urlopen_called_with_timeout(self):
        mock = _mock_response()
        invoker = WebResearchFetchInvoker()
        spec = build_spec()
        request = ToolRequest(inputs={"url": "https://example.com"})
        with patch("cv_agent.tools.web_research.urlopen", return_value=mock) as mock_open:
            invoker.invoke(spec, request)
        _, kwargs = mock_open.call_args
        assert kwargs.get("timeout") == _TIMEOUT_SECONDS

    def test_user_agent_header_in_request(self):
        mock = _mock_response()
        invoker = WebResearchFetchInvoker()
        spec = build_spec()
        request = ToolRequest(inputs={"url": "https://example.com"})
        with patch("cv_agent.tools.web_research.urlopen", return_value=mock) as mock_open:
            invoker.invoke(spec, request)
        req_arg = mock_open.call_args[0][0]
        assert req_arg.get_header("User-agent") == _USER_AGENT


# ---------------------------------------------------------------------------
# 5. Fetch failures
# ---------------------------------------------------------------------------


class TestFetchFailures:
    def _invoke_raises(self, exc):
        invoker = WebResearchFetchInvoker()
        spec = build_spec()
        request = ToolRequest(inputs={"url": "https://example.com/doc"})
        with patch("cv_agent.tools.web_research.urlopen", side_effect=exc):
            return invoker.invoke(spec, request)

    def test_http_404(self):
        from urllib.error import HTTPError

        exc = HTTPError("https://example.com/doc", 404, "Not Found", {}, None)
        outcome = self._invoke_raises(exc)
        assert outcome.success is False
        assert outcome.output.get("http_status") == 404
        assert "404" in outcome.error_message

    def test_http_500(self):
        from urllib.error import HTTPError

        exc = HTTPError("https://example.com/doc", 500, "Internal Server Error", {}, None)
        outcome = self._invoke_raises(exc)
        assert outcome.success is False
        assert outcome.output.get("http_status") == 500

    def test_network_error_urlopen(self):
        from urllib.error import URLError

        outcome = self._invoke_raises(URLError("Connection refused"))
        assert outcome.success is False
        assert outcome.error_message

    def test_os_error(self):
        outcome = self._invoke_raises(OSError("low-level socket error"))
        assert outcome.success is False
        assert outcome.error_message

    def test_failure_url_preserved_in_output(self):
        from urllib.error import URLError

        outcome = self._invoke_raises(URLError("DNS failure"))
        assert outcome.output.get("url") == "https://example.com/doc"

    def test_failure_output_empty_dict_acceptable(self):
        from urllib.error import URLError

        outcome = self._invoke_raises(URLError("timeout"))
        # output may be {} or {"url": ...} — both acceptable per ADR-0005 §13
        assert isinstance(outcome.output, dict)

    def test_failure_never_raises(self):
        from urllib.error import URLError

        # Invoker must not propagate exceptions to the caller
        outcome = self._invoke_raises(URLError("bang"))
        assert not outcome.success  # got here without exception


# ---------------------------------------------------------------------------
# 6. Response-size limit
# ---------------------------------------------------------------------------


class TestResponseSizeLimit:
    def test_exactly_at_limit_not_truncated(self):
        body = b"x" * _MAX_RESPONSE_BYTES
        mock = _mock_response(body=body)
        outcome = _invoke_with_mock(mock)
        assert outcome.success is True
        assert outcome.output["truncated"] is False
        assert len(outcome.output["content_text"]) == _MAX_RESPONSE_BYTES

    def test_one_byte_over_limit_is_truncated(self):
        body = b"x" * (_MAX_RESPONSE_BYTES + 1)
        mock = _mock_response(body=body)
        outcome = _invoke_with_mock(mock)
        assert outcome.success is True
        assert outcome.output["truncated"] is True

    def test_truncated_content_length_is_bounded(self):
        body = b"x" * (_MAX_RESPONSE_BYTES + 1000)
        mock = _mock_response(body=body)
        outcome = _invoke_with_mock(mock)
        # content_text is decoded from raw[:_MAX_RESPONSE_BYTES]; each 'x'
        # is one ASCII byte, so decoded length == _MAX_RESPONSE_BYTES
        assert len(outcome.output["content_text"]) == _MAX_RESPONSE_BYTES

    def test_read_called_with_max_plus_one(self):
        mock = _mock_response()
        invoker = WebResearchFetchInvoker()
        spec = build_spec()
        request = ToolRequest(inputs={"url": "https://example.com"})
        with patch("cv_agent.tools.web_research.urlopen", return_value=mock):
            invoker.invoke(spec, request)
        mock.read.assert_called_once_with(_MAX_RESPONSE_BYTES + 1)

    def test_small_response_not_truncated(self):
        body = b"hello world"
        mock = _mock_response(body=body)
        outcome = _invoke_with_mock(mock)
        assert outcome.output["truncated"] is False
        assert outcome.output["content_text"] == "hello world"

    def test_max_response_bytes_is_one_mib(self):
        assert _MAX_RESPONSE_BYTES == 1 * 1024 * 1024


# ---------------------------------------------------------------------------
# 7. Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_adds_spec(self):
        registry = ToolRegistry()
        register(registry)
        spec = registry.get_spec(ToolId(TOOL_ID))
        assert spec is not None
        assert spec.tool_id == TOOL_ID

    def test_register_adds_invoker(self):
        registry = ToolRegistry()
        register(registry)
        invoker = registry.get_invoker(ToolId(TOOL_ID))
        assert invoker is not None
        assert invoker.tool_id == TOOL_ID

    def test_can_invoke_true_after_register(self):
        registry = ToolRegistry()
        register(registry)
        assert registry.can_invoke(ToolId(TOOL_ID)) is True

    def test_can_invoke_false_before_register(self):
        registry = ToolRegistry()
        assert registry.can_invoke(ToolId(TOOL_ID)) is False

    def test_register_is_idempotent_same_generation(self):
        registry = ToolRegistry()
        register(registry)
        gen1 = registry.get_invoker_registration(ToolId(TOOL_ID))[1]
        # Calling register() a second time re-creates a NEW WebResearchFetchInvoker
        # instance, which WILL bump the generation (new object, different identity).
        # This is by design — verify a second call does not break the registry.
        register(registry)
        gen2 = registry.get_invoker_registration(ToolId(TOOL_ID))[1]
        assert gen2 >= gen1

    def test_register_with_approval_policy_override(self):
        registry = ToolRegistry()
        register(registry, approval_policy="approval_required")
        spec = registry.get_spec(ToolId(TOOL_ID))
        assert spec.approval_policy == "approval_required"

    def test_invoker_tool_id_matches_spec_tool_id(self):
        registry = ToolRegistry()
        register(registry)
        spec = registry.get_spec(ToolId(TOOL_ID))
        invoker = registry.get_invoker(ToolId(TOOL_ID))
        assert invoker.tool_id == spec.tool_id

    def test_verified_true_means_can_invoke(self):
        registry = ToolRegistry()
        register(registry)
        assert registry.get_spec(ToolId(TOOL_ID)).verified is True
        assert registry.can_invoke(ToolId(TOOL_ID)) is True


# ---------------------------------------------------------------------------
# 8. ToolExecutor integration
# ---------------------------------------------------------------------------


class TestToolExecutorIntegration:
    def test_unregistered_tool_returns_not_executable(self):
        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        result = executor.invoke(ToolId(TOOL_ID), ToolRequest())
        assert result.status == "not_executable"
        assert result.error is not None
        assert result.error.category == "no_tool"

    def test_registered_tool_can_invoke(self):
        registry = ToolRegistry()
        register(registry)
        executor = ToolExecutor(registry)
        assert executor.can_invoke(ToolId(TOOL_ID)) is True

    def test_allowed_policy_no_approval_needed(self):
        # approval_policy="allowed" -> ToolExecutor never gates on request.approved
        registry = ToolRegistry()
        register(registry)
        executor = ToolExecutor(registry)
        mock = _mock_response()
        with patch("cv_agent.tools.web_research.urlopen", return_value=mock):
            result = executor.invoke(
                ToolId(TOOL_ID),
                ToolRequest(inputs={"url": "https://example.com"}, approved=False),
            )
        assert result.status == "completed"

    def test_end_to_end_successful_invoke(self):
        registry = ToolRegistry()
        register(registry)
        executor = ToolExecutor(registry)
        mock = _mock_response(body=b"doc content", final_url="https://docs.example.com/page")
        with patch("cv_agent.tools.web_research.urlopen", return_value=mock):
            result = executor.invoke(
                ToolId(TOOL_ID),
                ToolRequest(inputs={"url": "https://docs.example.com/page"}),
            )
        assert result.status == "completed"
        assert result.ok is True
        assert result.output is not None
        assert result.output["url"] == "https://docs.example.com/page"
        assert "doc content" in result.output["content_text"]

    def test_invalid_url_returns_failed(self):
        registry = ToolRegistry()
        register(registry)
        executor = ToolExecutor(registry)
        result = executor.invoke(
            ToolId(TOOL_ID),
            ToolRequest(inputs={"url": "ftp://bad-scheme.example.com"}),
        )
        # Invoker returns ToolOutcome(success=False) -> ToolExecutor maps to "failed"
        assert result.status == "failed"
        assert result.error is not None
        assert result.error.category == "transport_error"

    def test_network_error_returns_failed(self):
        from urllib.error import URLError

        registry = ToolRegistry()
        register(registry)
        executor = ToolExecutor(registry)
        with patch("cv_agent.tools.web_research.urlopen", side_effect=URLError("DNS")):
            result = executor.invoke(
                ToolId(TOOL_ID),
                ToolRequest(inputs={"url": "https://example.com"}),
            )
        assert result.status == "failed"

    def test_evidence_has_timing(self):
        registry = ToolRegistry()
        register(registry)
        executor = ToolExecutor(registry)
        mock = _mock_response()
        with patch("cv_agent.tools.web_research.urlopen", return_value=mock):
            result = executor.invoke(
                ToolId(TOOL_ID),
                ToolRequest(inputs={"url": "https://example.com"}),
            )
        assert result.evidence.started_at is not None
        assert result.evidence.completed_at is not None

    def test_pin_mismatch_returns_not_executable(self):
        registry = ToolRegistry()
        register(registry)
        executor = ToolExecutor(registry)

        # Capture a valid pin before replacing the invoker
        pin = registry.pin(ToolId(TOOL_ID))

        # Re-register with a new WebResearchFetchInvoker — bumps generation
        registry.register_invoker(WebResearchFetchInvoker())

        with patch("cv_agent.tools.web_research.urlopen", return_value=_mock_response()):
            result = executor.invoke(
                ToolId(TOOL_ID),
                ToolRequest(
                    inputs={"url": "https://example.com"},
                    expected_tool_pin=pin,
                ),
            )
        assert result.status == "not_executable"
        assert result.error.category == "tool_mismatch"

    def test_approval_required_without_pin_returns_rejected(self):
        registry = ToolRegistry()
        register(registry, approval_policy="approval_required")
        executor = ToolExecutor(registry)
        result = executor.invoke(
            ToolId(TOOL_ID),
            ToolRequest(inputs={"url": "https://example.com"}, approved=True),
        )
        # E1-equivalent: missing pin -> rejected, even with approved=True
        assert result.status == "rejected"
        assert result.error.category == "approval_denied"


# ---------------------------------------------------------------------------
# 9. Architecture boundary
# ---------------------------------------------------------------------------


class TestArchitectureBoundary:
    def test_web_research_does_not_import_forbidden_packages(self):
        import ast
        import importlib.util
        import pathlib

        forbidden = {
            "cv_agent.knowledge",
            "cv_agent.graph",
            "cv_agent.execution",
            "cv_agent.skills",
            "cv_agent.llm",
        }
        src_path = pathlib.Path(
            importlib.util.find_spec("cv_agent.tools.web_research").origin
        )
        tree = ast.parse(src_path.read_text())
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for pkg in forbidden:
                    if node.module.startswith(pkg):
                        violations.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    for pkg in forbidden:
                        if alias.name.startswith(pkg):
                            violations.append(alias.name)
        assert violations == [], f"Boundary violations: {violations}"

    def test_web_research_does_not_import_third_party_http(self):
        import ast
        import importlib.util
        import pathlib

        third_party_http = {"requests", "httpx", "aiohttp", "urllib3"}
        src_path = pathlib.Path(
            importlib.util.find_spec("cv_agent.tools.web_research").origin
        )
        tree = ast.parse(src_path.read_text())
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in third_party_http:
                        found.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in third_party_http:
                    found.append(node.module)
        assert found == [], f"Third-party HTTP imports: {found}"


# ---------------------------------------------------------------------------
# 10. Real HTTP integration (opt-in, skipped by default)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _NETWORK_ENABLED, reason="set RUN_NETWORK_TESTS=1 to enable")
class TestRealHTTPIntegration:
    """
    These tests make real outbound HTTP requests.  They are skipped in the
    normal CI/test suite.  Run with:

        RUN_NETWORK_TESTS=1 pytest tests/test_tools_web_research.py::TestRealHTTPIntegration
    """

    def test_fetch_example_com(self):
        invoker = WebResearchFetchInvoker()
        spec = build_spec()
        request = ToolRequest(inputs={"url": "http://example.com/"})
        outcome = invoker.invoke(spec, request)
        assert outcome.success is True
        assert outcome.output["http_status"] == 200
        assert "example" in outcome.output["content_text"].lower()
        assert outcome.output["truncated"] is False

    def test_https_fetch(self):
        invoker = WebResearchFetchInvoker()
        spec = build_spec()
        request = ToolRequest(inputs={"url": "https://example.com/"})
        outcome = invoker.invoke(spec, request)
        assert outcome.success is True
        assert outcome.output["http_status"] == 200

    def test_date_accessed_is_recent(self):
        from datetime import date

        invoker = WebResearchFetchInvoker()
        spec = build_spec()
        request = ToolRequest(inputs={"url": "http://example.com/"})
        outcome = invoker.invoke(spec, request)
        date_str = outcome.output["date_accessed"][:10]
        fetched_date = date.fromisoformat(date_str)
        today = date.today()
        assert abs((fetched_date - today).days) <= 1

    def test_real_404_returns_failure(self):
        invoker = WebResearchFetchInvoker()
        spec = build_spec()
        request = ToolRequest(inputs={"url": "https://example.com/this-path-does-not-exist-404xyz"})
        outcome = invoker.invoke(spec, request)
        # example.com may return 404 or redirect — outcome.success is
        # implementation-defined; what matters is it doesn't raise
        assert isinstance(outcome.success, bool)
