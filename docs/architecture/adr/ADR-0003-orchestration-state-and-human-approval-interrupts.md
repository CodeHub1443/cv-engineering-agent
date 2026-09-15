# ADR-0003: Orchestration state + human-approval interrupts

- **Status:** Accepted (retroactive — same allowance ADR-0001/0007/0008/0009 used; no
  live GitHub issue tracker wired up yet)
- **Date:** 2026-09-15
- **Layer:** orchestration
- **Canon:** `[P§5]`, `[P§10]`, `[P§21]`, `[P§24]`, `[P§29.8]`, `[P§34]`
- **Supersedes / Superseded by:** —
- **Issue:** #TBD

## 1. Context

`docs/roadmap/ROADMAP.md` Phase 1 names this exact deliverable: "ADR-0003 orchestration
state + approval interrupts," with an unmet exit-test item (a run halts at an approval
gate, restarts, and resumes with the approval still pending). A repository alignment
review (this session, prior turn) identified it as the actual critical-path blocker:
`RequirementsAnalysis.clarification_questions` (ADR-0008) had nowhere to pause and wait
for a real answer, and `SkillExecutionRequest.approved` (ADR-0009) had no real gate
producing it — both were data models with no live consumer. `docs/PROJECT.md` §21 is
explicit that LangGraph "should manage... human approval... checkpoints" — this ADR is
that management, not a new subsystem.

Before designing anything, `cv_agent/graph/` (the existing `build_graph()` — a
`START -> initialize -> END` stub with a `MemorySaver` checkpointer), the existing
`AgentState`, `CVAgent`, the requirements-analysis and execution subsystems, and the
installed LangGraph version (1.2.11) were inspected directly. LangGraph 1.2.11 ships the
modern dynamic-interrupt API (`langgraph.types.interrupt()` + `Command(resume=...)`),
confirmed empirically: a node calling `interrupt(payload)` pauses the graph, the caller's
`invoke()` returns a dict containing `"__interrupt__": [Interrupt(value=payload, ...)]`,
and `graph.invoke(Command(resume=answer), config=...)` re-enters the same node with
`interrupt()` now returning `answer`, continuing execution with all prior state intact.
This is the mechanism used below — no custom sleep/polling loop.

### Resolving the blocking open questions

`docs/state/OPEN_QUESTIONS.md` Q1–Q3 explicitly block this ADR. Resolved here, to the
extent this ADR's scope requires:

- **Q3 (approval transport)** — **resolved for this ADR's scope.** The transport is a
  LangGraph interrupt: the graph pauses, and *something* (today: a direct
  `CVAgent.resume_workflow()` call — see §7 limitations) supplies the resume value.
  Whether that resume value can arrive *hours later, after a process restart* is a
  property of the **checkpointer**, not of the node/graph structure — `MemorySaver` is
  in-process only (confirmed: state does not survive process exit), but LangGraph's
  checkpointer interface is swappable (`SqliteSaver`, `PostgresSaver`, ...) without
  restructuring any node. This ADR builds the interrupt structure correctly and defers
  the durable-transport question (CLI prompt vs. queued/async approval) to whenever a
  persistent checkpointer is actually wired in — see §8.
- **Q1 (unit of a project)** — **not resolved, and not blocking.** This ADR's
  checkpointing is keyed by `session_id` (a single run), not by "project" — no project
  concept is needed for interrupt/resume to work correctly. Q1 remains a real blocker
  for ADR-0004 (project memory), unchanged.
- **Q2 (where does the agent/training run)** — **not resolved, and not blocking.**
  Nothing in this ADR executes training or submits remote jobs; the execution boundary
  (ADR-0009) already runs in-process with zero real runtimes registered. Q2 remains open
  for ADR-0010.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** the orchestration state shape for the requirements-clarification and
  approval-gated-execution workflow (`AgentState`'s new fields), and the graph topology
  that pauses for a human answer/decision and resumes correctly
  (`cv_agent.graph.workflow`).
- **This does NOT own:**
  - producing the requirements analysis itself → `RequirementsAnalyzer` (ADR-0008),
    called by a node, not reimplemented;
  - deciding whether execution is permitted once approved/rejected → `SkillExecutor`
    (ADR-0009), called by a node, not reimplemented — the approval-gate node reads a
    binding's `approval_policy` via `SkillExecutor.get_binding()` and interrupts if
    needed, but the actual allow/reject enforcement still happens inside
    `SkillExecutor.execute()`, so the two layers agree by construction, not by
    duplicated logic;
  - the actual UI/transport a human uses to answer (CLI prompt today; see §8) → not
    this ADR's concern, deliberately kept outside the graph;
  - persisting anything beyond one run's checkpoint (project memory, cross-session
    history) → ADR-0004, not written.
