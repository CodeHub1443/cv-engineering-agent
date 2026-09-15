# ADR-0009: Skill execution & invocation boundary

- **Status:** Accepted (retroactive — same allowance ADR-0001/0007/0008 used; no live
  GitHub issue tracker wired up yet)
- **Date:** 2026-09-15
- **Layer:** execution (new)
- **Canon:** `[P§15]`, `[P§21]`, `[P§22]`, `[P§23]`, `[P§24]`, `[P§29.8]`, `[P§34]`
- **Supersedes / Superseded by:** —
- **Issue:** #TBD

## 1. Context

`docs/roadmap/ROADMAP.md` Phase 3's exit test has an unmet adapter/invocation half:
ADR-0007 gives the agent `Skill` discovery and deterministic resolution, but every
`Skill.executable` is hard-set `False` — nothing in the repo can actually run a
discovered skill. A prior turn requesting this exact deliverable ("Step 3") was
dropped before any work happened (`docs/state/JOURNAL.md`, 2026-09-15 entry;
`docs/state/DECISIONS.md` D-011); this ADR is that work, done properly rather than
retroactively invented.

Before designing anything, the actual installed skill environment
(`~/.claude/skills`, `~/.agents/skills`, 84 discovered skill directories) was
inspected directly — not assumed. Findings, concretely:

- Every `SKILL.md` is prose written to be *read by an LLM coding agent* (Claude
  Code/Codex) and acted on using *that agent's own tools*. 28 of the 84 declare an
  `allowed-tools:` frontmatter key (e.g. `allowed-tools: Read Bash`,
  `allowed-tools: Read Bash Write Edit Grep Glob`) — this is Claude Code's own
  agent-skill frontmatter, naming which of *the calling agent's* tools the skill may
  use while being followed. It is not a program interface this Python process can
  call.
- `cuda-agent` has no frontmatter at all — it is a plain-prose persona/instruction
  block ("You are a PyTorch and CUDA expert...").
- Some skills (`trt-perf-analysis`, `gstreamer-pipeline`) do bundle real,
  independently-runnable scripts (`scripts/run.sh` + `.py` files;
  `scripts/gst.py`). But nothing declares a stable, machine-readable invocation
  contract (entrypoint, argument schema, output schema) for those scripts — knowing
  which script to run with which arguments requires reading and following the
  prose, which is exactly the "skill instruction ≠ executable program" distinction
  requirement 6 of the originating request called out by name.
- The requested representative skill `jetson-diagnostic` does not exist under
  either root by that name — the closest matches are `network-diagnostics` and
  `camera-network-diagnostics`. Not fabricated; noted here instead.

Conclusion: **no generic, verified execution mechanism exists in the current
environment.** Building an adapter that pretends reading `SKILL.md` is execution
would violate `[P§35]` (silent invention) and the DECLARED/DISCOVERED/EXECUTABLE
discipline ADR-0001 §8a and ADR-0007 already established for capabilities and
skills. This ADR therefore builds the *boundary* — the types and the fail-safe
decision logic — with zero bindings registered, rather than a first adapter that
would misrepresent what it can do.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** the contract for attempting to run a resolved `Skill`
  (`cv_agent.execution`): request/result/status models, the
  `Skill -> ExecutionBinding -> ExecutionRuntime` chain, a deterministic, inspectable
  binding registry, and the approval-policy check gating execution.
- **This does NOT own:**
  - discovering skills or deciding which one is relevant to a task → `cv_agent.skills`
    (ADR-0007), unchanged, called by nothing in this package;
  - the actual approval workflow `docs/APPROVALS.md` describes (assembling a cost
    estimate, asking a human, recording the approval) → not implemented anywhere yet;
    this package only *checks* `SkillExecutionRequest.approved`, which a caller who
    already went through that workflow is expected to have set;
  - any concrete runtime's behavior (what DeepStream, TAO, a shell script, or an
    LLM-agent-driven skill invocation actually does) → hidden behind the
    `ExecutionRuntime` protocol; zero implementations of it exist in this codebase;
  - triggering execution automatically from `resolve()` or `analyze_requirements()` →
    both remain read-only; `CVAgent.execute()` is a distinct, explicitly-called method.
