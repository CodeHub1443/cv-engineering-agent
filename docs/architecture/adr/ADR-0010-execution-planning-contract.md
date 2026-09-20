# ADR-0010: Execution-planning contract (RequirementsAnalysis → ExecutionPlan)

- **Status:** Accepted — `plan_execution()` and the `plan_execution` graph node
  are implemented and wired into `build_requirements_workflow_graph()` (see
  §9, §10); structured `AgentState.planning_result` observability is
  implemented too (see §11); an explicit, pre-supplied execution-input
  channel is implemented too (see §12); same-session recovery from
  `missing_required_inputs` via a third interrupt kind is implemented too
  (see §13); group-aware planning + recovery, resolving Q20, is implemented
  too (see §14); a review correction enforcing true oneOf/XOR ("exactly
  one," not "at least one") is implemented too (see §15); ambiguous-candidate
  disambiguation via a fourth interrupt kind, resolving Q18, is implemented
  too (see §16)
- **Date:** 2026-09-16 (§13: 2026-09-17; §14/§15: 2026-09-18; §16: 2026-09-20)
- **Layer:** orchestration
- **Canon:** `[P§19]`, `[P§21]`, `[P§22]`, `[P§24]`, `[P§34]`, `[P§35]`
- **Supersedes / Superseded by:** — (extends ADR-0003 §3's graph topology and
  ADR-0009 §3's `ExecutionBinding`; supersedes neither)
- **Issue:** #TBD

> **Note on numbering (resolved 2026-09-16):** `docs/roadmap/ROADMAP.md` Phase 6
> aspirationally reserved "ADR-0010" for a future *training-execution* ADR
> (Phase 5, separately, reserved "ADR-0009" for a future *dataset-subsystem*
> ADR that never happened — ADR-0009 was actually assigned to
> skill-execution-boundary instead when it was actually written, and that
> earlier drift was simply left as-is). This repo's actual, evidenced
> numbering convention — confirmed by that exact prior case, not invented here
> — is: each ADR gets the next number free in `docs/architecture/adr/` at the
> time it is actually written; the roadmap's phase-scope bullets are
> speculative, non-binding placeholders for decisions not yet made, expected
> to drift once the real decision is written. This ADR keeps `0010` on that
> basis. `docs/roadmap/ROADMAP.md` Phase 6 has been updated to no longer claim
> that number for training execution (its own scope line now names the topic
> without a hardcoded number, deferring assignment to whenever that ADR is
> actually written) — existing accepted ADRs are not renumbered.

## 1. Context

A read-only architecture audit of `main @ ce8b91f` (after PR #30 —
`RequirementsAnalysis.skill_links`, ADR-0008 §9) found the next real gap: the
information needed to run something is now surfaced (`SkillLink.skill_id` +
`SkillLink.executable`), but nothing converts it into an actual execution
attempt. Concretely, inspecting `cv_agent/graph/workflow.py` and
`tests/test_workflow.py` directly (not assumed) found that ADR-0003 already
built the entire downstream mechanism — `AgentState.pending_execution:
{"skill_id", "inputs", "task"} | None` feeds an `approval_gate` node (checks
the binding's `approval_policy`, interrupts if `approval_required`) and an
`execute` node (builds a `SkillExecutionRequest` and calls
`SkillExecutor.execute()`, never reimplemented) — but **every single test that
exercises `pending_execution` supplies it as a hand-constructed literal
argument**; nothing derives it from `requirements_analysis["skill_links"]`.
`cv_agent/__main__.py::_cmd_execute` confirms the same gap at the CLI layer: it
hardcodes a single accepted `skill_id` and expects a human to already know
(from reading `cv_agent/execution/runtimes/trt_perf_analysis.py::_build_argv`'s
docstring — the only place it is written down anywhere) what `inputs` shape
that skill wants.

This ADR closes that gap at the type/contract level only — see §9 for what
is and is not implemented here.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** the `ExecutionPlan` type — the minimum information needed to
  turn one selected `SkillLink` into a `SkillExecutionRequest` — and the
  decision of *where* (which layer, which graph node) the act of selecting a
  candidate and constructing that plan belongs. It is a responsibility of the
  **existing LangGraph workflow layer** (`cv_agent.graph`, ADR-0003), not a new
  top-level package: a future `plan_execution` node, inserted into the
  *existing* `build_requirements_workflow_graph()` topology between
  `analyze_requirements` and `approval_gate`, is the intended home (§3, §5).
- **This does NOT own** (each already stated by its own ADR; restated here
  only to name why *this* new responsibility could not be folded into any of
  them):
  - **`RequirementsAnalyzer` (ADR-0008)** — its §2 already states it does not
    own "deciding which capability/skill to actually use." `RequirementsAnalysis.skill_links`
    is a *description of candidates*, not a decision. Folding selection in
    here would re-blur DISCOVER/DEFINE (`[P§21]`'s reasoning stage) with
    execution planning, exactly the reasoning/orchestration separation
    `[P§19]` requires kept apart, and would undo the deliberate, tested
    boundary PR #30 just drew (`skill_links` carries candidates with no
    ranking, no `selected_skill` field).
  - **`TaskResolver` (ADR-0007)** — its whole job is keyword-overlap matching
    of a task string to capabilities/skills; it has no notion of "this run's
    `AgentState`," "this run's already-answered clarification fields," or
    "has a human already supplied the `path` this skill needs." Planning
    needs that run-scoped context; resolution is stateless and reusable
    across runs.
  - **`SkillExecutor` (ADR-0009 §2)** — its own responsibility section already
    states it does not "discover skills or decide which one to use... those
    precede this." It is deliberately a narrow, skill-agnostic gate: given
    *one already-identified* `(Skill, SkillExecutionRequest)`, decide
    permit/deny and delegate. Teaching it to pick a skill from several
    candidates would collapse "is this specific request runnable" with
    "which of these five things should even be attempted" — two different
    questions this codebase has kept apart at every layer so far.
  - **`ExecutionRuntime` (ADR-0009 §3)** — a narrow `Protocol` around one
    already-selected skill's actual invocation (`invoke(skill, request)`). It
    has no visibility into `RequirementsAnalysis` at all, cannot and must not
    gain any — a runtime adapter (e.g. `TrtPerfAnalysisRuntime`) stays exactly
    as ignorant of *why* it was called as it is today.
- **Why this responsibility does not belong to an existing component:** every
  one of the four above already has one clean, narrow job and already says so
  in its own ADR. "Choose a candidate and construct a plan" is a genuinely new
  question — closer to "requirements" than "execution," but distinct from
  both: it needs `RequirementsAnalysis`'s *output* plus run-scoped state
  (clarification answers, prior plan attempts) that only the orchestration
  layer already carries (`AgentState`, via `cv_agent.graph`). `[P§21]`
  already assigns this class of decision — sequencing a multi-step run with
  human checkpoints — to LangGraph specifically, and ADR-0003 already proved
  the exact mechanism (a plain node reading upstream state, writing a new
  slot for a downstream node to consume) this ADR reuses rather than
  reinventing.

## 3. Decision

Define `ExecutionPlan` (module: `cv_agent.graph.planning`, new) as the
contract a future `plan_execution` graph node produces from
`AgentState["requirements_analysis"]["skill_links"]`, and the exact,
deterministic V1 rule for producing (or declining to produce) one:

**Selection (V1, deterministic, no LLM, no ranking):**
1. Filter `skill_links` to `executable == True` only — a non-executable
   candidate is never planned around, regardless of how well it matched.
2. **Zero** executable candidates → no plan (`pending_execution` stays
   `None`) — not an error, not a fabricated fallback; the existing
   `_route_after_approval` already treats `None` as a clean skip straight to
   `END` (ADR-0003), so this case needs no new handling downstream.
3. **Exactly one** executable candidate → a plan is constructed for it,
   subject to the input-completeness check below.
4. **More than one** executable candidate → **ambiguous — no silent
   selection** (`[P§35]`: fabricating a choice nobody actually made is the
   exact silent-invention failure mode the canon forbids). No plan is
   produced in V1; disambiguation is explicitly deferred (§8, and
   `docs/state/OPEN_QUESTIONS.md`).

**Input completeness (V1):** using the declared `ExecutionBinding.input_schema`
(ADR-0009 §11, this same change), check whether every `required=True`
`InputField` has a known value (from an explicit caller-supplied value —
mirroring `RequirementField`'s own `"caller_assumption"` discipline, ADR-0008
— never invented). If any required input is missing, **no plan is produced in
V1** — not an interrupt, not a guess. A future interrupt-based "ask the human
for this one missing input" extension is named and explicitly deferred (§8).

**What a plan is not:** constructing an `ExecutionPlan` — or writing it into
`AgentState["pending_execution"]` — approves nothing and executes nothing. It
is a pure state-transform, the same character as the existing
`analyze_requirements` node: no `interrupt()` call, no call to
`SkillExecutor`, no call to any `ExecutionRuntime`. The **existing**
`approval_gate` and `execute` nodes (ADR-0003, unmodified by this ADR) remain
the only enforcement and only invocation path — `SkillExecutor.execute()`
stays the sole code path that ever calls `ExecutionRuntime.invoke()`, exactly
as today.

**Intended graph topology** (future work, §9 — not built by this ADR):

```
analyze_requirements → (clarify loop, exactly as ADR-0003 today)
                              ↓
                        plan_execution   (NEW — this ADR's contract)
                              ↓
                        approval_gate    (ADR-0003, unmodified)
                              ↓
                          execute        (ADR-0003, unmodified)
```

`plan_execution` sits strictly after clarification resolves (so a plan can see
fully-clarified fields) and strictly before `approval_gate` (so every plan,
regardless of how it was produced, still passes through the one existing,
unmodified approval check before anything runs).

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Selection lives inside `RequirementsAnalyzer` | One fewer new node; `skill_links` and the selection logic would sit in the same module | ADR-0008 §2 already explicitly disclaims this ownership; PR #30 deliberately shipped `skill_links` with no ranking/selection field specifically to keep this boundary; would re-blur reasoning (DISCOVER/DEFINE, `[P§21]`) with orchestration, the exact `[P§19]` layer separation this codebase has enforced at every prior boundary (ADR-0007 vs 0008, ADR-0008 vs 0009) | Rejected — would undo a boundary decision made one PR ago, for no new capability |
| Selection lives inside `SkillExecutor`/`CVAgent.execute()` (pass it the whole `RequirementsAnalysis`, let it pick) | Fewer call sites; one method to call | `SkillExecutor`'s ADR-0009 §2 responsibility is narrow by design ("given (Skill, request), decide whether execution is possible/permitted" — not *which* Skill); would make the CLI's existing explicit `execute <skill_id>` contract ambiguous (which skill did it actually run?); would require `SkillExecutor` to import `cv_agent.requirements`, a new, unwanted dependency in a module ADR-0009 §1 built specifically execution-only | Rejected — collapses two different questions ("is this permitted" vs. "which of these should be attempted") into one already-narrow module |
| A new, standalone orchestration package outside `cv_agent.graph` / not LangGraph-based (e.g. `cv_agent/orchestration/`) | Callable without building a graph; simpler for a single synchronous call | Duplicates the exact pause-and-wait-for-a-human mechanism ADR-0003 already built and proved (`clarify`'s `interrupt()`) — the deferred missing-input-interrupt extension (§8) would need that same mechanism again if built outside the graph; ADR-0003 §6 already warns against growing a *third* parallel execution/orchestration mechanism (it already accepted the cost of two compiled graphs as a real, acknowledged trade-off, not one to repeat) | Rejected for the node itself; a plain, pure helper function *inside* `cv_agent.graph.planning` (not a separate package) that the node calls is compatible with this decision and left open for the implementation PR |

## 5. Interface

Types only — no implementation bodies (per this template's own rule and this
task's explicit instruction not to implement planning yet).

```python
# module: cv_agent.graph.planning (NEW)
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class ExecutionPlan:
    """
    The minimum information needed to turn one selected, executable
    SkillLink into a SkillExecutionRequest. Produced by a future
    `plan_execution` graph node (ADR-0010 §9, not yet implemented) from
    `AgentState["requirements_analysis"]["skill_links"]`. Constructing one
    approves and executes nothing — see ADR-0010 §3.
    """

    skill_id: str
    """The selected SkillLink.skill_id — the one, unambiguous executable
    candidate (ADR-0010 §3's selection rule)."""

    task_component: str
    """The selected SkillLink.task_component — provenance only (which task
    component's resolution produced this candidate), for the same
    evidence-trail reason every other *Link type in this codebase carries
    its originating context. Not consumed by approval_gate/execute today;
    carried for audit/logging when the plan is materialized."""

    inputs: dict[str, Any]
    """Same shape as SkillExecutionRequest.inputs — opaque to everything
    except the runtime the selected binding points at (see ADR-0009 §11).
    Built from caller-supplied values only; never fabricated (ADR-0010 §3's
    input-completeness rule)."""

    source_task: str | None
    """The original natural-language request/task this plan serves —
    mirrors SkillExecutionRequest.task, for the same evidence-trail reason."""


# module: cv_agent.graph.state (future addition, NOT made by this ADR — see §9)
# AgentState["pending_execution"] remains {"skill_id", "inputs", "task"};
# an ExecutionPlan materializes into that exact dict shape via
# {"skill_id": plan.skill_id, "inputs": plan.inputs, "task": plan.source_task}
# — task_component is intentionally not carried into pending_execution
# (approval_gate/execute never read it); it stays plan-side provenance only.
```

See ADR-0009 §11 (this same change) for `ExecutionBinding.input_schema` /
`InputField` — the sibling type this ADR's input-completeness check reads.

## 6. Consequences

As originally written (§9's types-only scope) — **enabled:** a concrete,
typed contract to build `plan_execution` against without re-deriving the
shape question; **migration/blast radius if reversed:** contained,
`ExecutionPlan` referenced by nothing yet. **Superseded by §10/§11:**
`ExecutionPlan`/`PlanningResult` are now referenced by the real
`plan_execution` graph node and `AgentState.planning_result`; reversing this
ADR now means reverting the topology change too (§10) — no longer a
zero-blast-radius types-only removal. `ExecutionBinding.input_schema` still
defaults to `()` and remains unpopulated by the one real binding
(`trt_perf_analysis.build_binding()`), so that part of the original
migration claim still holds.

## 7. Acceptance test

As originally written, this step's own acceptance test was necessarily
narrow — it proved the *contract types* were real, constructible Python
with the exact declared shape, not that any selection/planning *behavior*
worked. `tests/test_execution_planning_contract.py`: `ExecutionPlan`
constructs with exactly the four documented fields and is frozen/immutable;
`InputField`/`ExecutionBinding.input_schema` construct with the documented
shape and default to an empty tuple, preserving every existing
`ExecutionBinding` construction site unchanged (see ADR-0009 §11's own
acceptance-test note); `plan_execution()`'s own selection/input-completeness
rule (17 behavioral tests in the same file).

**The behavioral, graph-integrated acceptance test (§10, §11), added since:**
`tests/test_workflow.py::TestPlanExecutionIntegration` (one/zero/multiple
executable candidates, missing required input, planned execution through
both an `allowed` and an `approval_required` binding, clarification-before-
planning ordering, `planning_result` persistence across an approval resume)
and `TestManuallySuppliedPendingExecutionPrecedence` (the precedence rule
made explicit). All 18 pre-existing `test_workflow.py` tests continue to
pass with zero body changes.

**The explicit execution-input channel (§12), added since:**
`TestPlanExecutionIntegration::test_execution_inputs_satisfy_missing_required_input_and_produce_a_plan`
(the exact fixture that produces `missing_required_inputs` without it now
produces `"planned"` with it), `test_execution_inputs_survive_the_clarification_loop`
(supplied at `start_workflow()`, unchanged through a clarify interrupt/resume,
still reaches the plan), and
`TestManuallySuppliedPendingExecutionPrecedence::test_execution_inputs_are_ignored_when_pending_execution_is_supplied`
(precedence rule extended: a caller-supplied `pending_execution` still wins
even when `execution_inputs` is also supplied). Plus
`tests/test_memory_integration.py::TestExecutionInputsChannel` — the same
guarantee proven through the real `CVAgent.start_workflow()` API surface end
to end (real skill discovery, real `SkillExecutor`), not only at the graph
level.

## 8. Revisit trigger

- **Fired — see §10/§11:** the graph-integration implementation PR was
  written, and this ADR was amended in place (dated "Status" sections,
  matching ADR-0009 §9/§10/§11's own pattern) rather than superseded.
- When the "ambiguous — no silent selection" case (§3, step 4) needs a real
  resolution mechanism — an explicit human/CLI disambiguation choice, most
  likely — logged in `docs/state/OPEN_QUESTIONS.md`, not decided here.
- **Fired — see §13:** the "missing required input → no plan" V1 default
  (§3) was judged too silent in practice **for a caller who did not know the
  value in advance.** §12 closed the sub-case of a caller who *does* know it
  ahead of time; §13 closes the remaining sub-case — a caller who only
  learns the value after seeing `planning_result.status ==
  "missing_required_inputs"` — via the third interrupt kind named here,
  `provide_execution_inputs`, architecturally consistent with the existing
  `clarify` interrupt. `docs/state/OPEN_QUESTIONS.md` Q17 is resolved by
  §13.
- When a second individually-verified `ExecutionRuntime`/`ExecutionBinding`
  exists (ADR-0009 §8's own per-skill revisit trigger) — the first real
  stress test of whether `InputField`'s flat required/optional shape
  generalizes beyond `trt-perf-analysis`'s one example.
- When `docs/APPROVALS.md`'s real cost-estimate workflow is implemented — if
  planning ever selects a candidate whose binding is `approval_required`, the
  `approval_gate` interrupt payload will need that estimate to satisfy
  APPROVALS.md's own "before asking, the agent estimates the cost" rule; this
  ADR inherits that gap from ADR-0009 §8 rather than solving it.
- Explicitly **not yet triggered** by this ADR, and explicitly out of scope
  for every implementation step so far (§10, §11): LLM-assisted selection
  (deferred — see §1/§2's deterministic-only V1 rule; a future LLM role, if
  any, would be prose-explanation-only or a proposed-value-requiring-
  explicit-confirmation, mirroring `RequirementField.source ==
  "caller_assumption"` exactly, never a silent authority over
  `approval_decision` or selection).

## 9. Status — contract types (superseded status, kept for history)

**Types/interface only, as originally shipped.** `cv_agent.graph.planning.
ExecutionPlan` and `cv_agent.execution.binding.InputField`/`ExecutionBinding.
input_schema` (ADR-0009 §11) existed as real, tested-for-shape Python types,
with no node, no topology change, and no selection/input-completeness logic
wired in yet. **This section's "not implemented" list no longer describes
the current state — see §10, which built the node this section deferred.**

## 10. Status — graph integration (`plan_execution` node)

**Implemented (branch `feature/claude/execution-planning-contract`):** the
`plan_execution` node itself, using the unmodified `plan_execution()`
function from §9 — no change to selection/input-completeness logic.

- **Topology:** `analyze_requirements`/`clarify`'s existing routing target
  changed from `approval_gate` to a new `plan_execution` node; a new plain
  edge `plan_execution -> approval_gate` follows. `plan_execution` sits
  strictly after the clarification loop resolves and strictly before
  `approval_gate` — verified by
  `tests/test_workflow.py::TestPlanExecutionIntegration::
  test_planning_happens_only_after_clarification_completes`.
  `approval_gate`/`execute` node bodies, `_route_after_approval`,
  `SkillExecutor`, and `ExecutionRuntime` are byte-for-byte unchanged.
- **Precedence over a caller-supplied plan:** if `AgentState["pending_execution"]`
  is already set when this node runs — the pre-existing
  `start_workflow(pending_execution=...)` contract (ADR-0003 §3) — the node
  makes **no** `plan_execution()` call at all and leaves it untouched. This
  is not a bypass of the planner: an already-expressed, caller-supplied
  intent is not a decision `plan_execution()` was ever asked to make, so
  there is nothing for it to override. Verified by
  `TestManuallySuppliedPendingExecutionPrecedence` and by every pre-existing
  `TestApprovalGate` test continuing to pass with zero body changes.
  `AgentState["pending_execution"]`'s own shape is unchanged —
  `{"skill_id": str, "inputs": dict, "task": str | None}`; `task_component`
  is never added to it (carried only on the plan/in `steps`).
- **`available_inputs` was always `{}` at this step, superseded by §12:**
  at the time this section was written, nothing in `AgentState`
  legitimately represented "explicit execution inputs a human already
  supplied ahead of planning" — `clarification_answers` is keyed by
  `RequirementField.name`, not `InputField.name`, and repurposing it would
  itself be the "infer from arbitrary text" §3 forbids. §12 (below) closes
  that gap with a dedicated, distinctly-namespaced `AgentState.execution_inputs`
  field; `clarification_answers` itself is still never read for this
  purpose — see `docs/state/OPEN_QUESTIONS.md` Q17 for what §12 does *not*
  close.

## 11. Status — structured observability (`AgentState.planning_result`)

**Implemented (same branch, following a read-only review of §10's own
commit):** the review found that `PlanningStatus` and its diagnostic payload
(`candidate_skill_ids`, `missing_inputs`) were observable **only** by parsing
`AgentState["steps"]` for the `plan_execution` node's log entry — inconsistent
with how this same graph already treats `approval_decision`/`execution_result`
as dedicated, top-level, directly-queryable fields (`_node_approval_gate` sets
`approval_decision="not_required"` even for its own trivial no-op case). This
section closes that gap without touching `cv_agent.graph.planning` at all.

- **New field**, `cv_agent.graph.state.AgentState.planning_result:
  Optional[dict[str, Any]]` — `dataclasses.asdict()` of the `PlanningResult`
  (§9) produced by the most recent **actual** `plan_execution()` call this
  run, same serialization rationale as `requirements_analysis`/
  `execution_result` (§3, ADR-0003 §3: a plain dict, never the dataclass
  instance, so orchestration state stays independent of the reasoning/
  planning layer's own types). Shape: `{"status": PlanningStatus, "plan":
  dict | None, "candidate_skill_ids": tuple|list[str], "missing_inputs":
  tuple|list[str]}` — `plan`/`candidate_skill_ids`/`missing_inputs` are only
  meaningfully populated for the `PlanningStatus` value that documents them
  (§9's own `PlanningStatus` docstring, unchanged).
- **`None` has two causes — the same ambiguity `execution_result` already
  has, not a new one:** the `plan_execution` node has not run yet this run,
  **or** it ran but made no `plan_execution()` call at all because
  `pending_execution` was already caller-supplied (§10's precedence rule). A
  caller-supplied plan was never a `plan_execution()` decision, so there is
  no `PlanningResult` to report for it — `planning_result` is deliberately
  left `None` rather than given an ad-hoc "skipped" placeholder value, which
  would have meant inventing a status `PlanningStatus` itself does not have
  (out of scope: this section does not touch `cv_agent.graph.planning`).
  `AgentState["steps"]` still carries the
  `"caller_supplied_pending_execution_preserved"` entry for that case,
  unchanged from §10 — `steps` is not replaced by this field, it remains the
  chronological audit trail; `planning_result` is the queryable snapshot of
  the latest planning attempt, when one was actually attempted.
- **Persistence across resume:** `planning_result`, once set, survives an
  `approval_gate` interrupt/resume untouched, since `plan_execution` never
  re-runs after `approval_gate` starts (LangGraph's dynamic `interrupt()`
  re-enters only the node that called it — ADR-0003 §1) — verified by
  `test_planning_result_persists_unchanged_across_an_approval_resume`.
- **Container-type caveat carried over from ADR-0004:** `candidate_skill_ids`/
  `missing_inputs` are tuples on a fresh, non-checkpoint-restored `.invoke()`
  but may come back as lists after a checkpoint save/restore (e.g. after a
  `resume_workflow()` call) — the same instability
  `CVAgent._sync_memory_after_run()` already documents for
  `requirements_analysis`'s own tuple fields. Callers should not assume a
  specific container type, only iterate.
- **Not changed by this section:** `cv_agent.graph.planning`
  (`PlanningResult`, `PlanningStatus`, `plan_execution()` itself — no new
  status value, no selection-logic change), `pending_execution`'s shape,
  `approval_gate`/`execute`, `SkillExecutor`, `ExecutionRuntime`, any CLI
  surface.

## 12. Status — explicit execution-input channel (`AgentState.execution_inputs`)

**Implemented (branch `feature/claude/execution-input-channel`), API
parameter only — CLI flags deferred.** §10 shipped the `plan_execution` node
always calling `plan_execution()` with `available_inputs={}`, honestly
documented as a real gap (`docs/state/OPEN_QUESTIONS.md` Q17) rather than
faked. This section gives a caller who already knows a required input's
value **before** a run starts a real, explicit way to supply it — closing
the sub-case of Q17 where the value is known in advance, and leaving open
only the sub-case where it is learned mid-run (Q17, restated below).

- **New field**, `cv_agent.graph.state.AgentState.execution_inputs:
  dict[str, Any]` — caller-supplied values keyed by `InputField.name`
  (ADR-0009 §11, e.g. `"path"`). Defaults to `{}`. **Deliberately a
  different namespace from `clarification_answers`**, which stays keyed by
  `RequirementField.name` (e.g. `"deployment_target"`) — the two dicts are
  never merged, cross-read, or used to fill each other in. Folding one into
  the other would be exactly the "infer an execution input from arbitrary
  request/answer text" failure `[P§35]` and §3's own input-completeness rule
  already forbid.
- **How a caller supplies it:** `CVAgent.start_workflow()` gains one new
  keyword-only parameter, `execution_inputs: Optional[dict[str, Any]] =
  None`, stored verbatim into `AgentState["execution_inputs"]` (`{}` if
  omitted — the exact same "no plan if a required input is missing"
  behavior as before this parameter existed, so every existing caller is
  unaffected). No CLI flag is added in this step (`_cmd_workflow_demo`
  remains unchanged) — deferred, not forgotten; the API parameter is the
  complete V1 surface.
- **How `plan_execution` receives it:** `_node_plan_execution` reads
  `state.get("execution_inputs") or {}` and passes it as `plan_execution()`'s
  `available_inputs` argument — the one line §10 previously hardcoded to
  `{}`. `cv_agent.graph.planning.plan_execution()` itself is **unchanged** —
  it already accepted `available_inputs` as a parameter; only the node's own
  value changed.
- **Precedence over a caller-supplied `pending_execution` is unchanged and
  unaffected:** if `pending_execution` is already set when `plan_execution`
  runs, the node still makes **no** `plan_execution()` call at all (§10's
  existing rule) — `execution_inputs`, if also supplied in that run, is
  simply unused, not merged into the caller's own plan. Verified by
  `TestManuallySuppliedPendingExecutionPrecedence::
  test_execution_inputs_are_ignored_when_pending_execution_is_supplied`.
- **Survives the clarification loop:** `execution_inputs` is written once,
  at `start_workflow()`, and no node between `initialize` and
  `plan_execution` — including `clarify`/`analyze_requirements`'s loop-back —
  ever touches it. Verified by
  `test_execution_inputs_survive_the_clarification_loop`, which supplies
  `execution_inputs` on a request that also triggers a real clarification
  interrupt/resume and confirms the same value reaches the eventual plan
  unchanged, while `clarification_answers` (populated by the resume) stays
  in its own separate field.
- **V1 is pre-supply only — no same-session retry, Q17 stays open, narrowed:**
  there is no interrupt that pauses `plan_execution` to ask for a missing
  value, and none is added here. If a run reaches
  `planning_result.status == "missing_required_inputs"`, the only recovery
  in V1 is a **new** `start_workflow()` call with `execution_inputs` now
  supplied — `plan_execution` never re-runs within the same session once the
  graph has moved past it (`approval_gate`/`END`). This is a real, named
  limitation, not an oversight — seen as acceptable for V1 per this task's
  own explicit decision. `docs/state/OPEN_QUESTIONS.md` Q17 is reworded (not
  struck through) to describe exactly this narrower remaining gap.
- **No cross-binding collision guard:** `plan_execution()`'s missing-input
  check reads `available_inputs` by field *name* only, scoped to the one
  already-selected candidate's `input_schema` — so a name collision between
  two different bindings' declared fields (e.g. both happening to declare a
  required `"path"`) cannot affect *which* candidate gets selected
  (`execution_inputs` is never consulted during selection, only afterward,
  during the single selected candidate's own completeness check). It could
  still mean a value supplied with one skill in mind incidentally also
  satisfies a completeness check for a different skill_id in a different run
  that happens to declare the same field name. Not a problem with today's
  one real binding; explicitly not guarded against here per this task's own
  scope decision — retained as a documented future consideration for when a
  second individually-verified binding exists (ADR-0009 §8's per-skill
  trigger).
- **Tests:** `tests/test_workflow.py::TestPlanExecutionIntegration` (2 new:
  the missing-input fixture satisfied by `execution_inputs`, survival across
  a clarification interrupt/resume) and
  `TestManuallySuppliedPendingExecutionPrecedence` (1 new: precedence over a
  caller-supplied plan); `tests/test_memory_integration.py::
  TestExecutionInputsChannel` (2 new: end-to-end through the real
  `CVAgent.start_workflow()` API and real skill discovery — supplied value
  produces a plan and a completed execution; omitted value preserves the
  pre-existing missing-input behavior exactly). All pre-existing tests in
  both files continue to pass with the `_start()`/fixture helpers extended,
  not rewritten (an `execution_inputs` key added to the shared initial-state
  dict, defaulting to `{}`).
- **Not implemented by this section:** any CLI flag (`_cmd_workflow_demo` or
  otherwise) for supplying `execution_inputs`; the Q17 interrupt-based
  mid-run recovery path; a cross-binding collision guard. All three remain
  open, named above rather than silently deferred.

## 13. Status — same-session recovery from `missing_required_inputs`

**Implemented (branch `feature/claude/q17-input-recovery`).** Closes
`docs/state/OPEN_QUESTIONS.md` Q17's remaining sub-case: a caller who only
learns a required execution input's value **after** `plan_execution` already
produced `planning_result.status == "missing_required_inputs"` now has a
same-session recovery path — a third interrupt kind,
`provide_execution_inputs`, architecturally consistent with the existing
`clarify` interrupt (ADR-0003) but a distinct namespace (never
`clarification_answers`).

### 13.1 Topology

`plan_execution`'s existing plain edge to `approval_gate` becomes a
conditional edge, `_route_after_planning`, with a new node,
`provide_execution_inputs`, and a new plain edge back to `plan_execution`:

```
plan_execution ──status=="missing_required_inputs" AND not yet attempted──→ provide_execution_inputs
     │  ↑                                                                           │
     │  └────────────────(always loops back — exactly once, ever)──────────────────┘
     │
     ├──(execution_input_recovery.attempted == True)───┐
     │                                                  │
     │      recovery.terminal == False                  recovery.terminal == True
     │               │                                          │
     │               ▼                                          ▼
     │         approval_gate → execute → END                   END
     │
     └──(recovery never attempted: planned / no_executable_candidate /
          ambiguous_candidates / caller-supplied pending_execution)──→ approval_gate → execute → END
          (unchanged from §10/§12)
```

`approval_gate`/`execute` node bodies, `SkillExecutor`, `ExecutionRuntime`,
and `plan_execution()` itself (the pure function, `cv_agent.graph.planning`)
are all byte-for-byte unchanged. `_node_plan_execution` gains an additive
branch (only active when a recovery record is already present in state —
see 13.3); it is otherwise identical to §10/§12's version.

### 13.2 Data model

`cv_agent.graph.planning.PlanningResult` gains three fields, populated
whenever exactly one candidate was selected (status `"planned"` or
`"missing_required_inputs"`; `None` for `"no_executable_candidate"`/
`"ambiguous_candidates"`):

```python
selected_skill_id: str | None = None
selected_binding_id: str | None = None
selected_input_schema: tuple[InputField, ...] | None = None
```

`selected_input_schema` is a verbatim snapshot of the selected candidate's
`ExecutionBinding.input_schema` at the moment of selection — not just its
`binding_id`. This is deliberate: `binding_id` string equality alone does
not prove the underlying contract is unchanged (the same `binding_id` could
be re-registered with a renamed field, a changed `description`/`default`,
or a flipped `required` flag) — see 13.4.

**Serialization fidelity, verified on PR #33 review:** `dataclasses.asdict()`
(the same serialization every other `AgentState` dict field already uses,
ADR-0003 §3) converts each `InputField` in the tuple to a plain dict
carrying all four attributes — `name`, `required`, `description`, `default`
— never just the name; list order matches declaration order (a deliberate,
documented consequence: reordering a binding's declared fields with no
other change is itself treated as a contract change, per 13.5). Both the
checkpointed side (`AgentState["planning_result"]["selected_input_schema"]`,
read by `provide_execution_inputs` and stored into
`execution_input_recovery["expected_input_schema"]`) and the retry side
(freshly `asdict()`'d inside `_node_plan_execution`) are plain `list[dict]`
before comparison — never compared as raw dataclass instances or via
`repr()`/object identity — so `==` is a genuine, deterministic,
value-based structural comparison, confirmed through a real `MemorySaver`
checkpoint round-trip (`tests/test_workflow.py::
test_full_input_field_contract_survives_the_real_checkpoint_round_trip`),
not just an in-memory one.

`cv_agent.graph.state.AgentState` gains `execution_input_recovery:
Optional[dict[str, Any]]`:

```python
{
    "attempted": bool,
    "outcome": "supplied" | "incomplete" | "invalid" | "cancelled" | "binding_mismatch",
    "terminal": bool | None,
    "mismatch_detail": "identity_changed" | "schema_changed" | "still_incomplete_after_supply" | None,
    "expected_skill_id": str,
    "expected_binding_id": str,
    "expected_input_schema": list[dict],
    "requested": list[str],
    "accepted": list[str],
    "still_missing": list[str],
    "rejected": list[dict],
}
```

### 13.3 Field ownership / replay safety

LangGraph's dynamic `interrupt()` re-runs a node's pre-interrupt code on
resume (confirmed empirically — see 13.6). `provide_execution_inputs`
therefore reads `expected_skill_id`/`expected_binding_id`/
`expected_input_schema`/`requested` **only** from the already-checkpointed
`AgentState["planning_result"]` — never a live `ExecutionBindingRegistry`
lookup, which would be replay-unsafe (it could observe a registry mutated
during the pause). It writes the record once, on resume: `attempted=True`,
a raw `outcome` (never `"binding_mismatch"` at this point), and the
classification fields; `terminal`/`mismatch_detail` are left `None` here —
only `_node_plan_execution`'s retry, holding a fresh `plan_execution()`
result, can finalize them. This intermediate shape is never externally
observable: `provide_execution_inputs -> plan_execution` is a plain edge,
so both nodes run inside one `resume_workflow()` call before control
returns to any caller.

### 13.4 Deterministic classification (ADR-0010 §13's rule)

Relative to `requested` (the complete `missing_inputs` list from the one
and only ask) and `declared_names` (every field name the checkpointed
`expected_input_schema` snapshot declares):

- A resume value that is not a `dict`, or an empty `dict`, →
  `"cancelled"`.
- Every `requested` name got a valid (declared, non-blank) value →
  `"supplied"`.
- At least one, but not all, `requested` names got a valid value →
  `"incomplete"`.
- Zero `requested` names got a valid value (whether because they were
  never mentioned, or mentioned with an undeclared name/blank value) →
  `"invalid"`.

A field attempted-but-rejected (blank, or not a declared name) and a field
never mentioned at all are treated identically for this verdict — both
simply mean "not fulfilled" — but remain individually visible via
`rejected` (why an attempt failed) and `still_missing` (`requested` minus
`accepted`).

`"binding_mismatch"` is never produced by this classification — it can only
be applied afterward, by `_node_plan_execution`, overriding whatever the
above produced.

### 13.5 Identity + schema guard (the only path to `pending_execution`)

On retry, `_node_plan_execution` calls `plan_execution()` fresh, then — only
when a recovery record is present — determines the final outcome by
re-deriving everything from checkpointed state, never trusting the raw
classification alone:

```python
identity_ok = (fresh.selected_skill_id == expected_skill_id
               and fresh.selected_binding_id == expected_binding_id)
schema_ok = normalize(fresh.selected_input_schema) == expected_input_schema

if not identity_ok:      final_outcome, terminal, detail = "binding_mismatch", True, "identity_changed"
elif not schema_ok:      final_outcome, terminal, detail = "binding_mismatch", True, "schema_changed"
elif raw_outcome != "supplied": final_outcome, terminal, detail = raw_outcome, True, None
elif fresh.status != "planned": final_outcome, terminal, detail = "binding_mismatch", True, "still_incomplete_after_supply"
else:                     final_outcome, terminal, detail = "supplied", False, None

pending_execution = plan if (final_outcome == "supplied" and not terminal) else None
```

ID equality alone is deliberately **not** treated as sufficient — `schema_ok`
performs a full structural comparison of the binding's declared
`input_schema` (every field's name/required/description/default), so a
same-`binding_id` binding whose contract changed shape underneath the
pause is caught, not just a different `binding_id` entirely. A changed or
missing binding is therefore structurally incapable of producing an
executable plan under a different identity: the only write of
`pending_execution` is gated on this comparison, and it happens strictly
**before** `pending_execution` is ever constructed (verified on PR #33
review — see `_node_plan_execution`'s own control flow: `plan_allowed` is
recomputed from `final_outcome`/`terminal` before the block that builds
`pending` ever runs).

**`still_incomplete_after_supply` is an invariant/safety guard, not a
normally-reachable branch** (raised explicitly on PR #33 review, kept
deliberately): if `identity_ok` and `schema_ok` both hold, every requested
field name is, by construction, a required field of the (unchanged)
selected binding, and a raw `"supplied"` classification already means every
one of those names has a valid value in the now-merged `execution_inputs`
— so `plan_execution()`'s own missing-field check (§3) cannot find anything
absent, and `fresh.status` must be `"planned"`. No test constructs a real
scenario reaching this branch; it exists only to keep the "never fabricate
a plan" guarantee unconditional rather than dependent on that reasoning
continuing to hold as the codebase evolves.

### 13.6 Confirmed LangGraph API characteristics (empirical, not assumed)

Two findings from building and testing this feature, both confirmed by
direct experimentation against the installed LangGraph, not assumed from
documentation:

- **Interrupt replay:** a node's code before `interrupt()` re-executes on
  every resume (LangGraph matches `interrupt()` calls positionally against
  the checkpoint) — this is why §13.3's read boundary matters; it is the
  first node in this codebase whose pre-interrupt code could otherwise have
  depended on a live, mutable object.
- **`Command(resume=...)` does not reliably deliver a literal empty dict.**
  `Command(resume={})` and `Command(resume=None)` are both **not**
  delivered by the installed LangGraph — the graph silently re-pauses at
  the same interrupt (or, for `None`, raises inside LangGraph's own
  internals) instead of resuming with that value. This contradicts
  `tests/test_workflow.py`'s pre-existing `clarify`-interrupt comment
  ("`Command(resume=None)` itself is unsupported... an empty mapping is the
  correct way to represent 'no answers supplied'") — that comment's second
  half does not hold; `clarify`'s own existing test for this
  (`test_empty_resume_value_produces_no_fabricated_answers`) happens to
  still pass only because it never asserts `"__interrupt__" not in
  resumed`. **Not fixed here** — `clarify`'s behavior is unchanged,
  out of this task's scope — but `provide_execution_inputs`'s own tests
  and `CVAgent.resume_workflow()`'s docstring document the correct,
  actually-deliverable way to signal "declined/cancelled": any non-`dict`
  falsy value (e.g. `""`), not a literal `{}`.

### 13.7 What this does not change

Caller-supplied `pending_execution` precedence (§10) is unaffected:
`planning_result` stays `None` for that path, so `_route_after_planning`
never engages recovery at all. First-pass `"planned"`/
`"no_executable_candidate"`/`"ambiguous_candidates"` routing is unchanged.
`approval_gate`/`execute` are never modified, never auto-approve, and never
run for a terminal recovery outcome — `pending_execution`,
`approval_decision`, and `execution_result` are all guaranteed `None`
whenever `execution_input_recovery["terminal"] is True`. `TRT-perf-analysis`
`input_schema` is deliberately left unpopulated — see 13.8.

### 13.8 TRT `path`/`data` XOR contract — separate open question, not resolved here

Inspected `cv_agent/execution/runtimes/trt_perf_analysis.py::_build_argv()`
directly (not assumed): it requires **exactly one** of `path`/`data` —
`ValueError` if both are given, `ValueError` if neither is given (confirmed
by `tests/test_execution_trt_perf_analysis.py::test_both_path_and_data_raises`
and its neighboring "neither given" test). This is a genuine XOR, not an
unconditional requirement on `path`. `ExecutionBinding.input_schema`'s
`InputField.required: bool` is deliberately flat (ADR-0009 §11) and cannot
express "exactly one of A or B" — marking either field `required=True`
would misrepresent the real contract (`[P§35]`), and marking both
`required=False` would be truthful but never trigger
`"missing_required_inputs"` for this binding at all, since `plan_execution()`
only inspects `required=True` fields. **`trt_perf_analysis.build_binding()`
is not changed by this work** — every test for this feature uses a
synthetic fixture binding with a real `required=True` field, the same
pattern `tests/test_execution_planning_contract.py`'s own pre-existing
`plan_execution()` tests already use. A real, unfaked end-to-end test of
this recovery flow against the actual installed `trt-perf-analysis` binding
remains blocked until a separate, future decision resolves how (or
whether) to extend `InputField`/`input_schema` with an XOR/oneOf construct
— logged as new `docs/state/OPEN_QUESTIONS.md` Q20, not decided here.

### 13.9 Tests

`tests/test_execution_planning_contract.py::TestPlanningResultSelectedIdentity`
(6 tests: populated for `"planned"`/`"missing_required_inputs"`, absent for
`"no_executable_candidate"`/`"ambiguous_candidates"`, empty schema is `()`
not `None`, and — added on PR #33 review —
`test_asdict_preserves_the_full_input_field_contract_per_entry`, a unit-level
proof that `dataclasses.asdict()` keeps all four `InputField` attributes
per entry, not just names). `tests/test_workflow.py::
TestProvideExecutionInputsRecovery` (18 tests: full valid resume reaches
`approval_gate` unchanged including an `approval_required` binding; partial
resume is `"incomplete"`; a field explicitly supplied-but-blank classifies
identically to an omitted one (mixed valid/invalid); all-invalid resume is
`"invalid"`; a LangGraph-deliverable falsy non-dict resume is `"cancelled"`;
a non-mapping resume does not crash; the recovery round never interrupts
twice; `clarification_answers`/`execution_inputs` stay separate; a
different `binding_id` registered under the same `skill_id` during the
pause is detected as `"identity_changed"`; the same `binding_id`
re-registered with a structurally different `input_schema` during the
pause is detected as `"schema_changed"`, even though a plain ID comparison
would have missed it; caller-supplied `pending_execution` never engages
this interrupt; and — added on PR #33 review —
`test_full_input_field_contract_survives_the_real_checkpoint_round_trip`, a
multi-field schema with a real `description`/`default` on each field,
resumed through the real `MemorySaver` checkpoint via `_start()`/`_resume()`
(not an in-memory/mocked shortcut), asserting no false-positive
`"schema_changed"` for a binding that never actually changed). Two
pre-existing tests updated, not rewritten:
`test_one_executable_candidate_populates_pending_execution` (full
`planning_result` dict-equality assertion extended with the three new
fields) and `test_missing_required_input_no_plan_no_execution` (now also
asserts the interrupt this exact fixture triggers, since it no longer
terminates the run directly). Full suite 362 → 381 passing, zero
regressions.

## 14. Status — group-aware planning + recovery, resolving Q20

**Added (branch `feature/claude/q20-input-field-groups`, issue #39).** §13.8
named the gap directly: `trt_perf_analysis.build_binding()` could not honestly
populate `input_schema` for its real `path`/`data` XOR contract, so every §13
test used a synthetic fixture binding with a plain `required=True` field instead
— a genuine, unfaked end-to-end test of the recovery flow against the real
binding stayed blocked. ADR-0009 §12 (same branch) adds the schema-layer type,
`RequiredFieldGroup`, and populates the real binding; this section is the
planning/recovery-layer half of the same decision.

### 14.1 `plan_execution()` becomes group-aware

`ExecutionBinding.input_field_groups` (ADR-0009 §12) is read alongside
`input_schema`: an `"exactly_one"` group is satisfied the moment any one member
name is a key in `available_inputs` — same presence-only posture as an
individual `required=True` field, never a value/type check, never a rejection of
"more than one member supplied" (that stays `_build_argv()`'s job). An
unsatisfied group reports **every** member name in `PlanningResult.missing_inputs`
— not a composite `"path|data"` string — so the shape callers already read
(`tuple[str, ...]`) is unchanged; a caller sees "one of these is missing," which
is what §14.2 below relies on.

`PlanningResult` gains `selected_input_field_groups: tuple[RequiredFieldGroup,
...] | None`, the same checkpointed-snapshot pattern as `selected_input_schema`
(§13.5), set together with it for both `"planned"` and
`"missing_required_inputs"`.

### 14.2 `provide_execution_inputs` recovery becomes group-aware

§13's `_classify_execution_input_resume()` originally required **every**
`requested` name to be answered to reach outcome `"supplied"` — correct for
individually-required fields, but wrong for a group: requiring both `path` AND
`data` to "recover" from a real XOR contract would misrepresent it, and would
make the real binding's recovery flow practically unusable (supplying both
`path` and `data` together is itself invalid per `_build_argv()`). Fixed:
`_classify_execution_input_resume()` gains a `field_groups` parameter — every
still-unsatisfied `RequiredFieldGroup.field_names` from the checkpointed
snapshot (reconstructed in `_node_provide_execution_inputs` as: any group whose
`field_names` are a full subset of `requested`, since an unsatisfied group's
members are, by §14.1's own construction, entirely present in `missing_inputs`)
— fulfillment for a group is "at least one accepted," fulfillment for every
other requested name is unchanged ("that exact name accepted"). The interrupt
payload also gains a `"field_groups"` key (`[{"kind": ..., "field_names": [...]
}]`) alongside the existing `"missing_inputs"`, for a caller/CLI that wants to
render "supply one of path/data" rather than two independent prompts — `python
-m cv_agent workflow` itself is **not** changed to use this (see "Not done"
below); the existing per-field prompt loop already produces a correct resume
dict when a human simply leaves the unwanted field blank, since a blank value
was already filtered out before reaching the classifier (D-025's existing
behavior, unchanged).

### 14.3 Retry-time identity+schema guard extended to groups

`_node_plan_execution`'s recovery-retry comparison (§13.5's "structural, never ID
alone" guarantee) now also compares `expected_input_field_groups` against a
fresh `plan_execution()` call's `selected_input_field_groups` — a binding whose
individual fields are unchanged but whose group constraint was altered or
removed underneath the pause (e.g. `path`/`data` stop being mutually exclusive)
is still caught as `"schema_changed"`, not silently missed by comparing
`input_schema` alone.

One correctness subtlety, found while building this, not anticipated in §13:
`RequiredFieldGroup.field_names` is a tuple field, so it is subject to the exact
same tuple-vs-list checkpoint-round-trip instability ADR-0004's own
`CVAgent._sync_memory_after_run()` docstring already documents for other
`AgentState` tuple fields — `InputField` has no container-typed attributes, so
§13's original `dataclasses.asdict()`-based comparison never had to think about
this. Both sides of the group comparison (the value written into
`execution_input_recovery["expected_input_field_groups"]`, and the value freshly
computed on retry) are now built by explicit dict construction with
`field_names` forced through `list(...)`, never left as whatever
`dataclasses.asdict()` or the checkpoint happened to preserve — otherwise a
binding that never actually changed could false-positive as
`"schema_changed"` purely from a container-type mismatch that carries no real
meaning.

### 14.4 `trt_perf_analysis.build_binding()`

See ADR-0009 §12 for the schema/binding-layer change itself — this section only
notes that it is what makes §14.5's real end-to-end test possible at all.

### 14.5 Genuine, unfaked end-to-end test against the real binding

The gap §13.8 named as blocked is now closed:
`tests/test_execution_trt_perf_analysis.py::TestRealPlanningAndRecovery`
(`@requires_real_skill`, skipped — not faked — when the real skill isn't
installed) exercises `CVAgent.start_workflow()`/`.resume_workflow()` against the
real, registered `trt-perf-analysis` binding: (1) pre-supplying only `path` via
`execution_inputs` reaches `"planned"` and a real, completed subprocess
execution; (2) supplying nothing at all triggers the real
`provide_execution_inputs` interrupt, whose payload names both `path` and `data`
plus the `field_groups` entry, and resuming with only `data` (the other XOR
member — not the one used in test 1) reaches outcome `"supplied"`, a produced
plan, and a real, completed subprocess execution. Neither test uses a fixture
binding or a fake runtime.

### 14.6 What this does NOT do

- Does not add "reject if more than one group member is supplied" at the
  planning or recovery-classification layer — stays `_build_argv()`'s job,
  unchanged, per ADR-0009 §12's own stated scope.
- Does not change `python -m cv_agent workflow`'s CLI prompt UX to mention
  groups explicitly — the existing per-field prompt loop already produces a
  correct answer for a group when a human leaves the unwanted field blank
  (§14.2); a friendlier "choose one of path/data" prompt is a CLI-layer UX
  improvement, not required for the recovery mechanism itself to be correct,
  and was left out to keep this change scoped to the planning/recovery
  contract.
- Does not touch Q18 (ambiguous-candidate disambiguation) — a separate,
  independently-decided open question with its own future issue.

### 14.7 Tests

**Per-file counts below corrected on PR #40 review** (verified directly against
`git diff` rather than estimated — the original text's per-file breakdown did
not reconcile against the actual diff, though its aggregate total happened to;
see §15.7 for the review-correction pass's own, separately-counted tests):

8 new tests in `tests/test_execution_planning_contract.py` (one renamed —
`test_existing_trt_perf_analysis_binding_declares_its_real_contract`, the real
binding's now-populated schema — plus 7 genuinely new: group satisfied by
either member, unsatisfied group reports both names, "both supplied" still
satisfied at this first version's planning layer — since corrected, see §15 —
group + individually-required field enforced together, the real binding's
neither-supplied case reports both names, and `selected_input_field_groups`
populated for both the "planned" and "missing_required_inputs" statuses); 5
new tests in `tests/test_workflow.py::TestProvideExecutionInputsRecovery` (interrupt
payload names every member and the group itself, supplying only one member
recovers as `"supplied"`, supplying neither is `"invalid"`, a group satisfied
but a separate individually-required field still missing is `"incomplete"`, a
group silently removed underneath the pause is detected as `"schema_changed"`)
plus one pre-existing test (`test_one_executable_candidate_populates_
pending_execution`) updated for the new `selected_input_field_groups` key; 9
new tests in `tests/test_execution.py` (`RequiredFieldGroup`/`ExecutionBinding`
construction-time validation — undeclared name, individually-required
contradiction, frozen/shape checks, defaults) plus 1 new test in
`tests/test_execution_trt_perf_analysis.py` (real schema shape, non-skipped);
2 new `@requires_real_skill` tests in `tests/test_execution_trt_perf_analysis.
py::TestRealPlanningAndRecovery` (§14.5). Total: 25 new `def test_` additions,
1 renamed (net 24 new test functions, matching the reported 405 → 429 full
suite delta exactly).

## 15. Status — true oneOf/XOR correction (review finding on PR #40)

**Added (branch `feature/claude/q20-input-field-groups`, same PR #40, before
merge).** An independent review of §14's first implementation, explicitly
re-verifying every claim rather than trusting the PR description, found that
§14's `plan_execution()`/recovery-classifier check — "a group is satisfied the
moment ANY one member has a known value," deliberately never rejecting "more
than one supplied" — did not fully satisfy the Q20 decision as stated: "Use a
declarative oneOf/XOR field-group construct. The intended semantics are
EXACTLY ONE alternative, not merely at least one." §14's version would let a
human/caller supply both `path` and `data` together, produce a `"planned"`
result, and — for a hypothetical future `approval_required` grouped binding —
reach a real human approval interrupt for an input combination guaranteed to
fail at the runtime. This section closes that gap: enforcement moves from
"presence" to "exactly one," checked and reported before any plan, approval,
or execution is ever attempted, for both the first-pass and the recovery-retry
path. See ADR-0009 §13 for the companion schema-layer fix (group-membership
overlap validation) done in the same pass.

### 15.1 `plan_execution()`: `"conflicting_inputs"`, a new `PlanningStatus`

`PlanningStatus` gains `"conflicting_inputs"`: for each `RequiredFieldGroup`,
`plan_execution()` now counts how many of its members are present in
`available_inputs` — zero is (unchanged) folded into `"missing_required_
inputs"`, exactly one is satisfied, two or more is `"conflicting_inputs"`.
Checked and returned *before* `"missing_required_inputs"` even when both would
otherwise apply to different fields/groups of the same candidate — a
contradictory answer needs correcting regardless of what else is missing.
`PlanningResult` gains `conflicting_inputs: tuple[str, ...]`, the exact member
names that were supplied together, sorted; never populated alongside
`missing_inputs` in the same result (one field per status, mirroring how
`candidate_skill_ids` is scoped to `"ambiguous_candidates"` alone).
`selected_skill_id`/`selected_binding_id`/`selected_input_schema`/
`selected_input_field_groups` are populated for `"conflicting_inputs"` too —
the same three-statuses-now pattern §13/§14 already established for
`"missing_required_inputs"`.

Still presence/count only, never value/type validation:
`TrtPerfAnalysisRuntime._build_argv()` remains the sole authoritative check of
a field's actual *content* — this layer cannot and does not replace it, it
only moves the *count* check (which needs no knowledge of a field's meaning)
earlier, before any plan is ever produced.

### 15.2 `provide_execution_inputs` recovery: a new `"conflicting"` outcome

`_classify_execution_input_resume()`'s fulfillment rule tightens from "any one
group member accepted" to "exactly one" — two or more accepted together for
the same group now returns outcome `"conflicting"` (a new value in that
function's own return vocabulary, distinct from — never conflated with —
`PlanningStatus`'s `"conflicting_inputs"`, the same two-vocabulary separation
`"supplied"`/`"planned"` etc. already have). `_node_provide_execution_inputs`
also computes and records `execution_input_recovery["conflicting"]` (a new
key, sibling to `"still_missing"`) — the member names actually supplied
together — the moment the interrupt resumes, not deferred to the retry,
consistent with `"still_missing"`/`"rejected"` already being computed there
rather than left for later.

**A real, reachable edge case found and fixed here, not merely theoretical:**
`_classify_execution_input_resume()`'s own `field_groups` parameter only
covers groups *reconstructed from `requested`* — groups the interrupt payload
actually asked about, i.e. groups that were entirely unsatisfied at plan time.
A resume payload may legally name any declared field, not only requested
ones (accepted, not rejected, by that function's own existing rule); if it
supplies the *other* member of a group already satisfied by an earlier
round's `execution_inputs`, the per-round classify call has no visibility into
that combination at all and reports `"supplied"`. `_node_plan_execution`'s
retry — which always re-derives everything via a fresh `plan_execution()`
call against the fully merged `execution_inputs` — still catches it, since
that function has no notion of "requested" at all, only "present." A new,
explicit branch (checked before the pre-existing "not planned" invariant
guard, itself updated to note this is no longer purely theoretical) maps
`result.status == "conflicting_inputs"` on retry to outcome `"conflicting"`,
`terminal=True`, `mismatch_detail="conflicting_inputs_supplied"` — labeled
precisely, not folded into the generic `"still_incomplete_after_supply"`
catch-all. Exercised by `tests/test_workflow.py::
TestProvideExecutionInputsRecovery::
test_conflict_introduced_by_an_unsolicited_extra_field_is_still_caught`.

### 15.3 Routing: no new interrupt kind

`"conflicting_inputs"` deliberately does **not** get its own interrupt or
recovery round — it is not "missing information to ask for," it is "a
contradiction to remove." `_route_after_planning`'s existing first-pass
fallthrough (`return "approval_gate"`, unchanged) already handles it exactly
like `"ambiguous_candidates"`/`"no_executable_candidate"`: no
`pending_execution` is ever set, so `approval_gate` no-ops to
`approval_decision = "not_required"`, `status = "done"`, without interrupting
or executing anything. On the recovery-retry path, a `"conflicting"` `raw_
outcome`/finalized `final_outcome` is `terminal=True`, routing straight to
`END` via the pre-existing terminal-outcome check — never reaching
`approval_gate` at all on that path, an even stricter guarantee. Neither path
required any change to `_route_after_planning` itself. This deliberately does
**not** expand into Q18 (ambiguous-candidate disambiguation) — a separate,
independently-decided open question, untouched here.

### 15.4 `ExecutionBinding.__post_init__`: group-membership overlap

See ADR-0009 §13 — the schema-layer half of this same review pass, done
together since the review found both gaps in the same read-through.

### 15.5 Documentation corrections

- `docs/state/STATUS.md` was 64 lines against its own documented 60-line hard
  cap (`CLAUDE.md` §7) — rewritten to fit within it.
- §14.7's per-file test-count breakdown did not reconcile against the actual
  diff (its aggregate total of 25 happened to be correct; the four per-file
  numbers did not sum to how the tests were actually distributed) — corrected
  above, verified directly against `git diff` rather than re-estimated.

### 15.6 What this does NOT do

- Does not add a "choose one" interrupt for the conflicting case — see §15.3.
- Does not touch `python -m cv_agent workflow`'s CLI — unaffected either way,
  since it already relies on `payload["missing_inputs"]` alone and a
  conflicting-inputs run never reaches the `provide_execution_inputs`
  interrupt in the first place (§15.3).
- Does not revisit Q18 or any other open question — out of scope for this
  correction, per explicit instruction.

### 15.7 Tests

9 new `def test_` additions, 1 renamed (net 8 new test functions, matching the
reported 429 → 437 full suite delta exactly): 2 in
`tests/test_execution_planning_contract.py`
(`test_supplying_both_group_members_together_is_conflicting_inputs` — a
rename/rewrite of §14's now-incorrect `..._still_satisfies_the_group` test —
plus `test_conflict_takes_priority_over_a_separate_missing_required_field`,
new); 3 in `tests/test_workflow.py::TestPlanExecutionIntegration`/
`TestProvideExecutionInputsRecovery`
(`test_conflicting_pre_supplied_inputs_reject_before_approval_or_execution`,
first-pass; `test_supplying_both_group_members_at_the_interrupt_is_
conflicting`, direct recovery; `test_conflict_introduced_by_an_unsolicited_
extra_field_is_still_caught`, the §15.2 edge case) plus one pre-existing test
(`test_one_executable_candidate_populates_pending_execution`) extended for the
new `conflicting_inputs` key; 2 in `tests/test_execution.py`
(`test_field_belonging_to_two_groups_is_rejected`,
`test_two_disjoint_groups_are_still_accepted` — proving the overlap check
rejects only actual sharing, not every multi-group binding); 2 in
`tests/test_execution_trt_perf_analysis.py::TestRealPlanningAndRecovery`
(`test_pre_supplying_both_path_and_data_together_is_rejected_before_
execution`, `test_recovery_supplying_both_path_and_data_together_is_
rejected_before_execution` — both against the real binding, both asserting
`execution_result is None`, proving the real subprocess is never invoked).
Full suite 429 → 437 passing, zero regressions; `ruff`/`mypy` clean on every
touched file except the same pre-existing findings already documented in §14
(unchanged line-content, only shifted by inserted lines — confirmed via `git
diff` against `main`), plus the one new `"__interrupt__"` TypedDict-gap finding
§14 already disclosed, which remains the same single occurrence (not
multiplied by these new tests, which all use `assert ... is not None`
narrowing before indexing).


## 16. Status — ambiguous-candidate disambiguation (`choose_candidate`), resolving Q18

**Added (branch `feature/claude/q18-candidate-disambiguation`, issue #41).**
§3 step 5 (and §8's own "not decided" note) deliberately produced *no plan*
when more than one executable candidate matched, surfacing them only via
`planning_result.candidate_skill_ids` — nothing ever asked anyone to choose.
The owner decided Q18 directly (2026-09-18, asked alongside Q20): **a
clarification-style interrupt**, explicitly *not* a CLI `--skill <id>`
override. This section implements it. Q20's own PR (#40) intentionally left
Q18 unbuilt; nothing here depends on or changes Q20's group/XOR machinery.

### 16.1 `plan_execution()`: `selected_skill_id` + `candidate_descriptions`

`plan_execution()` gains one optional keyword, `selected_skill_id: str | None
= None`. It is consulted **only** when more than one candidate survives step 1–2:
if it names one of them, that candidate is selected and *everything after
selection is the identical code path* as if it had been the sole candidate
(input completeness, XOR checks, plan construction) — the disambiguation
path never duplicates or forks that logic. `None`, or a value naming no
current candidate, changes nothing: `"ambiguous_candidates"` is returned as
before. The function never treats an unrecognized choice as a default, and
ignores the parameter entirely when there is exactly one candidate.

`PlanningResult` gains `candidate_descriptions: tuple[str, ...]`, parallel
(same order, same length) to `candidate_skill_ids`, populated only for
`"ambiguous_candidates"`. The source is each candidate's
`ExecutionBinding.description`, deliberately not `Skill.description`
(`SKILL.md` frontmatter): `plan_execution()`'s only dependencies are
`RequirementsAnalysis` and `ExecutionBindingRegistry`, and reading `Skill`
would mean also depending on `SkillInventory` — a boundary this function has
never crossed. The snapshot is captured once, at plan time, so the interrupt
never needs a live lookup (§16.3).

### 16.2 The interrupt: `choose_candidate`

A new node, inserted on the same `plan_execution` fan-out as
`provide_execution_inputs`, and checked **first** in `_route_after_planning`:
`plan_execution()` cannot even evaluate a candidate's input completeness until
exactly one candidate is selected, so unresolved ambiguity always takes
routing priority.

```
plan_execution ──ambiguous_candidates AND selection not yet attempted──> choose_candidate
      ^                                                                        │
      └──────────────────── plain edge, always loops back ─────────────────────┘
```

- **Payload:** `{"type": "choose_candidate", "candidates": [{"skill_id": ...,
  "description": ...}, ...]}` — every offered candidate's ID and description.
- **Resume value:** a bare `skill_id` string (like `approval_gate`'s bare
  `"approved"`/`"rejected"`; this is a single choice, not a key/value set).
- **Classification** (`_classify_candidate_choice`, deterministic): not a
  non-blank string → `"cancelled"` (never coerced — a dict, `0`, `None`,
  `""` are all cancelled); a string, after `strip()`, not *exactly* in the
  offered set → `"invalid"` (no case folding, no prefix/"closest match", no
  fallback candidate); otherwise `"selected"`.
- **Persistence:** a `"selected"` choice is written to `AgentState.
  candidate_choice` (a namespace distinct from `execution_inputs`/
  `clarification_answers` — a `skill_id` is a different kind of thing than an
  `InputField.name`); the full record goes to `AgentState.
  candidate_selection` (`attempted`, `outcome`, `terminal`,
  `expected_candidate_skill_ids`, `chosen_skill_id`). `candidate_choice` is
  never set for an invalid/cancelled answer.
- **One shot:** `candidate_selection["attempted"]` bounds this to exactly one
  interrupt/resume round per run, the same explicit-flag pattern
  `clarification_attempted` and `execution_input_recovery["attempted"]`
  already use. An invalid, cancelled, or no-longer-valid choice is
  `terminal=True`, routes straight to `END` (bypassing `approval_gate`,
  same "a failed recovery can never read as approval-not-required" rule as
  §13), and sets `status="done"`. There is never a second prompt and never a
  default candidate.

### 16.3 Replay safety and the retry's authoritative re-check

Everything `choose_candidate` reads *before* `interrupt()` comes only from
the already-checkpointed `planning_result` — never a live
`ExecutionBindingRegistry` lookup — for the same reason §13 documents
(LangGraph re-runs a node's pre-interrupt code on resume).

The interrupt node's `"selected"` only proves the choice matched what was
*offered*; it says nothing about whether the choice still resolves anything
*now*. So `terminal` is left `None` there and finalized only by
`_node_plan_execution`'s retry, which re-runs `plan_execution(...,
selected_skill_id=candidate_choice)` against the current registry and
requires `result.selected_skill_id == chosen_skill_id`. Anything else is
`"candidate_mismatch"`, terminal. **This must be an identity check, not
merely "still ambiguous?"**: if the chosen skill's binding is deregistered
during the pause, only the *other* candidate remains; `plan_execution()` then
sees exactly one candidate and would plan it — silently running a skill the
human never chose. (Found while writing the retry logic, before any test was
written; pinned by `test_chosen_skill_deregistered_during_the_pause_never_
falls_back_to_the_other`, which was mutation-checked: with the identity check
weakened to an "is it still ambiguous?" test, it fails.)

### 16.4 Composition with the other recovery kinds

`_node_plan_execution` previously gated its recovery-finalization block on
`recovery.get("attempted") is True` alone. That was safe only because the old
topology never re-entered the node after `execution_input_recovery` was
finalized. With two independent recovery kinds a run can now visit the node
several times (ambiguous → choose → retry finalizes candidate selection →
missing input → provide inputs → retry finalizes input recovery), so both
finalization blocks are now gated on `attempted is True AND terminal is
None` — each round is finalized exactly once and never re-finalized by a later
retry. For every pre-existing test this gate is behavior-preserving
(`_node_provide_execution_inputs` always writes `terminal: None`, so the
first retry always satisfies it). If the chosen candidate then needs inputs,
the chain continues into `provide_execution_inputs` as before, with its own
identity/schema guard (§13) also catching a mid-pause candidate swap.

### 16.5 What is deliberately unchanged

- **Caller-supplied `pending_execution`** (§10) is still checked first in
  `_node_plan_execution`, before any planning: no `planning_result`, no
  disambiguation, no interrupt, even when several candidates are in play.
- **`python -m cv_agent execute <skill_id>`** (ADR-0009 §10) is a separate code
  path that never touches `plan_execution()` or the workflow graph.
- **Exactly one candidate** never raises the interrupt.
- **`approval_gate`'s policy is untouched**: choosing a skill is not
  approving it — an `approval_required` chosen candidate still reaches the
  approval interrupt (tested).
- **No `--skill` flag and no pre-supply channel** — the owner chose the
  interrupt design over an override; `start_workflow()` gained no parameter.
  It only initializes the two new state keys to `None`.

### 16.6 CLI

`python -m cv_agent workflow` handles the new kind: it prints every candidate
and prompts for the `skill_id`; a blank/EOF answer resumes with `""`
(classified `"cancelled"`), and `--approve` is never read as a candidate
choice. `_print_workflow_summary` reports `Candidate selection: outcome=…
terminal=… chosen=…`. `_MAX_INTERRUPT_ROUNDS` (8) already covers the new
maximum of four interrupt kinds; its and `_run_workflow_interactive`'s
docstrings now say four. `_cmd_workflow` still registers no execution
binding, so the interrupt remains unreachable through that command against
any real installed skill today — exactly the documented posture of
`provide_execution_inputs`/`approval_gate` (only one real binding exists) —
and is exercised through fixture-graph-backed tests instead.

### 16.7 Tests

31 new tests, no test deleted (one dict-equality assertion in
`test_one_executable_candidate_populates_pending_execution` extended for the
new `candidate_descriptions` key). `tests/test_execution_planning_contract.py::
TestCandidateDisambiguationSelection` (7: descriptions parallel to sorted IDs;
a valid selection resolves ambiguity; an unoffered ID is ignored, never a
default; `None` never picks; the selected candidate still gets input-
completeness checks; irrelevant with a single candidate; a non-executable
skill cannot be selected). `tests/test_workflow.py::TestChooseCandidateInterrupt`
(16, real compiled graph + real `MemorySaver`: payload lists every ID and
description; either candidate can be chosen and only it runs; whitespace
tolerated; 7 parametrized invalid/cancelled answers — unknown ID, prefix, wrong
case, `""`, whitespace, a dict, `0` — all terminal, nothing executed, no
second interrupt, `approval_gate` bypassed; mid-pause deregistration →
`candidate_mismatch`; chosen candidate then missing inputs chains into
`provide_execution_inputs` with the candidate round *not* re-finalized;
`approval_required` choice still reaches approval; caller-supplied
`pending_execution` bypasses disambiguation; a single candidate never
interrupts) plus `TestChooseCandidateThroughCVAgent` (2, the real `CVAgent`
API with real skill discovery and durable memory). `tests/test_cli_workflow.py::
TestChooseCandidateCli` (6). Full suite 437 → 468 passing, zero regressions;
`ruff` and `mypy` on every touched file show exactly the findings `main`
already has (compared directly against a disposable `git worktree` of `main`).
