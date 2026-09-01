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
ADR-0002 (LLM gateway) are accepted. Decisions Q1–Q4, Q7–Q8 are recorded. ADR-0003
(orchestration state & checkpointing) is drafted and proposed.

## In flight

| Item | Issue | State |
|---|---|---|
| ADR-0003 architecture | #— | proposed / awaiting PM review |
| ADR-0004 architecture | #— | unblocked (Q1–Q2, Q8 settled) |

## Next 3 actions

1. Review and accept/revise ADR-0003 (orchestration state).
2. Draft ADR-0004 (project memory / experiment ledger) using resolved Q1–Q2 & Q8.
3. Keep Q5 deferred until Phase 1 core architecture ADRs are complete.

## Blockers

- Q5 in `docs/state/OPEN_QUESTIONS.md` is deferred, blocking ADR-0005/ADR-0007.
- Downstream implementation work is gated on Phase 1 ADR acceptance.

## Do not start yet

Stage workflows, RAG, training execution, SkillSource/skill discovery, or
CapabilityResolver implementation. These depend on accepted architecture ADRs.

