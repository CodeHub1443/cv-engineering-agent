# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-21 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) →
6 (partial, execution planning) · **Health:** green pending review (#43 fix on a branch)

## Where we are

`main` is at `3230361` (PR #42, Q18 `choose_candidate`; 493 tests). Branch
`fix/claude/43-approval-integrity` implements **#43 approval integrity** (ADR-0003 §10,
ADR-0009 §14, ADR-0010 §17, D-032): the approval pause pins the whole binding + a runtime
generation, the gate decides from the pin only, a recorded rejection is terminal before any
registry read, and the executor compares the pin at its single lookup. 108 new tests, 601
total green; **not merged — PR review pending.** Documented limits (§10.8): in-place
mutation of a registered runtime, process restart, thread safety.

**Implemented:** skill discovery/resolution (ADR-0007), requirements analysis +
skill_links (ADR-0008), execution boundary (ADR-0009, one real
`ExecutionRuntime`), orchestration + four interrupt kinds (ADR-0003, ADR-0010
§13/§16), project memory (ADR-0004), planning + true-XOR recovery + candidate
disambiguation (ADR-0010 §9–§16), real CLI input handling for `workflow` (#34).

**Still NOT implemented:** bindings for 83 other skills, RAG, MCP, research,
autonomous training, a real LLM provider, cost estimation, a persistent
checkpointer (Q3), an approval cost estimate (Q19), `pending_execution` in
`workflow`, real-skill CLI reachability of `provide_execution_inputs`/
`choose_candidate` (#44; `choose_candidate` also needs a second real binding).

## In flight

| Item | Issue | State |
|---|---|---|
| Approval-pause binding integrity (2 defects) | #43 | implemented + tested on branch; awaiting PR review/merge |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decisions |

## Next 3 actions

1. Review and merge the #43 PR (`fix/claude/43-approval-integrity`).
2. Owner decisions on #44 (opt-in registration; second real binding is blocked).
3. Q19 (cost estimate) / Q3 (durable checkpointer) — tracked in `OPEN_QUESTIONS.md`.

## Blockers

- Q3 blocks a restart-survivable approval (pins are process-local); Q19 a real
  cost estimate. #43's merge is pending review.

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, cost estimation,
registering an unverified binding, a second `ExecutionRuntime`/skill
binding, skill ranking/auto-selection, unrestricted autonomous execution,
merging the two graphs, a second `ProjectMemoryStore` backend, wiring
`pending_execution` into `workflow` (out of #34) — `[P§34]`.
