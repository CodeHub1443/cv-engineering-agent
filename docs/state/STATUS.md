# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-20 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) →
6 (partial, execution planning) · **Health:** green

## Where we are

`main` is at `752bc1c` (PR #40 squash-merged 2026-09-18 — Q20 true-XOR field
groups, #39 closed; 437 tests green on merged `main`). This branch (issue
#41, PR pending) implements Q18 by owner decision (a clarification-style
interrupt, not a `--skill` override): a fourth interrupt kind,
`choose_candidate` (ADR-0010 §16). Ambiguous executable candidates now pause
the graph, present every candidate's skill_id + description, validate the
human's bare-skill_id answer against the exact offered set, persist it, and
resume planning via `plan_execution(..., selected_skill_id=...)`, whose retry
re-confirms the choice against the current registry (identity check, so a
mid-pause deregistration can never silently plan the *other* skill). One
shot; invalid/cancelled/mismatched is terminal, never a default.

**Implemented:** skill discovery/resolution (ADR-0007), requirements
analysis + skill_links (ADR-0008), skill execution boundary (ADR-0009, one
real `ExecutionRuntime`), orchestration + four interrupt kinds (ADR-0003,
ADR-0010 §13/§16), project memory (ADR-0004), execution planning + true-XOR
recovery + candidate disambiguation (ADR-0010 §9–§16), real CLI input
handling for `workflow` (#34).

**Still NOT implemented:** bindings for 83 other skills, RAG, MCP, research,
autonomous training, a real LLM provider, cost estimation, a persistent
checkpointer (Q3), an approval-gate cost estimate (Q19), `pending_execution`
wired into `workflow` (out of #34's scope). `choose_candidate` is unreachable
via the CLI against a *real* skill today (one real binding exists).

## In flight

| Item | Issue | State |
|---|---|---|
| Q18 `choose_candidate` interrupt | #41 | 468 tests pass, PR pending review |
| ADR-0001/0003/0004/0007/0008/0009/0010 | #— | accepted (retroactive) |

## Next 3 actions

1. Review the Q18 PR (owner decision to merge; not this agent's to make).
2. Decide Q19 (cost estimate) if an approval-gated binding appears.
3. Decide Q3 (durable checkpointer) or the next roadmap phase item.

## Blockers

- None for #41. Q3 blocks a restart-survivable approval interrupt;
  Q19 blocks a real approval flow with an actual cost estimate.

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, cost estimation,
registering an unverified binding, a second `ExecutionRuntime`/skill
binding, skill ranking/auto-selection, unrestricted autonomous execution,
merging the two graphs, a second `ProjectMemoryStore` backend, wiring
`pending_execution` into `workflow` (out of #34) — `[P§34]`.
