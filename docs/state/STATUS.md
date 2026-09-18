# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-19 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) →
6 (partial, execution planning) · **Health:** green

## Where we are

`main` is at `0a7c778` (PR #36/#35 merged 2026-09-18 — real CLI input handling
for `workflow`, #34, closed). This branch (Q21 fix, PR pending) closes #37: declining
every clarification question used to make `_route_after_analysis` re-raise
`clarify` indefinitely (truthiness on `clarification_answers` couldn't tell
"attempted, declined" from "never attempted"), plus a second, independent gap —
`Command(resume={})` never reaches `clarify` at all (same LangGraph
characteristic ADR-0010 §13 already documented for `provide_execution_inputs`)
— both confirmed empirically. Fixed: new `AgentState["clarification_attempted"]`
flag (ADR-0003 §9) + CLI resumes with `""`, never `{}`, on full decline.

**Implemented:** skill discovery + resolution (ADR-0007), requirements analysis +
skill_links (ADR-0008), skill execution boundary (ADR-0009, one real opt-in
`ExecutionRuntime`: `trt-perf-analysis`), orchestration + approval interrupts
(ADR-0003, now with a correct clarify loop bound), project memory (ADR-0004),
execution planning (ADR-0010 §9–§13), real CLI input handling for `workflow`
(#34) — decline-all path now completes cleanly, not the CLI's safety cap.

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
| Clarify attempted-flag fix (Q21) | #37 | implemented, 405 tests pass, PR pending |
| ADR-0001/0003/0004/0007/0008/0009/0010 | #— | accepted (retroactive) |

## Next 3 actions

1. Review and merge the Q21 fix PR (#37).
2. Decide Q18/Q20 (owner decisions; nothing to build until answered).
3. Only after that decision: a second `ExecutionRuntime` — forbidden below until then.

## Blockers

- None for #37. Q3 blocks a restart-survivable approval interrupt; Q20 blocks a
  real (non-fixture) end-to-end recovery test.

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, cost estimation, registering an
unverified binding, a second `ExecutionRuntime`/skill binding, skill
ranking/auto-selection, unrestricted autonomous execution, merging the two graphs,
a second `ProjectMemoryStore` backend, populating `trt_perf_analysis`'s schema
before Q20, wiring `pending_execution` into `workflow` (out of #34) — `[P§34]`.
