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
ADR-0002 (LLM gateway), ADR-0003 (orchestration state & checkpointing), and
ADR-0004 (project memory & experiment ledger) are accepted. Phase 1 substrate ADR
specification is complete. Decisions Q1–Q4, Q7–Q8 are recorded.

## In flight

| Item | Issue | State |
|---|---|---|
| Phase 1 milestone promotion PR #18 | #18 | open (under Official PM review) |

## Next 3 actions

1. Await Official PM review and merge of milestone promotion PR #18 (dev-munna -> main).
2. Assess Q5 (NVIDIA capability inventory) before Phase 2 ADR-0005 (tool/MCP boundary).
3. Prepare Phase 2 architecture (ADR-0006 knowledge/RAG or Q5 discovery for ADR-0005).

## Blockers

- Q5 in `docs/state/OPEN_QUESTIONS.md` is deferred, blocking ADR-0005/ADR-0007.
- Downstream implementation work is gated on Phase 1 ADR acceptance.

## Do not start yet

Stage workflows, RAG, training execution, SkillSource/skill discovery, or
CapabilityResolver implementation. These depend on accepted architecture ADRs.

