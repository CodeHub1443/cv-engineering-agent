# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-28 · **Phase:** 0 → 1 (partial) → 2 (partial) → 3 (partial) →
4 (partial) → 5a (complete) → 5b (decisions + ADR-0013 accepted + job foundation + workflow integration PR open) ·
**Health:** green

## Where we are

ADR-0013 is fully implemented through the workflow layer:
- `cv_agent/execution/host.py` — `HostVerifier`, `LinuxNvidiaHostVerifier` (PR #67, merged)
- `cv_agent/execution/jobs/` — `JobRuntime`, `JobExecutor`, `LinuxNvidiaJobRuntime` (PR #67, merged)
- `cv_agent/graph/state.py` — `pending_job`, `job_approval_decision`, `active_job_handle`, `job_result` fields (this PR, open)
- `cv_agent/graph/workflow.py` — `build_job_workflow_graph()` + four graph nodes (this PR, open)
- `cv_agent/runtime/agent.py` — `CVAgent(job_executor=...)`, `start_job_workflow()`, `resume_job_workflow()` (this PR, open)

**Job workflow integration complete:** The graph can represent a CV job request through the full approval/pin integrity path. `_node_start_job` passes the exact approved `job_execution_pin` to `JobExecutor.start_job()`. E1 rule preserved. Host verification inside `JobExecutor`. No direct runtime invocation from graph nodes. `SkillExecutor`/`ExecutionRuntime`/existing workflow graph unchanged.

## In flight

| Item | Issue | State |
|---|---|---|
| ADR-0013 workflow integration | #67 (follow-on) | PR open on `feature/claude/adr-0013-workflow-integration`; 1048/1048 tests pass |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decision (Q23) |

## Next 3 actions

1. Owner merges workflow-integration PR.
2. Register a real CV skill binding (individually verified per ADR-0009 §8 — same precedent as D-014's `trt-perf-analysis`).
3. Establish the first baseline run (person detection + tracking, zero-shot inference, `ExperimentRecord` with `baseline_id="SELF"`).

## Blockers

- Q10 (dataset storage backend) still open — blocks first real baseline.
- Q3 (restart-survivable checkpointer) remains open but does not block the first baseline.

## Do not start yet

Training, NAS, or optimization runs; cost estimation beyond D-047; a second LLM provider;
merging the two graphs; embeddings/vector search; downloading models or datasets; a
durable `KnowledgeStore`; multi-provider routing — `[P§34]`.
