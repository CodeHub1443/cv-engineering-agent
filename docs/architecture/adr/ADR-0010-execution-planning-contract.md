# ADR-0010: Execution-planning contract (RequirementsAnalysis → ExecutionPlan)

- **Status:** Proposed — types/interface only, no behavior implemented (see §9)
- **Date:** 2026-09-16
- **Layer:** orchestration
- **Canon:** `[P§19]`, `[P§21]`, `[P§22]`, `[P§24]`, `[P§34]`, `[P§35]`
- **Supersedes / Superseded by:** — (extends ADR-0003 §3's graph topology and
  ADR-0009 §3's `ExecutionBinding`; supersedes neither)
- **Issue:** #TBD

> **Note on numbering:** `docs/roadmap/ROADMAP.md` (Phase 5) aspirationally
> reserved "ADR-0010" for a future *training-execution* ADR, and "ADR-0009" for
> a future *dataset-subsystem* ADR that never happened — ADR-0009 was actually
> assigned to skill-execution-boundary instead when it was actually written.
> This repo's real practice, evidenced by that exact prior collision, has never
> been to honor the roadmap's speculative pre-allocation; each ADR gets the
> next number free in `docs/architecture/adr/` at the time it is actually
> written. This ADR follows that same precedent — `0010` is the next unused
> file number, not a claim on the roadmap's training-execution topic. Flagged
> here, not silently resolved; a human may choose to renumber either this ADR
> or the roadmap's Phase 5 bullet.

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

- **Enables:** a concrete, typed contract a future implementation PR can
  build `plan_execution` against without re-deriving the shape question;
  unblocks writing that PR's own ADR-0003-topology-extension and its tests
  against a stable target.
- **Makes harder:** nothing removed; purely additive types.
- **Costs:** one new module (`cv_agent/graph/planning.py`, ~30 lines, one
  dataclass, no logic), one new dataclass in `cv_agent/execution/binding.py`
  (ADR-0009 §11), no new dependency.
- **Migration / blast radius if reversed:** contained — `ExecutionPlan` is
  referenced by nothing yet (no node, no CLI command, no test beyond a shape
  check); removing it touches no other module. `ExecutionBinding.input_schema`
  defaults to `()`, so every existing construction site (exactly one:
  `trt_perf_analysis.build_binding()`) is unaffected whether or not it is
  ever populated.

## 7. Acceptance test

This step's own acceptance test is necessarily narrow — it proves the
*contract types* are real, constructible Python with the exact declared
shape, not that any selection/planning *behavior* works (none is implemented
— see §9). `tests/test_execution_planning_contract.py` (new): `ExecutionPlan`
constructs with exactly the four documented fields and is frozen/immutable;
`InputField`/`ExecutionBinding.input_schema` construct with the documented
shape and default to an empty tuple, preserving every existing
`ExecutionBinding` construction site unchanged (see ADR-0009 §11's own
acceptance-test note). The **behavioral** acceptance test — selection rule,
input-completeness check, graph routing, `pending_execution` materialization
— is explicitly deferred to the implementation PR this ADR unblocks (§9).

## 8. Revisit trigger

- When the implementation PR is actually written (§9) — at that point this
  ADR's §7 gains its real, behavioral acceptance test, and this ADR is
  amended (a dated "Status" section, matching ADR-0009 §9/§10's own pattern)
  rather than superseded.
- When the "ambiguous — no silent selection" case (§3, step 4) needs a real
  resolution mechanism — an explicit human/CLI disambiguation choice, most
  likely — logged in `docs/state/OPEN_QUESTIONS.md`, not decided here.
- When the "missing required input → no plan" V1 default (§3) is judged too
  silent in practice — the natural extension is a third interrupt kind
  (`provide_execution_inputs`), architecturally consistent with the existing
  `clarify` interrupt but a distinct product decision — logged in
  `docs/state/OPEN_QUESTIONS.md`, not decided here.
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
  for the PR that will implement §9's node: LLM-assisted selection (deferred
  — see §1/§2's deterministic-only V1 rule; a future LLM role, if any, would
  be prose-explanation-only or a proposed-value-requiring-explicit-
  confirmation, mirroring `RequirementField.source == "caller_assumption"`
  exactly, never a silent authority over `approval_decision` or selection).

## 9. Status

**Types/interface only (this change).** `cv_agent.graph.planning.ExecutionPlan`
and `cv_agent.execution.binding.InputField`/`ExecutionBinding.input_schema`
(ADR-0009 §11) exist as real, tested-for-shape Python types. **Not
implemented:** the `plan_execution` node itself, any change to
`build_requirements_workflow_graph()`'s topology or routing, any change to
`approval_gate`/`execute`, any CLI command, any selection/input-completeness
logic. `AgentState.pending_execution` is unchanged — still populated only by
an explicit caller argument to `start_workflow()`, exactly as before this ADR.
A future implementation PR builds the node against this contract and amends
this section.
