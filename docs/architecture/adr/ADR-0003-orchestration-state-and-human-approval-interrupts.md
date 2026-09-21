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
is *intended* to happen **exactly once** per run — a deliberate, hard-coded loop bound
to prevent an infinite interrupt loop, not configurable in this ADR.

**Correction (§9, 2026-09-19 — Q21):** this section originally stated the bound was
enforced by `_route_after_analysis` routing to `clarify` only while `clarification_answers`
is still empty. That claim was wrong for exactly the case it was meant to cover: a human
declining *every* question resumes with an empty answers value, which is indistinguishable
by truthiness from "never asked" — the graph re-raised `clarify` indefinitely instead of
routing to `approval_gate`. Confirmed empirically, not theoretical. See §9 for the actual
fix; the loop bound is now an explicit `clarification_attempted` flag, not
`clarification_answers`' emptiness.

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

## 9. Status — clarification loop-bound fix (Q21)

Found while implementing #34 (real CLI input handling, `docs/state/OPEN_QUESTIONS.md`
Q21, filed 2026-09-18): `_route_after_analysis`'s loop bound (§3) was implemented as
`bool(state.get("clarification_answers"))` — truthiness, not "was `clarify` already
attempted this run." A human declining *every* clarification question resumes with an
empty answers value; `clarification_answers` stays falsy, indistinguishable from "never
asked," and the graph re-raised `clarify` indefinitely. Confirmed empirically via direct
graph invocation (not synthesized): five consecutive `Command(resume={})` calls left the
run interrupted every time.

A second, independent, transport-level gap was confirmed in the same investigation:
`Command(resume={})` (a literal empty dict) is not delivered to `clarify` at all — the
graph silently re-pauses without `_node_clarify`'s body ever running (`steps` gains no
new entry). `Command(resume="")` (a non-dict falsy value) *is* delivered correctly. This
is the same LangGraph `Command(resume=...)` characteristic ADR-0010 §13 already documented
for `provide_execution_inputs`, now confirmed for `clarify` too — not a coincidence, the
same LangGraph mechanism underlies both interrupts.

**Fix (both, one PR, not a broadened contract):**
1. New `AgentState` field `clarification_attempted: bool` (`cv_agent/graph/state.py`),
   set unconditionally by `_node_clarify` on every resume — mirrors
   `execution_input_recovery["attempted"]`'s existing pattern (§13 of ADR-0010) rather
   than inventing a new one. `_route_after_analysis` routes on this flag, never on
   `clarification_answers`' truthiness. `CVAgent.start_workflow()` initializes it to
   `False`.
2. `cv_agent/__main__.py`'s `_resume_value_for_interrupt` resumes with `""`, never `{}`,
   when every clarification question is declined — the existing `provide_execution_inputs`
   convention, now applied symmetrically to `clarify`.

No interrupt payload shape changed, no resume-value contract changed, no new interrupt
kind — `AgentState` gains one additive, optional field. Verified in advance (before
implementing) by monkeypatching the routing predicate against the real graph: reaches
`status == "done"` in exactly one `clarify` round when every question is declined; valid/
partial-answer paths are unaffected (existing tests pass unmodified). Manually verified
end to end against the real CLI post-fix: `python -m cv_agent workflow "..."` with stdin
closed now exits 0 with `Final status: done`, one `[INTERRUPT] clarification`, never
`WorkflowStuckError`.

`_MAX_INTERRUPT_ROUNDS` (`cv_agent/__main__.py`, introduced by #34 as a CLI-only
mitigation before this fix existed) is kept as defense-in-depth, not as the fix — the
graph itself is now bounded to at most three interrupts per run (clarify,
provide_execution_inputs, approval_gate, each at most once), deterministically.

**Tests:** `tests/test_workflow.py` — declining every question interrupts exactly once
and reaches `status == "done"` with unknowns still genuinely unknown
(`test_declining_every_question_does_not_repeat_the_interrupt`); a literal `{}` resume
is pinned as non-delivering (`test_literal_empty_dict_resume_does_not_clear_the_clarify_interrupt`);
the pre-existing empty-resume test now resumes with `""` and asserts the interrupt
actually clears, not just that the answers dict looks right
(`test_empty_resume_value_produces_no_fabricated_answers`, corrected — the prior version
resumed with `{}` and only checked `clarification_answers`, which passed even under
total non-delivery because that's the field's own pre-clarify default). `tests/test_cli.py`
— the CLI's decline-everything path now asserts exit 0 and clean completion, replacing
the version that asserted `WorkflowStuckError`/exit 3 as the (then-)expected outcome.

