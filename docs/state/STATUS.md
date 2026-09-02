# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-02 · **Phase:** 1 — Architecture & ADR Specification · **Health:** green

## Where we are

Phase 0 governance is complete. The repository operates with the agreed three-level
development flow: `main` → `dev-munna` → short-lived branches. `dev-munna` is the PM
integration branch; `main` remains the official integration/release branch and is
promoted from `dev-munna` by the Official PM.

The frozen project definition is `docs/PROJECT.md`. ADR-0001 (capability model),
ADR-0002 (LLM gateway), and ADR-0003 (orchestration state & checkpointing) are accepted.
Decisions Q1–Q4, Q7–Q8 are recorded. ADR-0004 is unblocked for drafting.

## In flight

| Item | Issue | State |
|---|---|---|
| ADR-0004 architecture | #— | unblocked (ready for drafting) |

## Next 3 actions

1. Draft ADR-0004 (project memory / experiment ledger) using resolved Q1–Q2 & Q8.
2. Keep Q5 deferred until Phase 1 core architecture ADRs are complete.
3. Prepare tool/MCP boundary architecture pending Q5 resolution.

## Blockers

- Q5 in `docs/state/OPEN_QUESTIONS.md` is deferred, blocking ADR-0005/ADR-0007.
- Downstream implementation work is gated on Phase 1 ADR acceptance.

## Do not start yet

Stage workflows, RAG, training execution, SkillSource/skill discovery, or
CapabilityResolver implementation. These depend on accepted architecture ADRs.

