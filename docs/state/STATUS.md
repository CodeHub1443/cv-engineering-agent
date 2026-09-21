# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-21 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) →
6 (partial, execution planning) · **Health:** green

## Where we are

`main` is at `a92ec2e` (PR #46 squash-merged 2026-09-21 — #43 approval integrity,
closed; 601 tests green): the approval pause pins the whole binding + a runtime
generation, the gate decides from the pin only, a recorded rejection is terminal
before any registry read, and the executor compares the pin at its single lookup
(ADR-0003 §10, D-032; limits in §10.8). PR #45 was closed as superseded by #46.

**In review:** PR #49 (`feature/claude/47-approval-prompt-context`, `abd3370`) —
Issue #47: the CLI approval prompts (`workflow` prompt + echo, `execute`'s
`_confirm_approval`) now show `runtime_id` and `description`. Display only;
616 tests green (601 + 15); **not merged.**

**Implemented:** skill discovery/resolution (ADR-0007), requirements analysis +
skill_links (ADR-0008), execution boundary (ADR-0009, one real
`ExecutionRuntime`), orchestration + four interrupt kinds (ADR-0003, ADR-0010
§13/§16), project memory (ADR-0004), planning + true-XOR recovery + candidate
disambiguation (ADR-0010 §9–§16), real CLI input handling for `workflow` (#34),
approval integrity (ADR-0003 §10, #43).

**Still NOT implemented:** bindings for 83 other skills, RAG, MCP, research,
autonomous training, a real LLM provider, cost estimation, a persistent
checkpointer (Q3), an approval cost estimate (Q19), `pending_execution` in
`workflow`, real-skill CLI reachability of `provide_execution_inputs`/
`choose_candidate` (#44; `choose_candidate` also needs a second real binding).

## In flight

| Item | Issue | State |
|---|---|---|
| CLI approval prompt shows runtime + description | #47 | PR #49 open; awaiting review/merge |
| `_cmd_execute` approval-path + `ValueError`-branch test | #48 | tracked; not started |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decisions |

## Next 3 actions

1. Review and merge PR #49 (closes #47).
2. #48 (tests for `_cmd_execute`'s approval path) — fixture-based, no real skill needed.
3. Owner decisions on #44; Q19 (cost estimate) / Q3 (durable checkpointer) in `OPEN_QUESTIONS.md`.

## Blockers

- Q3 blocks a restart-survivable approval; Q19 a real cost estimate. None block PR #49.

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, cost estimation,
registering an unverified binding, a second `ExecutionRuntime`/skill
binding, skill ranking/auto-selection, unrestricted autonomous execution,
merging the two graphs, a second `ProjectMemoryStore` backend, wiring
`pending_execution` into `workflow` (out of #34) — `[P§34]`.
