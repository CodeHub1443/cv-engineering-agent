# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-01 · **Phase:** 1 — Architecture & ADR Specification · **Health:** green

## Where we are

Phase 0 governance is complete. The repository operates with the agreed three-level
development flow: `main` → `dev-munna` → short-lived branches. `dev-munna` is the PM
integration branch; `main` remains the official integration/release branch and is
promoted from `dev-munna` by the Official PM.

The frozen project definition is `docs/PROJECT.md`. ADR-0001 (capability model) and
ADR-0002 (LLM gateway) have been reviewed and accepted. Their interfaces are now the
architectural baseline for the remaining Phase 1 decisions.

## In flight

| Item | Issue | State |
|---|---|---|
| Q1–Q5 PM decisions | #— | blocking |
| ADR-0003 / ADR-0004 architecture | #— | blocked pending Q1–Q3 / Q1–Q2 |

## Next 3 actions

1. Resolve Q1–Q5 with the PM; record each decision before drafting blocked ADRs.
2. Draft ADR-0003 (orchestration state) after Q1–Q3 are settled.
3. Draft ADR-0004 (project memory / experiment ledger) after Q1–Q2 are settled.

## Blockers

- Q1–Q5 in `docs/state/OPEN_QUESTIONS.md` remain blocking for ADR-0003/ADR-0004 and,
  for Q5, ADR-0005/ADR-0007.

## Do not start yet

Stage workflows, RAG, training execution, SkillSource/skill discovery, or
CapabilityResolver implementation. These depend on the accepted registry/gateway,
state model, and memory architecture.
