# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-28 · **Phase:** 0 → 1 (partial) → 2 (partial) → 3 (partial) →
4 (partial) → 5a (complete) → 5b (decisions recorded, no baseline execution) ·
**Health:** green

## Where we are

`main` is at `e6cff6e` (PR #60: Phase 5a Dataset Core). Two docs-only PRs are open,
not yet merged: **#62** (Q2/Q4/Q5, D-040..D-042) and this session's **#64** (Q24/Q25/Q10,
the Job/Process Execution Boundary scope, a first-baseline cost/spend exception, and
the research-acquisition mechanism — D-043..D-048), branched from #62's tip since it
needs D-040. CI green on the merged commit; 950 tests as of `main`.

**Owner decisions recorded 2026-09-28 (issue #63, one new Proposed ADR):** Q24/D-043 —
reference project is Person Detection + Tracking; the Agent must research/select the
model, research/recommend the dataset, and propose metrics itself (never hardcoded).
Q25/D-044 — confirms Linux+NVIDIA GPU host, controller/workload as separate processes;
does not name a concrete machine and does not change D-040. Q10/D-045 — V1 dataset
backend is the local filesystem, behind the already-generic `DatasetStore` protocol
(ADR-0012 §9 appended, not rewritten). Job/Process Execution Boundary/D-046 — controlled
local subprocess jobs, no Kubernetes/distributed/remote in V1; new **ADR-0013**
(Proposed, scope only — no protocol design, no code). Q6/Q19/D-047 — the first V1
baseline is exempt from a pre-execution cost estimate (approval itself still required);
`docs/APPROVALS.md` gained a "Scoped exceptions" section. Research Acquisition/D-048 —
V1 mechanism is web research via an ADR-0005 `ToolInvoker` feeding ADR-0006's Knowledge
boundary, no MCP SDK (ADR-0005 §12 / ADR-0006 §10 appended). **No code changed this
session** — decisions and documentation only.

**Implemented:** LLM gateway w/ one real provider (ADR-0002), skill discovery/resolution
(ADR-0007), requirements analysis (ADR-0008), execution boundary + one real
`ExecutionRuntime` (ADR-0009), Tool/MCP boundary (ADR-0005), Knowledge/Context boundary
(ADR-0006), Experiment Ledger (ADR-0011), Dataset Core (ADR-0012), orchestration + four
interrupt kinds (ADR-0003/0010), project memory (ADR-0004), approval integrity
(ADR-0003 §10), enforced CI.

**Still NOT implemented:** a dataset backend (Q10 answered, module not built), any real
`ToolInvoker`/MCP client or research acquisition, a durable `KnowledgeStore`, bindings
for 83 other skills, the job/process execution boundary's actual protocol (ADR-0013 is
Proposed, not Accepted), training/baseline execution, multi-provider routing, spend
limits, a persistent checkpointer (Q3), real-skill CLI reachability (Q23), and wiring
any new package into `CVAgent`.

## In flight

| Item | Issue | State |
|---|---|---|
| Merge PR #62 (Q2/Q4/Q5) | #61 | docs-only PR pending owner review |
| Merge PR #64 (Q24/Q25/Q10/ADR-0013/Q6-Q19-exception/research mechanism) | #63 | docs-only PR pending owner review, stacked on #62 |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decision (Q23) |

## Next 3 actions

1. Owner merges #62, then #64 (in that order — #64 was branched from #62's tip).
2. A follow-up architect session resolves ADR-0013 §5's open protocol-shape questions
   (extend `ExecutionRuntime` vs. new protocol; approval-pin model for a long-running
   job; host-verification placement) and moves it from Proposed toward Accepted.
3. Once ADR-0013 is Accepted: implement the local-filesystem `DatasetStore` backend
   (D-045), the research-acquisition `ToolInvoker` (D-048), and bind one real
   `ExecutionRuntime` for the Person Detection + Tracking reference project — only then
   can a first baseline run and write a real `ExperimentRecord`.

## Blockers
- Nothing blocked on engineering — every open item needs owner review/merge or a
  dedicated architect-mode design session (ADR-0013).

## Do not start yet

Implementing the job runner, the dataset backend module, the research tool, the
evaluation subsystem, model selection, or any CV pipeline code; downloading models or
datasets; a durable `KnowledgeStore`; autonomous training; a second LLM provider; cost
estimation beyond D-047's narrow exception; merging the two graphs; wiring any new
package into `CVAgent`/`LangGraph`; embeddings/vector search — `[P§34]`.
