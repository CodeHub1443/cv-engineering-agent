# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-22 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) →
6 (partial, execution planning) · **Health:** green

## Where we are

`main` is at `9f7ad6a` (PR #49 squash-merged 2026-09-21 — Issue #47 closed; 622
tests green, incl. #48's work-in-progress branch). The CLI approval prompts
(`workflow` prompt + echo, `execute`'s `_confirm_approval`) show `runtime_id`
and `description` from the pinned approval context. #43's approval-integrity
pinning (ADR-0003 §10, D-032) remains the enforcement layer; #47 is display
only. PR #45 was closed as superseded by #46 (#43's PR).

**In progress:** branch `feature/claude/48-cmd-execute-approval-tests` — Issue #48:
`_cmd_execute` gains an injectable `prompt` keyword-only parameter (default `input`, never
passed by `main()` — no live-CLI behavior change) so its approval-required and
unpinnable-binding branches can be tested in-process against a fixture skill root, no real
skill installed. 6 new tests; 622 total green. Not committed/pushed yet — awaiting review.

**Implemented:** skill discovery/resolution (ADR-0007), requirements analysis +
skill_links (ADR-0008), execution boundary (ADR-0009, one real
`ExecutionRuntime`), orchestration + four interrupt kinds (ADR-0003, ADR-0010
§13/§16), project memory (ADR-0004), planning + true-XOR recovery + candidate
disambiguation (ADR-0010 §9–§16), real CLI input handling for `workflow` (#34),
approval integrity (ADR-0003 §10, #43), CLI approval prompt context (#47).

**Still NOT implemented:** bindings for 83 other skills, RAG, MCP, research,
autonomous training, a real LLM provider, cost estimation, a persistent
checkpointer (Q3), an approval cost estimate (Q19), `pending_execution` in
`workflow`, real-skill CLI reachability of `provide_execution_inputs`/
`choose_candidate` (#44; `choose_candidate` also needs a second real binding).

## In flight

| Item | Issue | State |
|---|---|---|
| `_cmd_execute` approval-path + `ValueError`-branch tests | #48 | implemented on branch; not committed |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decisions |

## Next 3 actions

1. Review, commit, and open a PR for #48's branch.
2. Owner decisions on #44 (opt-in registration; second real binding is blocked).
3. Q19 (cost estimate) / Q3 (durable checkpointer) — tracked in `OPEN_QUESTIONS.md`.

## Blockers

- Q3 blocks a restart-survivable approval; Q19 a real cost estimate. Nothing blocks #48.

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, cost estimation,
registering an unverified binding, a second `ExecutionRuntime`/skill
binding, skill ranking/auto-selection, unrestricted autonomous execution,
merging the two graphs, a second `ProjectMemoryStore` backend, wiring
`pending_execution` into `workflow` (out of #34) — `[P§34]`.