- **Why this responsibility does not belong to an existing component:** neither
  `RequirementsAnalyzer` nor `SkillExecutor` can own "pause and wait for a human," because
  both are plain synchronous callables usable outside any graph (and are exercised that
  way already — `CVAgent.analyze_requirements()`, `CVAgent.execute()`). Interrupt/resume
  is inherently an orchestration concern (`[P§21]`), which is why `docs/PROJECT.md` §21
  assigns "human approval... checkpoints" to LangGraph specifically.

## 3. Decision

Extend `AgentState` (kept as ONE TypedDict — no parallel state type) with six new
optional fields, grouped by concern:

- Requirements/clarification: `requirements_analysis: dict | None`,
  `clarification_answers: dict[str, str]`.
- Approval/execution: `pending_execution: dict | None`, `approval_decision: str | None`,
  `execution_result: dict | None`.
- (`pending_human_input`/`human_feedback` already existed, reserved since the Step-1
  scaffold; left as-is for a future node that only needs a single free-text answer.)

`requirements_analysis` and `execution_result` store `dataclasses.asdict()` of the
reasoning-layer dataclasses, not the dataclass instances themselves — deliberately, for
two reasons: (1) orchestration state stays a plain, serializable structure independent of
the reasoning layer's types (`[P§19]`/`[P§21]` separation — the graph should not import
`RequirementsAnalysis` as *its* type, only read a dict shaped like one); (2) LangGraph's
checkpoint serializer already warns that storing an unregistered arbitrary class
(confirmed empirically) will be **rejected in a future version** — dicts avoid that
entirely.

New graph: `cv_agent.graph.workflow.build_requirements_workflow_graph()`, a **second,
separate** compiled graph from `cv_agent.graph.builder.build_graph()`. Topology:

```
START -> initialize -> analyze_requirements
                            |
              (unanswered clarification questions,
               none answered yet this run?)
                  yes /         \ no
                     v           v
                 clarify    approval_gate
              (interrupt)        |
                     \      (pending_execution present AND
                      \      its binding requires approval?)
                       \        yes /        \ no / none pending
                        v          v          v
              analyze_requirements   execute   END
              (loop back once, now
               routes straight to
               approval_gate)              execute -> END
```

`clarify` and `approval_gate` are the only interrupt points, both using
`langgraph.types.interrupt()`. The loop back from `clarify` to `analyze_requirements`
happens **exactly once** — `_route_after_analysis` only routes to `clarify` when
`clarification_answers` is still empty, so a second pass through `analyze_requirements`
(even with unknowns remaining, if the human answered only some questions) always routes
to `approval_gate` instead. This is a deliberate, hard-coded loop bound to prevent an
infinite interrupt loop; it is not configurable in this ADR.

`CVAgent` gains `.start_workflow(task, *, session_id=None, pending_execution=None)`,
`.resume_workflow(session_id, resume_value)`, `.get_workflow_state(session_id)`
(inspect-only). `python -m cv_agent workflow "<task>"` demonstrates the clarification
round-trip end to end in one process.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Insert the new nodes into the existing `build_graph()`/`run()` topology instead of a second graph | Matches that module's own docstring ("later steps will insert nodes... without restructuring existing node contracts"); one graph, not two | `tests/test_graph.py` and `tests/test_agent.py` hard-assert the *exact* current topology (`status=="ready"`, exactly one `initialize` step) for **every** call to `run()`, including with a real task string — unconditionally inserting `analyze_requirements` etc. after `initialize` would change that behavior for calls those tests make, and instruction constraints for this work explicitly required all pre-existing tests to keep passing unmodified | Rejected for now; kept as two graphs with a named revisit trigger (§8) to merge once `run()` itself is ready to carry real reasoning nodes for every call, not just workflow-specific ones |
| Store `RequirementsAnalysis`/`SkillExecutionResult` dataclass instances directly in `AgentState` | Simpler node code (no `asdict()`/dict-indexing); confirmed empirically to actually work today | LangGraph's own checkpoint serializer prints "Deserializing unregistered type ... This will be blocked in a future version" for exactly this case (confirmed empirically) — silently relying on an explicitly-deprecating pickle fallback is not a foundation to build on; also couples orchestration state to reasoning-layer types (`[P§21]`) | Rejected; state stores plain dicts |
| Legacy static `interrupt_before=["clarify"]` compile-time interrupts instead of dynamic `interrupt()` | Simpler mental model, no in-node call | Cannot carry a structured payload (the actual questions) to the caller at the pause point, and resuming can't feed a value back into the paused node's own return — would need extra plumbing to reconstruct what's being asked; the dynamic API is what `docs/PROJECT.md`/ADR-0009 already anticipate (approval *decision*, not just a bare pause) | Rejected; dynamic `interrupt()` used throughout |
| Let the `execute` node decide approval itself (skip `approval_gate` as a separate node) | Fewer nodes | Would blur "is this even gated" with "pause and wait for the decision" into one node, and would make it harder to test the interrupt payload's shape independent of execution — also weakens the "interrupt/resume state must be the source of the decision" requirement's auditability (one node, one job) | Rejected; kept as two nodes, `approval_gate` then `execute` |

