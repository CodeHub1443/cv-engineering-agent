"""
cv_agent.tools.executor — ToolExecutor.

Transport-agnostic: this module never imports or names a specific transport,
MCP SDK, or vendor. It only knows the `ToolSpec`/`ToolInvoker` protocols from
`models.py`/`invoker.py`. See ADR-0005 §5, §9.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cv_agent.tools.invoker import ToolInvoker
from cv_agent.tools.models import (
    ToolError,
    ToolEvidence,
    ToolId,
    ToolRequest,
    ToolResult,
    ToolSpec,
)
from cv_agent.tools.registry import ToolRegistry, tool_pin_is_well_formed, tool_pin_mismatch


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ToolExecutor:
    """
    Invokes a named tool through whatever `ToolSpec`/`ToolInvoker` the
    registry has for it — and fails safely, with a structured result, when
    it can't.

    This class owns exactly one responsibility: given (tool_id, request),
    decide whether invocation is possible and permitted, and if so, delegate
    to the registered invoker and report what happened. It does not:
      - decide *whether* a tool should be invoked, or which one a task
        needs → reasoning layer (ADR-0008), reached through capability/
        skill resolution (ADR-0001/ADR-0007) — that precedes this;
      - implement the human-approval workflow `docs/APPROVALS.md`
        describes — it only *checks* the flag a caller who already went
        through that workflow is expected to set on the request;
      - know what any specific invoker does — that lives behind the
        `ToolInvoker` protocol;
      - construct anything other than the `ToolResult` it itself returns —
        a `ToolInvoker` cannot set `tool_id`/`status`/evidence (ADR-0005
        §9 rule 7).
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def can_invoke(self, tool_id: ToolId) -> bool:
        """Inspect only — never invokes anything."""
        return self._registry.can_invoke(tool_id)

    @staticmethod
    def _pin_codes(
        tool_id: ToolId,
        pin: object,
        spec: ToolSpec,
        generation: int | None,
    ) -> tuple[str, ...]:
        """Mismatch codes for a SUPPLIED pin against the executor's own
        read; `()` means the pin matches. A malformed pin (including one
        for a different tool_id) is `tool_pin_malformed` for every policy."""
        if not tool_pin_is_well_formed(pin, tool_id=tool_id):
            return ("tool_pin_malformed",)
        try:
            live_spec = spec.pin()
        except ValueError:
            return ("spec.unpinnable",)
        return tool_pin_mismatch(pin, {"spec": live_spec, "invoker_generation": generation})

    def invoke(self, tool_id: ToolId, request: ToolRequest) -> ToolResult:
        spec = self._registry.get_spec(tool_id)

        if spec is None:
            return ToolResult(
                tool_id=tool_id,
                status="not_executable",
                evidence=ToolEvidence(tool_id, None, None, None),
                error=ToolError(
                    "no_tool", f"No ToolSpec registered for tool_id '{tool_id}'."
                ),
            )

        # ADR-0005 §5/§9: the invoker and its registration generation come
        # from ONE registry read, and these same locals are what the pin is
        # compared against AND what is invoked below — the instance invoked
        # is the instance whose generation was compared, by construction
        # rather than by two lookups agreeing.
        registration = self._registry.get_invoker_registration(tool_id)
        invoker: ToolInvoker | None = registration[0] if registration is not None else None
        generation = registration[1] if registration is not None else None

        pin = request.expected_tool_pin

        # E1-equivalent (ADR-0003 §10 rule E1, restated for tools, ADR-0005
        # §9 rule 2): an absent pin can never authorize an approval-required
        # invocation, whatever `request.approved` says.
        if pin is None and spec.approval_policy == "approval_required":
            return ToolResult(
                tool_id=tool_id,
                status="rejected",
                evidence=ToolEvidence(tool_id, generation, None, None),
                error=ToolError(
                    "approval_denied",
                    "Invocation requires approval per docs/APPROVALS.md ([P§24]) "
                    "and approval is not bound to a tool pin "
                    "(request.expected_tool_pin was not supplied).",
                ),
            )

        # ADR-0005 §9 rule 6: checked for ANY approval_policy whenever a pin
        # IS supplied, not only approval_required — a caller that chooses to
        # pin an "allowed" tool anyway still gets replacement detection.
        if pin is not None:
            codes = self._pin_codes(tool_id, pin, spec, generation)
            if codes:
                return ToolResult(
                    tool_id=tool_id,
                    status="not_executable",
                    evidence=ToolEvidence(tool_id, generation, None, None),
                    error=ToolError(
                        "tool_mismatch", "integrity check failed: " + ", ".join(codes)
                    ),
                )

        if not spec.verified:
            return ToolResult(
                tool_id=tool_id,
                status="not_executable",
                evidence=ToolEvidence(tool_id, generation, None, None),
                error=ToolError(
                    "tool_not_verified",
                    f"ToolSpec '{tool_id}' is declared but not verified — a "
                    "declared spec is not evidence it works.",
                ),
            )

        if spec.approval_policy == "rejected":
            return ToolResult(
                tool_id=tool_id,
                status="rejected",
                evidence=ToolEvidence(tool_id, generation, None, None),
                error=ToolError(
                    "approval_denied", f"ToolSpec '{tool_id}' rejects invocation unconditionally."
                ),
            )

        if spec.approval_policy == "approval_required" and not request.approved:
            return ToolResult(
                tool_id=tool_id,
                status="rejected",
                evidence=ToolEvidence(tool_id, generation, None, None),
                error=ToolError(
                    "approval_denied",
                    "Invocation requires approval per docs/APPROVALS.md "
                    "([P§24]) and request.approved is False.",
                ),
            )

        if invoker is None:
            return ToolResult(
                tool_id=tool_id,
                status="not_executable",
                evidence=ToolEvidence(tool_id, generation, None, None),
                error=ToolError(
                    "no_tool", f"ToolSpec '{tool_id}' has no registered ToolInvoker."
                ),
            )

        started_at = _now_iso()
        try:
            outcome = invoker.invoke(spec, request)
        except Exception as exc:  # noqa: BLE001 — an invoker's own bug, not ours to type
            return ToolResult(
                tool_id=tool_id,
                status="failed",
                evidence=ToolEvidence(tool_id, generation, started_at, _now_iso()),
                error=ToolError("transport_error", str(exc)),
            )
        completed_at = _now_iso()

        if outcome.success:
            return ToolResult(
                tool_id=tool_id,
                status="completed",
                evidence=ToolEvidence(tool_id, generation, started_at, completed_at),
                output=outcome.output,
            )

        return ToolResult(
            tool_id=tool_id,
            status="failed",
            evidence=ToolEvidence(tool_id, generation, started_at, completed_at),
            error=ToolError(
                "transport_error", outcome.error_message or "Invoker reported failure."
            ),
        )
