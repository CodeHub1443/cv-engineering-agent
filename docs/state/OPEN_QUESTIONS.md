# OPEN QUESTIONS

> Questions the canon does not answer that must be answered before certain work can
> proceed. **Answered questions are struck through, not deleted** — the answer and its
> date stay, because "why is it like this" is asked more often than "what is it."
>
> An agent that hits an unanswered question adds it here and stops; it does not invent
> the answer `[P§35]`.

## Blocking — work cannot proceed until answered

~~**Q2. Where does the agent run, and where does training run?** `[P§10]`, `[P§13]`,
`[P§24]` — Local workstation, remote GPU box, cloud, or all three? Does the agent submit
jobs or execute them in-process? *Blocks: ADR-0010.* (No longer blocks ADR-0003 — nothing
in that ADR executes training or submits remote jobs; see ADR-0003 §1.)~~ — **Answered 2026-09-24 (owner decision, D-040):** V1 runs on a **local Linux/NVIDIA GPU execution host**. The Agent/controller process and CV workload processes are **separate**: training, evaluation, benchmarking and optimization execute as **controlled jobs/processes**, not inside the Agent process. *Does NOT decide:* cloud execution, remote workers, Kubernetes, distributed training, or a future scheduler; nor the identity/model of the host, nor whether the controller runs on the same machine as the workloads (see Q25), nor a job lifecycle/supervision design (a future training-execution ADR must conform to this answer). It does not resolve Q3, Q6, or Q19.

**Q3. What is the human-approval transport?** `[P§24]` — CLI prompt only, or must
approvals survive process restart (a queued request answered hours later)? The latter
makes approvals a persisted entity, not an interrupt. **Partially resolved 2026-09-15
(ADR-0003 §1):** the transport is a LangGraph interrupt; whether it survives a process
restart is a property of the checkpointer (swappable), not the graph/node structure.
ADR-0003 ships with `MemorySaver` (confirmed: does not survive process restart) and
defers the durable/queued-approval decision. *Still blocks: a durable/async approval
transport (persistent checkpointer swap-in, ADR-0003 §8 revisit trigger).*

~~**Q4. Is the first target a real project or a reference project?** `[P§30]` — Building
against the prison/garment examples as a real deliverable versus as a test fixture
changes Phase-1 scope substantially. *Blocks: ROADMAP Phase 1 exit test.*~~ — **Answered 2026-09-24 (owner decision, D-041):** V1 validation uses a **controlled reference CV engineering project** before any customer-specific project. *Does NOT decide:* which reference project (see Q24), a customer project, or a permanent exclusion of customer projects.

~~**Q5. Which NVIDIA capabilities are actually installed and invocable today?** `[P§15]` —
The design says "discover and invoke, do not duplicate." Discovery mechanism depends on
whether these are MCP servers, CLI tools, Python SDKs, or agent skills.
*Blocks: ADR-0005, ADR-0007.*~~ — **Answered 2026-09-24 (owner decision, D-042), as a decision about the execution/tool *mechanism*:** V1 uses the **existing explicit Skill/CLI mechanism** behind the `ToolInvoker`/execution boundaries. **MCP SDK integration is deferred**; the abstraction must stay transport-agnostic so MCP can be added later without changing Agent reasoning or approval semantics. *Does NOT decide:* a future MCP implementation, multi-provider tooling, autonomous tool execution, or approval thresholds (Q6). It does not list which capabilities are installed — that stays a runtime fact reported by skill discovery (ADR-0007, `python -m cv_agent skills`) — and it authorizes no binding: each skill still needs its own individually verified binding (ADR-0009 §8). Whether the first real mechanism is an ADR-0009 skill binding or an ADR-0005 `ToolInvoker` wrapping a CLI is not decided here (ADR-0005 §8(c) stays open).

## Soon — needed within one or two phases

