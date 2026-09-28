# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-28 · **Phase:** 0 → 1 (partial) → 2 (partial) → 3 (partial) →
4 (partial) → 5a (complete) → 5b (decisions + ADR-0013 accepted, no baseline yet) ·
**Health:** green

## Where we are

`main` now contains Phase 0–5a complete plus all Phase 5b decision records (D-043..D-048,
merged PR #62 + #64) and ADR-0013 has been moved from Proposed to **Accepted** with a
full design on branch `feature/claude/adr-0013-job-execution-design` (PR pending).

**ADR-0013 design decided (D-049, this session):** three open protocol-shape questions
are answered: (1) `JobRuntime` is a distinct sibling protocol — not an extension of
`ExecutionRuntime`; same `ExecutionBindingRegistry` for pin/binding, separate `job_runtimes`
dict; (2) approval-integrity: existing ADR-0003 §10 pin model applies unchanged — pin
captured at plan time, checked by `pin_mismatch()` at `start_job()` time, E1 rule
preserved; (3) host verification: new `HostVerifier` protocol in `cv_agent.execution.host`,
called by `JobExecutor.start_job()` before `runtime.start()`, mismatch → `host_mismatch`
terminal status. `SkillExecutor`/`ExecutionRuntime`/all existing callers are UNCHANGED.
No source code was modified this session — interface stubs and ADR only.

**Implemented:** LLM gateway w/ one real provider (ADR-0002), skill discovery/resolution
(ADR-0007), requirements analysis (ADR-0008), execution boundary + one real
`ExecutionRuntime` (ADR-0009), Tool/MCP boundary (ADR-0005), Knowledge/Context boundary
(ADR-0006), Experiment Ledger (ADR-0011), Dataset Core (ADR-0012), orchestration + four
interrupt kinds (ADR-0003/0010), project memory (ADR-0004), approval integrity
(ADR-0003 §10), enforced CI.

**Still NOT implemented:** `cv_agent.execution.jobs` subpackage (ADR-0013 Accepted,
stubs not yet committed), `cv_agent.execution.host` module, `LinuxNvidiaHostVerifier`,
a concrete `JobRuntime` for the reference project (ADR-0009 §8 per-skill verification
still required), a dataset backend (Q10/D-045 answered, module not built), any real
`ToolInvoker` for research acquisition (D-048), a durable `KnowledgeStore`, bindings
for 83 other skills, training/baseline execution, multi-provider routing, spend limits,
a persistent checkpointer (Q3), real-skill CLI reachability (Q23), `AgentState`
`pending_job`/`job_approval_decision`/`active_job_handle`/`job_result` fields, graph
nodes for job workflow, wiring new packages into `CVAgent`.

## In flight

| Item | Issue | State |
|---|---|---|
| ADR-0013 full design + D-049 | #65 | PR open on branch `feature/claude/adr-0013-job-execution-design`; no code change |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decision (Q23) |

## Next 3 actions

1. Owner merges ADR-0013 design PR (docs/ADR only — no code change, CI green).
2. Implement ADR-0013 protocol stubs: `cv_agent/execution/host.py`, `cv_agent/execution/jobs/`
   subpackage (models, runtime Protocol, executor) — per-skill verification still needed
   before any concrete runtime is considered working.
3. Implement `LinuxNvidiaHostVerifier` + first `JobRuntime` for the Person Detection +
   Tracking reference project (individually verified per ADR-0009 §8, same precedent as
   D-014's `trt-perf-analysis`).

## Blockers

- Nothing blocked on engineering — every next step follows from ADR-0013 (Accepted).
- Q3 (restart-survivable checkpointer) remains open but does not block the first baseline.

## Do not start yet

Training, NAS, or optimization runs; cost estimation beyond D-047; a second LLM provider;
merging the two graphs; embeddings/vector search; downloading models or datasets; a
durable `KnowledgeStore`; multi-provider routing — `[P§34]`.
