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
constructed empty in `CVAgent.__init__` — **no binding is registered automatically,
by `CVAgent` or anything else in this codebase** (still true after §9: one real,
individually-verified adapter now exists as an opt-in module, but nothing wires it
in by default). CLI: `python -m cv_agent executions` lists discovered skills against
registered bindings/runtimes and reports the executable count against a fresh
`CVAgent` (0/84 unless a caller has explicitly opted a specific binding in — see §9).

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
  and a place for a *future, individually-verified* adapter to register into without
  redesigning anything — it just calls `register_binding()` + `register_runtime()`.
  *Realized for one skill, §9:* `trt-perf-analysis`'s bundled scripts are exactly
  such an adapter now, registering through this same unmodified mechanism.
- **Makes harder:** nothing removed; purely additive.
- **Costs:** one new package (`cv_agent/execution/`), ~260 lines, no new dependency.
  *Updated, §9:* plus `cv_agent/execution/runtimes/` (one adapter module, ~260
  lines) — still no new third-party dependency; it shells out to the skill's own
  script with this process's own Python.
- **Migration / blast radius if reversed:** contained — `CVAgent.execute()`,
  `.can_execute()`, `.execution_bindings`, and the `executions` CLI command are the
  only consumers; removing the package does not touch `cv_agent.skills` or
  `cv_agent.capabilities`. *Updated, §9:* removing `cv_agent/execution/runtimes/`
  specifically touches nothing else at all — it is never imported by `CVAgent`,
  `SkillExecutor`, or the CLI; only a caller that explicitly opted in loses that one
  binding.
- **Honesty cost accepted deliberately:** `python -m cv_agent executions` reports
  `Executable: 0/84` against a fresh `CVAgent` and the real environment. This is
  correct, not a regression — no execution mechanism was actually verified when this
  ADR was first written, so claiming otherwise would have been the exact violation
  this ADR exists to prevent. *Updated, §9:* one mechanism is now verified
  (`trt-perf-analysis`), but the count stays honest either way — `CVAgent`'s default
  registry is still empty, so `executions` still reports `0/84` unless a caller has
  explicitly called `register()` first (see §9); this ADR does not claim more than
  what is actually wired into whichever `CVAgent` instance is asking.

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

**§9 addition:** `tests/test_execution_trt_perf_analysis.py` — argv-contract unit
tests, mocked subprocess error-mapping (timeout, missing interpreter, non-zero exit,
non-JSON/non-object stdout — no timing races, no installed-skill dependency),
registry/approval-gate wiring (including that an `approval_required` binding never
calls `invoke()` without `request.approved=True`, and that a fresh `CVAgent`'s
registry stays empty by default even after this module exists), and — skipped, not
faked, when the skill isn't actually installed — genuine subprocess invocation of
the real `scripts/analyze_trt_perf.py` through `CVAgent.execute()`: a successful
real run, two real runs producing byte-identical structured output, the real
empty-folder failure (exit `2`), and the real per-backend-malformed-JSON case
(exit `0`, that one backend reported `"status": "failed"` inside otherwise valid
structured output — verified empirically, not assumed).

## 8. Revisit trigger

When a specific skill's invocation contract (e.g. `trt-perf-analysis`'s
`scripts/run.sh <script> <args>`) is deliberately inspected, tested end-to-end
against the real script, and verified reliable enough to register as the first real
`ExecutionBinding`/`ExecutionRuntime` pair — at that point `verified=True` becomes
true for one skill, not all of them at once. **Fired — see §9: `trt-perf-analysis`
is that one skill.** Also when the approval workflow `docs/APPROVALS.md` describes
gets an actual implementation that sets `SkillExecutionRequest.approved`, rather
than a caller setting it directly — **still open**, unaffected by §9 (the
`trt-perf-analysis` binding needs no approval at all — see §9 — so it does not
exercise this trigger).

## 9. Status

**Implemented (branch `feature/claude/execution-binding`):** the first real,
individually-verified `ExecutionRuntime`/`ExecutionBinding` pair, per §8's revisit
trigger.

