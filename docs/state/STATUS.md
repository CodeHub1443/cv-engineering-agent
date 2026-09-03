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
ADR-0004 (project memory & experiment ledger), and ADR-0005 (tools & MCP boundary)
are accepted. Decisions Q1–Q5, Q7–Q8, D-022, and D-023 are recorded. ADR-0006
(Knowledge / RAG) is the next architectural specification.

## In flight

| Item | Issue | State |
|---|---|---|
| Phase 1 milestone promotion PR #18 | #18 | open (under Official PM review) |
| ADR-0006 Knowledge & RAG specification | #TBD | in drafting on `docs/issue-adr-0006-knowledge-rag` |

## Next 3 actions

1. Complete architectural review and verification of ADR-0006 (Knowledge & RAG).
2. Await Official PM review and merge of milestone promotion PR #18 (dev-munna -> main).
3. Advance Phase 2 research pipeline specification per `docs/RESEARCH_POLICY.md`.

## Blockers

- Q10 in `docs/state/OPEN_QUESTIONS.md` is open, blocking ADR-0009.
- Downstream implementation work is gated on Phase 1 ADR acceptance.

## Do not start yet

Stage workflows, RAG, training execution, SkillSource/skill discovery, or
CapabilityResolver implementation. These depend on accepted architecture ADRs.