## 10. Proposed amendment — approval integrity (issue #43, Q22)

> **Status of this section: IMPLEMENTED (issue #43, branch `fix/claude/43-approval-integrity`),
> pending PR review and merge.** Approved by the owner 2026-09-21 with clarifications A1-A3
> (resolved in 10.14); deviations from the approved text are listed in 10.15.
> `[P§24]`, `[P§29.8]`, `[P§34]`, `[P§35]`.
> Owner decisions applied (2026-09-21): **D1** ADR-0003 owns the approval/execution
> contract, ADR-0009 §14 holds the executor-side interface, ADR-0010 §17 the
> description-pinning extension, no ADR-0011; **D2** adopt the runtime-generation token;
> **D4** strict description pinning through input recovery, fail closed; **D5′** the
> existing `ExecutionError(category, message)` with one added category
> `binding_mismatch`, no new `AgentState` field; **D6** approval-required direct callers
> must supply a valid pin, `approved=True` never bypasses integrity; **D7**
> `approval_decision=None` for a missing or malformed pin, `not_required` only when no
> binding existed at capture. Revision 3 — replaces revisions 1 and 2 in full.

### 10.1 Context — the reproduced defect and what code inspection established

`pending_execution` pins only `skill_id`. Between the human being shown an approval
request and the skill running, the graph re-resolves the binding live by `skill_id` in
two places (`_node_approval_gate`, `SkillExecutor.execute()`) and nothing compares the
result with what the human was shown. Reproduced on `main` `3230361` and pre-Q18
`752bc1c` (issue #43, scenarios A–D):

| | Replacement policy | Decision | Recorded | Result | Replacement ran |
|---|---|---|---|---|---|
| A | `approval_required` | approved | `approved` | `completed` | yes |
| B | `approval_required` | rejected | `rejected` | `rejected` | no |
| C | `allowed` | rejected | `not_required` | `completed` | **yes — rejection overridden** |
| D | `allowed` | approved | `not_required` | `completed` | yes |

Facts established by reading the code, each relied on below:

1. **Two mechanisms.** (i) Nothing compares the executing binding with the approved one
   (A, D). (ii) `_node_approval_gate` calls `executor.get_binding()` *before*
   `interrupt()`; LangGraph re-runs that on resume, and a replacement whose policy is not
   `approval_required` returns `not_required` before the recorded decision is read (C).
2. **Rejection lives only in the executor, keyed to the live policy.**
   `_route_after_approval` sends every non-`None` `pending_execution` to `execute`;
   `_node_execute` computes `approved = decision in ("approved", "not_required")` and
   calls the executor, whose only refusal is `approval_required and not request.approved`.
   A live policy of `allowed` executes after a recorded `rejected`.
3. **`approval_decision` has one writer**, `_node_approval_gate`; `start_workflow()`
   initializes it to `None`; the gate runs at most once per run; `execute → END` is the
   only edge out of `execute`, so nothing after execution can re-plan or re-ask.
4. **`SkillExecutor.execute()` has two production callers**: `_node_execute` and
   `CVAgent.execute()` → `python -m cv_agent execute`. Plus three test call sites passing
   `approved=True` (`tests/test_execution.py:214,250`;
   `tests/test_execution_trt_perf_analysis.py:417`).
5. **The direct CLI path does have a pause.** `_cmd_execute` reads the binding, then
   `_confirm_approval()` blocks on `input()`, then `agent.execute()` re-reads the
   registry. Issue #43's out-of-scope note describes this path as having "no pause between
   approval and execution" (ADR-0009 §10 itself only describes the command and its approval
   handling and makes no such claim); that description is inaccurate. It is not exploitable
   today (single-threaded, fresh registry) but is not a sound exemption.
6. **The registry has no removal API** (`register_binding`, `register_runtime`, getters,
   listers only). A binding or runtime can be added or *replaced*; it cannot be
   deregistered except by mutating the private dicts.

### 10.2 Lifecycle

```
PLAN → SNAPSHOT → APPROVAL REQUEST → RECORDED DECISION → INTEGRITY VALIDATION → OUTCOME
```

1. **Plan.** `plan_execution()` / recovery / a caller-supplied plan yields
   `pending_execution = {skill_id, inputs, task}` (unchanged).
2. **Immutable execution snapshot.** In the *same* `_node_plan_execution` update that
   writes a non-`None` `pending_execution`, the node writes `pending_execution["execution_pin"]`
   from `ExecutionBindingRegistry.pin(skill_id)` (10.4, ADR-0009 §14), once. "Immutable"
   is a rule, not a type: `_node_plan_execution` is the only writer of `pending_execution`
   (one write site), writes the pin exactly once with the plan, and no other node or later
   visit re-captures or edits it.
3. **Approval request.** `_node_approval_gate` decides **from the pin only** and reads the
   live registry never (replay safety, ADR-0010 §13/§16). Outcomes: 10.5 table.
4. **Recorded decision.** The interrupt's resume value (`approved`, anything else →
   `rejected`) is written to `approval_decision` by the gate, the sole writer.