- **Skill selected:** `trt-perf-analysis` — chosen by directly inspecting the real
  installed skill directory (`~/.agents/skills/trt-perf-analysis`, confirmed also
  present at `~/.claude/skills/trt-perf-analysis`), not the D-012/§1 mention alone
  (that mention was verified, not assumed, before relying on it).
- **Why it has a valid executable contract:** `scripts/analyze_trt_perf.py`'s own
  module docstring states it uses only Python standard-library modules; it exposes a
  stable `argparse` CLI (`path` positional, or repeated `--data LAYER [PROFILE]`,
  optional `--model-name`/`--output`) — a machine-readable contract, not prose a
  human/LLM must interpret. Exit-code/stdout behavior was verified empirically
  against the real script (not assumed from reading alone): exit `0` with one JSON
  object on stdout whenever it can produce structured data at all (including when a
  specific backend's own input fails validation — the script treats that as a valid,
  informative outcome, not a crash); exit `2` with a one-line `error: ...` message on
  stderr when it cannot process the input at all (e.g. no `layers_*.json`/
  `profile_*.json` present).
- **Invocation contract (`cv_agent/execution/runtimes/trt_perf_analysis.py`):**
  `TrtPerfAnalysisRuntime.invoke(skill, request)` derives the script's path from the
  real, discovered `skill.location` (never a hard-coded filesystem path), and runs
  it as a subprocess with this process's own interpreter (`sys.executable`, or the
  `SKILL_PYTHON` environment variable if set — the same override the skill's own
  `scripts/run.sh`/`run.cmd` wrappers honor) rather than shelling through those
  wrappers, since this process already knows which Python it is running under.
  `request.inputs` accepts exactly one of `{"path": "<folder>"}` or
  `{"data": [[layer, profile?], ...]}`, plus optional `{"model_name": "<str>"}`;
  `--output` is never forwarded — the result is always read from stdout, so
  invocation stays read-only regardless of caller input.
- **What the adapter guarantees:** the real, unmodified skill script runs, unaltered
  and uncopied, against exactly the files named in `request.inputs`; a timeout
  (default 30s, per-instance override), a missing interpreter, a non-zero exit, or
  non-JSON/non-object stdout are all reported as `RuntimeOutcome(success=False,
  error_message=...)`, never raised past this adapter and never fabricated as
  success. `verified=True`/`approval_policy="allowed"` apply to this one
  `ExecutionBinding` only (`binding_id="trt-perf-analysis-local-subprocess-v1"`) —
  `"allowed"` because the invocation is read-only, local, deterministic, and
  Python-stdlib-only, which needs no approval gate per `CLAUDE.md` §3 rule 10, not
  because approval was bypassed.
- **Registration stays opt-in, never automatic:** `cv_agent/execution/runtimes/
  trt_perf_analysis.register(registry)` must be called explicitly by a caller that
  has itself discovered the skill; `CVAgent.__init__` does not call it. A fresh
  `CVAgent`'s `execution_bindings` registry — and `python -m cv_agent executions`'s
  `0/84` report — are unchanged by this module's mere existence.
- **What remains non-executable:** every other skill among the 84 discovered
  ones — this ADR's §8 trigger fires **per skill**, not in bulk, exactly as
  written; no other binding was added, declared, or implied. `gstreamer-pipeline`
  (the other bundled-script candidate named in §1) remains uninspected for this
  purpose. The approval workflow `docs/APPROVALS.md` describes still has no real
  implementation (§8, still open) — irrelevant to this binding specifically, since
  it needs no approval, but still true of the codebase generally.

## 10. Status — first real application-layer consumer

