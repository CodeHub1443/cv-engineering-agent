# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-15 · **Phase:** 0 → 1 (partial) → 3 (partial) → 4 (partial) ·
**Health:** green

## Where we are

Doc consistency pass complete (D-006–D-009). `docs/PROJECT.md` is frozen canon.

**Implemented:** Skill discovery + resolution (ADR-0007), requirements analysis +
task decomposition (ADR-0008), skill execution boundary (ADR-0009, zero bindings
registered — see below). **Orchestration state + human-approval interrupts
(ADR-0003, this session):** `cv_agent/graph/workflow.py` — a real LangGraph
interrupt/resume graph (`interrupt()`/`Command(resume=...)`, not polling) pauses for
requirements-clarification (re-analyzes with the human's answer) and approval-gated
execution (resumes with the decision as the source of truth before `SkillExecutor`
may run). `CVAgent.start_workflow()`/`.resume_workflow()`/`.get_workflow_state()`;
CLI `workflow`. Kept as a **second** graph, separate from the existing
`build_graph()`/`run()` stub (unchanged, regression-tested) — see ADR-0003 §4/§8.

**Still NOT implemented:** any real execution binding (ADR-0009 §5, `0/84`), project
memory (no ADR-0004 — `requirements_analysis` vanishes when a checkpoint is
discarded; `MemorySaver` doesn't survive a restart, Q3's durability half deferred),
RAG, MCP, research subsystem, autonomous training, optimization/deployment/
monitoring, an LLM/semantic resolver. Every capability in
`spec/capability_registry.json` is still `status: "planned"`.

## In flight

| Item | Issue | State |
|---|---|---|
| GitHub scaffolding (labels, templates, CI, milestones) | #— | not started |
| ADR-0001 capability model — seed written, needs review | #— | proposed |
| ADR-0003 orchestration state + approval interrupts | #— | accepted (retroactive) |
| ADR-0007/0008/0009 | #— | accepted (retroactive) |
| First real `ExecutionRuntime` adapter | #— | not started |
| ADR-0004 project memory | #— | not started |

## Next 3 actions

1. ADR-0004 project memory — persist `RequirementsAnalysis` beyond one run's
   checkpoint; resolves `OPEN_QUESTIONS.md` Q1 as a prerequisite.
2. Verify one real skill end-to-end (candidate: `trt-perf-analysis`'s
   `scripts/run.sh`) and register the first genuinely-verified binding.
3. Human review of `CLAUDE.md`, `docs/architecture/OVERVIEW.md`, ADR-0003/0007/0008/0009.

## Blockers

- `OPEN_QUESTIONS.md` Q1 blocks ADR-0004; Q3's durable-transport half blocks a
  restart-survivable approval flow (needs a persistent checkpointer).

## Do not start yet

RAG, MCP, real LLM providers, autonomous training, registering an unverified binding,
unrestricted autonomous execution, merging the two graphs before `run()` needs it —
`[P§34]`.
