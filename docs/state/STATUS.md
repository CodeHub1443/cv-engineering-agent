# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-17 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) →
6 (partial, execution planning) · **Health:** green

## Where we are

`main` is at `48e7c13` (PR #32 — pre-supplied execution-input channel, ADR-0010
§12). This branch (`feature/claude/q17-input-recovery`, unmerged) closes Q17's
remaining sub-case: a caller who learns a required execution input's value only
**after** `missing_required_inputs` can now supply it and resume planning in the
*same* session via a new `provide_execution_inputs` interrupt — one round only,
identity+schema-gated, bypassing `approval_gate` on any failure outcome (ADR-0010 §13).

**Implemented:** skill discovery + resolution (ADR-0007), requirements analysis +
skill_links (ADR-0008), skill execution boundary (ADR-0009, one real opt-in
`ExecutionRuntime`: `trt-perf-analysis`), orchestration + approval interrupts
(ADR-0003), project memory (ADR-0004), execution planning + `planning_result`
(ADR-0010 §9–§11), pre-supplied execution-input channel (ADR-0010 §12). **This
session:** same-session `missing_required_inputs` recovery (ADR-0010 §13) —
`provide_execution_inputs` node, `PlanningResult.selected_skill_id`/
`selected_binding_id`/`selected_input_schema`, `AgentState.execution_input_recovery`.

**Still NOT implemented:** bindings for 83 other skills, RAG, MCP, research,
autonomous training, a real LLM provider, cost estimation, a persistent checkpointer
(Q3), skill disambiguation (Q18), an approval-gate cost estimate (Q19),
execution-input oneOf/XOR schema support (Q20 — blocks only a real, unfaked
end-to-end recovery test against `trt-perf-analysis`; the mechanism is
binding-agnostic and fixture-tested).

## In flight

| Item | Issue | State |
|---|---|---|
| `provide_execution_inputs` recovery (ADR-0010 §13) | #— | implemented, tests pass, PR pending |
| ADR-0001/0003/0007/0008/0009/0010 | #— | accepted (retroactive) |

## Next 3 actions

1. Review and merge the Q17-recovery PR.
2. Decide Q18 (candidate disambiguation) and Q20 (TRT XOR/oneOf schema support).
3. A second individually-verified `ExecutionRuntime` (`gstreamer-pipeline`, ADR-0009
   §9) — first stress test of `input_schema`/`execution_input_recovery` beyond one.

## Blockers

- None for this session's scope. Q3 still blocks a restart-survivable approval
  interrupt. Q20 blocks a real (not synthetic-fixture) end-to-end recovery test.

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, cost estimation, registering an
unverified binding, a second `ExecutionRuntime`/skill binding, skill
ranking/auto-selection, unrestricted autonomous execution, merging the two graphs,
a second `ProjectMemoryStore` backend, populating `trt_perf_analysis`'s
`input_schema` before Q20, fixing `clarify`'s empty-dict-resume gap (documented,
not fixed, out of scope) — `[P§34]`.
