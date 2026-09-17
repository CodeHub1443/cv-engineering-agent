# ADR-0010: Execution-planning contract (RequirementsAnalysis → ExecutionPlan)

- **Status:** Accepted — `plan_execution()` and the `plan_execution` graph node
  are implemented and wired into `build_requirements_workflow_graph()` (see
  §9, §10); structured `AgentState.planning_result` observability is
  implemented too (see §11); an explicit, pre-supplied execution-input
  channel is implemented too (see §12)
- **Date:** 2026-09-16
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
- **Narrowed by §12, not fired:** the "missing required input → no plan" V1
  default (§3) is judged too silent in practice **for a caller who did not
  know the value in advance.** §12 already closes the sub-case of a caller
  who *does* know it ahead of time. What remains open is a caller who only
  learns the value after seeing `planning_result.status ==
  "missing_required_inputs"` and has no way to resume the same run with it —
  the natural extension is still a third interrupt kind
  (`provide_execution_inputs`), architecturally consistent with the existing
  `clarify` interrupt but a distinct product decision — logged in
  `docs/state/OPEN_QUESTIONS.md` Q17, not decided here.
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
