# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-18 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) →
6 (partial, execution planning) · **Health:** green

## Where we are

`main` is at `3f4cde6` (PR #38 merged 2026-09-18 — Q21 clarify attempted-flag fix,
#37, closed). This branch (issue #39, PR pending) resolves `docs/state/
OPEN_QUESTIONS.md` Q20 by owner decision (asked directly, alongside Q18): a
oneOf/XOR field-group construct. New `RequiredFieldGroup` (ADR-0009 §12) on
`ExecutionBinding.input_field_groups` — presence-only, satisfied the moment any
one member is supplied; `plan_execution()` and the `provide_execution_inputs`
recovery interrupt are both made group-aware (ADR-0010 §14).
`trt_perf_analysis.build_binding()` now populates its real `path`/`data`/
`model_name` contract — the gap ADR-0009 §11/ADR-0010 §13.8 both left open,
closing the blocker on a genuine, unfaked end-to-end recovery test against the
real binding (now written and passing).

**Implemented:** skill discovery + resolution (ADR-0007), requirements analysis +
skill_links (ADR-0008), skill execution boundary (ADR-0009, one real opt-in
`ExecutionRuntime`: `trt-perf-analysis`, now with a real, group-aware
`input_schema`), orchestration + approval interrupts (ADR-0003, correct clarify
loop bound), project memory (ADR-0004), execution planning + group-aware
recovery (ADR-0010 §9–§14), real CLI input handling for `workflow` (#34).

**Still NOT implemented:** bindings for 83 other skills, RAG, MCP, research,
autonomous training, a real LLM provider, cost estimation, a persistent
checkpointer (Q3), skill disambiguation (Q18 — design decided: a clarification-
style interrupt; not yet built), an approval-gate cost estimate (Q19),
`pending_execution` wired into `workflow` (deliberately out of #34's scope).

## In flight

| Item | Issue | State |
|---|---|---|
| Q20 field groups + real trt-perf-analysis schema | #39 | implemented, 429 tests pass, PR pending |
| Q18 disambiguation interrupt | #— | decided, not yet built |
| ADR-0001/0003/0004/0007/0008/0009/0010 | #— | accepted (retroactive) |

## Next 3 actions

1. Review and merge the Q20 field-groups PR (#39).
2. Build Q18's disambiguation interrupt (design decided; needs its own issue) —
   or another owner-prioritized task.
3. Decide Q19 (approval-gate cost estimate) if/when a second, approval-gated
   binding is considered.

## Blockers

- None for #39. Q3 blocks a restart-survivable approval interrupt. Q19 blocks
  exercising an `approval_required` binding through a real, non-fake approval
  flow with an actual cost estimate.

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, cost estimation, registering an
unverified binding, a second `ExecutionRuntime`/skill binding, skill
ranking/auto-selection, unrestricted autonomous execution, merging the two graphs,
a second `ProjectMemoryStore` backend, wiring `pending_execution` into `workflow`
(out of #34) — `[P§34]`.
