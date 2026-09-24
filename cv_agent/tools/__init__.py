"""
cv_agent.tools — Tool / MCP boundary.

See ADR-0005 (Accepted). A generic, transport-agnostic contract for declaring
and invoking a named *tool* — distinct from `cv_agent.execution` (ADR-0009),
which is scoped specifically to running a *resolved Skill*. This package owns
`ToolSpec`/`ToolInvoker`/`ToolRegistry`/`ToolExecutor`; it does not decide
whether a tool should be invoked (reasoning, ADR-0008), does not discover or
resolve skills (`cv_agent.skills`, ADR-0007), does not implement the
skill-specific execution chain (`cv_agent.execution`, ADR-0009), and does not
select an MCP SDK, vendor, or concrete integration.

Leaf package: imports nothing from `cv_agent.execution`, `cv_agent.skills`,
`cv_agent.graph`, or `cv_agent.llm` (enforced by
`tests/test_tools.py::TestArchitectureBoundary`). Zero `ToolSpec`s and zero
`ToolInvoker`s are registered anywhere in this package — discovery/declaration
never implies executability (see `ToolSpec.verified`, `ToolRegistry.can_invoke`).
"""
