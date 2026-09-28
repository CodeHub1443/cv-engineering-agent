# ADR-0013: Job / Process Execution Boundary

- **Status:** Accepted
- **Date:** 2026-09-28 (scope, Proposed); revised 2026-09-28 (full design, Accepted)
- **Layer:** execution
- **Canon:** `[P§10]`, `[P§13]`, `[P§24]`, `[P§34]`
- **Supersedes / Superseded by:** —
- **Issue:** #63 (scope); #65 (design — this revision)

---

## 1. Context

D-040 (2026-09-24) decided *that* V1 runs on a local Linux/NVIDIA GPU execution host
with the Agent/controller process and CV workload processes **separate** — training,
evaluation, benchmarking, and optimization execute as controlled jobs/processes, never
in-process inside the Agent. D-040 explicitly named what it left open: "a job
start/monitor/cancel lifecycle design" is the future training-execution ADR's job. D-044
(2026-09-28) confirmed the host class (Linux + NVIDIA GPU) without naming a concrete
machine.

The first version of this ADR (Proposed, scope only, Issue #63) recorded the scope
decision and identified three open protocol-shape questions, explicitly deferring them
to "a dedicated architect session." This revision IS that architect session.

### What was read before designing

The following were inspected directly (not assumed):

- `cv_agent/execution/binding.py` — `ExecutionRuntime` (Protocol), `ExecutionBinding`,
  `ExecutionBindingRegistry`, `pin()`, `pin_mismatch()`, `canonical_json()`,
  `_pin_shape_ok()`.
- `cv_agent/execution/executor.py` — `SkillExecutor.execute()`, the full approval/pin
  check flow (E1 rule, binding mismatch, policy rejected, approval_required without
  approved, runtime None, invoke).
- `cv_agent/execution/models.py` — `SkillExecutionStatus` (`"started"` reserved, not
  reachable), `ApprovalPolicy`, `SkillExecutionRequest`, `RuntimeOutcome`,
  `ExecutionEvidence`, `ExecutionError`.
- `cv_agent/graph/state.py` — `AgentState`: `pending_execution`, `approval_decision`,
  `execution_result`, `execution_pin` shape `{"skill_id", "inputs", "task",
  "execution_pin"}`, recovery/disambiguation fields.
- `cv_agent/graph/workflow.py` — four interrupt points, `plan_execution`,
  `approval_gate` reading from pinned policy only (never a live read), `execute` node.
- `docs/architecture/adr/ADR-0003-orchestration-state-and-human-approval-interrupts.md`
  — approval-pin design (§10), D-030/D-032 audits, `pin_is_well_formed`, execution
  from pin only.
- `docs/architecture/adr/ADR-0009-skill-execution-boundary.md` — `ExecutionRuntime`'s
  synchronous contract, `"started"` reserved, ADR-0009 §8 per-skill verification rule.
- `docs/APPROVALS.md` — gated actions table, "Platform-sensitive actions" rule.
- `docs/state/DECISIONS.md` — D-040 through D-048.

No assumption was made about any component not listed here.

### Three open questions, answered in §3

1. **Protocol shape** — extend `ExecutionRuntime` vs. a distinct sibling protocol.
2. **Approval integrity** — how the existing pin model extends to a long-running action.
3. **Host verification** — where it lives and what happens on mismatch.

---

## 2. Responsibility (required — `[P§34]`)

- **This owns:** that a controlled CV workload (train / benchmark / optimize / evaluate)
  runs as a **separate OS process** on the Linux/NVIDIA execution host, under the
  Agent/controller's supervision, with a defined lifecycle (start → poll → cancel →
  collect → terminal outcome); that host requirements are verified before any
  platform-sensitive command is attempted; that the approval-integrity model from
  ADR-0003/ADR-0009 applies without weakening to the job-start decision.
- **This does NOT own:**
  - The synchronous `ExecutionRuntime`/`SkillExecutor` path — ADR-0009, UNCHANGED.
  - Any concrete `JobRuntime` implementation — the protocol is defined here, bindings
    and implementations are individually verified per ADR-0009 §8 precedent.
  - The LangGraph graph topology for a job workflow — that is a graph-layer concern
    (ADR-0003 territory); this ADR defines the types the graph nodes use, not the nodes
    themselves.
  - Kubernetes, distributed workers, remote execution — explicitly excluded from V1
    (D-046).
  - A specific host/GPU identity — D-044.
  - Cost estimation or approval thresholds — Q6/Q19, D-047's narrow first-baseline
    exception.
  - What model/dataset/metrics a job runs — D-043.
  - The skill-specific execution chain `Skill → ExecutionBinding → ExecutionRuntime` —
    ADR-0009; a job binding uses the same `ExecutionBinding` type and the same registry
    (§3.1).
