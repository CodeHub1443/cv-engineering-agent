# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-03 · **Phase:** 1 — Architecture & ADR Specification · **Health:** green

## Where we are

Phase 0 governance is complete. The repository operates with the agreed three-level
development flow: `main` → `dev-munna` → short-lived branches. `dev-munna` is the PM
integration branch; `main` remains the official integration/release branch and is
promoted from `dev-munna` by the Official PM.

The frozen project definition is `docs/PROJECT.md`. ADR-0001 (capability model),
ADR-0002 (LLM gateway), ADR-0003 (orchestration state & checkpointing),
ADR-0004 (project memory & experiment ledger), ADR-0005 (tools & MCP boundary),
ADR-0006 (knowledge & RAG), and ADR-0007 (skills architecture & discovery)
are accepted. Decisions Q1–Q5, Q7–Q8, D-022, D-023, D-024, and D-025
are recorded. ADR-0008 (Reasoning subsystem) is drafted on `docs/issue-adr-0008-reasoning`.

## In flight

| Item | Issue | State |
|---|---|---|
| ADR-0008 Reasoning Subsystem | #24 | proposed on `docs/issue-adr-0008-reasoning` |

## Next 3 actions

1. Open and verify PR for ADR-0008 (Reasoning Subsystem) into `dev-munna`.
2. Complete ADR-0008 acceptance synchronization on `dev-munna`.
3. Unblock downstream milestone when authorized by the Official PM.

## Blockers

- Q10 in `docs/state/OPEN_QUESTIONS.md` is open, blocking ADR-0009.
- Downstream implementation work is gated on architecture ADR acceptance.

## Do not start yet

Stage workflows, RAG, training execution, SkillSource/skill discovery, or
CapabilityResolver implementation. These depend on accepted architecture ADRs.
