"""
cv_agent.tools.invoker — ToolInvoker protocol.

See ADR-0005 §5. Deliberately symmetric in *shape* to
`cv_agent.execution.binding.ExecutionRuntime.invoke() -> RuntimeOutcome`
(ADR-0009 §5), but never substitutable for it — no shared base class, no
isinstance-compatible substitution (ADR-0005 §9 rule 4).
"""

from __future__ import annotations

from typing import Protocol

from cv_agent.tools.models import ToolOutcome, ToolRequest, ToolSpec


class ToolInvoker(Protocol):
    """Something that can actually invoke a tool, given inputs."""

    tool_id: str
    """
    Stable identifier, matched against `ToolRegistry.register_invoker`'s
    key. Stays a plain `str` here, not `ToolId`: it identifies which invoker
    instance this is at registration time, mirroring `ExecutionRuntime.
    runtime_id`'s own plain-str identity (ADR-0009 §5) — the typed `ToolId`
    is for catalogue-facing identifiers (`ToolSpec`/`ToolResult`/registry
    lookups), not every internal string with the same value.
    """

    def invoke(self, spec: ToolSpec, request: ToolRequest) -> ToolOutcome:
        """
        Invoke the tool. Must not raise for an ordinary failure — report it
        via `ToolOutcome(success=False, error_message=...)` instead; the
        executor treats an actual exception as a distinct case (a bug in the
        invoker, not an ordinary failed call) but reports both the same way
        in the returned status ("failed").

        Returns `ToolOutcome`, never `ToolResult` — a `ToolInvoker` has no
        field to set `tool_id`, `status`, or evidence with. `ToolExecutor`
        alone constructs the final `ToolResult` (ADR-0005 §9 rule 7).
        """
        ...
