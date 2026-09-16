"""
cv_agent.execution.runtimes — concrete, individually-verified ExecutionRuntime
adapters for real installed skills.

Nothing in this package is imported or registered automatically by
`cv_agent.runtime.agent.CVAgent` or `cv_agent.execution.executor.SkillExecutor`
— per ADR-0009 §8, each adapter here was inspected and verified for exactly
one skill and must be wired in explicitly by a caller (see each module's
`register()` function), never auto-discovered or bulk-registered. This
package must never grow a dispatch table keyed by skill_id — that would
recreate the "hardcode a large collection of bindings" shortcut ADR-0009
explicitly rejected; each adapter stays its own small, separately-reviewed
module.
"""
