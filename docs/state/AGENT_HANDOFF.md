# AGENT HANDOFF

> Current-session handoff. Read after `STATUS.md` and `DECISIONS.md` when continuity
> context is needed. This file is state, not canon; normative project facts cite `[P§n]`.

## Current state

- **Phase:** 1 — Architecture & ADR Specification
- **Integration branch:** `dev-munna`
- **Release/integration branch:** `main`
- **Work pattern:** `main` ← `dev-munna` ← short-lived work branches
- **Current architecture gate:** ADR-0001 accepted; ADR-0002 accepted; ADR-0003 accepted; ADR-0004 accepted.

## ADR status

| ADR | State |
|---|---|
| ADR-0001 — Capability model | **Accepted** |
| ADR-0002 — LLM Gateway | **Accepted** |
| ADR-0003 — Orchestration state | **Accepted** |
| ADR-0004 — Project memory / experiment ledger | **Accepted** |
| ADR-0005 — Tools / MCP | Unblocked (Q5 settled) |
| ADR-0006 — Knowledge / RAG | Not started |
| ADR-0007 — Skills | Unblocked (Q5 settled) |
| ADR-0008 — Reasoning | Not started |
| ADR-0009 — Dataset subsystem | Not started |
| ADR-0010 — Training | Unblocked (Q2 settled) |
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
- **D-019:** ADR-0003 orchestration state, checkpointing, and persistent approvals proposed; SQLite-backed state persistence, approval interrupts, and asynchronous external job handles defined.
- **D-020:** ADR-0003 Orchestration State Machine, Checkpointing, and Persistent Approvals is accepted; runtime checkpoint persistence at `.cv_agent/state/checkpoints.sqlite` with configurable retention reconciled with D-018 experiment ledger.
- **D-021:** ADR-0004 Project Memory and Experiment Ledger Persistence is accepted; dual-layer persistence (.cv_agent/memory/ and .cv_agent/state/experiments.sqlite), immutable completed results, explicit lifecycle transitions, relational baseline integrity, and workload-scoped metrics defined.
- **D-022:** Q5 — factual NVIDIA capability inventory: verified local host is macOS arm64 with zero installed NVIDIA hardware, drivers, or SDKs; 20 registry capabilities remain documented/planned (D-009); local NVIDIA execution tools are absent; remote execution targets (D-014) and NVIDIA MCP servers are currently unconfigured. NVIDIA capabilities are currently known but unavailable until a compatible execution target is configured; ADR-0005 and ADR-0007 are unblocked.

## Blocking questions

Q1–Q5, Q7–Q8 are resolved. Q10 (dataset storage/versioning) remains open and blocks ADR-0009. Downstream implementation work is gated on Phase 1 ADR acceptance.

## Next session

1. Await Official PM review and merge of milestone promotion PR #18 (`dev-munna` -> `main`).
2. Draft ADR-0005 (tools / MCP boundary) using the resolved Q5 capability discovery contract.
