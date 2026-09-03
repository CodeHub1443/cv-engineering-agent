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
and ADR-0006 (knowledge & RAG) are accepted. Decisions Q1–Q5, Q7–Q8, D-022,
D-023, and D-024 are recorded. ADR-0007 (Skills Architecture & NVIDIA Discovery)
is drafted on `docs/issue-adr-0007-skills`.

## In flight

| Item | Issue | State |
|---|---|---|
| ADR-0007 Skills Architecture & NVIDIA Discovery | #22 | proposed on `docs/issue-adr-0007-skills` |

## Next 3 actions

1. Review and refine ADR-0007 (Skills Architecture & NVIDIA Discovery) specification.
2. Formulate Phase 3 skill registry and NVIDIA adapter interfaces per `[P§15]`.
3. Prepare next milestone promotion PR when authorized by the Official PM.

## Blockers

- Q10 in `docs/state/OPEN_QUESTIONS.md` is open, blocking ADR-0009.
- Downstream implementation work is gated on architecture ADR acceptance.

## Do not start yet

Stage workflows, RAG, training execution, SkillSource/skill discovery, or
CapabilityResolver implementation. These depend on accepted architecture ADRs.
