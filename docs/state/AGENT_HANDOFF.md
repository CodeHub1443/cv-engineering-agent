# AGENT HANDOFF

> Current-session handoff. Read after `STATUS.md` and `DECISIONS.md` when continuity
> context is needed. This file is state, not canon; normative project facts cite `[P§n]`.

## Current state

- **Phase:** 1 — Architecture & ADR Specification
- **Integration branch:** `dev-munna`
- **Release/integration branch:** `main`
- **Work pattern:** `main` ← `dev-munna` ← short-lived work branches
- **Current architecture gate:** ADR-0001 acceptance, then ADR-0002 acceptance.

## ADR status

| ADR | State |
|---|---|
| ADR-0001 — Capability model | Proposed / awaiting acceptance |
| ADR-0002 — LLM Gateway | Draft / awaiting acceptance |
| ADR-0003 — Orchestration state | Blocked by Q1–Q3 |
| ADR-0004 — Project memory / experiment ledger | Blocked by Q1–Q2 |
| ADR-0005 — Tools / MCP | Blocked by Q5 |
| ADR-0006 — Knowledge / RAG | Not started |
| ADR-0007 — Skills | Blocked by Q5 |
| ADR-0008 — Reasoning | Not started |
| ADR-0009 — Dataset subsystem | Not started |
| ADR-0010 — Training | Blocked by Q2 |
| ADR-0011 — Evaluation | Not started |
| ADR-0012 — Optimization / deployment | Not started |
| ADR-0013 — Monitoring | Not started |

## Agreed decisions

- **A-18 / D-016:** Q7 — initial LLM provider classes are Anthropic, OpenAI, and Local/Ollama; routing is configuration-driven; transient failures may fall back sequentially; request/configuration failures fail fast; metadata is preserved. See ADR-0002.
- **A-19 / D-017:** Q8 — dual-layer persistence: Git-tracked structured project memory plus local SQLite at `.cv_agent/state/experiments.sqlite` for high-volume experiment rows. See ADR-0004.

## Blocking questions

Q1–Q5 remain unanswered in `docs/state/OPEN_QUESTIONS.md`. Do not invent answers.
Q1–Q3 block ADR-0003; Q1–Q2 block ADR-0004; Q5 blocks ADR-0005 and ADR-0007.

## Next session

1. Review/accept or revise ADR-0001.
2. Review/accept or revise ADR-0002.
3. Resolve Q1–Q5 with the PM before drafting the blocked ADRs.
