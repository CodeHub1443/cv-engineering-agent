# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-18 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) →
6 (partial, execution planning) · **Health:** green

## Where we are

`main` is at `3f4cde6` (PR #38 merged 2026-09-18). This branch (issue #39,
PR #40 open) resolves Q20 by owner decision: a true oneOf/XOR field-group
construct. New `RequiredFieldGroup` (ADR-0009 §12/§13), exactly-one enforced
by `plan_execution()`/`provide_execution_inputs` (ADR-0010 §14/§15) — review
corrected an initial "at least one" under-enforcement + added group-overlap
validation before merge. `trt_perf_analysis.build_binding()` now populates
its real `path`/`data`/`model_name` contract, closing the gap ADR-0009 §11
left open — the previously-blocked real end-to-end recovery test (incl. the
"both supplied" rejection path) now exists and passes.

**Implemented:** skill discovery/resolution (ADR-0007), requirements
analysis + skill_links (ADR-0008), skill execution boundary (ADR-0009, one
real `ExecutionRuntime`), orchestration + approval interrupts (ADR-0003),
project memory (ADR-0004), execution planning + true-XOR recovery (ADR-0010
§9–§15), real CLI input handling for `workflow` (#34).

**Still NOT implemented:** bindings for 83 other skills, RAG, MCP, research,
autonomous training, a real LLM provider, cost estimation, a persistent
checkpointer (Q3), skill disambiguation (Q18 — design decided, not built),
an approval-gate cost estimate (Q19), `pending_execution` wired into
`workflow` (out of #34's scope).

## In flight

| Item | Issue | State |
|---|---|---|
| Q20 field groups (true XOR, reviewed) | #39 | 437 tests pass, PR #40 open, awaiting merge decision |
| Q18 disambiguation interrupt | #— | decided, not yet built |
| ADR-0001/0003/0004/0007/0008/0009/0010 | #— | accepted (retroactive) |

## Next 3 actions

1. Merge PR #40 once approved (owner decision, not this agent's to make).
2. Build Q18's disambiguation interrupt (design decided; needs its own issue).
3. Decide Q19 (cost estimate) if a grouped, approval-gated binding appears.

## Blockers

- None for #39/PR #40. Q3 blocks a restart-survivable approval interrupt;
  Q19 blocks a real approval flow with an actual cost estimate.

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, cost estimation,
registering an unverified binding, a second `ExecutionRuntime`/skill
binding, skill ranking/auto-selection, unrestricted autonomous execution,
merging the two graphs, a second `ProjectMemoryStore` backend, wiring
`pending_execution` into `workflow` (out of #34) — `[P§34]`.