- **Why this responsibility does not belong to an existing component:**
  ADR-0009's `ExecutionRuntime.invoke()` is synchronous — it returns a terminal
  `RuntimeOutcome` before the call stack unwinds. A real-time detection benchmark on a
  GPU runs for an unknown duration; it cannot be modelled as "call `invoke()`, wait,
  return." Stretching `invoke()` to mean "block for minutes/hours" would misrepresent
  what ADR-0009 was verified for (one short, deterministic, read-only script) and would
  break every caller that assumes the call returns promptly. The boundary test
  (`CLAUDE.md` §3 rule 6): this boundary owns "a process that was started and is still
  running," which `ExecutionRuntime` explicitly has no concept of (`"started"` is
  reserved but never reachable — `models.py:26-30`).

---

## 3. Decision

### 3.1 Protocol shape: a distinct sibling protocol `JobRuntime`, not extending `ExecutionRuntime`

A `JobRuntime` is a sibling protocol to `ExecutionRuntime`, not an extension of it.
It shares the same `ExecutionBindingRegistry` for binding lookup and pin generation,
but is looked up through `JobExecutor`'s own `job_runtimes` dict, not through the
registry's `_runtimes` dict.

**Rationale:**

- `ExecutionRuntime.invoke()` is a function call that returns a terminal `RuntimeOutcome`.
  A `JobRuntime.start()` is a function call that returns a `JobHandle` and returns
  *immediately* — the job continues in a separate OS process. These are not the same
  contract extended; they are different contracts entirely.
- `SkillExecutor.execute()` is built around synchronous invocation. Making it
  conditionally async/long-running on certain bindings would collapse two different
  semantics into one class, exactly the concept-collapse ADR-0005 §2 refused for
  tools-vs-skills.
- Reusing `ExecutionBindingRegistry` (binding lookup and pin generation) is correct and
  desired: an `ExecutionBinding` maps `skill_id → runtime_id + approval_policy +
  verified`, which is exactly what a job needs too. The pin shape
  `{"binding": ..., "runtime_generation": ...}` is the same. The distinction is that
  `JobExecutor` resolves `runtime_id` against its own `job_runtimes` dict, not the
  registry's `_runtimes` dict — a skill cannot simultaneously have an `ExecutionRuntime`
  and a `JobRuntime` under the same `runtime_id`, documented as a convention.
- `SkillExecutionStatus`'s reserved `"started"` value (ADR-0009 §3: "reserved for a
  future asynchronous/long-running runtime") is finally made reachable, as a `JobResult`
  status. It remains unreachable from `SkillExecutor.execute()`.
- `SkillExecutor`, `ExecutionRuntime`, `ExecutionBindingRegistry`, and all callers of
  them are **unchanged** — no backward-compatibility break.

### 3.2 Approval integrity: same pin model, checked at `start_job()` time

The existing approval-generation/pin-integrity model (ADR-0003 §10, hardened by
D-030/D-032 audits) applies to a job **without modification to any existing type or
function**:

1. **Pin capture (plan time):** The `plan_job()` graph node reads
   `ExecutionBindingRegistry.pin(skill_id)` and stores the result as
   `pending_job["job_execution_pin"]`. Same `{"binding": ..., "runtime_generation": ...}`
   shape. Captured once; never re-captured.
2. **Approval gate (interrupt):** The `job_approval_gate` graph node reads the pinned
   policy from `pending_job["job_execution_pin"]` only (never a live registry read),
   interrupts if `"approval_required"`, and sets `job_approval_decision` from the
   `interrupt()` resume value — "approved" | "rejected" | "not_required".
   `job_approval_decision` is never rewritten after the gate.
3. **Pin check at start time:** `JobExecutor.start_job()` runs
   `pin_mismatch(expected_pin, live_pin)` — **the same function**, unchanged — before
   calling `runtime.start()`. A missing or malformed pin → `"rejected"` status; a
   mismatch → `"rejected"` status; job never starts.
4. **After start:** Once `JobHandle` is returned from `start()`, the pin's role is done.
   The running OS process is what was approved; there is no "mid-flight re-approval" for
   the same job. Cancellation is a graph-level interrupt, not a new approval gate.

