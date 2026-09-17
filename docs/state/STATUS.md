# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-17 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) →
6 (partial, execution planning) · **Health:** green

## Where we are

`main` is at `93549de` (PR #33, merged — same-session `missing_required_inputs`
recovery, ADR-0010 §13; a prior revision of this file wrongly showed it as
unmerged, corrected 2026-09-17 against `git log origin/main`, no code changed). A
caller who learns a required execution input's value only **after**
`missing_required_inputs` can now supply it and resume planning the *same*
session, via a one-round, identity+schema-gated `provide_execution_inputs`
interrupt that bypasses `approval_gate` on any failure outcome.

**Implemented:** skill discovery + resolution (ADR-0007), requirements analysis +
skill_links (ADR-0008), skill execution boundary (ADR-0009, one real opt-in
`ExecutionRuntime`: `trt-perf-analysis`), orchestration + approval interrupts
(ADR-0003), project memory (ADR-0004), execution planning + `planning_result`
(ADR-0010 §9–§11), pre-supplied execution-input channel (§12), same-session
`missing_required_inputs` recovery via `provide_execution_inputs` (§13).

**Still NOT implemented:** bindings for 83 other skills, RAG, MCP, research,
autonomous training, a real LLM provider, cost estimation, a persistent
checkpointer (Q3), skill disambiguation (Q18), an approval-gate cost estimate
(Q19), execution-input oneOf/XOR schema support (Q20 — blocks only a real,
unfaked end-to-end recovery test; the mechanism itself is binding-agnostic and
fixture-tested), real (non-synthetic) CLI input handling for `workflow` (#34).

## In flight

| Item | Issue | State |
|---|---|---|
| Real CLI input handling for `workflow` (clarify/approval/provide_execution_inputs) | #34 | not started |
| ADR-0001/0003/0004/0007/0008/0009/0010 | #— | accepted (retroactive) |

## Next 3 actions

1. Implement #34 — real `--answer`/`--input`/`--approve`/`--reject` + stdin
   handling for `workflow`, all three interrupt kinds (ROADMAP Phase 4's gap).
2. Decide Q18/Q20 — owner decisions; nothing to build until answered.
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
fixing `clarify`'s empty-dict-resume gap (documented, not fixed) — `[P§34]`.
