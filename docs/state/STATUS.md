# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-18 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) →
6 (partial, execution planning) · **Health:** green

## Where we are

`main` is at `b3f12a1` (PR #35 merged 2026-09-18 — PR #33 state corrected). This
branch (`feature/claude/workflow-cli-io`, PR #36 pending) closes #34: `python -m
cv_agent workflow` now handles real, caller-supplied input for all three
interrupt kinds (`clarify`/`provide_execution_inputs`/`approval_gate`) via
`--answer`/`--input`/`--approve`/`--reject` or a live stdin prompt — never a
fabricated placeholder. Pre-existed: a caller who learns a required execution
input's value only **after** `missing_required_inputs` can resume planning the
*same* session, via a one-round, identity+schema-gated `provide_execution_inputs`
interrupt that bypasses `approval_gate` on any failure outcome (ADR-0010 §13).

**Implemented:** skill discovery + resolution (ADR-0007), requirements analysis +
skill_links (ADR-0008), skill execution boundary (ADR-0009, one real opt-in
`ExecutionRuntime`: `trt-perf-analysis`), orchestration + approval interrupts
(ADR-0003), project memory (ADR-0004), execution planning (ADR-0010 §9–§13), real
CLI input handling for `workflow` across all three interrupt kinds (#34).

**Still NOT implemented:** bindings for 83 other skills, RAG, MCP, research,
autonomous training, a real LLM provider, cost estimation, a persistent
checkpointer (Q3), skill disambiguation (Q18), an approval-gate cost estimate
(Q19), execution-input oneOf/XOR schema support (Q20 — blocks only a real,
unfaked end-to-end recovery test; the mechanism itself is binding-agnostic and
fixture-tested), `pending_execution` wired into `workflow` (deliberately out of
#34's scope).

## In flight

| Item | Issue | State |
|---|---|---|
| Real CLI input handling for `workflow` | #34 | implemented, 403 tests pass, PR #36 pending |
| ADR-0001/0003/0004/0007/0008/0009/0010 | #— | accepted (retroactive) |

## Next 3 actions

1. Review and merge PR #36 (#34, implementation complete).
2. Decide Q18/Q20/Q21 (owner decisions; nothing to build until answered).
3. Only after that decision: a second `ExecutionRuntime` — forbidden below until then.

## Blockers

- None for #34. Q3 blocks a restart-survivable approval interrupt; Q20 blocks a
  real (non-fixture) end-to-end recovery test.

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, cost estimation, registering an
unverified binding, a second `ExecutionRuntime`/skill binding, skill
ranking/auto-selection, unrestricted autonomous execution, merging the two graphs,
a second `ProjectMemoryStore` backend, populating `trt_perf_analysis`'s schema
before Q20, wiring `pending_execution` into `workflow` (out of #34's scope),
fixing `_route_after_analysis`'s truthiness-based re-interrupt gap (Q21, new —
documented, not fixed) — `[P§34]`.
