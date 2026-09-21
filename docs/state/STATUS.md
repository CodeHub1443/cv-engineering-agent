# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-21 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) →
6 (partial, execution planning) · **Health:** yellow (known approval-gate gap, #43)

## Where we are

`main` is at `3230361` (PR #42 squash-merged 2026-09-21 — Q18 `choose_candidate`,
#41 closed; 493 tests green). Q18 is done (ADR-0010 §16); an independent audit
(D-030) tightened it before merge.

**Known defect, pre-existing, NOT fixed (#43):** the approval pause pins only
`skill_id`. Reproduced on `main` and pre-Q18 `752bc1c`: (1) a replacement
binding/runtime registered during the pause executes under approval granted for
the original; (2) a replacement with an `allowed` policy **overrides a human
rejection** (`approval_decision="not_required"`, also with an unchanged
`binding_id`). Needs an in-process registry mutation, so low likelihood today
(one real binding), but it is an approval-integrity defect `[P§24]`. ADR
amendment first (`pending_execution`'s shape changes).

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
| Approval-pause binding integrity (2 defects) | #43 | tracked, not started; ADR first |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decisions |

## Next 3 actions

1. Decide #43 priority; write its ADR amendment (ADR-0003/0009) before code.
2. Owner decisions on #44 (opt-in registration; second real binding is blocked).
3. Q19 (cost estimate) / Q3 (durable checkpointer) — tracked in `OPEN_QUESTIONS.md`.

## Blockers

- #43 blocks trusting `approval_gate` as a hard guarantee under registry
  mutation. Q3 blocks a restart-survivable approval; Q19 a real cost estimate.

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, cost estimation,
registering an unverified binding, a second `ExecutionRuntime`/skill
binding, skill ranking/auto-selection, unrestricted autonomous execution,
merging the two graphs, a second `ProjectMemoryStore` backend, wiring
`pending_execution` into `workflow` (out of #34) — `[P§34]`.