5. **Integrity validation.** `_node_execute` runs the ordered checks of 10.6; the
   executor then compares the pin against its own single registry read (10.7).
6. **Outcome.** Execute, or a terminal result. Always `status="done"`. Topology, node set
   and interrupt count (at most three, §9) are unchanged.

### 10.3 Three pin states — the definitions everything else uses

`pending_execution["execution_pin"]` is in exactly one of three states, distinguished by
*key presence* and *value*, never by truthiness:

| State | Test | Meaning | Can it arise? |
|---|---|---|---|
| **Missing** | key `"execution_pin"` not in `pending_execution` | never pinned | only by bypassing `_node_plan_execution` (hand-built state, direct node call) |
| **Explicit `None`** | key present, value `None` | *no binding was registered for `skill_id` at capture*, so nothing can execute | only the caller-supplied `pending_execution` path (a planned skill always has a binding) |
| **Present** | key present, value not `None` | a pin | always on a planned/recovered plan |

A *present* pin is **well-formed** or **malformed** per 10.4. Malformed includes a
non-dict value, any missing/extra key, wrong types, or `binding.skill_id !=
pending_execution["skill_id"]`. Missing and malformed are both "unusable pin": the
human cannot be shown a verified snapshot, so neither may reach an approval interrupt or
an execution. Explicit `None` is *not* unusable — it is a truthful "nothing to run".

**Direct-execution path.** `SkillExecutionRequest.expected_binding_pin` has only two
inputs: `None` (default) means **not supplied**, a dict means **supplied**. The request
cannot express "explicit `None`" — the graph resolves that state itself and never calls
the executor for it (10.5). Direct callers: not supplied / well-formed / malformed, per
the executor column of 10.5.

### 10.4 Canonical snapshot and equality (no reliance on object equality)

`ExecutionBinding.pin() -> dict` returns exactly:

```python
{
  "skill_id": str, "binding_id": str, "runtime_id": str,
  "approval_policy": "allowed" | "approval_required" | "rejected",
  "verified": bool, "description": str,
  "input_schema":       [ {"name": str, "required": bool,
                           "description": str, "default": <JSON-native>} , ... ],
  "input_field_groups": [ {"kind": str, "field_names": [str, ...],
                           "description": str} , ... ],
}
```

- **Built by explicit field access**, not `dataclasses.asdict` and not `repr`/`pickle`:
  each key above is read by name; tuples become lists; nothing is derived from object
  identity or default serialization behavior.
- **Order is significant** and preserved as declared: `input_schema` order, group order and
  each group's `field_names` order. A reordering is a mismatch (strict, consistent with
  strict description pinning).
