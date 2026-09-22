# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-22 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) →
6 (partial, execution planning) · **Health:** green

## Where we are

`main` is at `0e86979` (PR #50 squash-merged 2026-09-21 — Issue #48 closed; 622 tests
green): `_cmd_execute`'s approval-required/unpinnable-binding branches are covered by
6 fixture-based, in-process tests, no approval-required binding ever registered for
the real skill. #43's pinning (ADR-0003 §10, D-032) is the enforcement layer; #47/#48 are display/test-coverage work on top of it.

**Local, uncommitted (audit follow-up, not a new phase/decision):** `ROADMAP.md`/
`OVERVIEW.md` reconciled against the implementation through PR #50 — explicit
Implemented/Partial/Planned status per row; corrected the stale Dataset/Training
ADR-0009/ADR-0010 mappings (now different, real ADRs). `.github/workflows/ci.yml`
added (ruff+mypy+pytest on push/PR to `main`), `ruff`/`mypy` in the `dev` extra.
All 12 `ruff` + 6 `mypy` pre-existing findings fixed (dead code, unused imports,
stdlib-stub gaps, one factory-call gap via `type: ignore` in `llm/registry.py`).
622 tests green. **Not committed.**

**Implemented:** skill discovery/resolution (ADR-0007), requirements analysis +
skill_links (ADR-0008), execution boundary (ADR-0009, one real `ExecutionRuntime`),
orchestration + four interrupt kinds (ADR-0003, ADR-0010 §13/§16), project memory
(ADR-0004), planning + true-XOR recovery + candidate disambiguation (ADR-0010
§9–§16), real CLI input handling for `workflow` (#34), approval integrity
(ADR-0003 §10, #43), CLI approval prompt context (#47).

**Still NOT implemented:** bindings for 83 other skills, RAG, MCP, research,
autonomous training, a real LLM provider, cost estimation, a persistent checkpointer
(Q3), an approval cost estimate (Q19), `pending_execution` in `workflow`, real-skill
CLI reachability of `provide_execution_inputs`/`choose_candidate` (#44; needs a 2nd binding).

## In flight

| Item | Issue | State |
|---|---|---|
| Docs reconciliation + CI (this session) | audit follow-up | local, uncommitted |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decisions |

## Next 3 actions

1. Review and commit the local docs-reconciliation + CI changes.
2. Owner decisions on #44 (opt-in registration; second real binding is blocked).
3. Q19 (cost estimate) / Q3 (durable checkpointer) — tracked in `OPEN_QUESTIONS.md`.

## Blockers

- Q3/Q19 block restart-survivable approval/cost estimates, not this local CI/docs work.

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, cost estimation,
registering an unverified binding, a second `ExecutionRuntime`/skill
binding, skill ranking/auto-selection, unrestricted autonomous execution,
merging the two graphs, a second `ProjectMemoryStore` backend, wiring
`pending_execution` into `workflow` (out of #34) — `[P§34]`.