**Added (branch `feature/claude/execution-feedback-loop`):** `python -m cv_agent
execute <skill_id>` — the first CLI command that drives `CVAgent.execute()` with
real, user-supplied input rather than only being exercised from tests. Only
`trt-perf-analysis` is accepted (a single constant check, not a dispatch table —
see `cv_agent/__main__.py::_SUPPORTED_EXECUTE_SKILL_ID`'s docstring); this command
is itself the explicit, one-off caller that registers that one binding
(`cv_agent.execution.runtimes.trt_perf_analysis.register()`) into its own
short-lived `CVAgent` instance before calling `.execute()` — never bypassing
`SkillExecutor`, never duplicating its request-construction or approval-check
logic. `skills`/`resolve`/`capabilities`/`executions` are untouched by this
addition and still construct their own fresh, unregistered `CVAgent`, so §6's
honesty cost (`0/84` by default) is unchanged.

Approval handling (`_confirm_approval()`) never auto-approves: an
`approval_required` binding needs either an explicit `--approve` flag or a live
"y"/"yes" answer to a one-time prompt (`docs/APPROVALS.md` §"Agent behavior at a
gate," rule 3); `trt-perf-analysis`'s own `"allowed"` policy (§9) means this path
is implemented but not exercised by that binding — covered instead by unit tests
against a fake `approval_required` binding (`tests/test_cli_execute.py::
TestConfirmApproval`), since building a second real binding just to test this
was out of scope.

See ADR-0007 §9 for the separate, related decision this command depends on —
how `Skill.executable`/`SkillMatch.executable` became truthful in the first
place, so `--help`-level discovery (`skills`/`resolve`) and this command's own
`can_execute()` check agree.

## 11. Status — declared input contract (`ExecutionBinding.input_schema`)

**Added (branch `feature/claude/execution-planning-contract`), types only —
see ADR-0010 for the connector this unblocks.** `trt-perf-analysis`'s actual
input contract (`{"path": ...}` XOR `{"data": [...]}`, optional
`{"model_name": ...}`) has, until now, existed *only* as prose in
`cv_agent/execution/runtimes/trt_perf_analysis.py::_build_argv`'s docstring —
nowhere machine-readable. ADR-0010's planning connector needs to know, for any
registered binding, what inputs it requires *before* attempting to construct a
`SkillExecutionRequest`; this section adds exactly that, as data on
`ExecutionBinding`, nothing more.

- **New type**, module `cv_agent.execution.binding`:

  ```python
  @dataclass(frozen=True)
  class InputField:
      name: str
      required: bool
      description: str
      default: Any | None = None
  ```

- **`ExecutionBinding` gains one new field:** `input_schema: tuple[InputField, ...] = ()`.
  Default empty tuple — every existing `ExecutionBinding` construction site
  (exactly one today: `trt_perf_analysis.build_binding()`) is unaffected
  unless and until it is deliberately populated; this is additive, not a
  breaking change to the dataclass's existing positional/keyword shape.

- **Why this lives on `ExecutionBinding`, not a separate registry:** an input
  contract is a fact about *one specific skill_id + binding_id pairing* —
  exactly what `ExecutionBinding` already exists to declare (skill_id,
  binding_id, runtime_id, approval_policy, verified, description). A separate
  `cv_agent/execution/input_contracts.py` keyed by skill_id would duplicate
  the key `ExecutionBinding` already owns and could silently drift out of
  sync with whichever binding is actually registered for that skill_id at any
  given moment — two sources of truth for one pairing, with no mechanism
  keeping them consistent. Attaching it directly keeps one binding = one
  complete declaration, discoverable through the *existing*
  `ExecutionBindingRegistry.get_binding()`/`list_bindings()` — no new lookup
  path, no new registry.

- **What this is NOT:** `input_schema` is **planning metadata, not a
  replacement for runtime validation.** `TrtPerfAnalysisRuntime._build_argv()`
  remains the actual, authoritative enforcement of the contract (it still
  raises `ValueError` for an invalid combination, e.g. both `path` and `data`
  given, or neither) — nothing about this change relaxes or bypasses that. A
  future `plan_execution` node (ADR-0010) reads `input_schema` only to decide
  "do I already have enough to attempt a plan, or is something required
  missing" — a coarser, earlier check than the runtime's own validation, not
  a substitute for it. `SkillExecutionRequest.inputs` stays exactly as
  documented in `cv_agent/execution/models.py` — "opaque to the executor and
  binding registry" — this change does not touch that dict's own type or the
  executor's/registry's ignorance of its contents; it only adds a place to
  *declare*, alongside the binding, what a caller who wants to construct one
  correctly should know.

- **Backward compatibility:** an `ExecutionBinding` with no declared
  `input_schema` (the default `()`) is exactly as valid and executable as
  before this section — `SkillExecutor.execute()` never reads this field at
  all (confirmed: it only reads `verified`/`approval_policy`/`runtime_id`),
  so this addition changes zero existing behavior for the one real binding
  that exists today unless `trt_perf_analysis.build_binding()` is separately,
  deliberately updated to populate it (not done by this change — see ADR-0010
  §9: types only, no behavior).

**Not implemented by this section:** `trt_perf_analysis.build_binding()`
populating its own real `input_schema`; any code that reads
`ExecutionBinding.input_schema` for a real decision. Both are the
implementation PR's job (ADR-0010 §9), not this contract-only change's.

## 12. Status — mutually-exclusive field groups (`RequiredFieldGroup`), resolving Q20

**Added (branch `feature/claude/q20-input-field-groups`, issue #39).** §11's own
"not yet populated" gap and its later-documented revisit trigger (`docs/state/
OPEN_QUESTIONS.md` Q20, raised while building ADR-0010 §13): `InputField.required:
bool` is flat and cannot express trt-perf-analysis's real `path`/`data` contract
(`_build_argv()`, verified directly: exactly one of the two, `ValueError` for both
or neither) — marking either `required=True` would misrepresent it, and marking
both `required=False` would be truthful but could never trigger
`"missing_required_inputs"` at all. Resolved by owner decision (asked directly,
not invented): a "oneOf/XOR field-group construct" on the schema model.

- **New type**, module `cv_agent.execution.binding`:

  ```python
  @dataclass(frozen=True)
  class RequiredFieldGroup:
      kind: Literal["exactly_one"]
      field_names: tuple[str, ...]
      description: str = ""
  ```

  Presence-only, deliberately mirroring `InputField.required`'s own presence-only
  contract: a group is satisfied the moment ANY one member has a known value. It
  does **not** reject "more than one supplied" at the planning layer — that
  stricter half of a true XOR stays `TrtPerfAnalysisRuntime._build_argv()`'s own
  job (already enforced, unchanged), the same "coarser, earlier check, not a
  substitute for the runtime's own validation" posture §11 already established for
  individual fields.

- **`ExecutionBinding` gains one new field:** `input_field_groups: tuple[
  RequiredFieldGroup, ...] = ()`. Default empty tuple — additive, not a breaking
  change to any existing construction site. Validated in a new
  `ExecutionBinding.__post_init__`: every `field_names` entry must name an already-
  declared `InputField.name` in the same `input_schema`, and that field must be
  `required=False` — a field cannot be both unconditionally required and one
  option among several, a contradictory contract rejected at **construction** time,
  not discovered later at planning time. `RequiredFieldGroup` itself rejects fewer
  than two names or duplicate names in its own `__post_init__` — a group of one
  name is meaningless.

- **`trt_perf_analysis.build_binding()` now populates its real contract** — the
  gap §11 explicitly left open: `input_schema` gains `path`/`data` (each
  `required=False`) and `model_name` (genuinely optional, no group);
  `input_field_groups` gains one `RequiredFieldGroup(kind="exactly_one",
  field_names=("path", "data"))`. This is the first binding in the codebase to
  populate either field.

- **`plan_execution()` (ADR-0010 §3) and the `provide_execution_inputs` recovery
  interrupt (ADR-0010 §13) are both extended to be group-aware** — see ADR-0010
  §14 for the planning/recovery half of this decision; this section covers only
  the schema/binding-layer type and its validation.

**What this is NOT:** still planning metadata, not a replacement for runtime
validation — `TrtPerfAnalysisRuntime._build_argv()` remains the actual,
authoritative enforcement of "exactly one, not both." `SkillExecutionRequest.
inputs` is untouched by this change.

**Backward compatibility:** every existing `ExecutionBinding` construction site
that does not pass `input_field_groups` is unaffected — the default `()` means
`__post_init__`'s group-validation loop never executes, and every existing test
asserting `binding.input_field_groups == ()` still holds true for a binding that
does not populate it.
