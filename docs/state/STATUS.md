# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-01 · **Phase:** 0 — Foundation & governance · **Health:** green

## Where we are

Documentation consistency pass complete: authority hierarchy fixed (D-006), `spec/`
duplication/conflicts retired or reduced to canon-citing elaborations (D-007), git
workflow unified on single-trunk `main` + `feature/<owner>/<work>` (D-008), and
capability registry semantics corrected (D-009). `docs/PROJECT.md` is frozen canon.
The pre-existing code baseline `[P§32]` — package, config, LLM abstraction, mock
provider, LangGraph runtime, agent state, capability registry, CLI, tests — is present
but **not yet governed by ADRs**. No intelligence layers exist yet.

**Step 2 is NOT implemented.** None of the following exist in code: `SkillSource`,
skill discovery (global/local), metadata extraction, `CapabilityResolver`, real
executable-availability detection, a `skills` CLI, a `resolve` CLI, RAG, MCP
integration, a research subsystem, autonomous training, experiment execution,
optimization workflows, production deployment, or production monitoring. Every
capability in `spec/capability_registry.json` is `status: "planned"` (declared, no
executable binding) — none is `"available"`. Do not build any of the above without a
GitHub issue and, where architectural, an ADR.

## In flight

| Item | Issue | State |
|---|---|---|
| Governance docs committed & reviewed | #— | in progress |
| GitHub scaffolding (labels, templates, CI, milestones) | #— | not started |
| ADR-0001 capability model — seed written, needs review | #— | proposed |

## Next 3 actions

1. Human review of `CLAUDE.md` and `docs/architecture/OVERVIEW.md`; accept or amend.
2. Create GitHub labels, issue/PR templates, CI, and Phase-1 milestone with issues.
3. Accept or revise ADR-0001, then write ADR-0002 (LLM gateway) `[P§20]`.

## Blockers

- `docs/state/OPEN_QUESTIONS.md` Q1–Q5 are **blocking**: they must be answered before
  ADR-0003 (orchestration state) can be written.

## Do not start yet

Stage workflows `[P§6]`, RAG `[P§19]`, training execution `[P§10]`, SkillSource/skill
discovery, `CapabilityResolver`. These depend on the registry, gateway, state model,
and memory. Building them first is the failure mode `[P§34]` warns about.