- **Why this responsibility does not belong to an existing component:**
  `TaskResolver` (ADR-0007) already has the job of finding relevant capabilities and
  skills; folding "and now run one" into it would collapse resolution (a query) with
  execution (a side-effecting action), which is exactly the reasoning/orchestration
  vs. execution separation `[P§19]`/`[P§21]`/`[P§22]` requires kept apart.

## 3. Decision

`cv_agent/execution/`:

- `models.py` — `SkillExecutionRequest`, `SkillExecutionResult`,
  `SkillExecutionStatus` (`not_executable | started | completed | failed | rejected`),
  `ExecutionEvidence`, `ExecutionError`, `RuntimeOutcome`, `ApprovalPolicy`
  (`allowed | approval_required | rejected`).
- `binding.py` — `ExecutionBinding` (skill_id → binding_id, runtime_id,
  approval_policy, `verified: bool`), `ExecutionRuntime` (a narrow `Protocol`:
  `runtime_id` + `invoke(skill, request) -> RuntimeOutcome`, naming no concrete
  runtime), `ExecutionBindingRegistry` (plain dict-backed, deterministic lookups,
  `list_bindings()`/`list_runtimes()` sorted for inspection).
- `executor.py` — `SkillExecutor.execute(skill, request)`: no binding → constructs a
  status `Skill.executable=False`); unverified binding → `not_executable`; policy
  `rejected`, or `approval_required` without `request.approved` → `rejected`, without
  ever calling the runtime; otherwise delegates to the runtime, catching any
  exception as `failed` rather than propagating it.

`CVAgent` gets `.execute(skill, request)`, `.can_execute(skill_id)` (inspect-only),
and `.execution_bindings` (the registry, for read-only inspection). The registry is
constructed empty in `CVAgent.__init__` — **no binding is registered anywhere in
this codebase.** CLI: `python -m cv_agent executions` lists discovered skills against
registered bindings/runtimes and reports the executable count (0 today, honestly).