## 5. Interface

```python
# module: cv_agent.graph.state (additions to AgentState, TypedDict total=False)
requirements_analysis: Optional[dict[str, Any]]    # dataclasses.asdict(RequirementsAnalysis)
clarification_answers: dict[str, str]              # field_name -> human-supplied answer
pending_execution: Optional[dict[str, Any]]         # {"skill_id", "inputs", "task"} | None
approval_decision: Optional[str]                    # "approved" | "rejected" | "not_required" | None
execution_result: Optional[dict[str, Any]]          # dataclasses.asdict(SkillExecutionResult)

# module: cv_agent.graph.workflow
def build_requirements_workflow_graph(
    *,
    requirements_analyzer: RequirementsAnalyzer,
    executor: SkillExecutor,
    skill_inventory: SkillInventory,
    checkpointer: Any | None = None,
) -> Any: ...

# module: cv_agent.runtime.agent (additions to CVAgent)
def start_workflow(
    self, task: str, *, session_id: str | None = None,
    pending_execution: dict[str, Any] | None = None,
) -> AgentState: ...
def resume_workflow(self, session_id: str, resume_value: Any) -> AgentState: ...
def get_workflow_state(self, session_id: str) -> AgentState: ...
```

## 6. Consequences

- **Enables:** `RequirementsAnalysis.clarification_questions` and
  `SkillExecutionRequest.approved` are now both reachable through a real pause-and-wait
  mechanism instead of being dead-ended data models; `python -m cv_agent workflow`
  demonstrates it end to end.
- **Makes harder:** two compiled graphs now exist in the codebase instead of one, which
  is a real, acknowledged cost (see Alternatives) — a future session must not add a
  third without revisiting this decision.
- **Costs:** one new module (`cv_agent/graph/workflow.py`, ~250 lines), six new
  `AgentState` fields, three new `CVAgent` methods, no new dependency (LangGraph's
  interrupt API was already available in the installed version).
- **Migration / blast radius if reversed:** contained — `build_graph()`/`run()` are
  untouched (proven by a dedicated regression test); removing
  `cv_agent/graph/workflow.py` and the three new `CVAgent` methods would not affect
  `resolve()`, `analyze_requirements()`, or `execute()`, all of which remain plain
  synchronous calls usable with or without this graph.

## 7. Acceptance test

`tests/test_workflow.py` (graph pauses at clarification for a vague request, no
interrupt for a fully-specified one, state survives interruption, human answers are
incorporated into a re-run analysis, the graph reaches `status="done"` after resume,
the clarify loop fires at most once even with unknowns remaining, an empty resume
value fabricates nothing, an approval-required execution pauses with the runtime never
invoked before resume, approval permits execution, rejection prevents it — runtime
never called, an ambiguous/garbage resume value is treated as rejection not approval,
an `"allowed"`-policy binding executes with no interrupt at all, an unknown `skill_id`
in `pending_execution` fails safely as `not_executable`, no `pending_execution` skips
the execute node entirely) plus `CVAgent`-level integration tests (`start_workflow`,
`resume_workflow`, `get_workflow_state` is read-only, and — critically — `run()`/
`health_check()` behave identically to before this ADR). `tests/test_cli.py`'s
`workflow` command tests (demonstrates the interrupt+resume round trip; skips the
interrupt for a fully-specified request).

## 8. Revisit trigger

- When a persistent checkpointer (SQLite/Postgres) replaces `MemorySaver` — at that
  point Q3's "survive process restart" half becomes actually testable, and the CLI demo
  (currently necessarily single-process, see its own docstring) can become a genuine
  two-invocation demo.
- When `run()`'s own graph is ready to carry real reasoning nodes unconditionally (not
  just for an explicit workflow call) — at that point `build_graph()` and
  `build_requirements_workflow_graph()` should be reconciled into one topology, per the
  original Step-1 docstring's intent, rather than staying two graphs.
- When ADR-0004 (project memory) is written — `requirements_analysis` currently vanishes
  when a session's checkpoint is discarded; persisting it beyond one run's checkpoint is
  explicitly that ADR's job, not this one's.
