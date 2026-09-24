# ROADMAP

Phases, not a task list. **Every phase has a measurable exit test.** A phase is not done
because the work feels done; it is done when the exit test passes.

Sequence follows the dependency order in `docs/architecture/OVERVIEW.md` — substrate
before intelligence, intelligence before demo surface `[P§33]`, `[P§34]`.

Each phase maps to one GitHub milestone; the milestone description **is** the exit test.

---

## Phase 0 — Governance ⟨current⟩

**Goal:** the project can be worked on by any agent or human without re-deriving intent.

**Scope:** frozen canon; `CLAUDE.md` / `AGENTS.md`; architecture overview + responsibility
table; ADR template; rolling state files; approvals, research, evaluation, data contracts;
GitHub labels, templates, CI.

**Exit test:** a fresh session, given only the repo, reads `STATUS.md` and produces a
correct account of the project's next three actions and its hard rules — without being
told anything in chat.

**Status:** rolling state files, policy docs, ADR template, and GitHub labels/templates
are in place and actively maintained (`docs/state/DECISIONS.md` has 32+ logged rows as
of `main` `0e86979`). **Was not done, now added:** GitHub Actions CI (`ruff` + `mypy` +
`pytest` on push/PR to `main`) — previously the scope item this phase names ("GitHub
labels, templates, CI") had labels and templates but no CI at all, and `ruff`/`mypy`
weren't even declared as dev dependencies. The exit test itself (a fresh session
producing a correct account unprompted) has not been formally run/recorded — this
Status line does not claim the phase is done, only that its named scope items now exist.

---

## Phase 1 — Substrate

**Goal:** the skeleton the intelligence layers plug into. `[P§20]`–`[P§23]`, `[P§32]`

**Scope:** ADR-0001 capability model (accept/revise) · ADR-0002 LLM gateway ·
ADR-0003 orchestration state + approval interrupts · ADR-0004 project memory & experiment
ledger. Implementation of each behind its acceptance test. Retro-fit ADRs to the existing
baseline `[P§32]` where it stands, or record its debt.

