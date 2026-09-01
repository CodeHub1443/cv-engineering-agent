# AGENT HANDOFF

> Current-session handoff. Read after `STATUS.md` and `DECISIONS.md` when continuity
> context is needed. This file is state, not canon; normative project facts cite `[P§n]`.

## Current state

- **Phase:** 1 — Architecture & ADR Specification
- **Integration branch:** `dev-munna`
- **Release/integration branch:** `main`
- **Work pattern:** `main` ← `dev-munna` ← short-lived work branches
- **Current architecture gate:** ADR-0001 accepted; ADR-0002 accepted.

## ADR status

| ADR | State |
|---|---|
| ADR-0001 — Capability model | **Accepted** |
| ADR-0002 — LLM Gateway | **Accepted** |
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

- **D-010:** three-level development flow: short-lived work branches → `dev-munna` → final PR → `main`; `dev-munna` is the PM development/integration trunk and `main` is the Official PM integration/release trunk.
- **D-011:** ADR-0001 capability model accepted; four registry identities are semantic/type boundaries, not a requirement for independent storage backends.
- **D-012:** ADR-0002 LLM Gateway accepted; provider isolation, configuration-driven routing, transient fallback taxonomy, fast-fail request/configuration errors, normalized responses/errors, and reproducibility metadata are the Phase 1 gateway contract.
- **D-013:** Q1 — one CV Engineering Agent project per repository/workspace; project memory and experiment records are isolated to that project, with experiment identifiers scoped to the project.
- **D-014:** Q2 — the agent runs on the local workstation; training is submitted as an external job to a configured local, remote, or cloud GPU target and is not executed in-process.
- **D-015:** Q3 — human approvals are persistent workflow entities. The initial interaction surface may be CLI-based, but approval requests and state survive process restarts and support asynchronous approval.
- **D-016:** Q4 — Phase 1 architecture targets a real CV project; prison/garment examples are reference workloads and validation fixtures, not the architectural scope itself.
- **D-017:** Q7 — initial LLM provider classes are Anthropic, OpenAI, and Local/Ollama; routing is configuration-driven; transient failures may fall back sequentially; request/configuration failures fail fast; metadata is preserved. See ADR-0002.
- **D-018:** Q8 — dual-layer persistence: Git-tracked structured project memory plus local SQLite at `.cv_agent/state/experiments.sqlite` for high-volume experiment rows. See ADR-0004.

## Blocking questions

Q5 remains unanswered in `docs/state/OPEN_QUESTIONS.md`. Do not invent the installed/invocable NVIDIA capability inventory.

Q1–Q3 are resolved and unblock ADR-0003. Q1–Q2 are resolved and unblock ADR-0004. Q5 continues to block ADR-0005 and ADR-0007.

## Next session

1. Perform the final consistency/validation check for ADR-0002 and the PM decisions.
2. Draft ADR-0003 (orchestration state) using the resolved Q1–Q3 constraints.
3. Draft ADR-0004 (project memory / experiment ledger) using the resolved Q1–Q2 and Q8 constraints.
