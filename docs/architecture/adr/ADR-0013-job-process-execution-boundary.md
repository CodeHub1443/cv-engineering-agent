# ADR-0013: Job / Process Execution Boundary (scope, Proposed)

- **Status:** Proposed — scope and constraints only, recorded from an owner decision.
  No protocol/interface design, no implementation. Not yet accepted for build.
- **Date:** 2026-09-28
- **Layer:** execution
- **Canon:** `[P§10]`, `[P§13]`, `[P§24]`, `[P§34]`
- **Supersedes / Superseded by:** —
- **Issue:** #63

## 1. Context

D-040 (2026-09-24, `docs/state/DECISIONS.md`) decided *that* V1 runs on a local
Linux/NVIDIA GPU execution host with the Agent/controller process and CV workload
processes **separate** — training, evaluation, benchmarking, and optimization execute
as controlled jobs/processes, never in-process inside the Agent. D-040 explicitly named
what it left open: "a job start/monitor/cancel lifecycle design" is the future
training-execution ADR's job, not D-040's own. D-044 (2026-09-28) confirmed the host
class (Linux + NVIDIA GPU) without naming a concrete machine, and without changing
D-040's architecture beyond recording that confirmation.

No such lifecycle design exists yet. The only real execution boundary in the codebase
today is ADR-0009's `ExecutionRuntime` protocol (`cv_agent/execution/binding.py`):
`invoke(skill, request) -> RuntimeOutcome` is **synchronous** — it runs to completion
and returns — and its one real, verified binding (`trt-perf-analysis`, D-014) wraps a
short, deterministic, read-only script. `SkillExecutionStatus` (`cv_agent/execution/
models.py`) reserves a `"started"` value for "handed to the runtime but not yet
resolved... reserved for a future asynchronous/long-running runtime," but nothing
implements that reservation, and nothing in `cv_agent/execution/` names *where* a
runtime executes or verifies the host before running a platform-specific command
(`docs/APPROVALS.md`'s "Platform-sensitive actions" rule; `spec/11-platform-detection-
and-optimization.md` describes this need but has no code and no ADR).

The owner has now decided the shape this boundary must take at a **scope** level — this
ADR records that scope decision. It deliberately does not attempt the protocol-level
design (whether the boundary is a new sibling protocol, an extension of
`ExecutionRuntime`, or a supervisor sitting in front of it) — that is out of scope for
the task that produced this ADR, per its own explicit instruction not to design or
implement beyond recording the decision.

## 2. Responsibility (required — `[P§34]`)

- **This owns (at scope level; not yet a designed interface):** that a controlled CV
  workload (train / benchmark / optimize / evaluate) runs as a **separate OS process**
  on the Linux/NVIDIA execution host, under the Agent/controller's supervision, and that
  supervision must eventually be able to: launch it under control, monitor its progress,
  cancel it, observe its exit status, capture its stdout/stderr, capture
  runtime/resource metadata (at minimum whatever `docs/state/EXPERIMENTS.md`'s
  `hardware`/`train_time`/`gpu_hours`/`latency`/`memory`/`power` fields need), and
  collect the artifacts it produces.
- **This does NOT own (yet, or ever, per this decision):**
  - the protocol/interface shape — new type, new method on `ExecutionRuntime`, or a
    supervisor layer — deferred to a follow-up architect session (§8);
  - Kubernetes, distributed workers, or any remote/cloud execution — explicitly
    excluded from V1 by this decision, not merely undecided;
  - a specific host/GPU identity — D-044, untouched;
  - approval-pin semantics for a long-running action — ADR-0003 §10 / ADR-0009 §14
    already solved this for a *synchronous* call; whether that pin model generalizes to
    a job that outlives a single `interrupt()`/`Command(resume=...)` round-trip is an
    open question this ADR does not answer (§8);
  - cost estimation or thresholds — Q6/Q19, D-047's narrow first-baseline exception
    aside, untouched;
  - what model/dataset/metrics a job actually runs — D-043 (Q24), untouched;
  - the skill-specific execution chain `Skill → ExecutionBinding → ExecutionRuntime` —
    ADR-0009, unchanged; this ADR's eventual design must state its relationship to that
    chain explicitly rather than silently duplicating or bypassing it (§8).
- **Why this responsibility does not belong to an existing component:** ADR-0009's
  `ExecutionRuntime.invoke()` is synchronous and was designed and verified for exactly
  one short, deterministic, read-only skill (`trt-perf-analysis`) — it has no concept of
  "still running," no subprocess-supervision primitives, and no host-verification step.
  Stretching it silently to also mean "launch and supervise a real-time detection
  benchmark on a GPU for an unknown duration" would misrepresent what was actually
  verified for it, the same kind of concept-collapse ADR-0005 §2 named and refused for
  tools-vs-skills. A new, explicitly scoped boundary — even while its final shape is
  still open — is the honest placement.

> This section is answered at the scope level only: the new responsibility is named and
> distinguished from ADR-0009's, but the interface that will own it is not yet designed.
> Per `CLAUDE.md` §5, no architectural code follows until that design exists and this
> ADR (or a revision of it) is Accepted.

## 3. Decision

Record the owner's scope decision for V1's job/process execution boundary:

1. **Controlled local subprocess jobs.** CV workloads execute as separate OS processes
   on the Linux/NVIDIA execution host (D-044) — never as in-process function calls
   inside the Agent/controller, and never submitted to a remote scheduler.
2. **The boundary must eventually support:** controlled launch, monitoring,
   cancellation, exit status, stdout/stderr capture, runtime/resource metadata, and
   artifact collection. These are named as required capabilities of whatever the
   eventual design produces — not, themselves, a designed API.
3. **Explicitly excluded from V1:** Kubernetes, distributed workers, remote execution.
   A future scheduler remains conceivable (D-040 already left it open) but is not V1
   scope, and nothing built against this ADR should assume it is coming.
4. **This ADR does not authorize implementation.** No protocol is defined, no interface
   stub is written, no code changes. It exists so the scope is recorded honestly and so
   a future architect session has a named starting point instead of re-deriving it from
   D-040/D-044/D-046 scattered across `DECISIONS.md`.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Extend `ExecutionRuntime`/`SkillExecutionStatus`'s existing `"started"` reservation in place, no new ADR | Smallest diff; the reservation already exists | ADR-0009's boundary was verified for one short, synchronous, read-only skill; silently repurposing it for a long-running GPU job is exactly the concept-collapse §2 warns against, and the owner's decision explicitly frames this as its own boundary | Would misrepresent what ADR-0009 actually verified |
| Design the full protocol now, in this same task | Would unblock implementation sooner | The task that produced this ADR explicitly instructs "do not implement... beyond recording the decisions and the minimum required ADR/decision documentation"; the pin-model and host-verification questions (§8) are non-trivial and deserve their own dedicated design pass, the same way ADR-0005's first draft went through an explicit architecture review before acceptance | Out of scope by explicit instruction; premature relative to unresolved design questions |
| Treat this as a pure decision record (like D-040/D-041/D-042), no ADR file at all | Matches the "no ADR: not architectural" pattern used for Q24/Q25/Q10 elsewhere in this same batch | Unlike those, this decision *does* introduce a new module and a new state shape (job status/lifecycle) per `CLAUDE.md` §5's own definition of architectural — recording it as a plain decision row would misclassify it | Fails the CLAUDE.md §5 architectural test |

## 5. Interface

**Deliberately deferred — not decided at this stage.** The owner's decision fixed scope
and constraints (§3), not a protocol shape. Per `CLAUDE.md` §5, architect mode produces
"the ADR and interface stubs only," but that presupposes the interface has actually been
designed; here it has not, and the task that produced this ADR explicitly scoped itself
to recording the decision, not designing or implementing the boundary. A follow-up
architect session must resolve, before any interface is written:

- Does a job extend `ExecutionRuntime` (new method(s), new status values used for real)
  or is it a distinct, sibling protocol invoked from a different call site?
- How does `docs/APPROVALS.md`/ADR-0003 §10's approval-pin model — designed and
  hardened (D-030/D-032) for a *synchronous* action — extend to an action that starts,
  runs, and terminates across possibly many `interrupt()`/`Command(resume=...)` rounds?
- Where does host verification (Linux + NVIDIA GPU, per D-044) run, and what does it do
  on mismatch — refuse, per `docs/APPROVALS.md`'s "Platform-sensitive actions" rule?
- How does a terminal job outcome become an `ExperimentRecord` (ADR-0011) — is that
  wiring part of this boundary or a separate, later amendment (mirroring D-020's
  project-memory wiring pattern)?

## 6. Consequences

- **Enables:** a named place for the design work D-040 deferred to happen, once
  authorized — Phase 5b (baseline establishment) is otherwise blocked on exactly this.
- **Makes harder:** nothing yet — no code exists to be made harder.
- **Costs:** zero today — this ADR records scope only, no code.
- **Migration / blast radius if reversed:** none — nothing depends on this ADR yet.

## 7. Acceptance test

None yet — no implementation exists. A future revision of this ADR (or the ADR it is
superseded by, once the protocol design above is resolved) must define one before any
code is written, per `CLAUDE.md` §6 ("write the acceptance test first").

## 8. Revisit trigger

- The §5 protocol-shape question is resolved by a dedicated architect session —
  supersede or substantially revise this ADR with the actual interface, mirroring how
  ADR-0005's first draft (D-035) was revised into its accepted form (D-036) after
  review.
- A concrete host/GPU is provisioned and named (narrows D-044).
- The approval-pin-for-long-running-actions question is answered (may itself need an
  ADR-0003/ADR-0009 amendment, not only a change here).
- The first real baseline job (Q24's Person Detection + Tracking reference project) is
  actually attempted and this scope proves too narrow or too wide.