`started` is part of `SkillExecutionStatus` for forward compatibility with an
eventual asynchronous runtime, but is not reachable from today's synchronous
`SkillExecutor.execute()` — documented in `models.py`, not silently unreachable.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Treat "reading SKILL.md" as execution — a binding that shells out to an LLM agent re-reading the skill's prose | Every skill technically *can* be "run" this way today | This is exactly the "Skill instruction ≠ executable program" conflation the request explicitly forbade pretending; it would silently claim `executable=True` for skills whose actual behavior depends entirely on which LLM agent reads them and how, which is not verifiable or deterministic | Rejected — would violate `[P§35]` and the DECLARED≠EXECUTABLE invariant this whole architecture line (ADR-0001 §8a, ADR-0007) exists to protect |
| Build one adapter now for `trt-perf-analysis`/`gstreamer-pipeline` since they do bundle real scripts | Real, testable subprocess entrypoints exist for these two | Their invocation contract (which script, which flags, in what order) is still only documented in prose, not a machine-readable manifest; hardcoding one skill's script path/args as "the" execution adapter is exactly the "do not hard-code the 78 skills" / "no giant switch statement" rule the request warned against, generalized to n=1 | Rejected for this step; the `ExecutionRuntime` protocol is shaped so a future adapter for these two specifically could be added and *verified* (tested against the real scripts) without changing this ADR's boundary |
| A binding registry keyed by capability_id instead of skill_id | Would unify with `spec/capability_registry.json` more tightly | A capability can resolve to many skills (ADR-0007's `SkillMatch` is 1:many); execution is a property of one concrete skill instance, not the abstract capability | Rejected; `ExecutionBinding.skill_id` matches `Skill.skill_id`, one level below capability |

## 5. Interface

```python
# module: cv_agent.execution.models
SkillExecutionStatus = Literal["not_executable", "started", "completed", "failed", "rejected"]
ApprovalPolicy = Literal["allowed", "approval_required", "rejected"]
ExecutionErrorCategory = Literal["no_binding", "binding_not_verified", "approval_denied", "runtime_error"]

@dataclass(frozen=True)
class SkillExecutionRequest:
    inputs: dict[str, Any] = field(default_factory=dict)
    task: str | None = None
    requested_by: str = "agent"
    approved: bool = False

@dataclass(frozen=True)
class ExecutionEvidence:
    binding_id: str | None
    runtime_id: str | None
    started_at: str | None
    completed_at: str | None

@dataclass(frozen=True)
class ExecutionError:
    category: ExecutionErrorCategory
    message: str

@dataclass(frozen=True)
class SkillExecutionResult:
    skill_id: str
    status: SkillExecutionStatus
    evidence: ExecutionEvidence
    output: dict[str, Any] | None = None
    error: ExecutionError | None = None

@dataclass(frozen=True)
class RuntimeOutcome:
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

# module: cv_agent.execution.binding
class ExecutionRuntime(Protocol):
    runtime_id: str
    def invoke(self, skill: Skill, request: SkillExecutionRequest) -> RuntimeOutcome: ...

@dataclass(frozen=True)
class ExecutionBinding:
    skill_id: str
    binding_id: str
    runtime_id: str
    approval_policy: ApprovalPolicy
    verified: bool
    description: str = ""

@dataclass
class ExecutionBindingRegistry:
    def register_binding(self, binding: ExecutionBinding) -> None: ...
    def register_runtime(self, runtime: ExecutionRuntime) -> None: ...
    def get_binding(self, skill_id: str) -> ExecutionBinding | None: ...
    def get_runtime(self, runtime_id: str) -> ExecutionRuntime | None: ...
    def list_bindings(self) -> list[ExecutionBinding]: ...
    def list_runtimes(self) -> list[ExecutionRuntime]: ...

# module: cv_agent.execution.executor
class SkillExecutor:
    def __init__(self, registry: ExecutionBindingRegistry) -> None: ...
    def can_execute(self, skill_id: str) -> bool: ...
    def execute(self, skill: Skill, request: SkillExecutionRequest) -> SkillExecutionResult: ...
```

## 6. Consequences

- **Enables:** `python -m cv_agent executions`, `CVAgent.execute()`/`.can_execute()`,
  and a place for a *future, individually-verified* adapter (e.g. for
  `trt-perf-analysis`'s bundled scripts) to register into without redesigning
  anything — it just calls `register_binding()` + `register_runtime()`.
- **Makes harder:** nothing removed; purely additive.
- **Costs:** one new package (`cv_agent/execution/`), ~260 lines, no new dependency.
- **Migration / blast radius if reversed:** contained — `CVAgent.execute()`,
  `.can_execute()`, `.execution_bindings`, and the `executions` CLI command are the
  only consumers; removing the package does not touch `cv_agent.skills` or
  `cv_agent.capabilities`.
- **Honesty cost accepted deliberately:** `python -m cv_agent executions` reports
  `Executable: 0/84` against the real environment today. This is correct, not a
  regression — no execution mechanism was actually verified, so claiming otherwise
  would be the exact violation this ADR exists to prevent.

## 7. Acceptance test

`tests/test_execution.py` (not-executable without a binding, not-executable with an
unverified binding, not-executable with a binding pointing at an unregistered
runtime, executable with a verified binding + registered runtime, execution success,
execution failure via `RuntimeOutcome(success=False)`, execution failure via a raised
exception, `rejected` policy always rejects, `approval_required` without
`request.approved` rejects, `approval_required` with `request.approved=True` runs,
`allowed` runs without approval, deterministic binding/runtime lookup, sorted
`list_bindings()`, a fresh `CVAgent`'s registry is empty, `resolve()` and
`analyze_requirements()` never touch the execution registry) and
`tests/test_cli.py`'s `executions` command tests (zero-binding reporting against a
real discovered fixture skill, no filesystem mutation, `resolve` output carries no
execution-status language).

## 8. Revisit trigger

When a specific skill's invocation contract (e.g. `trt-perf-analysis`'s
`scripts/run.sh <script> <args>`) is deliberately inspected, tested end-to-end
against the real script, and verified reliable enough to register as the first real
`ExecutionBinding`/`ExecutionRuntime` pair — at that point `verified=True` becomes
true for one skill, not all of them at once. Also when the approval workflow
`docs/APPROVALS.md` describes gets an actual implementation that sets
`SkillExecutionRequest.approved`, rather than a caller setting it directly.
