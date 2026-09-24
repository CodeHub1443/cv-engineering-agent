# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-24 · **Phase:** 0 → 1 (partial) → 2 (partial) → 3 (partial) →
4 (partial) → 5a (implemented, PR pending) · **Health:** green

## Where we are

`main` is at `44539c3` (PR #58, Q16 SQLite Experiment Ledger, ADR-0011, merged; CI green).

**Phase 5a — Dataset Core is implemented** on `feature/claude/dataset-core` (issue #59,
ADR-0012), PR pending owner review: `cv_agent/datasets/` (stdlib only) — immutable
`DatasetManifest` (the dataset version, `docs/DATA.md`'s fields, keyed
`(dataset_id, version)`), recorded splits, deterministic temporal / camera / subject /
annotation-round / supplied-hash near-duplicate leakage checks (a manifest cannot exist
with a failed check; the report is recorded in it), a storage-agnostic `DatasetStore`
protocol and `InMemoryDatasetStore`. 88 new tests, suite 862 → 950. **Q10 is not
decided** — no backend, no persistence format, no hash computation.

**Implemented:** LLM gateway w/ one real provider (ADR-0002), skill discovery/resolution
(ADR-0007), requirements analysis (ADR-0008), execution boundary + one real
`ExecutionRuntime` (ADR-0009), Tool/MCP boundary (ADR-0005, no real tool), Knowledge/
Context boundary (ADR-0006, in-memory), Experiment Ledger (ADR-0011), **Dataset Core
(ADR-0012)**, orchestration + four interrupt kinds (ADR-0003/0010), project memory
(ADR-0004), approval integrity (ADR-0003 §10), enforced CI.

**Still NOT implemented:** a dataset backend (Q10), any real `ToolInvoker`/MCP client or
acquisition, a durable `KnowledgeStore`, bindings for 83 other skills, training/baseline
execution, multi-provider routing, spend limits (Q6/Q19), a persistent checkpointer (Q3),
real-skill CLI reachability (Q23/#44), and wiring any new package into `CVAgent`.

## In flight

| Item | Issue | State |
|---|---|---|
| Phase 5a Dataset Core (ADR-0012) | #59 | implemented, branch pushed; PR pending |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decision (Q23) |

## Next 3 actions

1. Owner reviews and merges the Dataset Core PR (issue #59).
2. Owner decisions, each independent: Q2 (where runs execute), Q4 (real vs reference
   target), Q10 (dataset storage backend), Q5 (first real tool), Q6/Q19 (approval
   thresholds / cost estimation), Q3 (durable approvals), Q23 (CLI reachability).
3. Next milestone, once Q2/Q4 and a real execution mechanism are decided: Phase 5b —
   baseline establishment (first real ledger rows; the point to wire the ledger in).

## Blockers

- Nothing blocked on engineering — every open item needs owner decision/review.

## Do not start yet

A dataset backend (Q10), perceptual-hash computation, a real `ToolInvoker`/MCP client or
acquisition, a durable `KnowledgeStore`, autonomous training, baseline execution, a second
LLM provider, cost estimation, an unverified or second binding/`ExecutionRuntime`,
unrestricted autonomous execution, merging the two graphs, wiring any new package into
`CVAgent`/`LangGraph`, embeddings/vector search — `[P§34]`.
