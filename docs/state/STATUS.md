# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-24 · **Phase:** 0 → 1 (partial) → 2 (partial) → 3 (partial) →
4 (partial) → 5a (complete) → 5b (prepared, not started) · **Health:** green

## Where we are

`main` is at `e6cff6e` (PR #60: Phase 5a Dataset Core, ADR-0012; before it PR #58: Q16
Experiment Ledger, ADR-0011). CI green, 950 tests.

**Owner decisions recorded 2026-09-24 (issue #61, no ADR — not architectural):**
Q2/D-040 — V1 runs on a local Linux/NVIDIA GPU host; Agent/controller and CV workloads
are separate processes (controlled jobs). Q4/D-041 — V1 validates on a controlled
reference CV project before any customer project. Q5/D-042 — V1 uses the existing
Skill/CLI mechanism behind the `ToolInvoker`/execution boundaries; MCP SDK deferred,
transport-agnostic. None decides cloud/remote/scheduler, a customer project, MCP,
thresholds or any binding. New: Q24 (which reference project), Q25 (which host/GPU).

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
| Record Q2/Q4/Q5 decisions (D-040..D-042) | #61 | docs-only PR pending owner review |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decision (Q23) |

## Next 3 actions

1. Owner reviews and merges the Q2/Q4/Q5 decision-record PR (issue #61).
2. Owner decisions that gate Phase 5b: Q24 (name the reference project), Q25 (name the
   host/GPU and controller topology); plus Q6/Q19 if the baseline includes a training or
   otherwise gated run, and Q10 if the dataset needs a durable store.
3. Phase 5b — baseline establishment: first needs an ADR for the job/execution boundary
   and one individually verified Skill/CLI mechanism (ADR-0009 binding or ADR-0005
   `ToolInvoker`); it produces the first real ledger rows.

## Blockers
- Nothing blocked on engineering — every open item needs owner decision/review.

## Do not start yet

A dataset backend (Q10), perceptual-hash computation, a real `ToolInvoker`/MCP client or
acquisition, a durable `KnowledgeStore`, autonomous training, baseline execution, a second
LLM provider, cost estimation, an unverified or second binding/`ExecutionRuntime`,
unrestricted autonomous execution, merging the two graphs, wiring any new package into
`CVAgent`/`LangGraph`, embeddings/vector search — `[P§34]`.
