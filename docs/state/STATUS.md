# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-01 · **Phase:** 1 — Architecture & ADR Specification · **Health:** green

## Where we are

Phase 0 governance is complete. The repository is now operating with the agreed
three-level development flow: `main` → `dev-munna` → short-lived branches. `dev-munna`
is the PM integration branch for this project; short-lived branches are used for each
work item and are merged back into `dev-munna` after review. `main` remains the official
integration/release branch and is promoted from `dev-munna` by the Official PM.

The frozen project definition is `docs/PROJECT.md`. The capability model seed
(ADR-0001) exists but remains proposed. The LLM gateway decision was previously drafted
as ADR-0002 and is being restored into the current `dev-munna` state so Phase 1 can
continue without losing the accepted Q7/Q8 work.

## In flight

| Item | Issue | State |
|---|---|---|
| Gitflow reconciliation (`main → dev-munna → short-lived`) | #— | in progress |
| ADR-0001 capability model | #— | proposed / awaiting acceptance |
| ADR-0002 LLM gateway | #11 | draft / awaiting acceptance |

## Next 3 actions

1. Reconcile and accept the repository Gitflow/state contract on the current branch.
2. Review and accept or revise ADR-0001, then accept/revise ADR-0002.
3. Resolve blocking Q1–Q5 before ADR-0003/ADR-0004 design proceeds.

## Blockers

- Q1–Q5 in `docs/state/OPEN_QUESTIONS.md` remain blocking for ADR-0003/ADR-0004 and,
  for Q5, ADR-0005/ADR-0007.

## Do not start yet

Stage workflows, RAG, training execution, SkillSource/skill discovery, or
CapabilityResolver. These depend on the registry, gateway, state model, and memory.