- **`default` must be JSON-native** (`None`, `bool`, `int`, finite `float`, `str`, and
  lists/dicts of these with `str` keys). This is validated **at the pin boundary** (A3):
  `pin()` raises `ValueError` otherwise, and `ExecutionBinding`/`InputField` construction
  is unchanged, so declaring or registering such a binding still works. A binding that
  cannot be pinned fails closed when the workflow tries to pin it: the graph stores a
  deliberately malformed marker, so it surfaces as `execution_pin_malformed` — never
  shown to a human for approval, never run. (Evidence: no binding in `cv_agent` sets a
  non-`None` default; a non-msgpack-serializable default such as `object()` already
  crashes `planning_result` checkpointing, independent of #43.)
- **Equality is canonical-JSON equality**, defined as
  `json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False)` on each value.
  It is type-sensitive (`1`, `1.0`, `true` differ), independent of dict key order and of
  list-vs-tuple container type (so a checkpoint round-trip cannot create a false
  mismatch), and never calls `==` on arbitrary objects.
- **Well-formedness** is a strict schema check on the same shape: `execution_pin` is a
  dict with exactly the keys `binding` and `runtime_generation`; `binding` is a dict with
  exactly the eight keys above with the listed types; every `input_schema` /
  `input_field_groups` entry has exactly its keys; `runtime_generation` is an `int ≥ 1`
  (not `bool`) or `None`. No extra keys.
- **`pin_mismatch(expected, live)`** compares per top-level key and returns sorted codes:
  `binding.<key>` for each differing `binding` key, and `runtime_registration` when
  `runtime_generation` differs. `()` means equal. A malformed `expected` returns
  `("execution_pin_malformed",)`.

### 10.5 Reconciled outcome table (the single authoritative statement)

Every other section, the ADR-0009 §14 executor order, and the acceptance tests defer to
this table. Columns: **graph** = what `_node_approval_gate` / `_node_execute` do;
**direct** = `SkillExecutor.execute()` called by any non-graph caller. `G` = result built
by `_node_execute` without invoking the executor; `E` = result built by the executor.

| # | Situation | `approval_decision` | Graph | Direct |
|---|---|---|---|---|
| 1 | **Recorded `rejected`** (any pin state, any live registry) | `rejected` | G: `rejected` / `approval_denied`. Executor **not** called; pin not validated; registry not read. | n/a (no recorded decision; `approved=False` → existing `approval_denied`) |
| 2 | **Pin key missing** | `None` (D7) | Gate: no interrupt. G: `not_executable` / `binding_mismatch`, `execution_pin_missing`. | n/a (`None` = not supplied, row 8) |
| 3 | **Pin malformed** | `None` (D7) | Gate: no interrupt. G: `not_executable` / `binding_mismatch`, `execution_pin_malformed`. | E: `not_executable` / `binding_mismatch`, `execution_pin_malformed` — for **every** policy; a supplied-but-invalid pin is never ignored |
| 4 | **Explicit `None`** (no binding at capture) | `not_required` (D7) | Gate: no interrupt. G: `not_executable` / `no_binding`; executor not called, **even if a binding was registered afterwards** ("a binding registered after capture was never approved"). | not expressible (request `None` = not supplied) |
| 5 | **Well-formed pin, decision inconsistent with pinned policy** — allowed set is: pinned `approval_required` ⇒ only `approved`; any other pinned policy ⇒ only `not_required`; `None` counts as inconsistent | as found, never rewritten | G: `not_executable` / `binding_mismatch`, `approval_decision_inconsistent`. (Unreachable through the gate; a fail-closed guard against hand-built or corrupted state — it stops a stray `not_required` from running an approval-required pin.) | n/a |
| 6 | **Well-formed pin, live differs**: `binding_id`, `runtime_id`, `approval_policy` (incl. same-`binding_id` flip, either direction), `verified`, `description`, `input_schema`, `input_field_groups`, or `runtime_generation` (10.8) | as recorded | E: `not_executable` / `binding_mismatch`, `"integrity check failed: <codes>"`; runtime never invoked | same E |
| 7 | **Well-formed pin, live identical** (incl. identical re-registration; another skill's binding replaced) | as recorded | E: proceeds to the existing verified / policy / runtime / `invoke` path | same |
| 8 | **Not supplied** (`expected_binding_pin is None`) | n/a | never happens (the graph passes the pin or resolves rows 1–5 itself) | approval-required live binding → E: `rejected` / `approval_denied`, "approval is not bound to an execution snapshot", **regardless of `approved`** (D6/E1); `allowed` or `rejected` policy → today's behavior unchanged |
| 9 | **Binding removed after capture** (private-dict mutation only; no removal API) | as recorded | E: `no_binding` (existing) | same |

For every `G` row and every `E` `not_executable`/`rejected` result the graph also sets
`planning_result["plan"] = None` (when a `planning_result` exists) and keeps
`pending_execution` as the record of what was approved. Every row is terminal; row 6
`approval_decision` may read `approved` while `execution_result.status` reads
`not_executable` — "approved, but the approved thing was not what would have run."

Message format for `binding_mismatch`: `"integrity check failed: <code>[, <code>…]"`,
codes sorted. `ExecutionErrorCategory` gains exactly one value, `"binding_mismatch"` (D5′);
none of `no_binding` / `binding_not_verified` / `approval_denied` / `runtime_error`
describes "what would run is not what was approved", and it matches the
`binding_mismatch` vocabulary ADR-0010 §13 already uses. No `AgentState` field is added:
`execution_result` already carries `error.category`/`error.message`, and execution has no
existing per-attempt record for a `mismatch_detail` to extend (unlike
`execution_input_recovery`/`candidate_selection`).

**Gate behavior (rows 2–4 and the normal case).** `pin` missing or malformed → no
interrupt, `approval_decision` untouched (`None`); explicit `None` → `not_required`;
well-formed with pinned policy `approval_required` → `interrupt()` with a payload built
from the pin (`skill_id`, `binding_id`, plus new `runtime_id`, `description`, `task`,
`inputs`); well-formed otherwise → `not_required`.

### 10.6 `_node_execute` — ordered checks (rejection first)

1. `approval_decision == "rejected"` → row 1. **Nothing below runs**: no pin validation, no
   registry read, no executor call. A binding, policy or runtime change cannot reach this
   branch because it consults no registry state; and an integrity failure cannot replace
   it because integrity is checked only afterwards.
2. pin key missing → row 2.
3. pin `None` → row 4.
4. pin malformed → row 3.
5. decision inconsistent with pinned policy → row 5.
6. Otherwise call the executor with `expected_binding_pin=pin` and
   `approved = (decision == "approved")`; map its result (rows 6, 7, 9).

### 10.7 Direct callers and the executor invariant (D6)

**Invariant E1 — an absent pin can never authorize an approval-required execution.**
`SkillExecutor.execute()` enforces it because it is the one choke point both production
callers share: live `approval_policy == "approval_required"` and `expected_binding_pin is
None` ⇒ `rejected` / `approval_denied`, even if `request.approved is True`. So `None`
means only "no snapshot to compare" and is honored solely where there is no approval
concept (`allowed`, or `rejected`-policy which refuses anyway). Executor order:
ADR-0009 §14.

`python -m cv_agent execute` for an `approval_required` binding captures
`registry.pin(skill_id)` from the same binding it displays, **before**
`_confirm_approval()`, and passes it; `--approve` and the interactive prompt are
therefore both bound to what the human saw. `CVAgent.execute()` is a pass-through.
The three existing `approved=True` test call sites must supply a pin if they target an
`approval_required` binding (checked at implementation time).

### 10.8 Runtime generation token (D2) — capture, check, and limits

**Evidence.** `register_runtime()` was an unconditional `self._runtimes[runtime_id] =
runtime`; no generation, token, version or fingerprint exists anywhere in
`cv_agent/execution`; runtimes are plain mutable classes; there is no removal API.
`runtime_id` alone proves only that the binding still *names* the same runtime, not that
the object is the same — this contract does not claim otherwise.

**Mechanism.** The registry stores each runtime as one tuple `(runtime, generation)` in
its existing dict, replaced by a single assignment. `register_runtime(r)`: no prior entry
→ generation `1`; prior entry whose object `is r` → generation unchanged (identical
re-registration is not a mismatch); otherwise → prior generation + 1 (a replacement,
including A→B→A, always differs). `get_runtime()` / `list_runtimes()` keep their
signatures. New inspect-only `get_runtime_registration(runtime_id) -> (runtime,
generation) | None` returns instance and generation from **one** dict read.

**Capture.** `registry.pin(skill_id)` reads the binding, then registration once:
`runtime_generation = generation` if the binding's `runtime_id` is registered, else
`None`.

**Check.** The executor reads the binding, then registration once, compares generation
(and the binding) via `pin_mismatch`, and — using *those same locals* — invokes that
tuple's `runtime`. The instance invoked is therefore the instance whose generation was
compared, by construction rather than by two lookups agreeing.

| Pinned `runtime_generation` | Live at execution | Result |
|---|---|---|
| `None` (runtime not registered at capture) | still unregistered | no mismatch; existing unregistered-runtime `no_binding` |
| `None` | registered before execution (gen ≥ 1) | `runtime_registration` mismatch — a runtime that appeared after capture was never approved |
| `n` | same object still registered (also after identical re-registration) | equal |
| `n` | replaced by a different object (gen > n) | `runtime_registration` mismatch |
| `n` | registry entry gone (private mutation only) | `runtime_registration` mismatch |

**Limitations — stated, not hidden.**
1. **In-place mutation.** Mutating the *same* registered object (monkeypatching `invoke`,
   changing its state, reassigning its `runtime_id` attribute) is invisible to any
   registry-level design. The token attests *which object is registered*, not what it does.
2. **Process restart.** Generations are process-local counters that reset on restart.
   Pins live in the `MemorySaver` checkpoint, which has the same lifetime, so they are
   consistent today; a pin restored into a process with different generations fails
   closed (the safe direction). Making pins durable belongs to Q3 and is not addressed or
   changed here.
3. **Thread safety.** `ExecutionBindingRegistry` is not thread-safe and this design does
   not make it so. The single-dict-read pairing gives instance/generation consistency
   under the interpreter's atomic dict operations only. The threat model is registry
   mutation *between* graph steps and pauses, not concurrent mutation inside one node.
4. **Private access.** Only the public `register_runtime()` maintains the generation;
   writing to `_runtimes` directly bypasses it.
5. **On-disk skill files are not pinned.** The pin covers registry objects (the binding and
   the registered runtime instance), not the files a runtime executes: e.g.
   `trt_perf_analysis` runs a script found next to `skill.location`, and the skill inventory
   is scanned once at `CVAgent` construction. Replacing those files during a pause is outside
   this contract (a filesystem-integrity concern, not a registry one).
6. **Rejected alternative.** `id(obj)` as the token — ids are reusable after garbage
   collection, giving a false match; a monotonic counter cannot.

### 10.9 Rejection invariant R, mapped to transitions

> **R.** An explicit human rejection is terminal for that execution and cannot be
> overridden by a replacement binding, runtime, policy or subsequent approval-policy
> evaluation.

- **Recorded once, authoritatively.** Gate → `interrupt()` → `approval_decision` written
  by the sole writer; the gate makes no live registry read before `interrupt()`, so a
  resume re-derives the same branch from checkpointed state and can neither skip the
  interrupt nor discard the value (fixes scenario C at the source).
- **Enforced before any executor invocation.** `_route_after_approval → execute` is
  unchanged, and `_node_execute`'s step 1 (10.6) returns `rejected` before any pin
  validation, registry read or executor call. Binding, policy and runtime changes have no
  path to it; the executor's own `approved=False` refusal remains only as defence in depth.
- **Never overwritten.** Integrity failures write `execution_result`, never
  `approval_decision`; nothing else writes it.
- **Terminal, no re-plan, no re-ask.** `execute → END` is the only edge out of `execute`;
  the plan is cleared; a changed execution needs a new run (D3).

### 10.10 Failure-path guarantees (all rows of 10.5)

Every failure (rows 1–6, 8, 9): (a) **terminal** — `status="done"`, `execute → END`;
(b) **`planning_result["plan"] = None`** when a `planning_result` exists, `pending_execution`
kept as the audit record; (c) **recorded decision preserved** — `approval_decision` is
never written after the gate, so a rejection stays `rejected` and an approval stays
`approved`; (d) **no silent re-plan** — nothing re-enters `plan_execution`; (e) **no
re-ask** (D3) — nothing re-enters `approval_gate`, and no interrupt is added.

### 10.11 Interfaces and state (details: ADR-0009 §14, ADR-0010 §17)

- `AgentState.pending_execution` gains `execution_pin`. No other state field.
- `ExecutionBinding.pin()`, `ExecutionBindingRegistry.pin()`, `get_runtime_registration()`, generation storage,
  `pin_mismatch()`, `pin_is_well_formed()`, `SkillExecutionRequest.expected_binding_pin`,
  `ExecutionErrorCategory += "binding_mismatch"`.
- `PlanningResult.selected_description` and `execution_input_recovery["expected_description"]`
  (ADR-0010 §17 — not new state, a key in an existing record).
- Approval interrupt payload gains `runtime_id`, `description` (additive).

### 10.12 Alternatives considered

| Alternative | Why not |
|---|---|
| Pin `binding_id` only | Misses a same-`binding_id` policy/description/schema flip (probe-confirmed in #43). |
| Graph-side live check, then executor | Two lookups leave a check/use window; one comparison inside the single lookup is stronger and mutation-testable once. |
| Treat absent `expected_binding_pin` as "no check" for everyone | The hole D6 closes: an approval-required direct call with `approved=True` would run unbound. |
| Exempt the CLI because it has "no pause" | False (`input()` is a pause) and unnecessary — the CLI can pass a pin. |
| `dataclasses.asdict` / `repr` / object `==` as the snapshot | Unspecified for arbitrary defaults; not stable across checkpoint round-trips. |
| `id(runtime)` as token | Reusable after GC. |
| Hash instead of snapshot | Not auditable; mismatch messages need field names. |
| Re-ask approval on mismatch | Owner decision D3: fail closed. |
| Seal/freeze the registry during a run | Changes registry semantics for every caller and any future hot-reload; heavier than the defect. |
| New ADR-0011 | No new responsibility `[P§34]`; owner decision D1. |

### 10.13 Acceptance tests (real compiled graph + real `MemorySaver` unless stated)

Every new comparison and branch is **mutation-checked**: deleting it must fail the named
test. Test names are proposals; IDs are for review cross-reference.

| ID | Case | Asserts |
|---|---|---|
| **T1** | Original reproduction A (`approval_required` replacement, approved) | `execution_result` = `not_executable`/`binding_mismatch`; `replacement.calls == []`; `approval_decision == "approved"` |
| **T2** | Reproduction B (replacement, rejected) | `rejected`; `replacement.calls == []`; result shape as before |
| **T3** | Reproduction C (`allowed` replacement, rejected) | `approval_decision == "rejected"`; `rejected`/`approval_denied`; `replacement.calls == []` and original never invoked |
| **T4** | Reproduction D (`allowed` replacement, approved) | `binding_mismatch`; `replacement.calls == []` |
| **T5** | Same-`binding_id` policy flip, both directions (`approval_required→allowed`, `allowed→approval_required`) | `binding_mismatch` with code `binding.approval_policy`; no runtime invoked; for `→allowed` after a rejection, `rejected` still wins |
| **T6** | Same-`binding_id` description / schema / group / `verified` flips | `binding_mismatch` with the matching `binding.<key>` code |
| **T7** | Runtime replacement: (a) different `runtime_id`; (b) same `runtime_id`, new object; (c) A→B→A | `binding_mismatch` (`binding.runtime_id` / `runtime_registration`); neither runtime invoked; (d) identical re-registration of the same object is **not** a mismatch and completes |
| **T8** | Runtime generation states of 10.8 table (`None`→registered later; unregistered stays unregistered) | per table |
| **T9** | Pin state: missing key | gate does not interrupt; `approval_decision is None`; `not_executable`/`binding_mismatch`, `execution_pin_missing`; executor not called |
| **T10** | Pin state: malformed — one test per shape (non-dict; missing key; extra key; wrong type; bad policy literal; `runtime_generation` = `True`/`0`/`"1"`; `binding.skill_id` ≠ pending) | as T9 with `execution_pin_malformed`; executor not called |
| **T11** | Pin state: explicit `None` (caller-supplied plan, no binding at capture), then a binding + runtime registered before resume | `approval_decision == "not_required"`; `not_executable`/`no_binding`; **executor not called** |
| **T12** | Caller-supplied plan: pinned at first observation; mutation after that ⇒ mismatch; second visit of the plan node does not re-pin | per 10.5 |
| **T13** | Rejection precedence: recorded `rejected` combined with each of {missing pin, malformed pin, mismatching pin, `allowed` replacement, unregistered runtime, decision-inconsistent state} | always `rejected`; executor never called; registry never read (stubbed to raise) |
| **T14** | Decision inconsistent with pinned policy (`not_required` on a pinned `approval_required`; `None` decision on a well-formed pin) | `approval_decision_inconsistent`; not executed |
| **T15** | Gate replay safety: registry stubbed to raise on any read after planning | gate still interrupts and resumes; decision recorded correctly |
| **T16** | Identical re-registration during the pause; unrelated skill's binding replaced | completes normally, no false mismatch |
| **T17** | Direct callers (executor unit tests): approval-required + `approved=True` + not supplied → `approval_denied`, runtime not invoked; `allowed` + not supplied unchanged; supplied-malformed → `binding_mismatch` for every policy; supplied-mismatching → `binding_mismatch`, `runtime.invoke` never called; supplied-matching completes; the instance invoked is the instance whose generation was compared |
| **T18** | Direct CLI (`_authorize_and_execute`, the sequence `_cmd_execute` calls): (a) `approval_required` — the pin is captured before `_confirm_approval()`, and a registry change made *inside the interactive prompt* ⇒ `binding_mismatch`, nothing run; (b) `--approve` — there is no prompt, so the tests assert the pin is captured and passed, and that a description change or runtime replacement injected *between pin capture and the executor call* ⇒ `binding_mismatch`, nothing run; (c) a declined prompt runs nothing; an `allowed` binding passes no pin and never prompts; (d) an unpinnable `approval_required` binding raises `ValueError` before any prompt. The `_cmd_execute` wrapper itself (real skill discovery, exit codes) is not covered by these tests |
| **T19** | Canonical snapshot: `pin()` shape exactly 10.4; order-significance; tuple/list and dict-key-order independence; `1` vs `1.0` vs `True` differ; non-JSON-native default fails at the pin boundary while construction is unaffected; checkpoint round-trip produces no false mismatch |
| **T20** | Failure-path invariants (10.10) for every failing row: terminal `status="done"`, `planning_result["plan"] is None`, `pending_execution` retained, `approval_decision` untouched, no second `plan_execution`/`approval_gate` visit in `steps` |
| **T21** | Description drift through input recovery (ADR-0010 §17): (a) during a `provide_execution_inputs` pause; (b) during the second pause of a choose → provide-inputs chain; (c) recovery record lacking `expected_description` | terminal `binding_mismatch`/`description_changed`; `pending_execution is None`; plan cleared; replacement never invoked; unchanged description and identical re-registration pass |
| **T22** | Mutation checks | removing each of: rejection-first branch, pin comparison, E1, well-formedness check, explicit-`None` branch, decision-consistency check, generation comparison, `description_ok` ⇒ its test(s) above fail |
| **T23** | Regression hygiene | existing node-level tests that hand-build `pending_execution`, and the three `approved=True` tests, updated to carry a pin; no behavioral assertion weakened; `ruff`/`mypy` compared against `main`; full suite green |

### 10.14 Ambiguities raised in review, and their resolution (owner, 2026-09-21)

- **A1 — kept.** `approval_decision_inconsistent` (row 5) stays as a defensive guard:
  a bare `not_required` (or `None`) must never run a pinned `approval_required` binding.
- **A2 — inspected, no unavoidable change.** Before implementing, every existing test
  that reaches `rejected` / `not_executable` through the graph was checked. The
  plan-clearing rule (10.5) applies to all such results, and **no existing assertion
  required a change for it**: the full pre-existing suite passed unmodified on that
  point. The only pre-existing tests edited are the three `approved=True` executor call
  sites (D6, need a pin) and exact-equality assertions on `pending_execution` /
  `planning_result`, which gained the additive `execution_pin` / `selected_description`
  keys (10.15). Pre-existing refusals reached through the graph (`binding_not_verified`,
  `rejected`-policy binding, skill not discovered) now also clear `planning_result["plan"]`
  — a small, intended behavior change: a plan that did not start is not left executable.
- **A3 — pin boundary, not constructor.** Non-JSON-native defaults are validated in
  `pin()` (10.4); no constructor restriction was needed for correctness, so there is no
  compatibility impact on existing bindings or on registering a binding.

### 10.15 Implementation status and deviations from the approved text

Implemented as specified, with these deliberate differences (none changes a row of 10.5):

1. **No `ExecutionBinding.__post_init__` default check** — A3, above.
2. **Executor code `binding.unpinnable`.** If a *supplied* pin exists but the live binding
   itself cannot be pinned (e.g. it was replaced by one with a non-JSON-native default), the
   executor returns `binding_mismatch` with code `binding.unpinnable` rather than raising.
3. **The gate keeps its `executor` parameter** in `_make_approval_gate_node(executor)` so
   the graph builder is unchanged; it is intentionally unused (the gate reads only the pin).
4. **Direct CLI refactor.** The approve-then-execute sequence moved into
   `cv_agent.__main__._authorize_and_execute()` (behavior-preserving) so the pin-before-
   prompt ordering is testable; `_cmd_execute` calls it.
5. **T22 mutation checks are run, not automated.** They are performed by temporarily
   breaking each comparison/branch and confirming a test fails (23 mutations, all killed —
   recorded in `docs/state/JOURNAL.md`); they are not a permanent part of the test suite.
6. **T20 is folded into the graph tests** via one shared assertion helper
   (`_assert_failure` in `tests/test_approval_integrity.py`) rather than a separate test.

Files: `cv_agent/execution/{models,binding,executor}.py`, `cv_agent/graph/{planning,state,workflow}.py`,
`cv_agent/__main__.py`; tests `tests/test_approval_integrity.py` (108 tests) plus the edits noted
under A2. Known limits are exactly those of 10.8 (in-place mutation, process restart, threading,
private-dict access); nothing beyond them was found.
7. **Review follow-ups (independent review of PR #46, 2026-09-21).** Added regression tests for
   falsy non-`None` pins at the executor, capture at runtime generation 2 and replacement after
   it, the approval payload (`runtime_id`, `description`), caller-forged `execution_pin` through
   `CVAgent.start_workflow`, and `--approve` mutation between pin capture and execution.
   `_node_execute` now passes `approved = (decision == "approved")`, exactly as 10.6 specifies
   (the first cut passed `decision in ("approved", "not_required")`; nothing but the executor
   reads `request.approved`, and it only matters for `approval_required`). `SkillExecutor.get_binding()`
   is **kept** as public API (removal would break external callers) with a corrected docstring: the
   gate no longer uses it. A caller may put an `execution_pin` key in `pending_execution`; it is
   used as given and fails closed unless it matches the live binding (covered by tests).
