# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-01 · **Phase:** 1 — Architecture & ADR Specification · **Health:** green

## Where we are

Phase 0 governance is complete. The repository operates with the agreed three-level
development flow: `main` → `dev-munna` → short-lived branches. `dev-munna` is the PM
integration branch; `main` remains the official integration/release branch and is
promoted from `dev-munna` by the Official PM.

The frozen project definition is `docs/PROJECT.md`. ADR-0001 (capability model) has been
reviewed and accepted. ADR-0002 (LLM gateway) has been critically reviewed but remains
draft pending resolution of interface-contract gaps identified during acceptance review.

## In flight

| Item | Issue | State |
|---|---|---|
| ADR-0002 LLM gateway contract refinement | #11 | draft / revision required |
| Q1–Q5 PM decisions | #— | blocking |

## Next 3 actions

1. Refine ADR-0002 and complete its acceptance review.
2. Resolve Q1–Q5 with the PM; record each decision before drafting blocked ADRs.
3. Draft ADR-0003 / ADR-0004 only after their blocking questions are settled.

## Blockers

- Q1–Q5 in `docs/state/OPEN_QUESTIONS.md` remain blocking for ADR-0003/ADR-0004 and,
  for Q5, ADR-0005/ADR-0007.

## Do not start yet

Stage workflows, RAG, training execution, SkillSource/skill discovery, or
CapabilityResolver implementation. These depend on the accepted registry/gateway,
state model, and memory architecture.