**Why this model does not need a new pin concept for long-running jobs:**
The pin is the approval for the *start decision* — "has what would run not changed since
approval was given?" A job that starts under an approved pin runs as the approved
process. The pin is not "approval to continue running" (that would require constant
re-approval through the job's lifetime); it is "approval to start," verified once.
Cancellation is always human-initiated through an interrupt, not an automatic
re-approval check.

**E1 rule preserved:** `expected_binding_pin` absent in `SkillExecutionRequest.approved`
→ no authorization for `"approval_required"` policy. Same rule in `JobExecutor`: a
missing `job_execution_pin` in `pending_job` → refused, `"rejected"` status, even if
`approved=True`.

### 3.3 Host verification: a distinct `HostVerifier` protocol, called by `JobExecutor` before `start()`

Host verification belongs in a new `cv_agent.execution.host` module as a `HostVerifier`
protocol, called by `JobExecutor.start_job()` **before** `runtime.start()` — never
inside the runtime implementation itself.

**Rationale:**

- Per `docs/APPROVALS.md`'s "Platform-sensitive actions" rule: "The agent must not
  execute Linux-specific or Jetson-specific commands on another platform." Verification
  must happen before the first platform-sensitive syscall, not after.
- Placing it inside each `JobRuntime` implementation would: (a) duplicate it across every
  runtime; (b) allow a careless runtime to skip it; (c) make it untestable without
  exercising the full runtime.
- `HostVerifier` is a `Protocol`, so it can be substituted in tests with a `FakeVerifier`
  and replaced at integration time with a real Linux/NVIDIA detector without changing
  `JobExecutor`.
- The module is `cv_agent.execution.host`, not `cv_agent.execution.jobs.host`, because
  host verification is a cross-cutting execution concern — future callers outside the job
  boundary (e.g., a platform-check CLI command) should be able to import it without
  depending on the jobs subpackage.
- `D-044` confirmed Linux + NVIDIA GPU as the host class for D-040's execution model.
  Nothing in this boundary names a concrete machine — `HostRequirement` names what is
  needed (OS, GPU vendor, min VRAM); `HostProfile` names what was detected.

**Mismatch behavior:** If `HostVerifier.verify()` returns `(False, reason)`, `JobExecutor`
returns a `JobResult` with `status="host_mismatch"` and the reason in `JobResult.error`.
The job never starts. This is a terminal, refuse-to-proceed outcome per the
"Platform-sensitive actions" rule — not a warning, not a soft failure.

---

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Extend `ExecutionRuntime` with new optional `start()` / `poll()` methods | One protocol, one registry | The existing Protocol has a single `invoke()` method; adding `start()`/`poll()` as optional methods with `...` bodies makes the contract incoherent — a runtime either blocks or doesn't. Every `ExecutionRuntime` implementor today (only `TrtPerfAnalysisRuntime`) would need to be reviewed for the new optional surface. The `SkillExecutor.execute()` synchronous caller would need conditional logic to detect which kind of runtime it has | Rejected — concept collapse, same reason ADR-0013 §2 already named |
| Add a `start_async()` method directly to `SkillExecutor` | No new protocol, same executor | Makes `SkillExecutor` own two fundamentally different execution semantics; tests for the synchronous path would need to remain ignorant of the async path's state; the `"started"` status would become reachable from `SkillExecutor.execute()` in some cases but not others | Rejected — collapses responsibilities that ADR-0009 §2 deliberately separated |
| Put `HostVerifier` inside each `JobRuntime` implementation | Keeps each runtime self-contained | Verification becomes opaque to `JobExecutor`, untestable in isolation, and easily forgotten by a future runtime author; cannot be unit-tested without exercising the full runtime | Rejected — violates the "separate discovery from execution" principle; host/environment state is a cross-cutting concern, not a per-runtime decision |
| A separate `JobBindingRegistry` parallel to `ExecutionBindingRegistry` | Clean separation of job vs. skill state | The pin model (`ExecutionBinding.pin()`, `pin_mismatch()`, `_pin_shape_ok()`) already exists and is correct; reimplementing it for jobs doubles the maintenance surface and creates a risk of divergence in approval semantics | Rejected — reuse `ExecutionBindingRegistry` for binding/pin; `JobExecutor` supplies its own `job_runtimes` dict |
| Place host verification in the LangGraph graph nodes (before `start_job`) | Graph controls platform checks | The graph layer (`cv_agent.graph`) must not depend on `cv_agent.execution.host` directly — that is an execution-layer concern leaking into the orchestration layer, violating `[P§19]` | Rejected — host verification in `JobExecutor`, the execution layer |

---

## 5. Interface

Stubs only — types, signatures, no implementation bodies. Per `CLAUDE.md` §5,
implementation is a separate session.

### 5.1 `cv_agent.execution.host`

```python
# cv_agent/execution/host.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class HostProfile:
    """What was detected about the current execution host at verification time."""
    os: str                          # e.g. "linux", "darwin"
    gpu_available: bool
    gpu_vendor: str | None           # e.g. "nvidia", None if no GPU
    driver_version: str | None       # e.g. "535.183.01", None if not detected

@dataclass(frozen=True)
class HostRequirement:
    """What a job declares it needs from the host. None = unspecified/any."""
    os: str                          # required OS, e.g. "linux"
    gpu_vendor: str | None = None    # required GPU vendor; None = CPU-only / any
    min_vram_mb: int | None = None   # minimum VRAM in MB; None = unspecified

class HostVerifier(Protocol):
    """
    Checks that the current execution host satisfies a job's HostRequirement.

    Called by JobExecutor.start_job() before runtime.start() is called.
    Never raises — verification failure is returned as (False, reason).
    """
    def verify(self, requirement: HostRequirement) -> tuple[bool, str]:
        """
        Returns (True, "") if the current host satisfies `requirement`,
        or (False, human-readable reason) if it does not.
        Never raises; a detection failure counts as unsatisfied.
        """
        ...
```

### 5.2 `cv_agent.execution.jobs.models`

```python
# cv_agent/execution/jobs/models.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal[
    "not_submitted",   # never attempted — pre-flight check failed
    "started",         # process spawned, not yet confirmed running
    "running",         # confirmed running (at least one successful poll)
    "completed",       # process exited with success
    "failed",          # process exited with non-zero / runtime error
    "cancelled",       # was running, cancelled by caller
    "host_mismatch",   # host verification failed — never started
    "rejected",        # pin/approval check failed — never started
]
"""
Terminal states: completed, failed, cancelled, host_mismatch, rejected.
Non-terminal states: not_submitted, started, running.
`started` is the first reachable use of the value reserved in
SkillExecutionStatus (cv_agent.execution.models) since ADR-0009.
"""

JobErrorCategory = Literal[
    "no_binding",
    "binding_not_verified",
    "approval_denied",
    "binding_mismatch",
    "host_mismatch",
    "runtime_error",
    "cancelled",
]

@dataclass(frozen=True)
class JobHandle:
    """
    Opaque reference to a running job. Only the JobRuntime that issued it
    can interpret it; JobExecutor stores it verbatim.
    """
    job_id: str          # stable, assigned by JobRuntime at start time
    runtime_id: str      # runtime that issued this handle
    started_at: str      # ISO-8601 UTC timestamp

@dataclass(frozen=True)
class JobResourceMetadata:
    """
    Resource usage captured at job completion. Fields absent if the runtime
    could not measure them. Maps to ExperimentRecord's hardware/timing fields
    (ADR-0011) — never guessed, only captured.
    """
    wall_time_seconds: float | None = None
    gpu_hours: float | None = None
    peak_vram_mb: float | None = None
    peak_ram_mb: float | None = None
    avg_power_watts: float | None = None
    exit_code: int | None = None

@dataclass(frozen=True)
class JobOutcome:
    """
    Terminal result of a completed, failed, or cancelled job.
    Only present when status is completed, failed, or cancelled.
    """
    success: bool
    exit_code: int | None
    stdout: str | None               # full captured stdout, not streamed (V1)
    stderr: str | None               # full captured stderr
    artifacts: dict[str, str] = field(default_factory=dict)
    """name -> absolute path of produced artifact file."""
    resources: JobResourceMetadata = field(default_factory=JobResourceMetadata)
    error_message: str | None = None

@dataclass(frozen=True)
class JobResult:
    """
    What JobExecutor reports to the orchestration layer.
    Analogous to SkillExecutionResult (ADR-0009) — same design pattern.
    """
    skill_id: str
    job_id: str | None             # None if never started
    status: JobStatus
    evidence: "ExecutionEvidence"  # reuses cv_agent.execution.models.ExecutionEvidence
    outcome: JobOutcome | None = None
    error: "ExecutionError | None" = None  # reuses cv_agent.execution.models.ExecutionError

    @property
    def ok(self) -> bool:
        return self.status == "completed"

    @property
    def terminal(self) -> bool:
        return self.status in ("completed", "failed", "cancelled", "host_mismatch", "rejected")
```

### 5.3 `cv_agent.execution.jobs.runtime`

```python
# cv_agent/execution/jobs/runtime.py

from __future__ import annotations
from typing import Literal, Protocol
from cv_agent.execution.jobs.models import JobHandle, JobOutcome
from cv_agent.execution.models import SkillExecutionRequest
from cv_agent.skills.models import Skill

class JobRuntime(Protocol):
    """
    Protocol for a runtime that executes a CV workload as a separate OS
    process — the job analogue of ExecutionRuntime (ADR-0009).

    runtime_id must be stable and unique; it is stored in ExecutionBinding.
    runtime_id and a JobRuntime under that id in JobExecutor.job_runtimes
    may NOT both be registered as an ExecutionRuntime under the same id in
    ExecutionBindingRegistry — a runtime_id names exactly one kind of runner.
    """
    runtime_id: str

    def start(self, skill: Skill, request: SkillExecutionRequest) -> JobHandle:
        """
        Spawn the job as a separate OS process. Returns a JobHandle
        immediately — does NOT wait for the job to finish.
        Must not raise for an ordinary launch failure; instead raise a
        RuntimeError (JobExecutor treats any raise as a "failed" job that
        never reached "started").
        """
        ...

    def poll(self, handle: JobHandle) -> Literal["running", "completed", "failed", "cancelled"]:
        """
        Non-blocking check of a running job. Returns the current status.
        Must not raise — an unreachable/dead process should be reported as
        "failed", not as an exception.
        """
        ...

    def cancel(self, handle: JobHandle) -> None:
        """
        Request cancellation of the job. Does NOT wait for the process to
        exit — the caller must poll() until "cancelled" or "failed".
        Calling cancel() on an already-terminal job is a no-op.
        """
        ...

    def collect(self, handle: JobHandle) -> JobOutcome:
        """
        Wait for the job to reach a terminal state and collect all results
        (exit code, stdout, stderr, artifacts, resource metadata).
        Idempotent for already-terminal jobs.
        Must not raise; an unreachable process returns
        JobOutcome(success=False, exit_code=None, ...).
        """
        ...
```

### 5.4 `cv_agent.execution.jobs.executor`

```python
# cv_agent/execution/jobs/executor.py

from __future__ import annotations
from typing import Literal
from cv_agent.execution.binding import ExecutionBindingRegistry, pin_is_well_formed, pin_mismatch
from cv_agent.execution.host import HostRequirement, HostVerifier
from cv_agent.execution.jobs.models import JobHandle, JobOutcome, JobResult
from cv_agent.execution.jobs.runtime import JobRuntime
from cv_agent.execution.models import SkillExecutionRequest
from cv_agent.skills.models import Skill

class JobExecutor:
    """
    Runs a resolved Skill as a long-running OS process through a JobRuntime,
    applying the same approval/pin integrity model as SkillExecutor, plus
    host verification before start.

    Reuses ExecutionBindingRegistry for binding lookup and pin generation.
    Keeps its own job_runtimes dict (keyed by runtime_id) separate from
    the registry's _runtimes dict, because JobRuntime and ExecutionRuntime
    implement different protocols — a runtime_id names exactly one kind.

    Does not replace SkillExecutor — both coexist and use the same registry.
    """

    def __init__(
        self,
        registry: ExecutionBindingRegistry,
        job_runtimes: dict[str, JobRuntime],
        host_verifier: HostVerifier,
    ) -> None: ...

    def can_start(self, skill_id: str) -> bool:
        """Inspect only — never runs anything.
        True iff a verified binding with a registered job runtime exists."""
        ...

    def start_job(
        self,
        skill: Skill,
        request: SkillExecutionRequest,
        host_requirement: HostRequirement,
    ) -> tuple[JobHandle | None, JobResult]:
        """
        Validate approval/pin (same logic as SkillExecutor.execute()),
        verify host, then call runtime.start().

        Pre-flight checks, in order:
          1. No binding → (None, status="not_submitted", "no_binding")
          2. Binding not verified → (None, status="not_submitted", "binding_not_verified")
          3. Policy "rejected" → (None, status="rejected", "approval_denied")
          4. Missing pin with approval_required policy → (None, status="rejected", E1 rule)
          5. Pin supplied → pin_mismatch() (same function as SkillExecutor) → mismatch
             → (None, status="rejected", "binding_mismatch")
          6. approval_required + request.approved is False → (None, status="rejected")
          7. No job runtime registered → (None, status="not_submitted", "no_binding")
          8. host_verifier.verify(host_requirement) returns (False, reason) →
             (None, status="host_mismatch")
          9. runtime.start() raises → (None, status="failed", "runtime_error")
         10. Success → (JobHandle, status="started")

        Returns (handle, result). handle is None if the job never started.
        """
        ...

    def poll_job(
        self, handle: JobHandle
    ) -> Literal["running", "completed", "failed", "cancelled"]:
        """
        Non-blocking check. Delegates to the registered JobRuntime for
        handle.runtime_id. Raises RuntimeError if the runtime is not found
        (should not happen in normal operation; indicates a bug in the caller).
        """
        ...

    def cancel_job(self, handle: JobHandle) -> None:
        """
        Request cancellation. Does not wait. Raises RuntimeError if runtime
        not found.
        """
        ...

    def collect_job(self, handle: JobHandle) -> JobOutcome:
        """
        Block until terminal state and collect results. Idempotent.
        Raises RuntimeError if runtime not found.
        """
        ...
```

### 5.5 AgentState additions for job workflow (additions to `cv_agent.graph.state`)

```python
# Additions to AgentState (TypedDict total=False), cv_agent/graph/state.py

pending_job: Optional[dict[str, Any]]
"""What the caller is asking the graph to run as a job, if anything:
{"skill_id": str, "inputs": dict, "task": str | None,
 "job_execution_pin": dict | None}.
Analogous to pending_execution; job_execution_pin follows the same
pin shape and capture/compare discipline as execution_pin in
pending_execution (ADR-0003 §10)."""

job_approval_decision: Optional[str]
""""approved" | "rejected" | "not_required" | None.
Set only by the job_approval_gate node from the interrupt() resume value.
Never inferred. Never rewritten after the gate.
Stays None for a missing/malformed job_execution_pin."""

active_job_handle: Optional[dict[str, Any]]
"""dataclasses.asdict() of the JobHandle while the job is running,
or None. Set by start_job node; cleared when job reaches terminal state.
Plain dict (not the dataclass instance) for checkpoint safety — same
rationale as execution_result/requirements_analysis."""

job_result: Optional[dict[str, Any]]
"""dataclasses.asdict() of a JobResult when the job has reached a
terminal state, or None. Set by the job completion node."""
```

### 5.6 New graph nodes (signatures only — topology is a separate implementation PR)

```python
# New graph node functions — cv_agent/graph/workflow.py (additions)

def _node_plan_job(state: AgentState, ...) -> dict[str, Any]:
    """Captures pending_job including job_execution_pin. Analogous to
    _node_plan_execution. Never interrupts."""
    ...

def _node_job_approval_gate(state: AgentState, ...) -> dict[str, Any]:
    """Reads pinned policy from pending_job["job_execution_pin"] only
    (never a live registry read). Interrupts if "approval_required".
    Sets job_approval_decision from the interrupt() resume value.
    Analogous to _node_approval_gate."""
    ...

def _node_start_job(state: AgentState, ...) -> dict[str, Any]:
    """Calls JobExecutor.start_job(); sets active_job_handle on success.
    Analogous to _node_execute."""
    ...

def _node_poll_or_collect_job(state: AgentState, ...) -> dict[str, Any]:
    """Polls the running job; transitions to collect when terminal.
    Sets job_result and clears active_job_handle at terminal state."""
    ...
```

---

## 6. Lifecycle / state model

```
  ┌─────────────────────────────────────────────────┐
  │                  Pre-flight checks               │
  │  (in JobExecutor.start_job(), before start())    │
  │                                                   │
  │  no binding → not_submitted                       │
  │  not verified → not_submitted                     │
  │  policy=rejected → rejected (terminal)            │
  │  missing pin + approval_required → rejected       │
  │  pin mismatch → rejected                          │
  │  not approved → rejected                          │
  │  no job runtime → not_submitted                   │
  │  host mismatch → host_mismatch (terminal)         │
  │  start() raises → failed (terminal)               │
  └─────────────────────────────────────────────────┘
                        │
               start() returns JobHandle
                        │
                        ▼
                    started  ───── poll() = "running" ─────► running
                        │                                       │
                        │                                poll() = "running"
                        │                                       │ (loop)
                        │                                       │
                        └──────────┬────────────────────────────┘
                                   │
                    ┌──────────────┼──────────────────┐
                    │              │                  │
             poll()=           poll()=         cancel() called
           "completed"         "failed"        then poll()=
                    │              │           "cancelled"
                    ▼              ▼                  ▼
               completed       failed           cancelled
              (terminal)      (terminal)        (terminal)
```

**Terminal states:** `completed`, `failed`, `cancelled`, `host_mismatch`, `rejected`.
A `JobResult` with a terminal status is immutable. `JobOutcome` is only present for
`completed`, `failed`, and `cancelled` — never for `host_mismatch` or `rejected`.

---

## 7. Approval-integrity model (summary)

```
plan_job node
  │  reads ExecutionBindingRegistry.pin(skill_id)
  │  writes pending_job["job_execution_pin"] = {...}  ← captured once, never re-read live
  ▼
job_approval_gate (interrupt)
  │  reads pending_job["job_execution_pin"]["binding"]["approval_policy"]
  │  interrupts if "approval_required"
  │  job_approval_decision = interrupt() resume value  ← set once, never rewritten
  ▼
start_job node
  │  calls JobExecutor.start_job(skill, request, host_req)
  │    ├─ pin_mismatch(request.expected_binding_pin, live_pin)  ← same function, ADR-0003
  │    ├─ host_verifier.verify(host_req)
  │    └─ runtime.start(skill, request)  ← only if all checks pass
  ▼
active_job_handle stored in AgentState
  ▼
poll/collect loop (no new approval checks — job is running as approved process)
  ▼
job_result stored in AgentState  (terminal)
```

**Invariant:** a `JobRuntime.start()` call is only reached if:
- A valid pin was captured at plan time (`job_execution_pin` is a well-formed dict).
- The approval gate has set `job_approval_decision = "approved"` or `"not_required"`.
- `pin_mismatch()` returned `()` (no drift since plan time).
- `host_verifier.verify()` returned `(True, "")`.

No execution can reach `start()` without satisfying all four conditions. This is
enforced structurally by `JobExecutor.start_job()`'s pre-flight check order (§5.4),
not by documentation.

---

## 8. Failure and cancellation semantics

| Condition | Status | `JobOutcome` present? | `error` present? |
|---|---|---|---|
| Pre-flight check failed (any) | `rejected` or `host_mismatch` or `not_submitted` | No | Yes |
| `runtime.start()` raises | `failed` | No | Yes (`runtime_error`) |
| Process exits with exit code 0 | `completed` | Yes | No |
| Process exits with non-zero exit code | `failed` | Yes | Yes (`runtime_error`) |
| `cancel_job()` called → process terminates | `cancelled` | Yes (partial) | Yes (`cancelled`) |
| Runtime unreachable during poll/collect | `failed` | Yes (empty) | Yes (`runtime_error`) |

**Cancellation:** Calling `cancel_job()` sends a termination signal to the OS process.
The caller must continue polling until `poll_job()` returns `"cancelled"` or `"failed"`.
`collect_job()` on a cancelled job returns a `JobOutcome(success=False, exit_code=None,
..., error_message="cancelled")`. Cancellation is **not a new approval gate** — it is
a human-initiated graph interrupt that sets a flag; the `poll_or_collect` node acts on
the flag.

**Partial stdout/stderr on cancellation:** V1 captures what was available up to
cancellation time. Truncated output is not an error condition — it is a normal property
of cancellation. `JobOutcome.stdout` / `.stderr` may be partial.

---

## 9. Artifact / result contract

`JobOutcome.artifacts` is `dict[str, str]` (name → absolute path). The runtime is
responsible for placing files at known paths before `collect()` returns. `JobExecutor`
does not copy or move artifacts — it accepts what the runtime reports.

**Linking to `ExperimentRecord` (ADR-0011):** The graph node that writes the ledger
entry (a later, separate implementation PR) maps `JobResult` → `ExperimentRecord`:

- `experiment_id` — assigned by the node, not the runtime.
- `dataset_version` — supplied as part of `pending_job["inputs"]`, referencing a
  `(dataset_id, version)` pair from `DatasetManifest` (ADR-0012). Never derived from
  `JobOutcome`.
- `hardware` — populated from `JobOutcome.resources` (wall time, GPU-hours, VRAM, RAM,
  power where captured).
- `artifact_paths` — from `JobOutcome.artifacts`.
- `status` — maps directly: `completed` → `"completed"`, `failed` → `"failed"`,
  `cancelled` → `"cancelled"`.

A `JobResult` with a non-terminal status is never written to the ledger — the node
waits for terminal state before writing.

---

## 10. Minimum implementation boundary for the first job runner

The minimum verifiable deliverable (one Phase 5b baseline run) requires:

| Component | ADR section | Needed? |
|---|---|---|
| `cv_agent.execution.host` module with `HostProfile`, `HostRequirement`, `HostVerifier` | §5.1 | Yes |
| `cv_agent.execution.jobs.models` module | §5.2 | Yes |
| `cv_agent.execution.jobs.runtime` module (`JobRuntime` Protocol) | §5.3 | Yes |
| `cv_agent.execution.jobs.executor` module (`JobExecutor`) | §5.4 | Yes |
| One real `JobRuntime` implementation (per ADR-0009 §8: individually inspected, verified) | — | Yes — separate PR |
| `LinuxNvidiaHostVerifier` concrete `HostVerifier` for Linux + NVIDIA GPU | §5.1 | Yes — separate PR |
| `AgentState` additions | §5.5 | Yes |
| Graph nodes `plan_job` / `job_approval_gate` / `start_job` / `poll_or_collect` | §5.6 | Yes — separate PR |
| `ExperimentRecord` wiring from `JobResult` | §9 | Yes — separate PR |
| Cost estimation machinery | — | No (D-047 exception applies to first baseline) |

Each "separate PR" item is a distinct GitHub issue per `CLAUDE.md` §6. The protocol
types and `JobExecutor` stubs (this ADR) are one PR; a concrete runtime, verifier, and
graph integration are subsequent PRs.

---

## 11. New owner decisions required

None. This ADR resolved all three open protocol-shape questions from the Proposed
version's §5 as design decisions within architect scope, not owner decisions:

1. Sibling protocol vs. extension → design decision (§3.1).
2. Approval-pin model for long-running jobs → existing model applies as-is (§3.2).
3. Host verification placement → `HostVerifier` protocol, `JobExecutor` calls it (§3.3).

The open questions **not** resolved by this ADR and still blocking full execution:
- **Q6** (approval cost-estimation thresholds) — open beyond D-047's narrow exception.
- **Q19** (general cost-estimation mechanism) — open beyond D-047.
- **Q3** (restart-survivable checkpointer) — `MemorySaver` does not survive a process
  restart; a job that outlives the current process cannot be resumed today. Noted as an
  acknowledged gap; does not block the first baseline run (same process, bounded wall
  time).

---

## 12. Acceptance test (first verifiable run)

These tests must pass before any implementation PR can be merged:

1. A `JobExecutor` with a verified `JobRuntime` and a `HostVerifier` that passes:
   - `start_job()` with a valid pin → returns `(JobHandle, JobResult(status="started"))`.
   - `poll_job(handle)` while process is alive → `"running"`.
   - `collect_job(handle)` after process exits cleanly → `JobOutcome(success=True, ...)`.
2. A `JobExecutor` with a `HostVerifier` that fails:
   - `start_job()` → `(None, JobResult(status="host_mismatch", ...))`.
   - Process was never started.
3. A `JobExecutor` with a valid binding but `approval_required` and `request.approved=False`:
   - `start_job()` → `(None, JobResult(status="rejected", error.category="approval_denied"))`.
4. Pin mismatch (modified binding between capture and start):
   - `start_job()` with a stale pin → `(None, JobResult(status="rejected", error.category="binding_mismatch"))`.
5. A `cancel_job()` on a running job:
   - Subsequent `poll_job()` eventually returns `"cancelled"`.
   - `collect_job()` returns `JobOutcome(success=False, ...)`.
6. All of the above use fake runtimes/verifiers constructed in the test file —
   no real subprocess, no GPU required.

---

## 13. Consequences

- **Enables:** Phase 5b first baseline run; `SkillExecutionStatus`'s reserved `"started"`
  value is finally reachable; a defined place for any future training/evaluation/NAS job
  to plug in.
- **Makes harder:** two executor classes now exist (`SkillExecutor`, `JobExecutor`). A
  `CVAgent` that wants both synchronous-skill and job execution needs both wired in. This
  is a named, accepted cost — the alternative of retrofitting one executor was rejected
  in §4.
- **Costs:** two new packages (`cv_agent/execution/jobs/`, `cv_agent/execution/host.py`),
  ~300–350 lines of stubs + tests for the protocol layer. No new third-party dependency.
- **Migration / blast radius if reversed:** none on existing code — `SkillExecutor`,
  `ExecutionRuntime`, `ExecutionBindingRegistry`, `CVAgent.execute()`, all existing
  tests, and the existing graph nodes are UNCHANGED by this ADR.

## 14. Revisit trigger

- A concrete `JobRuntime` for the Person Detection + Tracking reference project
  (D-043) is verified (ADR-0009 §8 rule: individually inspected, not assumed to work).
- Q3 (restart-survivable checkpointer) is resolved — at that point, the `active_job_handle`
  serialization and the cross-process handle semantics need review.
- The first real baseline run reveals gaps in `HostRequirement` / `HostProfile` fields
  that were not anticipated here.
- Training runs (Phase 6) require an ADR amendment for cost-estimation integration.
