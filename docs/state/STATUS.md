# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-28 · **Phase:** 0 → 1 (partial) → 2 (partial) → 3 (partial) →
4 (partial) → 5a (complete) → 5b (decisions + ADR-0013 complete + second real binding PR open) ·
**Health:** green

## Where we are

ADR-0013 is fully implemented and merged (PR #68, main). Second real CV skill binding open in PR:
- `cv_agent/execution/jobs/` — `JobRuntime`, `JobExecutor`, `LinuxNvidiaJobRuntime` (merged)
- `cv_agent/graph/workflow.py` — `build_job_workflow_graph()` + four graph nodes (merged)
- `cv_agent/runtime/agent.py` — `CVAgent(job_executor=...)` (merged)
- `cv_agent/execution/runtimes/deepstream_validate_pipeline.py` — second verified binding (this PR, open)

**Second binding (D-050):** `deepstream-generate-pipeline` skill's `scripts/validate_pipeline.py`
bound to `LinuxNvidiaJobRuntime`. Verified by personal inspection (777 lines, stdlib-only,
read-only validation). `approval_policy="allowed"`. `resolve_command(skill, pipeline_str)`
builds the subprocess command. 28 new tests (1076 total), ruff + mypy clean.

## In flight

| Item | Issue | State |
|---|---|---|
| Second real binding (deepstream-generate-pipeline) | — | PR open on `feature/claude/adr-0009-second-binding`; 1076/1076 tests pass |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decision (Q23) |

## Next 3 actions

1. Owner merges second binding PR.
2. Wire `ExperimentRecord` from `JobResult` + `CVAgent` dataset/experiment attrs (D-020 wiring pattern).
3. Establish the first baseline run (person detection + tracking, zero-shot inference, `baseline_id="SELF"`).

## Blockers

- Q3 (restart-survivable checkpointer) remains open but does not block the first baseline.

## Do not start yet

Training, NAS, or optimization runs; cost estimation beyond D-047; a second LLM provider;
merging the two graphs; embeddings/vector search; downloading models or datasets; a
durable `KnowledgeStore`; multi-provider routing — `[P§34]`.