**Q6.** What are the default cost thresholds for approval gates (GPU-hours, $, dataset
mutation scope)? `docs/APPROVALS.md` has placeholders. `[P§24]` — **Narrow exception
added 2026-09-28 (owner decision, D-047):** the *first* V1 baseline run is exempt from
needing a cost/spend estimate before execution (the normal approval gate/interrupt
still applies); this does not set any threshold value and Q6 itself remains open.
**Annotation 2026-11-12 (owner answer Q-S, issue #83):** for *LLM API calls only*, spend within the ADR-0020 daily ceiling ($5 per day, whole agent) is pre-authorized and spend above it is refused, not escalated. This sets no threshold for GPU-hours, other spend or dataset operations; Q6 itself remains open.

~~**Q16.** What is the persistence backend for the experiment ledger (`docs/state/
EXPERIMENTS.md`)? Files, SQLite, or a service? — split off from the former Q8
2026-09-15 when Q8's project-memory half was resolved (SQLite; see Q8, Answered,
D-017) — the experiment-ledger half was explicitly **not** resolved by that decision
(ADR-0004 does not move `EXPERIMENTS.md` into SQLite or change its contract) and
remains open. Does not block ADR-0004/`cv_agent/memory/` implementation.~~ —
**Answered 2026-09-24 (owner decision, D-038): SQLite**, mirroring `cv_agent/memory/`'s
`ProjectMemoryStore`/`SqliteProjectMemoryStore` pattern. Implemented as
`cv_agent/experiments/` (ADR-0011, issue #57): a separate `experiments.sqlite` file
(not a table inside project memory's database), behind an `ExperimentLedger`
`Protocol`. `docs/state/EXPERIMENTS.md` remains the human-facing schema definition;
the SQLite ledger is its machine-readable enforcement. Not yet wired into
`CVAgent`/the CLI — no training/evaluation subsystem exists to write real rows.
Does not resolve Q3, Q23, or any other open question.

**Q9.** LinkedIn as a research source `[P§17]` — what is the actual access mechanism, and
what are the terms-of-service constraints? The requirement is clear; the mechanism is
not.

~~**Q10.** Dataset storage and versioning: DVC, Git LFS, or external object store?
`[P§26]`~~ — **Answered 2026-09-28 (owner decision, D-045):** V1 dataset storage
backend is the **local filesystem**. `cv_agent/datasets/`'s `DatasetStore` protocol
(ADR-0012) is unchanged and stays storage-agnostic specifically so another backend
(DVC, Git LFS, object store) can be added later without touching `DatasetManifest`,
the leakage checks, or any caller. *Does NOT decide:* the on-disk layout, a concrete
`LocalFilesystemDatasetStore` implementation, perceptual-hash computation, or dataset
acquisition — none of that is built by this decision (see ADR-0012 §9). Building the
backend module is explicitly out of scope for the session that recorded this answer.

**Q19.** `docs/APPROVALS.md`'s real approval workflow — specifically, *producing a
cost estimate before asking* ("Before asking, the agent estimates the cost" — the
rule's own first line) — has no implementation anywhere in this codebase (confirmed:
ADR-0009 §8 already names this as open; the `approval_gate` graph node, ADR-0003,
interrupts with `{skill_id, binding_id, task, inputs}` only, no estimate field).
Distinct from **Q6** (which asks what numeric *thresholds* should trigger a gate,
assuming an estimation mechanism exists) — this asks whether any mechanism to
*produce* an estimate exists at all for a given binding, and if not, who's
responsible for building one. Currently moot for `trt-perf-analysis` (`"allowed"`
policy, never gated) but becomes load-bearing the moment ADR-0010's planning
connector — or anything else — ever selects a candidate whose binding is
`approval_required`. `[P§24]`, `[P§29.8]`. *Blocks: any `approval_required` binding
being exercised through a real, non-fake approval flow with an actual estimate
attached, including via ADR-0010's future planning connector.* — **Narrow exception
added 2026-09-28 (owner decision, D-047):** the *first* V1 baseline run does not need
a cost/spend estimate produced before it executes; actual runtime/resource
measurements are captured *after* execution where available and written to the
experiment ledger instead. No general estimation mechanism or cost model is invented
by this exception, and Q19 itself remains open for every run after the first.

~~**Q22.** *New 2026-09-21 (independent audit of PR #42; tracked as GitHub issue #43).*
`pending_execution` pins only `skill_id` (`{"skill_id", "inputs", "task"}`), and both
`_node_approval_gate` and `SkillExecutor.execute()` re-resolve the binding **live, by
`skill_id` alone**; nothing compares it with the binding the human was shown.
`provide_execution_inputs` (ADR-0010 §13) and `choose_candidate` (§16.3) already pin the
exact binding across their pauses — the approval pause, which is the one that authorizes
execution, does not. Two defects, **both reproduced on current `main` (`3230361`) and on
pre-Q18 commit `752bc1c`** (so pre-existing): **(1)** a replacement binding/runtime
registered during the approval pause executes under approval granted for the original;
**(2)** a replacement whose `approval_policy` is `"allowed"` **overrides a human
rejection** and executes with `approval_decision="not_required"` — also when the
replacement keeps the same `binding_id` and only flips the policy — because the gate's
live `get_binding()` before `interrupt()` re-runs on resume and discards the recorded
decision. Trigger requires mutating the in-process registry during a pause (low
likelihood today: one real binding), but it violates the replay-safety rule §13/§16
already impose on the newer interrupts and weakens the approval guarantee `[P§24]`.
Open design questions: where the execution-time check lives (execute node vs an expected-
binding field on `SkillExecutionRequest`); what a caller-supplied `pending_execution`
(ADR-0010 §10, no `binding_id`) pins; whether strict description pinning (owner decision,
#42) extends through the input-recovery retry and approval (today a description-only change
during the *second* pause of a chained recovery runs); and ADR-0010 §16.3's scope wording.
Architectural (changes `pending_execution`'s shape) — **an ADR amendment must precede
code.** Not implemented. *Blocks: treating `approval_gate` as a hard guarantee under
registry mutation.*~~ — **Implemented 2026-09-21 (issue #43, branch `fix/claude/43-approval-integrity`, ADR-0003 §10 / ADR-0009 §14 / ADR-0010 §17, D-032), pending PR review and merge.** Both defects and the same-`binding_id` policy-flip variant are covered by regression tests: the approval pause now pins the whole binding plus a runtime registration generation (`pending_execution["execution_pin"]`); the gate decides from the pin only; a recorded rejection is terminal before any pin validation, registry read or executor call; the executor compares the pin against its own single read; description pinning extends through `provide_execution_inputs`. Answers to the open design questions: the check lives in the executor (`expected_binding_pin`); a caller-supplied plan is pinned at first observation; strict description pinning was extended through input recovery and approval; §16.3's scope wording was corrected. Remaining, documented limits (ADR-0003 §10.8): in-place mutation of a registered runtime object, process restart (a persistent pin is Q3's concern), thread safety.

**Q23.** *New 2026-09-21 (split out of PR #42 by owner decision; GitHub issue #44).*
`python -m cv_agent workflow` builds a plain, unregistered `CVAgent` (ADR-0009 §5), so
`approval_gate` / `provide_execution_inputs` / `choose_candidate` are never reachable
against a **real** installed skill through the CLI; their CLI handling is proven only by
fixture-graph and fake-runtime `CVAgent` tests (accepted for #42). Two sub-problems with
different blockers: **(a)** opt-in registration of the real `trt-perf-analysis` binding from
`workflow` would make `provide_execution_inputs` reachable for real (its `path`/`data` XOR
contract is real, ADR-0009 §12) — an execution-surface design decision for the owner;
`approval_gate` still would not be, since that binding's default policy is `"allowed"`;
**(b)** `choose_candidate` needs **more than one** real binding, i.e. a second
`ExecutionRuntime`, currently on `STATUS.md`'s "Do not start yet" list — blocked on that
decision, not on engineering. *Blocks: any real-skill end-to-end CLI test of the three
interrupt kinds.*

~~**Q24.** *New 2026-09-24 (surfaced while recording Q4/D-041).* Q4 chose a controlled
*reference* project for V1 validation but did not name it. Which reference project —
its CV task and target scenario, its dataset source and provenance, and the operational
constraints (latency, recall, false-positive tolerance `[P§5]`) it is validated against?
Phase 5's exit test needs "a baseline ... on a named target", and `docs/DATA.md` requires
a dataset with a manifest. *Blocks: ROADMAP Phase 5b (baseline establishment).* `[P§30]`~~
— **Answered 2026-09-28 (owner decision, D-043):** the reference project is **Person
Detection + Tracking** — objective: high-performance, real-time, low-resource person
detection; input: CCTV/video stream; NVIDIA GPU is the target execution environment.
The **Agent must research and select** the detection/tracking model or approach — it
must not be hardcoded to YOLO, and the owner is not asked to pick one. The Agent must
similarly **research/recommend the reference dataset** and **propose the evaluation
metrics** (not have either handed to it). This is explicitly a **reference/proving-ground
task, not a specialization of the Agent** — the design and any code built for it must
stay generic. *Does NOT decide:* which specific model, dataset, or metric set is
actually selected (that is the Agent's own researched output, not an owner choice); the
job-execution mechanism that will run it (see D-046); the dataset storage backend (see
D-045). See `docs/architecture/adr/ADR-0013-job-process-execution-boundary.md` and
ADR-0005/ADR-0006's status appendices for what this now unblocks and what still doesn't
exist to act on it.

~~**Q25.** *New 2026-09-24 (surfaced while recording Q2/D-040).* Q2 chose a local
Linux/NVIDIA GPU execution host with a controller process separate from workload
processes, but did not say which host or GPU (a "named target" for every ledger row's
`hardware` field, `[P§25]`), nor whether the controller runs on that same host or on
another machine (this repository's sessions currently run on Windows, and
`docs/APPROVALS.md` forbids running Linux-specific commands on another platform).
*Blocks: ROADMAP Phase 5b (a baseline on a named target), and any execution binding that
must state where it runs.* `[P§13]`, `[P§25]`~~
— **Answered 2026-09-28 (owner decision, D-044):** the CV workload execution host is
**Linux + NVIDIA GPU**; the Agent/controller process and CV workload processes **remain
separate**, confirming — and explicitly **not changing** — D-040's architecture.
*Does NOT decide:* a concrete host/GPU identity (hostname, GPU model, driver/CUDA
version — the specific "named target" for a ledger row's `hardware` field is still not
named, only the platform class is); whether the controller runs on the same physical
machine as the workload or a different one (D-040 said "separate processes," which does
not by itself say "separate hosts"); the job lifecycle/supervision design (see D-046,
new ADR-0013).

## Deferrable

**Q11.** Multi-camera / multi-stream orchestration model. `[P§9]`
**Q12.** Monitoring backend and alerting surface. `[P§28]`
**Q13.** Does the agent ever fine-tune or serve its own models, or only orchestrate? 
**Q14.** Multi-user / team usage, or single-operator? Affects memory and approvals.

## Answered

~~**Q7.** Which LLM providers are actually available with keys, and what is the
routing policy per task class?~~ `[P§20]` — **Answered 2026-09-23 (owner decision,
D-033):** **Anthropic**, with credentials available; routing policy is **a single
configured model, no automatic fallback** — task-complexity-based routing (`[P§20]`'s
long-term vision) is explicitly deferred, not decided against, pending a second
authorized provider. See ADR-0002.

~~**Q0.** Should the canonical document be edited into the repository docs, or kept
verbatim?~~ — **Answered 2026-08-30:** kept verbatim and frozen as `docs/PROJECT.md`;
derived files cite it as `[P§n]`. See D-001.

~~**Q1. What is the unit of a "project"?**~~ `[P§25]`, `[P§33]` — Does the agent handle
one CV project per repository/workspace, or many projects with isolated memory? —
**Answered 2026-09-15 (owner decision):** **one CV project per repository/workspace**
in V1. The workspace/repository IS the project boundary — no `project_id`
abstraction, no project selection, no multi-tenant memory. Session identity
(`AgentState.session_id`) stays distinct from project identity; every session belongs
to the one implicit project (the workspace). No broader multi-repository workspace
abstraction in V1. Project Understanding is persistent current state with recoverable
revision history; experiments remain immutable append-only records. See D-015,
ADR-0004. *Clarified 2026-09-15 (D-019):* the boundary being "the workspace" does not
by itself guarantee any given process execution resolves it correctly — the
**calling application**, not `ProjectMemoryStore`, is responsible for resolving
`workspace_root` explicitly; `Path.cwd()` is a convenience default only.

~~**Q15. Is Project Understanding storage Git-tracked, and is it sensitive data?**~~
`[P§24]`, `[P§25]` — An ADR-0004 audit identified this as a missing decision: the ADR
named a storage backend as open (Q8) but never addressed whether persisted Project
Understanding is committed to the repository or kept local, nor whether it is
sensitive data under `docs/APPROVALS.md` — a real gap given `docs/PROJECT.md` §5/§30's
own worked examples (prison security, factory floors) can surface operationally
sensitive facility detail. — **Answered 2026-09-15 (owner decision):** Project
Understanding is classified as **potentially sensitive project data**, governed by
`docs/APPROVALS.md`'s data/privacy rule. It must be **durable across process
restarts** but must **NOT** be automatically stored in Git-tracked repository files —
V1 persistent storage is **local/project-scoped and gitignored by default**.
Durability does not imply Git tracking. This does not change `EXPERIMENTS.md`'s
contract (that ledger's own tracking status is unaffected). External-LLM transmission
remains governed by the existing approval/privacy rules regardless of persistence —
storing data locally grants no new permission to send it externally. *Distinct from
and does not resolve* **Q8**, which stays open (files vs. SQLite vs. a service — this
decision constrains *where implied by Git*, not *which technology*). See D-016,
ADR-0004.

~~**Q8. What is the persistence backend for project memory?**~~ files, SQLite, or a
service? — **Answered 2026-09-15 (owner decision):** **SQLite**, for V1. Local and
project-scoped — the database file lives in the project's gitignored
persistent-state area (per Q15/D-016: not Git-tracked). Must survive process
restarts. SQLite stays **behind** the `ProjectMemoryStore` `Protocol` (ADR-0004 §5) —
no `cv_agent` module outside `cv_agent/memory/` may import a SQLite-specific type or
depend on it directly, so a future backend can replace it without touching callers.
No external database/service is required for V1. This resolves Q8 for **project
memory only** — the experiment ledger's own backend question is unaffected and spun
off separately as **Q16** (Soon), since ADR-0004 does not move `EXPERIMENTS.md` into
SQLite or change its contract. See D-017, ADR-0004.

~~**Q17.** Same-session recovery when `plan_execution` returns
`missing_required_inputs`.~~ *Narrowed 2026-09-17 (ADR-0010 §12):* a caller who
already knows a required execution input's value **before** a run starts got a real
channel — `CVAgent.start_workflow(execution_inputs=...)`. — **Answered 2026-09-17
(ADR-0010 §13):** a caller who only learns the missing value **after**
`plan_execution` already produced `planning_result.status ==
"missing_required_inputs"` now has a same-session recovery path — a third interrupt
kind, `provide_execution_inputs`, architecturally consistent with the existing
`clarify` interrupt (ADR-0003), bounded to exactly one prompt per run, gated by an
explicit identity+schema comparison against checkpointed state before any plan may
be produced from it, and bypassing `approval_gate` entirely on any
incomplete/invalid/cancelled/binding-mismatch outcome so a failed recovery can never
be read as "approval not required." See ADR-0010 §13 for the full design. Spun off a
new, separate, unresolved question, **Q20**, for the TRT `path`/`data` XOR contract
this work found `InputField`'s flat schema model cannot express.

~~**Q21.** `cv_agent/graph/workflow.py`'s `_route_after_analysis` decides whether to
route back to the `clarify` interrupt again using
`bool(state.get("clarification_answers"))` — truthiness, not "was clarify already
attempted this run". A human who declines to answer *every* clarification question
resumes with an empty answers value; `clarification_answers` stays falsy, and the
graph re-raises the same `clarify` interrupt indefinitely rather than treating
"asked and declined" as answered — confirmed empirically: reproduced a genuine,
unbounded loop via the real graph. What should the real fix be, and does `clarify`'s
own separately-documented empty-dict-`Command(resume=...)`-not-reliably-delivered
gap need fixing in the same pass?~~ — **Answered 2026-09-19 (ADR-0003 §9, D-026):**
new `AgentState["clarification_attempted"]: bool`, set unconditionally by
`_node_clarify` on every resume — mirrors `execution_input_recovery["attempted"]`'s
existing pattern (ADR-0010 §13). `_route_after_analysis` now routes on this flag,
never on `clarification_answers`' truthiness. The empty-dict-delivery gap **was**
confirmed to need fixing in the same pass — not the same root cause (routing logic
vs. LangGraph transport), but both compound into the same symptom and neither fix
alone was sufficient — resolved by having the CLI resume with `""`, never `{}`, when
every question is declined, the same convention already established for
`provide_execution_inputs`. See ADR-0003 §9 for the full design and empirical
confirmation.

~~**Q20.** *New 2026-09-17 (ADR-0010 §13, discovered while resolving Q17).*
`ExecutionBinding.input_schema`/`InputField.required: bool` (ADR-0009 §11) is
deliberately flat and cannot express `trt-perf-analysis`'s real input contract,
confirmed by direct inspection of `_build_argv()`: exactly one of `path`/`data` is
required (a genuine XOR), not `path` unconditionally. Marking either field
`required=True` would misrepresent the contract (`[P§35]`); marking both
`required=False` would be truthful but could never trigger
`missing_required_inputs` for this binding at all. What should the schema model
gain — a oneOf/XOR field-group construct, a separate validation callback, something
else — and who owns designing it?~~ — **Answered 2026-09-18 (owner decision, asked
directly alongside Q18): a oneOf/XOR field-group construct.** New
`RequiredFieldGroup` (ADR-0009 §12) on `ExecutionBinding.input_field_groups`.
**Corrected 2026-09-18, same day, on independent PR #40 review (D-028):** the
first implementation checked presence only ("at least one member supplied"),
deferring "reject more than one" entirely to the runtime — this under-enforced
the decision's own "EXACTLY ONE alternative" wording. Fixed before merge: a
group is now satisfied only when *exactly* one member is present; two or more
together is a new, distinct `"conflicting_inputs"`/`"conflicting"` outcome,
caught and reported before any plan, approval interrupt, or execution is ever
attempted (ADR-0010 §15). `plan_execution()` and the `provide_execution_inputs`
recovery interrupt are both group-aware (ADR-0010 §14/§15); `ExecutionBinding.
__post_init__` also rejects a field belonging to more than one group (ADR-0009
§13). `trt_perf_analysis.build_binding()` populates its real `path`/`data`/
`model_name` contract. The blocked genuine, unfaked end-to-end recovery test
against the real binding — including the true-XOR "both supplied" rejection
path — is now written and passing (skipped, not faked, on a machine without
the skill installed) — see ADR-0009 §12/§13, ADR-0010 §14/§15, D-027, D-028.

**Q26. (2026-09-30) How should standard benchmark datasets (COCO, VOC, ImageNet, etc.) be
registered in `DatasetManifest` without requiring perceptual hash computation as a
prerequisite?** `DatasetManifest` construction raises `LeakageError` when any item has
`perceptual_hash=None` (the near-duplicate check is fail-closed). For a 5000-image
dataset like COCO val2017, computing perceptual hashes would require loading all 5000
images — a separate operation not part of the evaluation pipeline. Options: (a) compute
hashes in a separate step before `DatasetManifest` creation; (b) add an explicit
`skip_near_duplicate_check=True` flag to `DatasetManifest` (requires a recorded rationale,
e.g., "public benchmark with known provenance — near-duplicate check is not the leakage
concern for this split"); (c) a separate `BenchmarkDatasetRef` type that does not require
leakage checks for publicly-released, externally-validated datasets; (d) record the
dataset reference as a plain string in `ExperimentRecord.dataset_version` only, with
provenance in notes (current approach for D-061/EXP-20260930-01). **Current status:**
using approach (d) for now (D-061). This question blocks full `DatasetManifest`
registration of COCO val2017 and any future benchmark dataset.

~~**Q18.** When ADR-0010's V1 selection rule finds **more than one** executable
`SkillLink` candidate for a task component, it explicitly produces no plan rather than
silently picking one (`[P§35]`) — surfaced via `AgentState.planning_result.
candidate_skill_ids` (ADR-0010 §11). What should actually happen instead — an explicit
CLI `--skill <id>` override (mirroring `_cmd_execute`'s existing explicit-skill_id
CLI contract), a clarification-style interrupt asking the human to choose, or something
else?~~ — **Answered 2026-09-18 (owner decision, asked directly alongside Q20): a
clarification-style interrupt**; **implemented 2026-09-20 (ADR-0010 §16, D-029, issue
#41):** a fourth interrupt kind, `choose_candidate`, fires when `plan_execution()`
reports `"ambiguous_candidates"`, presents every candidate's skill_id + description,
validates the human's bare-skill_id answer against the exact checkpointed offered set,
persists it (`AgentState.candidate_choice`/`candidate_selection`) and resumes planning
via `plan_execution(..., selected_skill_id=...)`, whose retry independently re-confirms
the choice against the current registry. One shot: an invalid/cancelled/no-longer-valid
choice is terminal and never silently defaults. **Audit-corrected 2026-09-20 (D-030):**
the choice is pinned to the exact binding *shown* (`binding_id` + description snapshotted
at ask time), not merely a `skill_id`; a terminal recovery failure clears
`planning_result.plan`; a malformed offer fails closed; and empty `{}`/`None` resumes are
documented as LangGraph behavior, not classified answers. No CLI `--skill` override was built
(not chosen). Caller-supplied `pending_execution` and `python -m cv_agent execute` are
untouched.

**Q27.** **Size-stratified mAP (small/medium/large)**: Per-size-category mAP requires
the COCO API (`pycocotools`) and `instances_val2017.json` (the official COCO annotation
file, ~250 MB, not yet downloaded). Without it, the diagnosis module can measure GT bbox
SIZE DISTRIBUTION but cannot report separate mAP values for small/medium/large objects.
Options: (a) download `instances_val2017.json` and run `faster-coco-eval` (already
attempted; skipped because file absent); (b) implement a custom IoU-based TP/FP/FN
breakdown per size bucket from predictions.json + GT labels + image dimensions (requires
loading image headers for all 5000 images, feasible with PIL); (c) accept the gap and
proceed to the conf-threshold sweep experiment which does not require size-stratified mAP.
**Current status:** gap documented in ADR-0015 §5. Q27 unresolved. Opened D-064.
~~**Q28. (2026-10-04) Which mAP protocol is canonical for `yolo val` evaluations?** The
`yolo_eval` binding defaults to `conf=0.25` (`DEFAULT_CONF`). Ultralytics' validation
default is `conf=0.001`. At 0.25 the PR curve is truncated, so the reported mAP@.5:.95
(0.459 baseline) understates the detector's mAP, and sweep rankings by mAP are artifacts
(EXPERIMENTS.md, sweep result). Options: (a) `conf=0.001` for all mAP reporting, with the
operating threshold reported separately as fixed-threshold P/R (recommended); (b) keep
0.25 and label the metric "truncated mAP". Changing the default changes the binding, so it
needs an owner decision. Blocks: EXP-20261004-01 Stage 0. Owner: Tanvir.~~ — **Answered
2026-10-04 (owner decision, D-067): option (a), accepted.** `yolo_eval` default is now
`conf=0.001` (with a test). Fixed-threshold P/R is a separate measurement, never reported as
mAP. The inference binding's 0.25 default is unchanged (operating point; see Q30).

**Q29. (2026-10-04) Where is the canonical experiment ledger, and how do we fix the row
gaps? — ANSWERED 2026-10-04 (owner approval).** Recovery executed from the Trash copy by copy with
checksum and SQLite integrity verification (LEDGER-RECOVERY.md §4a, Part 1 and Part 2). The Trash
copy is untouched. The database stays gitignored under the D-015 SQLite convention, with no per-run
JSON snapshots. Provenance and write rules are implemented (ADR-0016). The default ledger path is
fixed to the repository's state root (no cwd-relative creation). Historical rows keep NULL
`commit_sha`. No SHA was fabricated.

~~**Q30. (2026-10-04) What precision floor, or operating point, does the person-detection
target require? — OPEN. OWNER INPUT REQUIRED before any production operating point is
defined.** Fixed-threshold recall rises 0.670→0.773 at conf=0.10, but precision falls
0.776→0.541. No precision floor, operating point, or pass/fail threshold on precision or
fixed-threshold recall has been set by any document. EXP-20261004-01 defines **no** pass/fail criteria
for this reason, and it reports threshold-free small-object AP50 from the full curve. Reported
fixed-threshold P/R at conf 0.25 is reference-only. Related: Q24 (reference project), Q25 (target hardware).
Owner: Tanvir.~~ — **Answered 2026-10-14 (owner decision, D-077): precision floor 0.75 at
conf=0.25, IoU >= 0.5.** Fixed-threshold precision only; never mAP. Reference operating point
conf=0.25. D-069 is answered in the same session (D-078) with the AP gains still provisional (Q32).

**Q31. (2026-10-04) Should the repository pin the trt-perf-analysis skill version and output
schema, or track the installed skill?** Current behaviour: the real-skill tests read the installed
skill's declared `schema_version` and its layers + profile input contract (`tests/trt_skill_contract.py`).
A skill upgrade therefore fails visibly in tests and is not silently pinned. Pinning "1.2" in the
repository would fail on any machine with a different installed skill, and the skill's own schema
is the authority. This is a genuine ownership decision between repository and skill, and it is
not guessed here. **Until decided:** track the installed skill; do not hard-code a version. Owner:
Tanvir, or the skill owner.

**Q32. (2026-10-14) Are the provisional AP acceptance thresholds (+0.010 overall AP@0.5:0.95,
+0.020 small-person AP@0.5) valid gates? — OPEN for (a), (c) and (d); (b) answered 2026-11-04 (D-082). OWNER INPUT REQUIRED before any run that is
meant to drive a decision.** Baseline provenance matches EXP-20261004-01 (0.517 / 0.3556 at 640).
Missing evidence: (a) run-to-run variance of `yolo val` and of any training seed (one run per
configuration so far); ~~(b) which inference precision defines the baseline (FP16-requested
EXP-20261004-01 versus FP32 EXP-20261004-04, 0.518 / 0.3547)~~ — **(b) answered 2026-11-04 (owner
decision, D-082): FP16-requested EXP-20261004-01 is the baseline; candidates must match its precision;** (c) the practical rationale for the
delta sizes on this dataset; (d) whether "improve" means >= the delta or any positive change.
Until answered, issue #76 encodes the thresholds as provisional-labelled configuration. Owner: Tanvir.

**Q33. (2026-11-04) Should training and acceptance identifiers be typed identities rather than free strings?** `[P§32]` Review finding L3 on ADR-0019: `TrainingJobRequest` and `TrainingApproval` carry `experiment_id`, `approval_ref`, `scope`, `model`, `precision`, `dataset_version` and `hardware_target` as validated strings, and `evaluate_candidate(variable_under_test=...)` takes a string. CLAUDE.md §8 says registries hold typed identities, not free strings. Which identities become types, and which registry owns them, changes state shape and is not decided here. **Until decided:** strings stay format-validated where a format exists (EXP ids, 40-hex SHA). Owner: Tanvir.

~~**Q34. (2026-11-12) Should `LLMRequest.temperature` be removed, or kept as an ignored field? (Q-I)** `[P§20]` Opus 5.5 rejects it (live check L-1) and the docs say to omit it. Removal touches `research.py:266`, `selector.py:286` and the temperature assertions in `tests/test_llm_anthropic.py` and `tests/test_llm_mock.py`. *Safe default:* remove it in slice G1. Real adapters never send it either way. ADR-0020 §3.9 assumes removal. Owner: Tanvir.~~ — **Answered 2026-11-12 (owner): safe default** (remove `LLMRequest.temperature` in slice G1). ADR-0020 acceptance, issue #89.

~~**Q35. (2026-11-12) When `stop_reason` is `max_tokens` and some text exists, raise or return the partial text with a flag? (Q-J)** `[P§20]` Call sites parse JSON, so partial text is a silent defect. *Safe default:* raise `LLMTruncatedError`. Owner: Tanvir.~~ — **Answered 2026-11-12 (owner): safe default** (raise `LLMTruncatedError` even when some text exists). ADR-0020 acceptance, issue #89.

~~**Q36. (2026-11-12) Adapter `max_retries`: 0 or 2? (Q-K)** The current adapter uses 2. With retries one `complete()` can be several HTTP attempts, which blurs the one-row-per-call log and the one-reservation budget. *Safe default:* 0 (fail closed, D3). Owner: Tanvir.~~ — **Answered 2026-11-12 (owner): safe default** (adapter `max_retries=0`). ADR-0020 acceptance, issue #89.

~~**Q37. (2026-11-12) Add the provider request ID to the call log beyond the D4 field list? (Q-L)** *Safe default:* no, keep exactly D4; the ID stays in `LLMResponse`. Adding it helps provider support. Owner: Tanvir.~~ — **Answered 2026-11-12 (owner, issue #83):** yes, the provider `request_id` is added to the call log (the D4 fields plus `request_id`). See ADR-0020 §5.1 (Q-L).

**Q38. (2026-11-12) How does an experiment record reference LLM calls? (Q-M)** `[P§25]` Option 1: a `llm_call_ids=...` token in the existing `notes` field. Option 2: a typed field, which needs an ADR-0011 amendment and a change to both `docs/state/EXPERIMENTS.md` and `cv_agent/experiments/models.py`. *Safe default:* option 1 now. Owner: Tanvir.

**Q39. (2026-11-12) Which tier for the NARRATIVE task class? (Q-N)** Recommended `fast` (short prose over computed fields, never a source of fact, D-011). It stays `offline` until `PROJECT_DATA` is allowed (see Q40). *Safe default:* `fast`. Owner: Tanvir.

~~**Q40. (2026-11-12) Selector and analyzer send free-text project data. Allow `PROJECT_DATA` for hosted tiers, or restructure the prompts? (Q-O)** `[P§24]` `select_candidate` sends `task_description` (`selector.py:273-274`) and the analyzer narrative sends the raw request (`analyzer.py:292`). Under default-deny the strong tier and the NARRATIVE route have no permitted production use until this is answered (ADR-0020 §3.1). *Safe default:* keep `PROJECT_DATA` blocked and restructure the selector prompt to structured fields later. Owner: Tanvir.~~ — **Answered 2026-11-12 (owner, issue #103):** keep `PROJECT_DATA` blocked for hosted tiers; restructure the SELECTION and NARRATIVE prompts so only structured fields are sent (SELECTION may also carry provenance-bound public-web claims). Design in ADR-0023 (Proposed). Recorded as D-094. Track order: Q40, then Q41, then Phase 6.

**Q41. (2026-11-12) Open an issue for a user-facing research entry point? (Q-P)** `perform_research` has no production caller, so D9 (research extraction on the fast tier) can only be proven at config and test level. *Safe default:* a separate issue after slice G7. Owner: Tanvir.

~~**Q42. (2026-11-12) Missing call-log store: explicit `cv-agent llm-log init`, or auto-create on first use? (Q-Q)** Auto-create would let a deleted file silently reset the day's spend. *Safe default:* explicit init, fail closed. Owner: Tanvir.~~ — **Answered 2026-11-12 (owner): safe default** (explicit `cv-agent llm-log init`, fail closed when the store is missing (G2)). ADR-0020 acceptance, issue #89.

~~**Q43. (2026-11-12) Call-log retention: keep forever, or prune after N days? (Q-T)** About 36,500 small rows per year at the call limit. *Safe default:* keep, append-only, no pruning. Owner: Tanvir.~~ — **Answered 2026-11-12 (owner): safe default** (keep the call log, append-only, no pruning). ADR-0020 acceptance, issue #89.

~~**Q44. (2026-11-12) Where is the project `.env` looked up: main checkout root (shared by worktrees) or the current directory? (Q-U)** ADR-0021 §3 item 2 assumes the main checkout root. *Safe default:* main checkout root. Owner: Tanvir.~~ — **Answered 2026-11-12 (owner): safe default** (the project `.env` is looked up at the main checkout root (done in C2)). ADR-0020 acceptance, issue #89.

~~**Q45. (2026-11-12) Which machine hosts measured CV runs, and which GPU is it? (Q-V)** The brief names the Windows RTX 3050; the experiment ledger records measured runs on a Linux host with an RTX 3060 12 GB (`docs/state/EXPERIMENTS.md`). A future local LLM tier must never use a measured-run GPU (D1, D-074, ADR-0018 §6). **Not answered at the time of writing** (the owner's answer was left blank in the D0 instruction). *Safe default:* treat both GPUs as measured hosts; any local tier is CPU-only. Owner: Tanvir.~~ — **Answered 2026-11-12 (owner, issue #83):** both PCs (Windows RTX 3050 and Linux RTX 3060) are measured CV hosts and no LLM runs locally on either; the local tier and ADR-0022 stay plan-only, and if ever enabled must not use either GPU (D1, D-074). Recorded as D-091 (Q-V).

**Q46. (2026-11-12) Second adapter dialects: Ollama native only for `keep_alive: 0`, or also `/v1`? (Q-W)** Ollama documents `keep_alive` on `/api/chat` and `/api/generate` but not on `/v1/chat/completions` (docs.ollama.com, retrieved 2026-11-12). The httpx-versus-openai-SDK choice belongs to ADR-0022. *Safe default:* both dialects, native for Ollama. Owner: Tanvir.

~~**Q47. (2026-11-12) Provider-name strings outside the gateway (`CLAUDE.md` §3.8): what to do with the borderline hits?** `cv_agent/graph/state.py:40` (docstring "e.g. 'mock', 'anthropic'"); commented examples at `config/default.toml:8-9` and `cv_agent/resources/config/default.toml:8-9` (obsolete once `overrides` is deleted in slice G5); `cv_agent/resources/spec/capability_registry.json:1163-1170` ("claude-code", "OpenAI Codex" worker-runtime identities, not LLM-gateway use). *Safe default:* reword the docstring and remove the TOML examples in G5; leave the capability registry entries and ask whether §3.8 covers them. Owner: Tanvir.~~ **Resolved in part (2026-11-12, housekeeping-2, issue #107).** Fixed: `cv_agent/graph/state.py:40` docstring reworded to be provider-neutral. The two TOML comment examples no longer exist (the default.toml files name no provider or model). Deliberately left, by class: (1) worker-runtime names ("Claude Code", "Codex" in `execution/binding.py`, `executor.py`, `capability_registry.json:1163-1170`): identities of coding-worker runtimes, not LLM-gateway use, per the Q47 safe default; (2) the `~/.claude/skills` path convention (`skills/local.py`, `deepstream_validate_pipeline.py`, `trt_perf_analysis.py`): a filesystem location, not a provider or model; (3) `CLAUDE.md` references in docstrings: they cite this file; (4) `capability_registry.json` data: registry entries, not gateway code; (5) tests, `pyproject.toml` extras, config and docs: the gateway adapters and their tests legitimately name the provider, and docs describe it. Whether §3.8 covers class (1) and (4) is still an owner call; no executable code outside `cv_agent/llm/` names a provider.

**Q48. (2026-11-12) The canon exists in three copies. Which to keep?** `docs/PROJECT.md` and the root `CV Engineering Agent.md` are byte-identical (1716 lines); `docs/archive/PROJECT_SOURCE_DRAFT.md` differs (1721 lines). `docs/PROJECT.md` is frozen. *Safe default:* change nothing; owner decides whether the root copy stays or is marked as a mirror. Owner: Tanvir.

**Q49. (2026-11-12) The `anthropic>=0.40,<1` SDK pin: move to a newer major?** PyPI shows 1.0.0 (2026-08-20), 2.0.0 (2026-10-21) and 2.8.0 (2026-11-10, retrieved 2026-11-12); 2.x depends on `httpx2`, not `httpx`. Breaking changes are not reviewed. *Safe default:* slice G1 raises the lower bound to 0.125 and keeps `<1`; a 2.x upgrade is its own issue after a changelog review. Owner: Tanvir.

~~**Q50. (2026-11-12) Does the owner accept ADR-0020 (LLM gateway v2, Proposed)?** The gateway-v2 D-entry waits for acceptance. Slices G1 to G7 need it; C1 and C2 need only ADR-0021 (Accepted). *Safe default:* hold until the owner has reviewed ADR-0020. Owner: Tanvir.~~ — **Answered 2026-11-12 (owner): safe default** (ADR-0020 accepted (D-092)). ADR-0020 acceptance, issue #89.

~~**Q51. (2026-11-12) Design questions Q-A to Q-H, Q-R and Q-S of the LLM gateway v2 design.**~~ — **Answered 2026-11-12 (owner, issue #83), as recommended in the design report:** Q-A daily limit of 100 calls; Q-B at most 24,000 input characters per call; Q-C hosted tiers may receive `PUBLIC_WEB` and `PROJECT_METADATA` only (`PROJECT_DATA` blocked); Q-D delete `LLMConfig.overrides` (and `provider`/`model`) for typed tiers; Q-E accept ADR-0021 first and hold ADR-0020 until reviewed; Q-F the day boundary is calendar day at UTC+06:00; Q-G hosted tiers are used from one machine only, the owner's Windows PC, the only machine holding the project `.env` key, and on any other machine hosted calls fail closed with `LLMCredentialError` (so the $5 per day ceiling is the true whole-agent ceiling); Q-H tiers, model facts and prices live in the gateway-owned `cv_agent/llm/catalog.toml`; Q-R the credential rule is folded into an existing `CLAUDE.md` §3 line with no net line growth (slice C1); Q-S the ADR-0020 daily ceiling counts as the LLM-spend threshold (pre-authorized within, refused above), see the Q6 annotation. Q-L and Q-V are answered under Q37 and Q45. *Does NOT decide:* ADR-0020 acceptance (Q50) or any other open question.

~~**Q52. (2026-11-12) What are the real maximum output tokens of `claude-opus-5-5` and `claude-haiku-5-5`?** `catalog.toml` records `max_output_tokens = 64000` for both, the previous generation's documented limit, not a verified 5.5 figure (slice G5, issue #97). It only feeds the load-time check "tier `max_tokens` above the model maximum"; the binding cap is `[llm.budget] max_output_tokens` (4000), so no call is affected. *Safe default:* leave 64000, marked UNVERIFIED in the catalog; verify against the models documentation when prices are next refreshed. Owner: Tanvir.~~ **Answered 2026-11-12 (owner-supplied, issue #99):** both models are 128000 per the Anthropic model docs; `catalog.toml` updated. The binding cap stays `[llm.budget] max_output_tokens` (4000).

**Q53. (2026-11-12) Windows `test_baseline_wiring` fails with PermissionError (WinError 32).** Five tests in `test_baseline_wiring.py` fail on Windows because a SQLite file is still open when the temp directory is cleaned up. An earlier NotADirectoryError flake did not reproduce in five isolated runs or in the full run. *Safe default:* a test-only PR that closes the connection before cleanup. Owner: Tanvir.

**Q54. (2026-11-12) Durable KnowledgeStore backend (ADR-0006 §8): needed before research results can feed SELECTION across processes.** The only `KnowledgeStore` today is `InMemoryKnowledgeStore`, which is not durable, and no CLI command wires one. *Safe default:* in-process store only; design the durable backend in a separate DESIGN-ONLY ADR, written together with ADR-0023 S4 (the KnowledgeStore writer). Owner: Tanvir.