**Status:** ADR-0003 accepted; `cv_agent/graph/workflow.py` implements a real
LangGraph interrupt/resume graph (`langgraph.types.interrupt()` +
`Command(resume=...)`, not custom polling) for requirements-clarification and
approval-gated execution, built as a second graph alongside the existing
`build_graph()` stub (kept unchanged — see ADR-0003 §4). `CVAgent.start_workflow()`
/`.resume_workflow()`/`.get_workflow_state()`; CLI `workflow`. ADR-0004 accepted,
implemented, **and now wired into `CVAgent`**: `AgentConfig.workspace_root` +
`CVAgent.memory` (lazy `SqliteProjectMemoryStore`, local, gitignored, durable across
restarts) — `start_workflow()`/`resume_workflow()` write a `SessionRecord` per
session and an immutable `ProjectUnderstandingRevision` whenever requirements
analysis factually changes. `cv_agent/graph/workflow.py` itself remains untouched —
persistence wraps the graph invocation in `CVAgent`, not inside a node. **Since
2026-09-21 (issue #43, ADR-0003 §10, PR #46, merged as `a92ec2e`):** the approval
pause itself was hardened — `pending_execution` now carries an immutable
`execution_pin` (a canonical binding snapshot + runtime-registration generation)
captured once at plan time; `approval_gate` decides from that pin only, never a live
registry read; a recorded rejection is checked before any pin validation or executor
call, so a binding/runtime replaced during the pause can neither execute under a stale
approval nor override a rejection. `SkillExecutor`/`ExecutionBindingRegistry`
(ADR-0009) gained the comparison primitives this depends on (`ExecutionBinding.pin()`,
runtime-generation tracking) — cross-cutting into Phase 3's scope. 108 dedicated tests
(`tests/test_approval_integrity.py`). **Since 2026-09-23 (ADR-0002, D-033):** the LLM
gateway gained its first real adapter, `AnthropicProvider` (`cv_agent/llm/
anthropic_provider.py`), lazily registered in `cv_agent.llm.registry`; `FakeLLMProvider`
remains the default and every existing call site is unaffected. Single configured
model, no automatic fallback — task-complexity routing (`[P§20]`) remains future work
pending a second authorized provider. **Not done:** the cost-estimate + persisted
approval-record mechanism `docs/APPROVALS.md` specifies is still unimplemented
(`docs/state/OPEN_QUESTIONS.md` Q19) — low-impact today only because the one real
binding defaults to `"allowed"`, so no approval gate fires in practice yet; this is
unchanged by ADR-0002, which deliberately does not invent a cost/call-budget
mechanism for the same reason.

**Exit test:**
1. A capability with no satisfying skill resolves to "known but unavailable" and is
   reported as such, not as an error.
2. Two different LLM providers are swappable by configuration alone; `grep` finds no
   provider name outside the gateway. *(Met 2026-09-23, ADR-0002: `"mock"` and
   `"anthropic"` are both selectable via `LLMConfig.provider` alone; a structural
   test — `tests/test_llm_anthropic.py::TestArchitectureBoundary` — enforces that
   `anthropic` is imported nowhere outside `cv_agent/llm/anthropic_provider.py`.)*
3. A workflow run halts at an approval gate, the process is restarted, and the run
   resumes from the checkpoint with the approval still pending. *(Halts at an approval
   gate and resumes with the decision as the source of truth: met, in-process —
   `tests/test_workflow.py`. Survives an actual process restart: not yet — the default
   checkpointer, `MemorySaver`, is in-process only; see ADR-0003 §1/§8.)*
4. An experiment row can be written and read back with the full `[P§25]` schema enforced.
   *(Met 2026-09-24, ADR-0011/Q16: `cv_agent/experiments/`'s SQLite-backed
   `ExperimentLedger` — `tests/test_experiments.py`, 90 tests. Not yet wired into
   `CVAgent`/the CLI; no real training run has written a row.)*

---

## Phase 2 — Knowledge & research

**Goal:** the agent stops answering ecosystem questions from pretrained memory.
`[P§16]`–`[P§19]`

**Scope:** ADR-0005 tool/MCP boundary · ADR-0006 retrieval, provenance, freshness ·
research pipeline per `docs/RESEARCH_POLICY.md` · source-class weighting.

**Status:** partially started. **Since 2026-09-24:** ADR-0005 (tool/MCP boundary) is
**Accepted and implemented** — `cv_agent/tools/` (`docs/architecture/adr/ADR-0005-
tool-mcp-boundary.md`), the generic `ToolSpec`/`ToolInvoker`/`ToolRegistry`/
`ToolExecutor` boundary, fail-closed, invoker-registration-generation protected,
71 tests. Zero tools/invokers registered, no MCP SDK/vendor selected,
`OPEN_QUESTIONS.md` Q5's MCP-vs-skill half left explicitly unresolved — this is the
boundary only, not a real integration. **Also since 2026-09-24:** ADR-0006 (knowledge/
context boundary) is **Accepted and implemented** — `cv_agent/knowledge/`
(`docs/architecture/adr/ADR-0006-knowledge-context-boundary.md`): `Provenance`/
`KnowledgeItem` (fail-closed at construction — no item can exist without valid
provenance), `SourceClass`→`EvidenceWeight` per `docs/RESEARCH_POLICY.md`'s table,
`KnowledgeStore` protocol with an in-memory reference implementation, and
deterministic `assemble_context()`, 55 tests. This is the storage/provenance
contract only — no acquisition mechanism (web research/live fetching) exists yet, no
durable backend is chosen, no embeddings/ranking.

**Exit test:** asked "what should we use to detect small objects on a Jetson today", the
agent returns candidates each carrying source, source class, and date; it declines to
rank them without a benchmark; and every stored item lacking provenance is rejected by
the store. *(Provenance-rejection half: met 2026-09-24 — `KnowledgeItem` cannot be
constructed without valid `Provenance`, `tests/test_knowledge.py`. Live-query half: not
met — no acquisition mechanism populates the store with real candidates yet.)*

---

## Phase 3 — Skills & NVIDIA integration

**Goal:** external expertise invoked, not duplicated. `[P§15]`, `[P§23]`, `[P§29.9]`

**Scope:** ADR-0007 skill registry & discovery · NVIDIA skill adapters (DeepStream, TAO,
TensorRT, Model Optimizer, CUDA agent) as external-provenance skills.

**Status:** partially done. ADR-0007 accepted; `cv_agent/skills/` implements
discovery (`LocalSkillSource`) and deterministic (non-LLM) resolution (`TaskResolver`)
— the agent can enumerate what's discovered vs. merely declared, per the exit test's
second half. ADR-0009 accepted; `cv_agent/execution/` implements the execution
*boundary* (`SkillExecutor`, `ExecutionBinding`/`ExecutionBindingRegistry`,
`CVAgent.execute()`/`.can_execute()`, `python -m cv_agent executions`) and now has its
first real tenant: `trt-perf-analysis` is an individually-verified, CLI-executable
`ExecutionRuntime` binding (`python -m cv_agent execute trt-perf-analysis`) — but
inspection of the other 83 installed skills found every one is prose for an LLM agent
to read and act on with its own tools, not a program with a verifiable invocation
contract (see ADR-0009 §1). **Since 2026-09-21 (issues #47/#48, PRs #49/#50, merged as
`9f7ad6a`/`0e86979`):** the CLI's approval prompts (`workflow` and `execute`) now show
the runtime and description the pinned approval is compared against, not just the
skill/binding id (#47); `_cmd_execute`'s approval-required and unpinnable-binding
branches — previously unreachable, since the one real binding is `"allowed"` — are now
covered by 6 fixture-based, in-process tests via a monkeypatched registration and an
injectable `prompt` parameter, with no approval-required binding ever registered for
the real skill (#48). Both are CLI-surface/test-coverage work on top of the ADR-0003
§10 hardening above, not new capability. **Not done:** adapters for those other 83
skills, a second `SkillSource` (only local filesystem discovery exists).

**Exit test:** a quantization capability resolves to an external NVIDIA skill; the repo
contains **no** reimplementation of that skill's logic; and the agent can enumerate which
external capabilities are installed versus merely known. *(Enumeration half: met via
`python -m cv_agent resolve`. Adapter/invocation half: met for one skill —
`trt-perf-analysis`, real and CLI-executable; the other 83 remain unadapted.)*

---

## Phase 4 — DISCOVER / DEFINE workflow

**Goal:** the interaction in `[P§5]` and `[P§30]` actually works.

**Scope:** ADR-0008 reasoning nodes · the elicitation workflow · project understanding
written to memory · CV task decomposition.

**Status:** partially done. ADR-0008 accepted; `cv_agent/requirements/` implements
deterministic requirements analysis (known/unknown/assumed fields), CV task
decomposition into candidate components with rationale, matched-skill/executable-status
links (ADR-0008 §9), and clarification-question generation — callable via
`CVAgent.analyze_requirements()` / `python -m cv_agent analyze`. ADR-0003 gives the
clarification questions a real LangGraph interrupt node (`cv_agent/graph/workflow.py`)
that actually pauses and waits for the human's answer, then re-runs the analysis with
it — `CVAgent.start_workflow()`/`.resume_workflow()` / `python -m cv_agent workflow`.
ADR-0004 accepted; `start_workflow()` persists a `SessionRecord` and, when a run's
requirements analysis changes, a `ProjectUnderstandingRevision`, to durable, SQLite-
backed project memory. `python -m cv_agent workflow` now accepts real, caller-supplied
input for all three interrupt kinds (`clarify`/`provide_execution_inputs`/
`approval_gate`) via `--answer`/`--input`/`--approve`/`--reject` or a live stdin
prompt — never a fabricated placeholder. **Not done:** this command still never
registers an execution binding or accepts a `pending_execution` payload, so
`approval_gate`/`provide_execution_inputs` remain unreachable through it against any
real installed skill (a separate, not-yet-authorized decision); and this workflow
graph is separate from `run()`'s own graph, not merged into it (ADR-0003 §4/§8). A
real, pre-existing gap where declining every clarification question could re-raise
`clarify` indefinitely (`docs/state/OPEN_QUESTIONS.md` Q21) is now fixed (ADR-0003 §9).
Ambiguous executable candidates (more than one skill qualifies) no longer just end the
run with no plan: a fourth interrupt kind, `choose_candidate` (ADR-0010 §16, Q18),
presents them, validates the human's choice against the offered set, and resumes
planning — never silently picking one.

**Exit test:** given "I have a prison project — escape-attempt detection", the agent asks
targeted operational questions before naming any model, and produces a written
PROJECT UNDERSTANDING + CV TASK DECOMPOSITION persisted to project memory. If it names
YOLO before the questions, the phase fails. *(Questions + decomposition half: met via
`analyze_requirements()`, now with a real pause-for-answer via `start_workflow()`/
`resume_workflow()`. Persistence-to-memory half: met — `start_workflow()` writes to
`cv_agent/memory/`, now driven by real CLI-supplied answers, not only
programmatically.)*

---

## Phase 5 — Data & baseline

**Goal:** measurable ground truth. `[P§26]`, `[P§29.2]`

**Scope:** a dataset-subsystem ADR (`ADR-0009` had been reserved for it but went to
the skill execution-boundary work, per this repo's real numbering practice; it is
`ADR-0012`) · manifests, versions, splits, leakage checks · baseline establishment
workflow.

**Status:** partially started. **Phase 5a — Dataset Core — is implemented (2026-09-24,
ADR-0012, issue #59):** `cv_agent/datasets/` — immutable `DatasetManifest` (the dataset
version, `docs/DATA.md`'s manifest fields), recorded splits, deterministic temporal /
camera / subject / annotation-round / supplied-hash near-duplicate leakage checks
(a manifest cannot exist with a failed check; the report is recorded in it), a
storage-agnostic `DatasetStore` protocol and an in-memory reference implementation,
88 tests. **Not done:** any storage/versioning backend (`OPEN_QUESTIONS.md` Q10 is
still open — none was chosen), computing perceptual hashes (they are supplied), the
baseline establishment workflow (Phase 5b — needs Q4/Q2 and a real execution
mechanism), and any wiring into `CVAgent` or the experiment ledger. `docs/DATA.md`
remains the authoritative policy.

**Exit test:** a dataset version is created, a temporal- and camera-leakage check runs and
**fails** a deliberately leaky split, and a baseline run is recorded with accuracy,
latency, memory, and power on a named target.

---

## Phase 6 — Train / evaluate / diagnose

**Goal:** the experiment loop. `[P§10]`, `[P§12]`, `[P§24]`, `[P§27]`

**Scope:** a training-execution ADR (number TBD — `ADR-0010` is now
`docs/architecture/adr/ADR-0010-execution-planning-contract.md`, assigned when
that decision was actually written, per this repo's real numbering practice —
see its own header note) · ADR-0011 evaluation & failure analysis.

**Status:** not started. No training-execution or evaluation ADR has been written; no
`cv_agent` training/evaluation module exists; `docs/state/EXPERIMENTS.md`'s schema is a
hand-maintained convention with zero real rows recorded — no code reads or writes it.

**Exit test:** a training run requests approval with a cost estimate, runs after approval,
writes a complete ledger row, produces a composite result per `docs/EVALUATION.md`, and
returns a ranked failure-category analysis with a proposed next experiment.

---

## Phase 7 — Optimize / benchmark / deploy

**Goal:** hardware-aware delivery. `[P§13]`, `[P§14]`

**Scope:** ADR-0012 optimization & deployment · ONNX → TensorRT → FP16 → INT8 pipeline ·
profiling · DeepStream integration.

**Status:** not started. ADR-0012 has not been written. Note: `trt-perf-analysis`
(Phase 3's one real binding) *analyzes* already-produced TensorRT layer/profile JSON —
it does not export, quantize, or deploy anything, so it is not partial progress on this
phase's own scope.

**Exit test:** an optimization is applied, re-measured for accuracy **and** system
metrics, compared to baseline under identical conditions, and rejected automatically if
accuracy regressed beyond the stated tolerance.

---

## Phase 8 — Monitor & iterate

**Goal:** the system outlives deployment. `[P§28]`

**Scope:** ADR-0013 monitoring · drift detection against the validated baseline.

**Status:** not started. ADR-0013 has not been written; no monitoring/drift-detection
code exists. Blocked behind Phases 5–7 (nothing is deployed yet to monitor).

**Exit test:** a simulated production deviation (confidence-distribution shift, FPS drop,
camera degradation) is detected and reported against the validated baseline.

---

## Standing rule

If a phase's exit test cannot be written as something runnable, the phase is not
understood well enough to start.
