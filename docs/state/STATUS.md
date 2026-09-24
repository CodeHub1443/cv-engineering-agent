# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-24 · **Phase:** 0 → 1 (partial) → 2 (partial) → 3 (partial) →
4 (partial) → 6 (partial, execution planning) · **Health:** green

## Where we are

`main` is at `10fb89f` (PR #52 ADR-0002, #54 ADR-0005, #56 ADR-0006 all merged).
**Q16 is resolved (owner: SQLite) and the Experiment Ledger is implemented** on
`feature/claude/q16-sqlite-experiment-ledger` (issue #57), PR pending:
`cv_agent/experiments/` (ADR-0011) — `ExperimentRecord` (every `EXPERIMENTS.md`
schema field verbatim; `hardware`/`latency`/`memory` as nested value objects),
`ExperimentLedger` protocol, `SqliteExperimentLedger` in its own `experiments.sqlite`
file. Rule 1 enforced: upsertable while `proposed`/`running`, locked once terminal.
90 new tests, suite 772 → 862, `ruff`/`mypy cv_agent` clean. Not wired into
`CVAgent`/CLI — no training/evaluation subsystem exists to write real rows.

**Implemented:** LLM gateway w/ one real provider (ADR-0002), skill discovery/
resolution (ADR-0007), requirements analysis (ADR-0008), execution boundary (ADR-0009,
one real `ExecutionRuntime`), Tool/MCP boundary (ADR-0005, no real tool), Knowledge/
Context boundary (ADR-0006, in-memory only), **Experiment Ledger (ADR-0011, this
branch)**, orchestration + four interrupt kinds (ADR-0003, ADR-0010), project memory
(ADR-0004), approval integrity (ADR-0003 §10, #43), enforced CI.

**Still NOT implemented:** any real `ToolInvoker`/MCP client or research/acquisition,
a durable `KnowledgeStore` backend, bindings for 83 other skills, autonomous
training, multi-provider routing/fallback, call/spend-limit enforcement (Q6/Q19), a
persistent checkpointer (Q3), real-skill CLI reachability (Q23/#44), wiring
`cv_agent.experiments` into anything.

## In flight

| Item | Issue | State |
|---|---|---|
| Q16 SQLite Experiment Ledger (ADR-0011) | #57 | implemented, branch pushed; PR pending |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decision (Q23) |

## Next 3 actions

1. Owner reviews and merges the Q16 PR (#57).
2. Owner decisions on Q3 (durable checkpointer) and Q23 (CLI real-skill wiring) —
   separate, independent; neither is implied by Q16's answer.
3. Owner decides whether/when a first real `ToolInvoker`/acquisition mechanism or
   a training/evaluation subsystem (which would write real ledger rows) is built.

## Blockers

- Nothing blocked on engineering — every open item needs owner decision/review.

## Do not start yet

A real `ToolInvoker`/MCP client, real web-research/acquisition, a durable
`KnowledgeStore` backend, MCP vendor selection, autonomous training, a second LLM
provider/fallback, cost estimation, an unverified binding, a second
`ExecutionRuntime`/skill binding, unrestricted autonomous execution, merging the two
graphs, wiring `cv_agent.tools`/`knowledge`/`experiments` into `CVAgent`/`LangGraph`,
embeddings/vector search — `[P§34]`.
