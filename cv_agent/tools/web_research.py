"""
cv_agent.tools.web_research — verified ToolInvoker for web-research-fetch.

ADR-0005 §13 personal inspection notes (required before verified=True,
applying the discipline ADR-0009 §8 established for ExecutionBindings):

The implementation uses only Python stdlib modules: ``datetime``,
``urllib.error``, ``urllib.parse``, and ``urllib.request``.  No third-party
library is imported, and no entry is added to ``pyproject.toml`` —
satisfying ADR-0005 §13's explicit "no new dependency" constraint.

Fetch behaviour, confirmed by reading every line of this module:

- Only http:// and https:// URLs are accepted.  A missing, non-string, or
  blank ``url`` input, an unsupported scheme, or a URL without a host
  component returns ``ToolOutcome(success=False)`` before any network call.

- Responses are read in one bounded call: at most ``_MAX_RESPONSE_BYTES``
  (1 MiB = 1 048 576 bytes).  ``response.read(_MAX_RESPONSE_BYTES + 1)``
  reads that many bytes from the wire; if more were available (``len(raw) >
  _MAX_RESPONSE_BYTES``), the body is truncated to exactly
  ``_MAX_RESPONSE_BYTES`` bytes and ``truncated=True`` is added to the
  output dict.  On a non-truncated response, ``truncated`` is ``False``.
  Nothing beyond ``_MAX_RESPONSE_BYTES`` is held in memory by this invoker.

- The Content-Type charset is extracted by ``_charset_from_content_type``;
  the fallback is UTF-8.  Decoding uses ``errors="replace"``, so no
  ``UnicodeDecodeError`` can escape.  An unrecognised codec name
  (``LookupError``) falls back to UTF-8 silently.

- The final URL after HTTP redirects is ``response.geturl()``, not the
  requested URL.

- ``date_accessed`` (ISO 8601 UTC ``YYYY-MM-DDTHH:MM:SSZ``) is captured
  immediately after the connection is established, before reading the body.

- HTTP error responses (4xx/5xx) are caught as ``urllib.error.HTTPError``
  and returned as ``ToolOutcome(success=False)`` with the HTTP status in
  the output dict.  ``HTTPError`` is a subclass of ``URLError`` and is
  checked first.

- Network failures (``URLError``), timeouts during body reads
  (``OSError``/``TimeoutError``), and other OS-level errors are caught and
  returned as ``ToolOutcome(success=False, error_message=…)`` — never raised
  to the caller.  This mirrors ``ToolExecutor``'s own "catch, never
  propagate" posture (executor.py step 9).

- ``context_hint``, if supplied in ``request.inputs``, is acknowledged by
  ``WebResearchFetchInvoker.invoke()`` and silently ignored — it is for
  the calling layer's logging only and is never included in the HTTP
  request or the output.

- The HTTP ``User-Agent`` header identifies this invoker generically.

Side effects: one outbound HTTP GET per invocation.  No filesystem writes.
No subprocess.  No LLM calls.  No imports from ``cv_agent.knowledge``,
``cv_agent.graph``, ``cv_agent.execution``, ``cv_agent.skills``, or
``cv_agent.llm``.

``verified=True`` is set in ``build_spec()`` because this module's author
has read every line above and confirmed all stated behaviours (ADR-0005 §13
/ ADR-0009 §8 discipline applied to ToolInvokers).
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from cv_agent.tools.models import (
    ApprovalPolicy,
    ToolId,
    ToolInputField,
    ToolOutcome,
    ToolRequest,
    ToolSpec,
)
from cv_agent.tools.registry import ToolRegistry

TOOL_ID = "web-research-fetch"
_MAX_RESPONSE_BYTES = 1 * 1024 * 1024  # 1 MiB — bounded read, ADR-0005 §13
_TIMEOUT_SECONDS = 30
_USER_AGENT = "cv-agent/0.1 (web-research-fetch; read-only research; ADR-0005)"


def _charset_from_content_type(content_type: str) -> str:
    """Extract charset from a Content-Type header value; default UTF-8."""
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            charset = part[8:].strip().strip("\"'")
            return charset if charset else "utf-8"
    return "utf-8"


class WebResearchFetchInvoker:
    """
    Fetches a single HTTP/HTTPS URL and returns its decoded body text.

    Read-only — the only side effect is one outbound HTTP GET per call.
    Maps to ``ToolSpec(tool_id="web-research-fetch")`` (ADR-0005 §13).

    Responsibility boundary: this invoker returns raw HTTP content only.
    Claim extraction, ``Provenance`` construction, ``SourceClass`` assignment,
    and ``KnowledgeStore.put()`` belong to the calling research graph node
    (separate issue, ADR-0003 domain) — never to this class.
    """

    tool_id: str = TOOL_ID

    def invoke(self, spec: ToolSpec, request: ToolRequest) -> ToolOutcome:  # noqa: ARG002
        # context_hint, if supplied, is for the caller's logging only;
        # it is never sent in the HTTP request.
        url = request.inputs.get("url")

        # --- URL validation (before any network call) ---
        if not isinstance(url, str) or not url.strip():
            return ToolOutcome(
                success=False,
                output={},
                error_message=(
                    "Missing or empty 'url' input — "
                    "a non-blank string is required."
                ),
            )

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ToolOutcome(
                success=False,
                output={"url": url},
                error_message=(
                    f"Unsupported URL scheme {parsed.scheme!r}; "
                    "only http and https are accepted."
                ),
            )
        if not parsed.netloc:
            return ToolOutcome(
                success=False,
                output={"url": url},
                error_message="URL has no host component.",
            )

        # --- HTTP fetch ---
        req = Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urlopen(req, timeout=_TIMEOUT_SECONDS) as response:
                http_status: int = response.status
                content_type: str = response.getheader("Content-Type", "")
                final_url: str = response.geturl()
                date_accessed = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                raw: bytes = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            return ToolOutcome(
                success=False,
                output={"url": url, "http_status": exc.code},
                error_message=f"HTTP {exc.code} fetching {url!r}: {exc.reason}",
            )
        except URLError as exc:
            return ToolOutcome(
                success=False,
                output={"url": url},
                error_message=f"Network error fetching {url!r}: {exc.reason}",
            )
        except OSError as exc:
            # Catches bare TimeoutError / socket errors that arise after the
            # connection is established (e.g. during response.read()).
            return ToolOutcome(
                success=False,
                output={"url": url},
                error_message=f"OS error fetching {url!r}: {exc}",
            )

        # --- Bounded read + decode ---
        truncated = len(raw) > _MAX_RESPONSE_BYTES
        raw = raw[:_MAX_RESPONSE_BYTES]

        charset = _charset_from_content_type(content_type)
        try:
            content_text = raw.decode(charset, errors="replace")
        except LookupError:
            # Unknown codec name — fall back to UTF-8
            content_text = raw.decode("utf-8", errors="replace")

        return ToolOutcome(
            success=True,
            output={
                "url": final_url,
                "content_text": content_text,
                "content_type": content_type,
                "date_accessed": date_accessed,
                "http_status": http_status,
                "truncated": truncated,
            },
        )


def build_spec(
    *,
    approval_policy: ApprovalPolicy = "allowed",
) -> ToolSpec:
    """
    Build the verified ToolSpec for ``web-research-fetch`` (ADR-0005 §13).

    ``verified=True``: the author has personally inspected every line of
    this module and confirmed the stated behaviour (ADR-0009 §8 discipline
    applied to ToolInvokers).

    ``approval_policy`` defaults to ``"allowed"`` — a read-only HTTP GET
    falls in the "Read-only research, retrieval, analysis → ✅ free"
    category per ``docs/APPROVALS.md``.
    """
    return ToolSpec(
        tool_id=ToolId(TOOL_ID),
        name="Web Research Fetch",
        description=(
            "Fetch a single URL over HTTP and return its decoded body text, "
            "content type, and access timestamp. Read-only. No side effects. "
            "The calling graph node is responsible for claim extraction and "
            "KnowledgeItem construction — this invoker returns raw content only. "
            "See ADR-0005 §13."
        ),
        transport="http",
        side_effecting=False,
        approval_policy=approval_policy,
        input_schema=(
            ToolInputField(
                name="url",
                required=True,
                description="The URL to fetch (HTTP or HTTPS).",
            ),
            ToolInputField(
                name="context_hint",
                required=False,
                description=(
                    "Optional caller annotation for logging; "
                    "not sent in the HTTP request."
                ),
            ),
        ),
        verified=True,
    )


def register(
    registry: ToolRegistry,
    *,
    approval_policy: ApprovalPolicy = "allowed",
) -> None:
    """
    Explicit opt-in wiring — never called automatically by CVAgent.__init__.

    Registers the ToolSpec and a ``WebResearchFetchInvoker`` instance under
    ``"web-research-fetch"``.  The caller uses the same registry to construct
    a ``ToolExecutor`` for invocation:

        from cv_agent.tools.web_research import register
        from cv_agent.tools.executor import ToolExecutor
        from cv_agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        register(registry)
        executor = ToolExecutor(registry)
        result = executor.invoke(ToolId("web-research-fetch"), ToolRequest(
            inputs={"url": "https://example.com/paper.html"},
        ))
    """
    registry.register_spec(build_spec(approval_policy=approval_policy))
    registry.register_invoker(WebResearchFetchInvoker())
