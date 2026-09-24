# JOURNAL

> **Append-only.** Never edit or delete a past entry — if an entry was wrong, write a new
> entry saying so. One entry per session. This is the project's memory of *how* it got
> here; `STATUS.md` holds only *where* it is.

Entry format:

```
## YYYY-MM-DD — <session title> (<branch or PR>)
**Did:**       what changed, concretely
**Why:**       the reason, citing [P§n] or ADR-XXXX
**Broke:**     what went wrong, including dead ends — record these, they are the
               most valuable lines in this file
**Learned:**   what a future session should know
**Left open:** what was deliberately not done
```

---

## 2026-08-30 — Governance scaffold (docs bootstrap)

**Did:** Froze the project definition as `docs/PROJECT.md` (§1–§35, verbatim). Created
`CLAUDE.md`, `AGENTS.md`, architecture overview with the responsibility table, ADR
template, seed ADR-0001 (capability model), roadmap, rolling state files, and the
approvals / research / evaluation / data contracts.

**Why:** `[P§35]` — the canonical document must be turned into operational repository
files without losing or contradicting any of it. The `[P§__]` citation convention exists
so drift from canon is greppable rather than a matter of opinion.

**Broke:** Nothing yet — no code touched.

**Learned:** The document's own §29 principles and §34 boundary test are strong enough to
serve directly as machine-enforceable rules; they were lifted into `CLAUDE.md` rather
than paraphrased.

**Left open:** Every ADR except the seed. GitHub scaffolding. Answers to Q1–Q5 in
`OPEN_QUESTIONS.md`.

---

## 2026-09-01 — Documentation + capability-state correction pass

**Did:** Full documentation consistency audit, then corrected everything it found.
(1) Retired `spec/00-vision.md`, `01-principles.md`, `02-architecture.md` (fully
duplicated `docs/PROJECT.md` or conflicted with ADR-governed `docs/architecture/
OVERVIEW.md`) and `07-human-approval-and-safety.md`, `09-artifact-and-experiment-
contracts.md` (conflicted with `docs/APPROVALS.md` / `docs/state/EXPERIMENTS.md`;
unique content merged in first). Reduced `spec/03-agent-runtime.md` and `spec/05-
cv-engineering-lifecycle.md` to technical elaborations that cite the canon instead of
restating it, with explicit "not implemented yet" headers.
(2) Rewrote `docs/development/GITHUB_FLOW_V1.md` and `GITHUB_DEVELOPMENT_MODEL.md`:
retired the two-trunk `main`/`dev-munna` model with its two-stage PM approval gate
(neither is how the project actually works); replaced with single trunk `main` +
`feature/<owner>/<work>` branches, PR reviewed and merged by the project owner.
Updated `CLAUDE.md` §6 and `AGENTS.md`'s Workflow section to match.
(3) Added `spec/` and `docs/development/` to README's document map and a pointer
(not a bulk-read requirement) in `CLAUDE.md` §2, since neither tree was discoverable
from any prescribed entry point before this.
(4) Capability registry semantics: found `spec/capability_registry.json` marked
every capability `status: "available"`/`"partial"` (20 entries, after a concurrent
session's additions) with zero executable skill/tool bindings anywhere in
`cv_agent/`, and `CapabilityRegistry.check_item()` hardcoded `available: True`
unconditionally. Introduced `status: "planned"` (declared, no executable binding),
tightened `"available"` to require a verified executable binding, set all 20
capabilities to `"planned"`, and made `check_item()` report `executable: False` with
a reason. `select()`/`Capability.is_available` now require `status == "available"`
strictly (previously counted `"partial"` too). Logged as an interim correction in
ADR-0001 §8a — does not implement the ADR's `Resolution`/`resolve()` design.

**Why:** `[P§35]`, `[P§23]`, ADR-0001 §3 ("known but unavailable" as a first-class
state) — a registry that claims a capability is usable when nothing can invoke it is
a false claim, not a documentation nitpick. The git-workflow and spec-duplication
fixes were explicit user corrections to what this repo's process and canon actually
are, not architectural choices of my own.

**Broke:** Found and fixed two unrelated concurrency-introduced bugs while verifying:
`cv_agent/capabilities/registry.py` and `cv_agent/config/settings.py` imported
`importlib.resources.abc.Traversable`, which doesn't exist before Python 3.12 (this
repo targets 3.10+) — added a fallback to `importlib.abc.Traversable`. Also found
`cv_agent/config/settings.py` referenced an undefined `_REPO_ROOT` name in dead code
(`_default_config_path`/`_default_registry_path`, unused elsewhere) — defined it.
Also found `cv_agent/resources/spec/capability_registry.json` (the packaged runtime
copy) had drifted from `spec/capability_registry.json` (the source of truth) — still
9 stale `"available"` entries after the source had grown to 20 `"planned"` ones, so
the actual running CLI was reporting the old, wrong data. Synced it and added
`tests/test_package_resources.py::test_packaged_registry_matches_source_of_truth`
so this can't silently drift again.

**Learned:** Multiple files in this repo (`spec/00-11`, `docs/development/*`,
`cv_agent/capabilities/registry.py`) were edited concurrently by another session
while this pass was running — several `Read`-then-`Edit` calls failed with
"file modified since read" and had to be re-read. Don't trust a file's content from
earlier in a long session without re-reading it immediately before editing,
especially anything under active multi-session development.

**Left open:** `docs/development/GITHUB_FLOW_V1.md` and `GITHUB_DEVELOPMENT_MODEL.md`
still duplicate each other substantially (by design — one is the procedural
reference, one the executive summary — but they should be watched for drift the same
way the capability registry copies were). Q1–Q5 in `OPEN_QUESTIONS.md` remain
unanswered and still block ADR-0003. No commit or push was made — see git status.

---

## 2026-09-08 — Step 2: skill discovery + deterministic resolution (ADR-0007)

**Did:** Added `cv_agent/skills/` — `models.py` (`Skill`, `SkillEvidence`, kept
independent from `RegistryItem`), `source.py` (`SkillSource` protocol), `local.py`
(`LocalSkillSource`, scans `<root>/<skill_id>/SKILL.md` under `~/.claude/skills` +
`~/.agents/skills` by default, hand-rolled flat-frontmatter parser — no new
dependency), `inventory.py` (`SkillInventory`, aggregates sources, dedups by
`skill_id`), `resolver.py` (`TaskResolver`, deterministic keyword-overlap scoring
against capability + skill metadata, no LLM). Wired into `CVAgent` as
`.skills`/`.resolve()`. Added CLI subcommands `skills`, `capabilities`, `resolve
"<task>"` (default no-arg health check unchanged). Wrote `ADR-0007`. Added
`tests/test_skills.py` (23 tests) and `TestCLISkillsCapabilitiesResolve` (7 tests) in
`tests/test_cli.py`, all against isolated `tmp_path`/`CV_AGENT_SKILL_PATHS` fixtures.
Replaced `test_step_two_command_name_is_rejected_until_implemented` — a tripwire
written by a prior session to assert `skills` must NOT exist — with real tests for
the command that now exists; kept everything else. Extended `AgentConfig` with
`skill_paths`. Updated `STATUS.md`, `DECISIONS.md` (D-010).

**Why:** `[P§23]`, `[P§15]` — the capability registry can declare that
`cv.deployment.optimization` is relevant to `deepstream`/`tensorrt`/etc., but that's
a claim about relevance, not about what's actually installed. This closes that gap
without collapsing DECLARED, DISCOVERED, and EXECUTABLE into one concept — the same
distinction D-009 spent a session establishing for capabilities now applies to
skills too, and the resolver enforces it structurally (a `SkillMatch` type has no way
to report `executable=True`; the field is hard-set `False` at construction).

**Broke:** Nothing existing — full suite went from 99 → 126 passing, no regressions.
Deliberately removed one test whose entire assertion was "this command must not
exist yet," since the task it was guarding against is exactly what was asked for this
session; flagged explicitly rather than silently deleted.

**Learned:** The real `~/.claude/skills/` installation on this machine is
inconsistent — some `SKILL.md` files have YAML-style frontmatter
(`name`/`description`/`owner`/`version`/...), some (e.g. `cuda-agent`) are plain
prose with none at all. A discovery parser for this format has to degrade to "no
metadata beyond the directory name" rather than raise. Also: `capability_registry.json`'s
declared skill ids (`tensorrt`, `deepstream`, `jetson`) mostly don't match the real
installed skill ids (`deepstream-dev`, `deepstream-generate-pipeline`, ...) — exact-id
matching alone would find almost nothing, so the resolver also does keyword/tag
overlap independent of declared relevance. `cuda-agent` is the one skill id that
matches exactly in both the registry and the real environment, which made it a good
end-to-end validation case.

**Left open:** No second `SkillSource` (repository-local, remote catalog, MCP) — only
`LocalSkillSource`. No LLM/semantic resolver — `TaskResolver`'s deterministic scoring
is a keyword-overlap floor, not a ceiling. No execution binding for any skill — every
discovered skill is still `executable: false`. `ruff`/`mypy` still not wired into
`pyproject.toml` dev-dependencies (pre-existing gap, unchanged this session). No
commit or push was made — see git status.

---

## 2026-09-15 — Step 4: requirements understanding + CV task decomposition (ADR-0008)
## (Step 3 was requested first, in a separate turn — it never landed; see below)

**Did:** A turn requesting "Step 3 — Skill Execution & Invocation Boundary" preceded
this one but produced no output — the harness shows it as a dropped turn with no
response, and inspection confirmed zero Step 3 artifacts exist (no `execution.py`, no
ADR-0008-as-execution, no `executions` CLI, no `agent.execute()`). Flagged this to the
user explicitly rather than either fabricating a Step 3 or silently building it
unrequested; proceeded straight to the requested Step 4, since none of its 15
requirements actually depend on execution existing.

Added `cv_agent/requirements/` — `models.py` (`RequirementField` with
`InfoStatus = known|unknown|assumed`, `TaskHypothesis`, `CapabilityLink`,
`ClarificationQuestion`, `RequirementsAnalysis`), `rules.py` (`FIELD_DETECTORS`,
`TASK_HYPOTHESIS_RULES` — flat appendable lists, not a decision tree, matching the
pattern `cv_agent.skills.resolver` already used), `analyzer.py`
(`RequirementsAnalyzer.analyze()` — deterministic keyword extraction, calls the
existing `TaskResolver` for capability links, optional `LLMProvider` used only for a
`narrative_summary` prose field). Wired into `CVAgent.analyze_requirements()`. Added
CLI `analyze "<request>"`. Wrote `ADR-0008`. Added `tests/test_requirements.py` (27
tests) and 3 CLI tests in `test_cli.py`. Updated `STATUS.md`, `DECISIONS.md` (D-011).

**Why:** `[P§5]` — the agent must characterize the operational problem before naming
a model; `docs/PROJECT.md` §30 describes the product as producing PROJECT
UNDERSTANDING before anything else. Nothing in the repo did that yet — `TaskResolver`
(Step 2) matches a task string to capabilities but doesn't ask what the task actually
*is* first.

**Broke:** Nothing — full suite went from 126 → 153 passing, no regressions.

**Learned:** "Assumed" needed a hard rule to stay honest: the analyzer itself must
never promote an unknown field to assumed (that would be exactly the silent
invention `[P§35]` forbids) — only the *caller* can supply an explicit assumption via
a parameter. Also: routing the LLM call through a single `narrative_summary` field,
structurally separate from every fact-bearing field on `RequirementsAnalysis`, made
"the LLM can't fabricate a requirement" a property a test could actually assert
(`test_llm_never_used_for_field_extraction` feeds the mock a prompt-injection-shaped
fixed response and confirms the structured fields are unaffected).

**Left open:** The dropped Step 3 (skill execution) — genuinely not built, next
action in `STATUS.md`. No LangGraph node consumes `RequirementsAnalysis` yet — it's a
plain return value from `CVAgent.analyze_requirements()`, not agent state. No real
LLM provider — narrative summaries only ever come from the mock. `ruff`/`mypy` still
not wired into `pyproject.toml` (pre-existing gap). No commit or push — see git
status.

---

## 2026-09-15 — Step 3, redone: skill execution & invocation boundary (ADR-0009)

**Did:** Before writing any code, inspected the actual installed skill environment
directly (`~/.claude/skills`, `~/.agents/skills`, 84 skill directories) rather than
assuming an invocation mechanism. Findings: every `SKILL.md` is prose meant for an
LLM coding agent to read and act on with its own tools — 28 of 84 declare Claude
Code's own `allowed-tools:` frontmatter (e.g. `Read Bash`), `cuda-agent` has no
frontmatter at all (pure persona prose), and even the two skills that bundle real
scripts (`trt-perf-analysis`, `gstreamer-pipeline`) expose no machine-readable
invocation contract — just prose describing which script to run how. The requested
example `jetson-diagnostic` does not exist under that name (closest:
`network-diagnostics`, `camera-network-diagnostics`) — noted rather than fabricated.

Given that, built `cv_agent/execution/` — `models.py` (`SkillExecutionRequest`,
`SkillExecutionResult`, `SkillExecutionStatus` with five states including
`rejected`/`not_executable`, `ExecutionEvidence`, `ExecutionError`, `RuntimeOutcome`,
`ApprovalPolicy`), `binding.py` (`ExecutionBinding`, a narrow `ExecutionRuntime`
protocol naming no concrete runtime, `ExecutionBindingRegistry` — deterministic,
dict-backed, sorted listing), `executor.py` (`SkillExecutor.execute()` — fails safely
to `not_executable`/`rejected` without ever calling a runtime when no verified
binding exists or approval wasn't granted; catches runtime exceptions as `failed`
rather than propagating them). Wired `CVAgent.execute()`/`.can_execute()`/
`.execution_bindings`. Added CLI `executions`. Wrote `ADR-0009`. Added
`tests/test_execution.py` (22 tests, all fake runtimes/bindings) plus 3 CLI tests.
**Deliberately registered zero bindings anywhere** — the boundary exists; no adapter
does, because none could be honestly verified this session.

**Why:** `[P§15]`, `[P§21]`, `[P§22]`, `[P§24]`, `[P§34]` — Phase 3's exit test has an
adapter/invocation half that ADR-0007 explicitly left open; this closes the
*boundary* without closing the adapter gap dishonestly. Treating "an LLM agent can
read this SKILL.md" as `executable=True` would have been exactly the silent
invention `[P§35]` and the DECLARED≠EXECUTABLE line (ADR-0001 §8a, ADR-0007, now this
ADR) exist to forbid.

**Broke:** Nothing — full suite went from 153 → 175 passing, no regressions.

**Learned:** "Instruction file for an agent to read" and "executable program" are a
real, load-bearing distinction in this specific ecosystem, not a hypothetical one —
Claude Code's own `allowed-tools:` frontmatter convention is direct evidence a skill
is designed to be *followed by an agent's own tool access*, not invoked as a
subprocess with a defined I/O contract. A correct execution boundary for this
environment has to model "no verified binding exists" as the honest default, not a
placeholder to be filled in casually.

**Left open:** No `ExecutionRuntime` implementation exists for any real skill — the
next natural step (not requested this session) would be verifying
`trt-perf-analysis`'s `scripts/run.sh` end-to-end and registering it as the first
real binding, one skill at a time, never in bulk. The approval workflow
`docs/APPROVALS.md` describes is still doc-only — `SkillExecutionRequest.approved` is
trusted, not derived from an actual gate. No commit or push — see git status.

---

## 2026-09-15 — Repository alignment review (read-only)

**Did:** Full read-only inspection of the repository against `docs/PROJECT.md`,
`ROADMAP.md`, and all state/ADR files, per an explicit request not to assume Research
Engine was automatically next. Confirmed working tree matched exactly what the prior
two sessions built (no drift), re-ran the full suite (175 passed), and traced every
consumer of `RequirementsAnalysis.clarification_questions` and
`SkillExecutionRequest.approved` — found neither has a live caller: `AgentState` (read
directly) has no field for either, and `analyze_requirements()`/`execute()` are plain
method calls, never reached through `run()`'s graph.

**Why:** the user explicitly asked for a dependency-based recommendation, not an
assumed one — `docs/PROJECT.md` §33's own design order (registry → gateway →
orchestration state → memory → tools → knowledge → skills → stages → execution) was
compared against the actual build order (registry → skills → requirements →
execution), which skipped orchestration state and memory entirely.

**Broke:** Nothing — read-only, no files modified.

**Learned:** "Documented as not-yet-implemented" and "correctly identified as the
next blocking dependency" are different findings — this repo's docs already said
orchestration state was missing; the review's contribution was tracing *why* that
specific gap, not Research/RAG or a first execution adapter, was the one actually
blocking further progress (two already-built subsystems dead-ending at it).

**Left open:** Everything unchanged; this was analysis only. Recommendation:
ADR-0003 next — acted on immediately after in the same session (see below).

---

## 2026-09-15 — ADR-0003: orchestration state + human-approval interrupts

**Did:** Inspected the installed LangGraph version (1.2.11) directly rather than
assuming an API — confirmed empirically (small probe scripts, not committed) that the
modern dynamic `interrupt()`/`Command(resume=...)` API works as documented: a node's
`interrupt(payload)` call pauses the graph, `invoke()` returns a dict with
`"__interrupt__"`, and resuming re-enters the same node with `interrupt()` now
returning the supplied value, with all prior state intact. Also confirmed storing a
raw (non-registered) dataclass instance in checkpointed state works today but prints
a deprecation warning ("will be blocked in a future version") — decided against it.

Built `cv_agent/graph/workflow.py`: a second compiled graph (kept separate from
`cv_agent.graph.builder.build_graph()` — see ADR-0003 §4 for why) implementing
`initialize -> analyze_requirements -> [clarify interrupt, loops back once] ->
approval_gate -> [execute if pending_execution present]`. Extended `AgentState` with
`requirements_analysis`/`clarification_answers`/`pending_execution`/
`approval_decision`/`execution_result`, all storing plain dicts
(`dataclasses.asdict()`) rather than dataclass instances, for the serializer reason
above and to keep orchestration state decoupled from reasoning-layer types (`[P§21]`).
Added `CVAgent.start_workflow()`/`.resume_workflow()`/`.get_workflow_state()` and CLI
`workflow`. Added a public `SkillExecutor.get_binding()` passthrough so the
approval-gate node can read a binding's `approval_policy` without reaching into a
private attribute. Wrote `ADR-0003`, resolving `OPEN_QUESTIONS.md` Q1/Q2 (don't block
this ADR) and partially resolving Q3 (transport identified; durable/restart-survivable
resume deferred to a checkpointer swap). Added `tests/test_workflow.py` (18 tests: 14
graph-level with fakes, 4 through the real `CVAgent`) plus 2 CLI tests. Added
`python -m cv_agent workflow "<task>"` as a single-process interrupt/resume demo
(documented as necessarily single-process — `MemorySaver` doesn't survive process
restart).

**Why:** `[P§5]`, `[P§10]`, `[P§21]`, `[P§24]`, `[P§34]` — `docs/PROJECT.md` §21
assigns LangGraph "human approval... checkpoints" specifically; the prior session's
alignment review found `RequirementsAnalysis.clarification_questions` (ADR-0008) and
`SkillExecutionRequest.approved` (ADR-0009) were both dead-ended data models with no
real pause-and-wait mechanism. This makes both real for the first time.

**Broke:** Nothing — full suite went from 175 → 195 passing, no regressions. Verified
specifically that `run()`/`health_check()`/`build_graph()`'s existing behavior is
byte-for-byte unchanged (dedicated regression test), since a second graph was built
rather than modifying the first.

**Learned:** `Command(resume=None)` is unsupported by this LangGraph version — it hits
an internal `UnboundLocalError` (a library bug, not this repo's), not a clean
rejection. An empty dict `{}` is both the correct semantic representation of "no
answers supplied" and avoids the bug — used that in the "no fabricated answers" test
instead. Also: `dataclasses.asdict()` on a dataclass containing tuples-of-dataclasses
preserves the outer tuple's type but converts the contents to dicts recursively (JSON-
and msgpack-safe either way) — confirmed empirically before relying on it.

**Left open:** The two graphs (`build_graph()` and the new workflow graph) remain
separate — ADR-0003 §8 names their eventual merge as a revisit trigger, not done here.
`MemorySaver` is still the only checkpointer — a restart-survivable approval transport
(Q3's harder half) is deferred until a persistent checkpointer is wired in. No project
memory (ADR-0004) — `requirements_analysis` still vanishes when a session's checkpoint
is discarded. No commit or push — see git status.

## 2026-09-15 — ADR-0004 project memory: Q1/Q15/Q8 resolved, then implemented (feature/claude/project-memory)

**Did:** Three prior turns resolved every question blocking ADR-0004 in sequence, each
recorded as its own owner decision: **Q1** (`OPEN_QUESTIONS.md`, D-015) — one CV
project per repository/workspace in V1, no `project_id` abstraction; **Q15** (new
question, raised by an ADR-0004 self-audit, D-016) — Project Understanding is
sensitive data per `docs/APPROVALS.md`, durable but never Git-tracked, gitignored by
default; **Q8** (D-017) — SQLite, local/project-scoped, kept strictly behind the
`ProjectMemoryStore` Protocol. A second self-audit after each resolution found the ADR
internally consistent and confirmed no remaining question blocked implementation.
Then implemented: `cv_agent/memory/` — `models.py` (`ProjectUnderstandingRevision`,
`SessionRecord`, both backend-neutral dataclasses), `store.py` (the
`ProjectMemoryStore` `Protocol`, `ProjectMemoryError`, `default_db_path()` — zero
`sqlite3` references), `sqlite_store.py` (`SqliteProjectMemoryStore` — the only module
in the codebase that imports `sqlite3`). Two tables (`understanding_revisions`,
append-only with an autoincrement `seq` for guaranteed insertion order;
`sessions`, upserted by `session_id`), idempotent `CREATE TABLE IF NOT EXISTS` schema
init, every write inside `with self._conn:` for atomicity, every failure re-raised as
`ProjectMemoryError` (never swallowed). 28 new tests (`tests/test_memory.py`) —
initialization, empty-store behavior, immutable revision history, insertion-order
(not alphabetical) ordering, duplicate-`revision_id` rejection, session upsert,
close/reopen persistence across two and three restart cycles, closed-connection error
behavior, and a structural test asserting `sqlite3` is imported nowhere in the
codebase except `sqlite_store.py`. Not wired into `CVAgent`, the workflow graph, or
the CLI — out of scope by explicit instruction (ADR-0004 §6/§9 already said so).
`.gitignore` gained `/.cv_agent/`.

**Why:** `docs/roadmap/ROADMAP.md` Phase 1 names ADR-0004 as this project's remaining
substrate gap; `[P§25]`/`[P§30]` require project understanding to persist beyond one
conversation. `[P§21]` keeps memory a distinct layer from orchestration (ADR-0003) and
reasoning (ADR-0008) — neither of those modules' own ADRs claimed "remember across
process restarts" as their job.

**Broke:** Nothing — full suite went from 195 → 223 passing (28 new, zero regressions).

**Learned:** Resolving `default_db_path()` from `Path(__file__).resolve().parents[N]`
(the pattern `cv_agent/config/settings.py` already uses for its own resource-path
fallback) would have been wrong here specifically — for an installed `cv-agent`,
`__file__` sits in site-packages, so every project using the same installed copy would
share one physical database, silently reintroducing the exact multi-project
conflation Q1 rejected. Resolved from `Path.cwd()` instead (with an explicit
`workspace_root` override for callers/tests), matching how the "workspace IS the
project" decision actually has to be enforced at the filesystem level, not just in
prose.

**Left open:** No caller of `cv_agent/memory/` exists yet — Project Understanding
still only lives in a single run's `AgentState`/return value until a future PR wires
`ProjectMemoryStore` into `CVAgent` (revision-trigger policy still undecided, per
ADR-0004 §9). `docs/state/EXPERIMENTS.md` and its own backend question
(`OPEN_QUESTIONS.md` Q16) are untouched. No persistent LangGraph checkpointer. No
commit or push — see git status; branch `feature/claude/project-memory`.

## 2026-09-15 — workspace-root contract clarified (D-019), then Project Memory wired into CVAgent (D-020) (feature/claude/project-memory)

**Did:** A dedicated audit of `default_db_path()`'s `Path.cwd()` fallback (requested
separately, before any new code) found no actual guarantee ties process execution to
a workspace directory anywhere in the codebase — no CLI flag, no `CVAgent`
parameter, and the installed `cv-agent` console script is invocable from any
directory. Resolved by the owner (D-019): the calling application resolves
`workspace_root` explicitly; `Path.cwd()` stays only as a convenience default for
direct/standalone use; automatic `.git`-discovery stays out of scope for V1.
ADR-0004 updated (§1 item 13, §2, §5, §8, §9) — documentation only, no code.

Then the actual integration (D-020): `AgentConfig.workspace_root` (new field, not
TOML-sourced); `cv_agent.memory.store.open_store()` (new factory — mirrors
`cv_agent.llm.registry.get_provider()`, so `CVAgent` never imports
`SqliteProjectMemoryStore` directly); `CVAgent.memory` (public, **lazily**
constructed — `health_check()`/`resolve()`/`analyze_requirements()`/`execute()`
never touch disk for it); a `SessionRecord` written before `start_workflow()`'s graph
call (status "running", preserving `started_at` across a restart) and updated after
every `start_workflow()`/`resume_workflow()` call via a new private
`CVAgent._sync_memory_after_run()`; a `ProjectUnderstandingRevision` appended when
the run's `requirements_analysis` factually differs from `get_current_understanding()`
(decided the revision-trigger policy ADR-0004 §9 deferred to this PR). `cv_agent/
graph/workflow.py` itself was **not** touched — no node calls memory; `CVAgent` wraps
the graph invocation instead, keeping ADR-0003's checkpoint/interrupt mechanics and
this ADR's durable store two separate concerns (ADR-0004 §2). The CLI's
`_cmd_workflow_demo` (the one command touching memory) now explicitly resolves
`workspace_root=Path.cwd()` at the application boundary, per D-019.

**Why:** `[P§25]`/`[P§30]` require project understanding to persist beyond one
conversation; ADR-0004's own §9 named this exact integration as the remaining step
once Q1/Q8/Q15 were resolved.

**Broke:** Nothing in the final result, but two pre-existing tests were silently
broken by omission before being caught: `tests/test_workflow.py`'s
`TestCVAgentWorkflowWiring` and `tests/test_cli.py`'s CLI-subprocess `_run()` helper
both constructed `CVAgent()`/ran the CLI with no explicit `workspace_root`/`cwd` —
once `start_workflow()` started writing to memory, that meant every test run was
silently creating a real `.cv_agent/memory.sqlite` inside *this repository's own*
working directory. Caught by manually checking for a stray `.cv_agent/` after a green
test run (the tests themselves didn't fail — nothing asserted the repo stayed clean).
Fixed by pinning both to their existing `tmp_path` fixture.

**Learned:** Two things surfaced only by writing integration tests, not by reading
ADR-0004: (1) `AgentState["requirements_analysis"]`'s container types are not
stable — a fresh, never-yet-checkpointed `.invoke()` still has the tuples
`dataclasses.asdict()` produced, but the same field, once it has been through a
LangGraph checkpoint save/restore (as it always has by the time `resume_workflow()`
sees it), comes back with those tuples turned into lists — a bare `==` against this
store's own JSON-round-tripped value reported "different" for byte-for-byte identical
data. Fixed by JSON-normalizing both sides before comparing. (2) Even the *mock* LLM
provider re-words `narrative_summary` on every call (a per-call response counter), so
comparing the full dict meant the dedup never fired at all, including for a plain
restart of the exact same task with no new information — a real LLM would do the same
in production, non-deterministically. Fixed by excluding `narrative_summary`/
`llm_provider` from the comparison, grounded in ADR-0008's own existing "prose, never
a source of fact" field classification — not a new heuristic invented here.

**Left open (unchanged from before, still correctly out of scope):**
`docs/state/EXPERIMENTS.md` and `OPEN_QUESTIONS.md` Q16 untouched; no persistent
LangGraph checkpointer; no RAG/MCP/real LLM provider. **New, acknowledged
limitation:** the session-record write and the revision write inside one sync call
are two independent atomic SQLite transactions, not one — `ProjectMemoryStore` has no
cross-write transaction primitive, so a failure between the two writes is a narrow
gap, not silently hidden. 24 new tests (247 total), zero regressions. No commit, no
push — branch `feature/claude/project-memory`, still unmerged.

## 2026-09-16 — First real execution binding: trt-perf-analysis (feature/claude/execution-binding)

**Did:** Made exactly one real installed skill genuinely executable through the
existing execution boundary (ADR-0009 §8's revisit trigger). Inspected the real
installed skill environment directly (not assumed from ADR-0009's own prior mention)
and chose `trt-perf-analysis`: its `scripts/analyze_trt_perf.py` uses only Python
stdlib, exposes a stable `argparse` CLI, and is read-only/local/deterministic.
Verified its exit-code/stdout contract empirically against the real script before
writing any adapter code: exit `0` + one JSON object on stdout whenever structured
data can be produced at all (including when one backend's own input fails
validation — the script treats that as a valid outcome, not a crash); exit `2` + a
one-line stderr message when no input files exist. Added
`cv_agent/execution/runtimes/trt_perf_analysis.py` (`TrtPerfAnalysisRuntime`
implementing `ExecutionRuntime`, `build_binding()`, an explicit opt-in
`register(registry)`) and `tests/test_execution_trt_perf_analysis.py` (27 tests:
argv-contract units, mocked subprocess error-mapping, registry/approval-gate wiring,
and — skipped, not faked, if the skill isn't installed — genuine subprocess
invocation through `CVAgent.execute()`). Ran a standalone end-to-end script
(discovery → explicit `register()` → `CVAgent.execute()` → real subprocess → real
JSON result) to confirm the path works outside the test harness too. Updated
ADR-0009 (§3/§6/§7/§8, new §9) to record the decision without rewriting the
architecture; added D-014.

**Why:** The prior architecture audit (this session, read-only, against the real
merged `main` — not the unmerged memory branch) found the V1 chain stops exactly
here: requirements analysis, skill resolution, and the HITL approval gate are all
genuinely wired end-to-end, but every one of 84 discovered skills and 20 declared
capabilities reported `not_executable` — the agent could reason and ask but never
act. `[P§15]`/`[P§29.9]` ("discover and invoke, don't duplicate") and `CLAUDE.md`'s
own opening line ("performs... not merely knows") both point at this gap as the
actual highest-value next step, ahead of roadmap ordering.

**Broke:** Nothing — full suite went from 195 → 222 passing (27 new), zero
regressions; `tests/test_execution.py`'s existing FakeRuntime-based tests are
byte-for-byte unchanged. One test of my own was initially wrong, not the adapter:
I assumed a malformed `layers_*.json` would hit the script's process-level `DataError`
path (exit `2`); empirically it doesn't — a malformed *individual* backend is
reported as `"status": "failed"` inside an otherwise-successful (exit `0`) response,
which is the script's own documented contract ("exit 0 whenever structured data can
be emitted at all"). Fixed the test to assert the real, verified behavior instead of
the assumed one. Also discovered, after the real-invocation tests ran, that CPython
had written `.pyc` bytecode cache files into the real skill's own
`scripts/trt_perf/__pycache__/` (a standard, automatic side effect of importing that
package as a subprocess, not something this code does deliberately) — removed them
afterward to restore the exact pre-test state; no `.py` source file was ever touched.

**Learned:** `Skill.location` (the real, discovered `SKILL.md` path) is sufficient to
derive a skill's installation root (`Path(skill.location).parent`) for an adapter —
no hard-coded filesystem path is needed, so the same adapter works regardless of
whether a skill was found under `~/.claude/skills`, `~/.agents/skills`, or a
`CV_AGENT_SKILL_PATHS` override. Invoking the real script directly via
`sys.executable`/`SKILL_PYTHON` is equivalent to (and simpler/more portable than)
shelling through the skill's own `scripts/run.sh`/`run.cmd` Python-discovery
wrappers, since this process already knows its own interpreter. Timeout/error-path
tests are more robust mocking `subprocess.run` directly than racing real wall-clock
timing, and the task's own instructions explicitly allow this for
"expensive or environment-dependent portions."

**Left open:** 83/84 skills remain non-executable — this ADR-0009 §8 trigger fires
per skill, not in bulk, by design; `gstreamer-pipeline` (the other bundled-script
candidate ADR-0009 §1 named) is the next candidate, uninspected so far. Registration
stays fully opt-in — `CVAgent.__init__` does not call `register()`, so
`python -m cv_agent executions` against a fresh `CVAgent` still reports `0/84`;
wiring any binding into `CVAgent`'s default construction (conditional on real
discovery or otherwise) was deliberately not done, out of scope for this task. Two
independent branches (`feature/claude/project-memory`/PR #27, and this one) both
used `docs/state/DECISIONS.md` D-014 — will need renumbering when whichever merges
second lands (noted in `STATUS.md`). No commit, no push — see git status.

## 2026-09-16 — PR #27 rebased onto merged PR #28; D-014 collision resolved (feature/claude/project-memory)

**Did:** PR #28 (execution-binding) merged into `main` first (`f8e7049`), landing its
own `D-014` (trt-perf-analysis) — the exact collision the prior entry flagged.
Reconciled `feature/claude/project-memory` (PR #27) against the new `main`: applied a
pending PR-review fix (`_try_mark_session_error()` in `cv_agent/runtime/agent.py` —
when the graph invocation raises AND the subsequent session-error write itself also
fails, the original graph exception must still be what propagates, with the memory
failure attached as `__cause__`, never silently swallowed or silently swallowing the
graph failure; covered by a new real-connection-closing test in
`tests/test_memory_integration.py`, not mocked), renumbered only this branch's own
decision chain `D-014..D-019` → `D-015..D-020` (order, dates, and full semantic
content preserved; main's `D-014` untouched), then merged `origin/main` in. Merge
conflicts were confined to exactly the three rolling-state files both branches
independently touched — `DECISIONS.md`, `JOURNAL.md`, `STATUS.md` — resolved by
concatenation (main's `D-014` row first, chronologically, then this branch's
`D-015`-`D-020`; both `JOURNAL.md` entries kept, dated order; `STATUS.md` rewritten to
describe both shipped pieces at once). `cv_agent/execution/runtimes/`,
`ADR-0009-skill-execution-boundary.md`, and `tests/test_execution_trt_perf_analysis.py`
merged in with **zero conflicts** — confirming the two branches' changes were
genuinely disjoint, not just independently numbered.

**Why:** PR #27 needed to be mergeable against the post-PR-28 `main` without silently
losing either branch's decision history, and without the two `D-014`s (unrelated
decisions: execution binding vs. Q1 project-scope resolution) colliding into one row.

**Broke:** Nothing — full suite 251 → 278 passing after the merge (222 execution-
binding tests' worth of coverage plus this branch's 251, overlap deduplicated by the
merge itself), zero regressions. Confirmed `cv_agent/execution/binding.py`,
`executor.py`, `models.py`, `cv_agent/skills/`, `cv_agent/graph/workflow.py`, and the
`trt-perf-analysis` runtime are untouched by this branch's own changes — the merge
only combined them, it did not modify either side's implementation.

**Learned:** Two independently-branched features that each append to the same
"next free ID" ledger will always collide exactly this way — sequential IDs assigned
per-branch, not per-merge, are optimistic-locking without the lock. Nothing about this
ADR/decision-ledger design needs to change for V1 (both branches document *why* IDs
moved, which is the actual property the ledger exists to preserve), but the next
branch to add a `DECISIONS.md` row should check `origin/main`'s latest ID first, not
just its own branch point's.

**Left open:** Same as both prior entries — 83/84 skills still non-executable
(execution-binding side); `docs/state/EXPERIMENTS.md`/`OPEN_QUESTIONS.md` Q16, no
persistent LangGraph checkpointer, no RAG/MCP/real LLM provider (project-memory side).
No new scope introduced by this reconciliation itself. Commit made on
`feature/claude/project-memory`; branch pushed; PR #27 not merged — see git status.

## 2026-09-16 — Closed the requirements -> resolution -> execution feedback loop (feature/claude/execution-feedback-loop)

**Did:** A read-only architecture audit against merged `main` (`2cf3709`) found the
actual bottleneck was not another execution binding, RAG, research, a real LLM
provider, or persistent checkpointing — it was that the one real binding
(`trt-perf-analysis`, D-014) was invocable only from Python/tests, and
`Skill.executable`/`SkillMatch.executable` were hardcoded `False` everywhere,
completely disconnected from the real `ExecutionBindingRegistry`, so a real user had
no way to discover or invoke it through the product surface. Fixed both halves.
**(1)** `cv_agent/skills/inventory.py::SkillInventory` gained an optional
`is_executable: Callable[[str], bool] | None` predicate applied in `list()`/`get()`
via `dataclasses.replace()`; `cv_agent/skills/resolver.py::TaskResolver` now copies
`skill.executable` instead of independently hardcoding `False`; `CVAgent.__init__`
reordered to construct `ExecutionBindingRegistry`/`SkillExecutor` first and wires
`self._executor.can_execute` into `SkillInventory`. `cv_agent.skills` still imports
nothing from `cv_agent.execution` — the predicate is a plain callback, matching
`can_execute`'s own shape. **(2)** New `python -m cv_agent execute <skill_id>` CLI
command: identifies the skill, verifies `can_execute()`, builds
`SkillExecutionRequest` from `--path`/`--input KEY=VALUE`/`--model-name`, resolves
approval via `_confirm_approval()` (never auto-approves — `--approve` or a live
"y"/"yes" prompt answer required for `approval_required`), and calls
`CVAgent.execute()` — the real `SkillExecutor` path, never bypassed or duplicated.
Only `trt-perf-analysis` is accepted (one constant check, explicitly not a dispatch
table); this command is itself the one explicit, controlled caller that registers
that binding, into its own short-lived `CVAgent` instance. `skills`/`resolve`/
`capabilities`/`executions` are byte-for-byte behaviorally unchanged — still
construct a fresh, unregistered `CVAgent`, still report `executable=False`/`0/84` by
default.

**Why:** The audit's own explicit finding (see this session's read-only report): every
other candidate either had zero current consumer (RAG/research/experiment ledger) or
would harden a path nobody could reach yet (persistent checkpointing hardens an
approval interrupt the CLI never populated). This gap compounds — every future
`ExecutionRuntime` adapter would land in the same dead end `trt-perf-analysis` was in
without this fix first.

**Broke:** Nothing — full suite 278 → 305 passing (10 resolution-wiring tests in
`tests/test_skills.py`/`tests/test_agent.py`, 17 in new `tests/test_cli_execute.py`),
zero regressions. Two pre-existing tests
(`test_every_discovered_skill_is_not_executable`,
`test_resolve_matches_a_discovered_skill`) were inspected, not rewritten — both
remain correct as written since neither wires an `is_executable` predicate in, so
both still exercise the unchanged default path (see ADR-0007 §9's explicit note on
this).

**Learned:** `TaskResolver` already reads every `Skill` exclusively through
`SkillInventory` — making `SkillInventory` (not `TaskResolver`) the one
execution-aware injection point meant a single predicate fixes both the `skills` CLI
command and `resolve()`'s `SkillMatch.executable` at once, rather than needing the
predicate threaded through two places. Manually verified end-to-end against the real
installed skill and a hand-built deterministic fixture (`execute trt-perf-analysis
--path <folder-with-3-layer-fixture>`) before writing the automated smoke test — real
exit 0, real structured JSON on stdout, real `Status: completed`.

**Left open:** 83/84 skills still non-executable (this task explicitly excluded a
second binding); no cost-estimation code (`--approve` is a user-typed flag, not a
cost gate — out of scope, unchanged); RAG/research/real LLM providers/persistent
checkpointing/experiment ledger all explicitly out of scope for this task, per the
audit's own recommendation not to start any of them yet. Also fixed, in passing per
this task's explicit instruction: `docs/state/STATUS.md`'s stale "PR #27 still open"
statement (merged as `2cf3709`, now corrected). Not committed or pushed — branch
`feature/claude/execution-feedback-loop`, working tree only — see git status.

## 2026-09-16 — Surfaced matched skill + executable status from RequirementsAnalysis (feature/claude/requirements-skill-links)

**Did:** A follow-up architecture audit of merged `main` @ `7c284d2` found the single
next highest-priority gap: `RequirementsAnalyzer._link_capabilities()` already called
`TaskResolver.resolve()` once per task component and read `result.matched_capabilities`
to build `capability_links`, but discarded `result.matched_skills` — including the
truthful `executable` flag the previous session (D-021) had just wired up — on the same
line. A user running `analyze` had no way to learn which matched capability actually had
an executable skill behind it right now; they'd have to separately run `resolve` and
manually cross-reference. Fixed by adding `RequirementsAnalysis.skill_links: tuple[
SkillLink, ...]` (`task_component`, `skill_id`, `declared`, `matched_terms`,
`executable`) — a new top-level field, deliberately not nested inside `CapabilityLink`,
since one `resolve()` call's `SkillMatch`es aren't attributed to a single capability
(keyword-matched skills have no capability at all; a declared skill can belong to
several matched capabilities at once). `_link_capabilities()` now returns both tuples
from the one `resolve()` call already in scope — no second resolution pass, verified by
an explicit call-count test. `python -m cv_agent analyze` gained a "Matched skills"
section formatted like `resolve`'s own output.

**Why:** Same reasoning as D-021's audit, one layer up: every other candidate subsystem
either has no current consumer or hardens a path nobody can reach yet, while this gap
sat directly on the one path `docs/PROJECT.md` §5/§30 describes as the product — a
request should turn into engineering action, and the information needed to connect
"matched capability" to "executable skill" was already computed and thrown away one
line later.

**Broke:** Nothing — full suite 305 → 320 passing, zero regressions. One pre-existing
assertion (`TestDeterminism::test_same_input_same_output`) was extended, not rewritten,
to also cover `skill_links`.

**Learned:** A duck-typed fake `TaskResolver` (mirroring this repo's existing
`FakeRuntime`/`FakeLLMProvider` pattern) gave precise, deterministic control over
multiplicity/scoping test scenarios without fighting real keyword-overlap matching
internals — real resolver + real registry + fixture skills was reserved for the
executable-status and real-`trt-perf-analysis` tests, where the real wiring itself is
what's under test.

**Left open:** `RequirementsAnalyzer` still does not rank or select a skill — that
remains explicitly out of scope, per this task's own instruction and ADR-0008 §2's
unchanged boundary. Also fixed, per this task's explicit instruction:
`docs/roadmap/ROADMAP.md` Phase 3/Phase 4's stale "zero bindings registered"/"no memory
subsystem exists" status statements, both predating D-020/D-021. Not committed or
pushed — branch `feature/claude/requirements-skill-links`, working tree only — see git
status.

## 2026-09-17 — Explicit execution-input channel (feature/claude/execution-input-channel)
**Did:**       Added `AgentState.execution_inputs: dict[str, Any]` (new field, keyed
               by `InputField.name`, ADR-0009 §11) and
               `CVAgent.start_workflow(execution_inputs=...)`; the `plan_execution`
               node now reads `state.get("execution_inputs") or {}` as
               `plan_execution()`'s `available_inputs` instead of the hardcoded `{}`
               ADR-0010 §10 shipped with. `cv_agent.graph.planning` itself is
               unchanged. ADR-0010 gained §12; `docs/state/OPEN_QUESTIONS.md` Q17
               reworded (not struck through) to describe the narrower remaining gap.
**Why:**       A read-only design review (this session, prior turn) found the exact
               gap ADR-0010 §10 had already named honestly: no channel existed for a
               caller who already knows a required execution input's value before a
               run starts. Closing it unblocks any future binding whose
               `input_schema` declares a required field — today only
               `trt-perf-analysis`, which ships `input_schema=()`, so this was
               previously untestable end-to-end without a synthetic fixture.
**Broke:**     Nothing — full suite 362 passing (357 before this branch + 5 new: 3 in
               `tests/test_workflow.py::TestPlanExecutionIntegration`/
               `TestManuallySuppliedPendingExecutionPrecedence`, 2 in new
               `tests/test_memory_integration.py::TestExecutionInputsChannel`). Zero
               regressions; every pre-existing test's `_start()`/initial-state
               fixture was extended (one new dict key, default `{}`), not rewritten.
**Learned:**   Constructing a task string that both (a) triggers a real clarification
               interrupt and (b) still matches the same fixture skill after resume
               needed deliberate care — `_VAGUE_TASK` alone lacks the benchmarking
               vocabulary `_PLANNING_TASK`'s fixture skill matches on, so a new
               `_VAGUE_PLANNING_TASK` (vague on most fields, but keeps the
               person-detection trigger + benchmarking vocabulary) was needed to
               actually exercise "execution_inputs survives the clarify loop and
               still reaches a real plan," not just "survives and reaches
               no_executable_candidate."
**Left open:** Per this task's explicit scope decision: no CLI flag (API parameter
               only), no same-session retry/interrupt after
               `missing_required_inputs` (Q17, narrowed but still open), no
               cross-binding field-name collision guard (named as a documented
               future consideration for when a second individually-verified binding
               exists). Committed to branch `feature/claude/execution-input-channel`,
               not `main`.

## 2026-09-17 — Same-session `missing_required_inputs` recovery (Q17, ADR-0010 §13)

**Did:**       Closed Q17's remaining sub-case (ADR-0010 §12 had already closed the
               "known in advance" half): a new `provide_execution_inputs` interrupt
               node, architecturally consistent with `clarify` (ADR-0003), inserted
               between `plan_execution` and `approval_gate` in
               `cv_agent/graph/workflow.py`. `plan_execution -> approval_gate`
               became a conditional edge (`_route_after_planning`); a new plain edge
               `provide_execution_inputs -> plan_execution` closes the recovery
               loop, bounded to exactly one round via
               `AgentState.execution_input_recovery["attempted"]`. `PlanningResult`
               (`cv_agent/graph/planning.py`) gained `selected_skill_id`/
               `selected_binding_id`/`selected_input_schema`, populated for both
               `"planned"` and `"missing_required_inputs"` — the checkpointed
               identity+contract snapshot a retry compares against before ever
               producing a plan. Any incomplete/invalid/cancelled/
               `binding_mismatch` outcome routes straight to `END`, bypassing
               `approval_gate` entirely, so a failed recovery can never read as
               "approval not required" for a plan that was never produced.
**Why:**       `docs/state/OPEN_QUESTIONS.md` Q17's remaining half, resolved via a
               multi-round design review (4 rounds) that progressively tightened the
               design: distinguishing valid/incomplete/invalid/cancelled input
               (not just "did we ask once"), guaranteeing binding identity is
               checked explicitly rather than relying on implicit reselection,
               closing a schema-mutation gap (same `binding_id`, changed contract —
               ID equality alone is not sufficient), and making the terminal
               outcome caller-visible without a new lifecycle `status` value.
**Broke:**     Two real bugs found only by running the tests, not anticipated in
               design: (1) `status` never reached `"done"` on the new
               bypass-to-`END` path, since that was previously `approval_gate`'s
               job and `approval_gate` is now skipped for this case — fixed by
               having `_node_plan_execution` set it directly when finalizing a
               terminal recovery outcome. (2) `Command(resume={})` — a literal
               empty dict — is **not reliably delivered** by the installed
               LangGraph; the graph silently re-pauses at the same interrupt
               instead of resuming (confirmed empirically, not assumed). This
               contradicts this file's own pre-existing `clarify`-interrupt test
               comment claiming "an empty mapping is the correct way to represent
               'no answers supplied'" — that claim does not hold; `clarify`'s own
               existing test for it only passes because it never asserts
               `"__interrupt__" not in resumed`. Not fixed for `clarify` (out of
               this task's scope) — documented instead, in `CVAgent.
               resume_workflow()`'s docstring and this new interrupt's own test,
               that a non-`dict` falsy value (e.g. `""`), not `{}`, is the
               correctly-deliverable way to signal "declined."
**Learned:**   `trt_perf_analysis.build_binding()`'s real input contract is a
               genuine `path`/`data` XOR (verified by reading `_build_argv()`
               directly, not assumed) — `InputField.required: bool`'s flat model
               cannot express it truthfully. Populating `input_schema` for this
               binding was explicitly *not* done here; every test uses a synthetic
               fixture binding instead (same convention
               `tests/test_execution_planning_contract.py`'s pre-existing tests
               already use). Spun off as new, separate `OPEN_QUESTIONS.md` Q20.
**Left open:** Q20 (TRT XOR/oneOf schema support — blocks only a *real*,
               unfaked end-to-end test of this feature, not the mechanism itself).
               No CLI flag for resuming a `provide_execution_inputs` interrupt (the
               existing generic `resume_workflow()` already suffices — no dedicated
               wrapper added, matching `clarify`/`approval_gate`'s own precedent).
               Pre-existing `ruff`/`mypy` findings elsewhere in the touched files
               (`pending_prompt` unused in `_node_clarify`, unused `langgraph`
               import in `health_check()`, unused `PlanningResult` import in
               `test_execution_planning_contract.py`) confirmed pre-dating this
               branch via `git diff main` — not fixed, out of scope. Full suite 362
               → 379 passing, zero regressions. Branch
               `feature/claude/q17-input-recovery`, not `main`.

## 2026-09-18 — Real CLI input handling for `workflow` (issue #34, PR pending)
**Did:**       Replaced `python -m cv_agent workflow`'s auto-fabricated
               placeholder clarification answers with real, caller-supplied
               input across all three interrupt kinds (`clarify`,
               `provide_execution_inputs` since ADR-0010 §13,
               `approval_gate`) — `--answer`/`--input` KEY=VALUE flags
               (repeatable, `--input` reusing `execute`'s existing
               convention), `--approve`/`--reject` (mutually exclusive), and
               a live stdin prompt for anything a flag doesn't cover, never a
               fabricated value. New `_resume_value_for_interrupt` (pure
               dispatch on the interrupt's own `payload["type"]`),
               `_run_workflow_interactive` (drives the resume loop, duck-
               typed to `CVAgent.start_workflow()`/`.resume_workflow()`),
               `_print_workflow_summary`, all in `cv_agent/__main__.py`.
               Also fixed a stale/self-contradictory `docs/state/STATUS.md`
               (PR #33 shown as unmerged/pending when `main` was already at
               `93549de`; two of its own "next actions" directly
               contradicted its "do not start yet" list) — kept in its own
               PR (#35) per explicit instruction, not mixed into this one.
**Why:**       `docs/roadmap/ROADMAP.md` Phase 4 already named this
               explicitly as the remaining gap: the CLI only ever
               demonstrated interrupt/resume mechanics with synthetic
               answers. Since PR #33, a third interrupt kind existed at the
               graph level but was completely unreachable through any CLI
               path. Pure CLI-layer glue over the already-accepted
               `CVAgent` API (ADR-0003/ADR-0010 §10–§13) — no ADR needed, no
               new module/interface/state shape `[P§34]`.
**Broke:**     Found a genuine, pre-existing, unrelated bug while testing
               the real (non-synthetic) path for the first time:
               `cv_agent/graph/workflow.py`'s `_route_after_analysis`
               decides whether to re-raise `clarify` using
               `bool(state.get("clarification_answers"))` — truthiness, not
               "already attempted." A human who declines every
               clarification question resumes with an empty answers value,
               stays falsy, and the graph re-raises the same `clarify`
               interrupt **indefinitely** — reproduced directly (not a
               hypothetical): a bare `python -m cv_agent workflow "<vague
               task>"` with no `--answer` and closed stdin looped without
               bound until manually killed. The prior CLI never surfaced
               this because it always fabricated a non-empty placeholder
               answer for every question, so `clarification_answers` was
               never actually empty. Did **not** fix `_route_after_analysis`
               itself — out of this issue's approved scope (CLI input
               handling, not graph routing); instead added a CLI-only
               `_MAX_INTERRUPT_ROUNDS` safety cap (`WorkflowStuckError`,
               exit code 3, clear message) so the command aborts cleanly
               instead of hanging. Filed as new `OPEN_QUESTIONS.md` Q21 for
               the project owner to decide the real fix. Separately
               confirmed (via `git stash` diff against `main`) that all
               pre-existing `ruff`/`mypy` findings elsewhere in the repo
               predate this branch; this branch's own two touched files are
               fully clean, and actually fixed 2 of the old `__main__.py`
               mypy errors as a side effect of properly typing the new code.
**Learned:**   `_cmd_workflow` deliberately never registers any execution
               binding (same honesty default as `analyze`/`resolve`/
               `skills`), so `approval_gate`/`provide_execution_inputs` are
               real and generic but **structurally unreachable** through
               this CLI against any of the 84 real installed skills today —
               independent of Q20 (even a hypothetically-wired binding
               couldn't demonstrate them, since the only real one,
               `trt-perf-analysis`, has no required inputs and an "allowed",
               never-gated, policy). Verified both interrupt kinds for real
               instead via (a) a fixture-graph-backed test double
               (`_GraphAgent`, same construction `tests/test_workflow.py`
               already uses) driving `_run_workflow_interactive` end-to-end
               through a full clarify → provide_execution_inputs →
               approval_gate → execute run in one call, and (b) one manual,
               interactive-simulated run against a real `CVAgent` with a
               synthetic binding registered directly on `agent.
               execution_bindings` (mirroring `_cmd_execute`'s own real
               registration pattern) — both honestly labeled as synthetic,
               matching this codebase's existing Q20 posture.
**Left open:** Q21 (the `_route_after_analysis` truthiness/infinite-loop
               gap — real fix undecided). Q18/Q20 unchanged, not touched.
               Wiring `pending_execution`/a binding choice into `workflow`
               itself remains a separate, not-yet-authorized decision.
               21 new/updated tests (2 rewritten + 1 new in `tests/
               test_cli.py`, 21 new in new `tests/test_cli_workflow.py`).
               Full suite 381 → 403 passing (381 was PR #33's merged
               baseline, including its 2 post-review verification tests;
               22 net new here), zero regressions. `ruff`/`mypy` clean on
               both touched/new files.
               Branch `feature/claude/workflow-cli-io`, not `main`. Issue
               #34, PR pending; `docs/state/STATUS.md` correction is
               separately PR #35, also pending — the two PRs' STATUS.md
               diffs will need a rebase against whichever merges first.

---

## 2026-09-19 — Q21 fix: clarify attempted-flag, not answers-truthiness (fix/claude/q21-clarify-attempted-flag)

**Did:**       Fixed the pre-existing infinite-loop bug documented as Q21
               (found while building #34, filed 2026-09-18). Added
               `AgentState["clarification_attempted"]: bool`
               (`cv_agent/graph/state.py`), set unconditionally by
               `_node_clarify` on every resume — mirrors
               `execution_input_recovery["attempted"]`'s existing pattern
               (ADR-0010 §13) rather than inventing a new one.
               `_route_after_analysis` (`cv_agent/graph/workflow.py`) now
               routes on this flag, never on `clarification_answers`'
               truthiness. `CVAgent.start_workflow()` initializes it to
               `False`. CLI (`_resume_value_for_interrupt`'s
               `"clarification"` branch, `cv_agent/__main__.py`) resumes
               with `""`, never `{}`, when every question is declined —
               the same convention already used for
               `provide_execution_inputs`. Corrected ADR-0003 §3's own
               wrong claim about the loop bound and appended a new §9
               documenting the fix (mirrors ADR-0010's own pattern of
               appended `## N. Status —` sections instead of a new ADR
               file). `_MAX_INTERRUPT_ROUNDS` kept as defense-in-depth;
               its docstring updated to say so, not describe an active bug.
**Why:**       ADR-0003 §9 (Q21) — a human declining every clarification
               question must reach a normal completion, not hang the
               graph indefinitely. `[P§21]`, `[P§34]`.
**Broke:**     Nothing new — this *is* the bug fix. Two pre-existing tests
               encoded the buggy behavior as expected and had to be
               rewritten: `tests/test_cli.py`'s workflow-declines-everything
               test previously asserted exit 3/`WorkflowStuckError` (now
               asserts exit 0/clean completion); `tests/test_cli_workflow.py`'s
               all-blank-clarification test previously asserted `{}` (now
               asserts `""`, matching the corrected CLI contract).
**Learned:**   Empirically confirmed *two* independent bugs behind the one
               symptom, not one: (1) `_route_after_analysis`'s routing
               logic (the one Q21 named), and (2) `Command(resume={})`
               never reaching `_node_clarify`'s body at all — confirmed via
               direct graph invocation, 5/5 trials, not "unreliable," just
               never delivered. `Command(resume="")` *does* reach the node
               but, without fix (1), still loops via fix (1)'s bug — so
               neither fix alone is sufficient; both were needed together.
               Also found `tests/test_workflow.py::
               test_empty_resume_value_produces_no_fabricated_answers`
               resumed with `{}` and only asserted the answers dict's
               value, never `"__interrupt__" not in resumed` — this passed
               even under total non-delivery, because that's the field's
               own `start_workflow()` default; the assertion gave zero
               actual coverage of what its name claimed. Fixed to resume
               with `""` and check the interrupt actually clears; added a
               dedicated regression test pinning the `{}`-never-delivered
               characteristic separately, so it can't silently regress
               either way. Verified the fix concept *before* implementing
               it, by monkeypatching the routing predicate against the
               real graph — cheap and caught nothing wrong, but confirmed
               the design before writing it for real.
**Left open:** Q18 (candidate disambiguation), Q20 (TRT XOR/oneOf schema),
               Q3 (durable checkpointer) — unrelated, untouched. `docs/
               state/STATUS.md` rewritten as part of this PR (was stale,
               still describing #35/#36 as pending — corrected here rather
               than as a separate PR since nothing else is in flight this
               time). 4 new/updated tests in `tests/test_workflow.py`
               (2 new regression tests, 2 corrected), 1 rewritten in
               `tests/test_cli.py`, 1 rewritten in `tests/test_cli_workflow.py`.
               Full suite 403 → 405 passing, zero regressions. `ruff`/`mypy`
               clean on all touched files (3 pre-existing findings outside
               this diff's own lines confirmed unchanged from `main` via
               direct comparison, not touched by this branch). Manually
               verified against the real, unfaked CLI: `python -m cv_agent
               workflow "..."` with stdin closed now exits 0 with `Final
               status: done`, exactly one `[INTERRUPT] clarification`.
               Branch `fix/claude/q21-clarify-attempted-flag`, not `main`.
               Issue #37, PR pending.

## 2026-09-18 — Mutually-exclusive input field groups, resolving Q20 (feature/claude/q20-input-field-groups)
**Did:**       Asked the owner directly (Q18/Q20 were both explicitly
               "owner decision, nothing to build until answered" per
               `STATUS.md`'s own next actions) and got: Q18 -> a
               clarification-style interrupt (future work, not this PR);
               Q20 -> a oneOf/XOR field-group construct. Implemented Q20
               only, to keep this PR focused. New `RequiredFieldGroup`
               (`cv_agent.execution.binding`, ADR-0009 §12): `kind:
               Literal["exactly_one"]`, `field_names: tuple[str, ...]`,
               presence-only (satisfied the moment any one member has a
               value — never rejects "both supplied," that stays
               `_build_argv()`'s job). `ExecutionBinding` gains
               `input_field_groups`, validated in a new `__post_init__`
               (every member must be a declared, `required=False`
               `InputField`). `plan_execution()` (ADR-0010 §14) reads
               groups alongside `input_schema`; `PlanningResult` gains
               `selected_input_field_groups`, the same checkpointed-
               snapshot pattern as `selected_input_schema`. The
               `provide_execution_inputs` recovery interrupt
               (`_classify_execution_input_resume`) is now group-aware too
               — fulfillment is "any one group member accepted," not
               "every requested name answered," which would have made
               real recovery unusable for a genuine XOR. The retry-time
               identity/schema guard now also compares field groups.
               `trt_perf_analysis.build_binding()` finally populates its
               real contract — `path`/`data` (each `required=False`),
               `model_name`, and one `exactly_one` group — closing the gap
               ADR-0009 §11/ADR-0010 §13.8 both explicitly left open.
**Why:**       `STATUS.md`'s next action after the Q21 merge was exactly
               "decide Q18/Q20" — everything else (`Do not start yet`) was
               blocked on it. Q20 specifically blocked a genuine, unfaked
               end-to-end test of ADR-0010 §13's recovery flow against the
               real `trt-perf-analysis` binding; every prior recovery test
               used a synthetic fixture binding instead.
**Learned:**   `RequiredFieldGroup.field_names` is a tuple field, so it
               inherits the exact tuple-vs-list checkpoint-round-trip
               instability ADR-0004 already documents for other
               `AgentState` tuple fields — `InputField` never had this
               problem (no container-typed attributes), so §13's original
               `dataclasses.asdict()`-based schema comparison never had to
               think about it. Fixed by building both sides of the group
               comparison manually with `field_names` forced through
               `list(...)`, never left to whatever `asdict()`/the
               checkpoint happened to preserve — caught by writing the
               real end-to-end test, not anticipated in design. Also found
               (via the mock-registry unit tests, not the real-skill
               tests): `still_missing`'s original computation (`requested`
               minus `accepted`) doesn't know about groups — supplying
               only `data` from a `path`/`data` group left `path` listed
               as "still missing" even though the group was already
               satisfied. Fixed by excluding a satisfied group's other
               members from `still_missing`.
**Left open:** Q18 (ambiguous-candidate disambiguation interrupt) —
               answered by the owner but not implemented; separate future
               issue. CLI prompt UX for `python -m cv_agent workflow` is
               unchanged — the existing per-field prompt loop already
               produces a correct answer for a group when a human leaves
               the unwanted field blank; a friendlier "choose one of
               path/data" prompt was left out to keep this PR scoped to
               the planning/recovery contract, not CLI UX. 26 new/updated
               tests across `tests/test_execution.py`,
               `tests/test_execution_planning_contract.py`,
               `tests/test_workflow.py`,
               `tests/test_execution_trt_perf_analysis.py` (including 2
               genuine, unfaked `@requires_real_skill` end-to-end tests
               against the real installed binding — skipped, not faked,
               where the skill isn't installed). Full suite 405 → 429
               passing, zero regressions. `ruff`/`mypy` clean on all
               touched files except the same, already-tolerated
               `AgentState` has no key `"__interrupt__"` TypedDict gap
               `tests/test_workflow.py` already carried pre-existing (now
               also appears once in the new real-skill test, for the same
               structural reason — LangGraph injects that key at runtime,
               outside the TypedDict's own declared shape). Branch
               `feature/claude/q20-input-field-groups`, not `main`. Issue
               #39, PR pending.

## 2026-09-18 — Q20 review correction: true oneOf/XOR, not "at least one" (PR #40)
**Did:**       An independent review of PR #40 (explicitly re-verifying
               every claim rather than trusting the PR description — re-
               fetched, re-diffed cold, independently re-ran the full
               suite via a disposable `git worktree` baseline of `main`,
               manually invoked the real runtime directly) found the Q20
               implementation satisfied "declarative field-group
               construct" but not "EXACTLY ONE alternative" — `plan_
               execution()`/the recovery interrupt only ever checked "at
               least one member present," deliberately deferring "reject
               more than one" entirely to the runtime. Corrected: new
               `PlanningStatus` value `"conflicting_inputs"` — two or more
               members of an `"exactly_one"` group present in
               `available_inputs` is now caught and reported, with the
               exact offending names, *before* any plan, approval
               interrupt, or execution — checked ahead of
               `"missing_required_inputs"` when both would otherwise
               apply. `_classify_execution_input_resume()` gains a
               matching `"conflicting"` outcome for the recovery-interrupt
               path. `ExecutionBinding.__post_init__` (ADR-0009 §13) now
               also rejects a field belonging to more than one
               `RequiredFieldGroup` — a second review-identified gap, the
               invariant `_node_provide_execution_inputs`'s group
               reconstruction silently relied on.
**Why:**       The owner's Q20 decision was explicit: "a declarative
               oneOf/XOR field-group construct... EXACTLY ONE alternative,
               not merely at least one." The first implementation's own
               documented rationale ("coarser, earlier check, not a
               substitute for the runtime's own validation") was a
               reasonable general posture but didn't actually deliver what
               was decided — a caller could reach a real human approval
               interrupt for an input combination already guaranteed to
               fail. Caught by independent review before merge, not after.
**Learned:**   A genuinely subtler bug than "supply both at once, get
               rejected": a resume payload for `provide_execution_inputs`
               may legally name any declared field, not only ones the
               interrupt actually requested — `_classify_execution_input_
               resume()`'s own `field_groups` parameter only reconstructs
               groups that were *entirely* missing at plan time (i.e.,
               actually in `requested`), so a human answering the real ask
               plus an extra, unrequested field that happens to conflict
               with an *already-known* value (pre-supplied in an earlier
               round) slips past that function's own check and reports
               "supplied." Only `_node_plan_execution`'s retry — which
               re-derives everything fresh against the fully merged
               `execution_inputs`, with no notion of "requested" at all —
               still catches it. Added an explicit `result.status ==
               "conflicting_inputs"` branch in the retry (ahead of the
               pre-existing generic "not planned" invariant guard) so this
               is labeled "conflicting," not folded into a misleading
               generic "binding_mismatch." Verified with a dedicated
               regression test constructing exactly this scenario, not
               merely asserted from reasoning about the code.
**Left open:** Q18 — untouched, per explicit instruction not to expand
               scope. `docs/state/STATUS.md` was found 4 lines over its
               own documented 60-line hard cap during review — trimmed to
               fit. ADR-0010 §14.7's per-file test-count breakdown was
               found not to reconcile against the actual diff (its
               aggregate total of 25 happened to be correct; the four
               per-file numbers did not sum to how the tests were actually
               distributed) — recounted directly from `git diff` and
               corrected, with the correction itself noted inline rather
               than silently rewritten. 9 new/1 renamed tests (net 8) across
               `tests/test_execution_planning_contract.py`,
               `tests/test_workflow.py`, `tests/test_execution.py`,
               `tests/test_execution_trt_perf_analysis.py` (2 more genuine,
               unfaked `@requires_real_skill` tests proving the real
               binding rejects a "both supplied" conflict before ever
               invoking the real subprocess). Full suite 429 → 437
               passing, zero regressions; `ruff`/`mypy` clean except the
               same pre-existing findings already documented on this
               branch, confirmed unchanged by direct comparison against
               `main`. Branch `feature/claude/q20-input-field-groups`
               (same PR #40, not merged), issue #39.


## 2026-09-20 — Q18: ambiguous-candidate disambiguation interrupt (feature/claude/q18-candidate-disambiguation)
**Did:**       Merged PR #40 (squash, `752bc1c`; issue #39 auto-closed; 437
               tests green on the merged `main`), then implemented Q18 as its
               own issue (#41) and branch. New fourth interrupt kind
               `choose_candidate` (ADR-0010 §16): when `plan_execution()`
               reports `"ambiguous_candidates"` the graph pauses, presents
               every candidate's skill_id + description, validates the
               human's bare-skill_id answer against the exact checkpointed
               offered set, persists it (`candidate_choice`/
               `candidate_selection`) and routes back to `plan_execution`,
               which now takes an optional `selected_skill_id`. One shot; an
               invalid/cancelled/no-longer-valid choice is terminal and
               bypasses `approval_gate`. CLI handles the new kind (prompt +
               summary line), no new flag — the owner chose the interrupt
               over a `--skill` override.
**Why:**       Q18 was the owner-decided, unbuilt item `STATUS.md` named as
               next after Q20; until now `"ambiguous_candidates"` just ended
               the run with no plan and nobody was ever asked.
**Learned:**   (1) A naive retry has a silent-wrong-skill hole: the chosen
               skill's binding deregistered during the pause leaves ONE
               candidate, and `plan_execution()` happily plans it. An
               "is it still ambiguous?" check misses this entirely; the
               retry must require `result.selected_skill_id ==
               chosen_skill_id`. Caught by reasoning while writing the
               retry block, then pinned by a test and mutation-checked (the
               test fails when the check is weakened) — a passing test alone
               would not have proved it was load-bearing. (2) Adding a
               second recovery kind broke an assumption that had been
               silently true: `_node_plan_execution` was only ever
               re-entered once after `execution_input_recovery` was
               finalized, so gating on `attempted is True` sufficed. With
               choose → retry → provide inputs → retry a run visits it
               several times; both finalization blocks now gate on
               `attempted AND terminal is None` so each round finalizes
               exactly once (a chained-recovery test asserts the candidate
               round is not re-finalized). (3) My first test-helper trick
               (`_graph_for = OtherClass._graph_for`) added 4 mypy errors;
               replaced with a delegating method — caught by comparing
               against a `main` worktree baseline, not by eyeballing.
               (4) Long heredocs containing apostrophes break in this
               shell; test/doc bodies were written with the file tool.
**Left open:** Q3 (durable checkpointer) and Q19 (approval cost estimate)
               untouched. The new interrupt is unreachable through
               `python -m cv_agent workflow` against any REAL installed
               skill today (only one real binding exists, and `_cmd_workflow`
               registers none) — exercised via fixture-graph and real-`CVAgent`
               tests instead, same documented posture as
               `provide_execution_inputs`. `ExecutionBinding.description` is
               the only description source; a richer `Skill.description`
               would need `plan_execution()` to depend on `SkillInventory`
               (deliberately not done). 31 new tests; full suite 437 → 468,
               zero regressions; `ruff`/`mypy` findings on touched files
               identical to `main`'s. Branch
               `feature/claude/q18-candidate-disambiguation`, issue #41,
               PR pending — not merged.


## 2026-09-20 — Q18 audit fixes: pin the shown binding, clear stale plans, fail closed (PR #42)
**Did:**       An independent audit of PR #42 (probing empirically, not
               re-reading my tests) returned CHANGES REQUESTED with four
               findings; all fixed on the same branch before merge. D1: the
               choice was pinned by `skill_id` only, so a same-`skill_id`
               re-registration (new `binding_id`, runtime, description)
               during the pause ran the *replacement* under the human's
               earlier choice — now `candidate_binding_ids` is snapshotted
               at plan time, the choose node records
               `expected_binding_id`/`expected_description` from the
               checkpointed offer, and the retry requires skill, binding_id
               and current description to all match (terminal
               `candidate_mismatch` + `mismatch_detail` otherwise). D2:
               docs claimed `None`/`{}` are "cancelled"; they are not
               delivered by LangGraph at all — corrected everywhere and
               pinned by tests, not worked around. D3: `planning_result.plan`
               is cleared on any terminal recovery failure (both kinds).
               D4: the choose node fails closed on a malformed offer instead
               of `zip()`-truncating it.
**Why:**       The audit was right about D1, and it was a real integrity gap:
               my own retry check (`selected_skill_id == chosen`) answered
               "is it still the same *name*?" when the property that matters
               is "is it still the thing the human was *shown*?".
               `provide_execution_inputs` already pinned binding identity for
               exactly this reason; I had reproduced that discipline in the
               interrupt payload but not in the retry.
**Learned:**   (1) Identity checks need to be phrased against what the human
               saw, not against a lookup key — a name is only an identity if
               nothing behind it can change. (2) Every code fix was
               checked by mutation, not just by a passing test: dropping the binding comparison, dropping only the
               description comparison, dropping the plan-clearing line and
               dropping the malformed-offer guard each fail their tests. The
               description-only mutant matters: without a separate test the
               `binding_id` check alone would have masked a broken
               description check. (3) D3 forced a scope question I would not
               have asked myself: clearing the plan only for the new
               interrupt would leave `binding_mismatch` (ADR-0010 §13)
               carrying the same stale plan for a binding the human was never
               asked about — an invariant that depends on *which* recovery
               kind failed is one only half the readers can rely on, so it
               applies to both, and no existing test depended on the old
               behavior. (4) The `resume={}`/`resume=None` finding is a
               LangGraph characteristic, and my own docstring had it wrong
               ("`None`... is 'cancelled'") — a claim about behavior I had
               probed for `""` and extrapolated to `None`. (5) The suite
               passed all 23 new tests on the first run, which is exactly when
               to distrust them; the mutation pass is what showed they bite.
               (6) The repo has no CI, so "green" here means only what I ran
               locally; the PR says so.
**Left open:** Q3, Q19 untouched. `ExecutionBinding` description drift is now
               a mismatch, which is deliberately strict (a reworded
               description after the human read it terminates the run) — a
               looser policy would be a product decision, not a bug fix.
               `expected_candidate_skill_ids` is still recorded but only
               used at classify time; the retry pins by chosen identity. 25
               new tests; full suite 468 → 493, zero regressions;
               `ruff`/`mypy` on touched files identical to `main` (checked
               against a fresh worktree). Branch
               `feature/claude/q18-candidate-disambiguation`, PR #42 — not
               merged.


## 2026-09-21 — Close out Q18; record the approval-pause integrity gap (docs-only PR)
**Did:**       Merged PR #42 (squash, `3230361`; #41 closed; 493 tests green on
               merged `main`), then filed two follow-ups and refreshed rolling
               state in this docs-only PR. #43: the approval pause pins only
               `skill_id`; two defects reproduced on current `main` AND on
               pre-Q18 `752bc1c` — (1) a replacement binding/runtime registered
               during the approval pause runs under approval granted for the
               original; (2) a replacement with an `allowed` policy overrides a
               human REJECTION (`approval_decision="not_required"`, execution
               `completed`). #44: `workflow` cannot reach its interrupts against a
               real skill. Recorded as Q22/Q23 and D-031; `STATUS.md` corrected
               (it still said PR #42 was unmerged); ADR-0010 §16.3 gained a scope
               note. No source or test file changed; nothing implemented.
**Why:**       The #42 audit surfaced the approval gap while checking that a
               changed binding can never run after a pause. It is outside #42's
               diff and pre-existing, so it was split out rather than folded into
               a PR that had already been audited and approved.
**Learned:**   (1) I first reported the gap as "a replacement runs after
               approval". Re-verifying before writing the issue showed the worse
               half: a *rejection* is overridable. The cause is different, not a
               variant — the gate does a live `get_binding()` BEFORE
               `interrupt()`, LangGraph re-runs that on resume, and a replacement
               whose policy is `allowed` makes the node return
               `not_required` without ever reaching the recorded decision. An
               execution-time `binding_id` check alone would block the run but
               would still record `not_required`, and would miss a replacement
               that keeps the same `binding_id` and flips only the policy — the
               latter confirmed by a probe (`not_required`, `completed`, original
               runtime ran), not just by reading code. (2) "Pre-existing" was
               established by running the probe on a `git worktree` of `752bc1c`
               and printing `cv_agent.__file__` to prove which tree was loaded,
               not inferred from the diff not touching the gate. (3) A claim in
               my own draft of the issue ("fixing only the execution-time check
               would not fix Defect 2") was wrong as worded — that check WOULD
               block scenario C's execution — and was corrected before anyone
               relied on it. (4) The approval gate violates the replay-safety
               rule (no live registry read before `interrupt()` on resume) that
               ADR-0010 §13/§16 already impose on the two newer interrupts;
               that asymmetry is the root of Defect 2.
**Left open:** #43 (needs an ADR amendment first, then implementation and the
               regression tests listed in the issue, asserting the replacement
               runtime is never invoked), #44 (owner decisions; `choose_candidate`
               also needs a second real binding, currently prohibited), Q3, Q19
               (already tracked, untouched). Health marked yellow in `STATUS.md`
               until #43 is resolved.

## 2026-09-21 — #43 approval-integrity ADR amendment drafted (docs-only, proposed)
**Did:**        Drafted ADR-0003 §10 (proposed): whole-binding `binding_pin` in `pending_execution`, captured once in `plan_execution`; gate decides from the pin (no live read before `interrupt()`); a recorded rejection short-circuits in `_node_execute` without calling the executor; `SkillExecutor.execute()` compares the pin against its own single lookup (ADR-0009 §14, `expected_binding_pin`, new `binding_mismatch` category); mismatch is terminal, no re-approval. Reworded ADR-0010 §16.3's scope sentence. Updated Q22 and STATUS. No source/test change; DECISIONS not appended (nothing decided yet).
**Why:**        Issue #43 requires the ADR before code (`CLAUDE.md` §5); `[P§24]`.
**Broke/learned:** Rejection is enforced today only inside the executor via the *live* policy — a third fact beyond the two defects in #43, and the reason the graph itself must refuse to invoke after a rejection. Same-`runtime_id` runtime-object substitution is not detectable from serializable state (residual, decision D2).
**Left open:**  Owner decisions D1-D5 (ADR-0003 §10.11); then implementation of #43. #44, Q3, Q19 untouched.

## 2026-09-21 — #43 approval-integrity contract, revision 2 (docs-only, still proposed)
**Did:**        Revised ADR-0003 §10 after owner review (accepted D1/D3/D4/D5): one lifecycle (plan → immutable pin → approval request → recorded decision → integrity validation → outcome); pin = whole-binding snapshot + runtime registration generation; rejection branch runs first in `_node_execute` so no integrity result or replacement can override it; executor rule E1 (approval-required + no pin is refused even with `approved=True`) closes the "absent pin bypasses" hole; per-situation result table. Added ADR-0009 §14 (executor order, `pin_mismatch`, registry generation) and ADR-0010 §17 (`PlanningResult.selected_description`, `description_changed` through `provide_execution_inputs`). Updated Q22/STATUS. No source or test change; DECISIONS not appended.
**Why:**        Owner asked for a precise integrity contract before any code (`CLAUDE.md` §5); `[P§24]`.
**Broke/learned:** The direct CLI path is not pause-free — `_confirm_approval()` blocks on `input()` between `get_binding` and `execute`, contradicting ADR-0009 §10 / issue #43's "no pause" (unreachable today, but not a sound exemption). No registry generation/token exists; `register_runtime` overwrites unconditionally. `id(obj)` rejected as a token (reusable after GC). In-place mutation, restart and threading remain undetectable limits.
**Left open:**  D2, D5', D6, D7 (ADR-0003 §10.11). #44, Q3, Q19 untouched.

## 2026-09-21 — #43 approval-integrity contract, revision 3 (docs-only, finalized proposal)
**Did:**        Finalized ADR-0003 §10 with owner decisions D1/D2/D4/D5'/D6/D7. Defined the three pin states (missing key / explicit `None` / present-malformed) and one authoritative outcome table (§10.5) that graph, executor (ADR-0009 §14) and tests all defer to; canonical snapshot + canonical-JSON equality (no `asdict`/`repr`/object `==`); runtime-generation capture and check table; rejection-first ordering in `_node_execute`; terminal/plan-cleared/no-rewrite/no-re-plan/no-re-ask guarantees; 23 explicit acceptance tests (T1-T23). ADR-0010 §17: description pinning fails closed, including on absent snapshot. Q22/STATUS updated. No source/test change; DECISIONS not appended until approval.
**Why:**        Owner review of revision 2 flagged conflicting missing-pin descriptions, unspecified equality, and unspecified runtime-generation edge cases.
**Broke/learned:** Revision 2 said "missing pin" was handled at two layers with different codes and left a bare `not_required` able to run a pinned `approval_required` binding if state were hand-built (now row 5, `approval_decision_inconsistent`). The registry has no removal API, so "deregistered" is private-dict-only. No binding currently sets a non-`None` `InputField.default`.
**Left open:**  Owner approval of the contract; minor ambiguities A1-A3 (ADR-0003 §10.14). #44, Q3, Q19 untouched.

## 2026-09-21 — #43 approval integrity implemented (branch fix/claude/43-approval-integrity)
**Did:**        Implemented the owner-approved ADR-0003 §10 contract. `ExecutionBinding.pin()` (explicit field access, canonical-JSON equality), `ExecutionBindingRegistry.pin()`/`get_runtime_registration()` and a per-runtime registration generation (`(runtime, generation)` in one dict value); `pin_is_well_formed()`/`pin_mismatch()`; `SkillExecutionRequest.expected_binding_pin` and `ExecutionErrorCategory += "binding_mismatch"`; `SkillExecutor.execute()` reads binding + runtime registration once, enforces rule E1 (approval-required needs a pin even with `approved=True`), compares the pin, and invokes the same runtime instance. Graph: `_node_plan_execution` captures `execution_pin` once (also for caller-supplied plans, at first observation); the gate decides from the pin only and never interrupts on an unusable pin; `_node_execute` checks a recorded rejection first, then missing / explicit-None / malformed / decision-inconsistent, then calls the executor; every `rejected`/`not_executable` result clears `planning_result["plan"]`. Description pinning through `provide_execution_inputs` (`PlanningResult.selected_description`, `expected_description`, `description_changed`, fail closed on absence). `python -m cv_agent execute` now captures the pin before its prompt (`_authorize_and_execute`). Tests: `tests/test_approval_integrity.py` (85); the two `approved=True` approval-required executor tests now pass a pin; exact-equality assertions on `pending_execution`/`planning_result` gained the additive keys (`_without_pin`, `selected_description`).
**Why:**        Issue #43 / Q22, `[P§24]`; owner approval of ADR-0003 §10 rev.3 with A1-A3.
**Verified:**   Focused: 85 passed. Full suite 578 passed (493 baseline + 85), 0 failed. `ruff` on the touched files: identical to base (one pre-existing F841); `mypy cv_agent`: 6 errors vs 9 at base (3 pre-existing `None`-indexing errors in `_node_execute` disappeared with the new guard), `mypy tests/test_approval_integrity.py` clean. **T22 mutation checks:** 23 mutations applied one at a time and reverted — rejection-first branch, executor pin comparison, rule E1, executor well-formedness, explicit-None branch, decision-consistency guard, generation comparison, description comparison, generation increment, caller-plan pinning, plan clearing, separate-runtime-lookup, gate unusable-pin check, execute missing-key and malformed checks, always-re-pin, CLI dropping the pin, skill_id well-formedness, gate ignoring the pinned policy, gate explicit-None branch, recovery description snapshot, generation omitted from the pin, planned-path pin — every one made at least one test fail.
**Broke/learned:** A `float("nan")` default is the reachable "cannot be pinned" case: an `object()` default already crashes `planning_result` checkpointing (pre-existing, independent of #43). `allowed`→`approval_required` cannot be exercised inside a graph pause (an `allowed` pin has no pause after capture), so it is proven at the executor. A first mutation-script pattern matched two sites (the choose_candidate record also has `expected_description`) and was made unique — a reminder that a mutation check must confirm it hit exactly one place. No plan-clearing assertion in the existing suite needed changing (A2). The direct CLI has a real pause (`input()`), contrary to ADR-0009 §10 — corrected in §14.
**Left open:**  PR review/merge of #43. Limits documented in ADR-0003 §10.8 (in-place mutation, restart/Q3, threads). #44, Q3, Q19 untouched.

## 2026-09-21 — #43 review follow-ups (PR #46)
**Did:**        Applied the independent review's fixes. Tests (+23, 85 → 108 in `tests/test_approval_integrity.py`): falsy non-`None` pins at the executor for `allowed` and `approval_required` (`{}`, `[]`, `""`, `0`, `False`, `()`); pin capture at runtime generation 2 and a later replacement (generation 3); the exact approval payload (`runtime_id`, `description`); caller-forged `execution_pin` through the production entry point `CVAgent.start_workflow` (forged `allowed` over an approval-required binding, forged `approval_required` over an `allowed` one, an identical caller pin, explicit `None`, malformed, another skill's pin); `--approve` with a registry change between pin capture and the executor call (description and runtime object); an unpinnable approval-required binding raising before any prompt; refusal/mismatch evidence and the gate's `execution_pin_unusable` log entry. Code/docs: `_node_execute` passes `approved = (decision == "approved")` as ADR-0003 §10.6 specifies; stale docstrings corrected (`state.py` `execution_result`, `runtime/agent.py` `start_workflow`, ADR-0010 §10, `planning.py`, `SkillExecutor.get_binding`, which is kept as public API); ADR-0003 §10.8 limitation on on-disk skill files; ADR-0003 T18 now states what the `--approve` test covers; `_without_pin` consolidated into `tests/test_workflow.py`; the trailing blank line at the end of this file removed.
**Why:**        Review findings: coverage gaps found by 11 extra mutations (9 survived, none a production defect) and documentation discrepancies.
**Correction:** My 2026-09-21 revision-2 and implementation entries above say "ADR-0009 §10 / issue #43's 'no pause'". ADR-0009 §10 makes no such claim — it comes from issue #43's out-of-scope note; ADR-0003 §10.1 and ADR-0009 §14 are corrected. (Past entries are not edited.)
**Verified:**   `tests/test_approval_integrity.py` 108 passed; full suite 601 passed (493 baseline + 108). `ruff check cv_agent tests`: findings identical to base (line numbers normalized). `mypy cv_agent`: 6 errors vs 9 at base (all 6 pre-existing, in untouched files); `mypy tests/test_approval_integrity.py` clean. `git diff --check` clean. The 11 extra mutations from the review re-run: 10 killed; the one survivor removes the `except ValueError` branch in the `_cmd_execute` wrapper, which needs the real skill installed to reach.
**Left open:**  PR #45 / #46 sequencing (both contain `4979e50`) — owner decision. The `_cmd_execute` wrapper is still not covered by tests (needs the real skill installed).

## 2026-09-21 — #43 merged; CLI approval prompt context, Issue #47 (PR #49)
**Did:**        Close-out of #43: PR #46 squash-merged as `a92ec2e` (Issue #43 closed), PR #45 closed unmerged as superseded (its only commit `4979e50` is #46's parent), local checkout synced to `origin/main`, follow-up issues #47 (CLI prompt context) and #48 (`_cmd_execute` approval-path test) opened. Then implemented #47 on `feature/claude/47-approval-prompt-context` (commit `abd3370`, PR #49): a shared `_approval_prompt()`/`_shown()` in `cv_agent/__main__.py` renders the approval question for both CLI paths — `workflow` (values from the pinned approval payload, `.get()` so a payload without the new keys cannot raise) and `execute`'s `_confirm_approval` (values from the binding it is handed, never a second registry read); the `[INTERRUPT] approval` echo line also shows `runtime=` and `description=`. Whitespace is collapsed to one line; a blank/missing description renders `(no description)`, a missing runtime `(unknown)`. Documented the `_authorize_and_execute` caller contract. 15 new exact-text tests (7 in `tests/test_cli_execute.py`, 8 in `tests/test_cli_workflow.py`, incl. the real pinned payload through the real graph); a `binding_description` parameter added to that file's `_build_graph` helper.
**Why:**        #43 made the approval payload carry `runtime_id`/`description` and made description drift fail closed, but the CLI never showed either to the human being asked; `[P§24]`. Display only — payload, pinning, executor, decision handling and exit codes are unchanged, and the existing approval tests pass unmodified.
**Verified:**   Focused (`test_cli_execute` + `test_cli_workflow` + `test_approval_integrity`) 167 passed after the final docstring edit; full suite 616 passed (601 baseline + 15), run before that docstring-only edit. `ruff check cv_agent tests` and `mypy cv_agent` findings identical to `main` (mypy: 6 pre-existing errors in untouched files). `git diff --check` clean. 8 mutations (drop runtime/description from either prompt or the echo, remove whitespace collapsing, remove the empty fallback, require the new payload keys) each made a test fail; a 9th (`or ''`) is behavior-equivalent. No CI exists, so none of this is CI-verified.
**Broke/learned:** A review question — can the separate `registry.pin(...)` read in `_authorize_and_execute` differ from the binding shown? Not under the supported model: the sole caller is `_cmd_execute`, the two registry reads (`get_binding()`, then `pin()`) are straight-line code on a process-private `CVAgent` with no I/O between them and no threads/async anywhere in `cv_agent`; the only window is during the prompt, which is what the pin guards. It could diverge only if a future caller passed a binding not read from the registry — so the contract is documented, not enforced (a mismatch check would add a new failure outcome and belongs in its own issue). Process slip: #47's first commit and PR omitted the rolling-state docs this protocol requires; this entry and the `STATUS.md` rewrite fix that (no `DECISIONS.md` line — no decision was made; no `OPEN_QUESTIONS.md` change).
**Left open:**  PR #49 review/merge. #48 (tests for `_cmd_execute`'s approval and `ValueError` branches) not started. #44, Q3, Q19 untouched.

## 2026-09-22 — Issue #48: _cmd_execute approval-path tests (branch feature/claude/48-cmd-execute-approval-tests)
**Did:**        Synced local main to origin/main (9f7ad6a, PR #49/#47 merged) before starting. Added a keyword-only `prompt: Callable[[str], str] = input` parameter to `_cmd_execute` (cv_agent/__main__.py), threaded straight into its one `_authorize_and_execute(...)` call — the minimal seam #48's own acceptance criteria allowed, needed because `_authorize_and_execute`'s own `prompt` default is bound to the real `input` builtin once at import time, so `monkeypatch.setattr("builtins.input", ...)` cannot reach it. `main()` never passes this argument, so live CLI behavior is unchanged. New `TestExecuteCLIApprovalPath` in tests/test_cli_execute.py (6 tests), run in-process (never subprocess) against a `CV_AGENT_SKILL_PATHS`-isolated fixture skill root with `cv_agent.execution.runtimes.trt_perf_analysis.register` monkeypatched to install an approval_required fixture binding (real trt-perf-analysis binding stays untouched, still `"allowed"`): declined (live "n" and EOF) never runs; approved (live "y") and `--approve` each run once; a registry mutation performed from inside the prompt callback fails closed as `binding_mismatch`; a binding with a non-JSON-native default (`float("nan")`) fails before any prompt with exit 2. Module docstring rewritten to state which of the four test classes need no real skill (three of four; only TestExecuteCLIRealSkill is `requires_real_skill`-gated, and is now explicitly documented as never reaching the approval_required/unpinnable branches). STATUS.md rewritten (it was stale — still showing PR #49 as unmerged after the sync).
**Why:**        Issue #48 / `[P§24]`; the `_cmd_execute` wrapper (as opposed to `_authorize_and_execute`, already covered by tests/test_approval_integrity.py's T18) was untested for its approval decision, exit codes and messages.
**Verified:**   Focused (`tests/test_cli_execute.py`) 30 passed (24 pre-existing + 6 new). Full suite 622 passed (616 baseline at 9f7ad6a + 6). `ruff check cv_agent tests` and `mypy cv_agent`/`mypy tests/test_cli_execute.py` identical to the 9f7ad6a baseline after fixing one self-introduced `ruff` F821 (a missing `from typing import Any` in the new test file — caught before commit, not shipped). `git diff --check` clean. Two required mutation checks, each applied to a scratch copy of cv_agent/__main__.py and reverted: removing the `except ValueError` branch in `_cmd_execute` — killed (unhandled `ValueError` propagates, test fails); dropping `expected_binding_pin=pin` in `_authorize_and_execute`'s request — killed, though via a different path than first expected (rule E1, ADR-0003 §10.7, fires first: "approval is not bound to an execution snapshot", `approval_denied`, not `binding_mismatch` — the test's `"binding_mismatch" in err` assertion still correctly fails, so the mutation is caught).
**Broke/learned:** STATUS.md had drifted stale across the #47 merge + local main sync (no session had rewritten it since PR #49 merged) — a reminder that syncing main is not itself a rolling-state update. The dropped-pin mutation surfaces a different error category (`approval_denied` via E1) than a naive "it'll report binding_mismatch" expectation — both are correct under ADR-0003 §10.5's outcome table, and the test only needed to assert failure, not the specific category, to catch it; noted for anyone reading this test that the assertion is more specific than strictly required.
**Left open:**  Commit and PR for this branch (stopped for review per instruction). No approval_required binding registered for the real skill — out of scope, per the issue. #44, Q3, Q19 untouched.

## 2026-09-22 — Milestone 1: spec-to-implementation audit, docs reconciliation, CI (local, uncommitted)
**Did:**        Ran a specification-to-implementation audit of the whole project against docs/PROJECT.md, ROADMAP.md and OVERVIEW.md (read-only; findings reported, nothing changed). Then implemented its first recommended milestone, entirely as local working-tree changes on `main` (no branch, no commit): rewrote ROADMAP.md's Status lines for every phase (Implemented/Partial/Planned, none silently marked complete) and OVERVIEW.md's responsibility table (added a Status column; corrected the Dataset-subsystem/Training-subsystem rows, which still pointed at ADR-0009/ADR-0010 — both now real, different, accepted ADRs — framed explicitly as "a record of what happened, not a new design decision"). Added `.github/workflows/ci.yml` (ruff + mypy + pytest on push/PR to `main`) and `ruff`/`mypy` to `pyproject.toml`'s `dev` extra. Fixed all 12 pre-existing `ruff` findings (dead code in `graph/workflow.py`, unused imports in `requirements/models.py`/`skills/resolver.py`/two test files, 5 ambiguous `l` names in `test_agent.py`, one presence-probe import in `runtime/agent.py` given a wider `noqa`) and all 6 pre-existing `mypy` findings (two `importlib.resources.abc` stub-gap `type: ignore`s, a `builtins.list[...]` disambiguation in `capabilities/registry.py` for a method literally named `list`, a `Path`/`Traversable` `type: ignore` in `config/settings.py`, and the `LLMProvider`/`get_provider()` factory-call gap — see below). Two independent read-only reviews (by a separate reviewing pass) found no Blocker/Major and two Minor items; both are now resolved: (1) the `ci.yml` mypy-step comment pointed at a JOURNAL.md entry that did not yet exist — replaced with the concrete, verified fact instead (`mypy tests` → 18 pre-existing errors, 5 files); (2) the `LLMProvider.__init__` added to `cv_agent/llm/base.py` to resolve `mypy`'s `cv_agent/llm/registry.py:58: error: Unexpected keyword argument "model" for "LLMProvider"  [call-arg]` was new, untested runtime code (confirmed `FakeLLMProvider.__init__ is LLMProvider.__init__` → `False`, i.e. never executed by any subclass) — removed entirely; the same diagnostic is now resolved with a single scoped `# type: ignore[call-arg]` on `registry.py`'s `return cls(model=model)` line, with a comment explaining why the gap is real (mypy can't verify `Type[LLMProvider]` subclasses accept `model` since the ABC declares no `__init__`) but not a bug (every registered provider is required to accept it by `get_provider()`'s own pre-existing docstring, and a violation still fails loudly at the call site). No new code shipped for this finding — confirmed by re-running `mypy cv_agent` (clean) and `pytest tests/test_llm_mock.py` (19 passed) after the change.
**Why:**        `CLAUDE.md` §6/§7; the audit's Blocker-free, evidence-gated report recommended this as the lowest-risk, highest-leverage next step (closes Phase 0's own stated "CI" scope gap; removes the single-largest process risk — every prior PR's ruff/mypy/pytest claim was self-reported only, never independently checked — before the project takes on more complexity).
**Verified:**   `ruff check cv_agent tests` — 0 findings (was 12). `mypy cv_agent` — 0 errors, 38 files (was 6). `pytest` — 622 passed, matching every prior baseline exactly; also re-run focused after the `llm/base.py` revert: `tests/test_llm_mock.py` 19 passed. `mypy tests` (whole tree, not a CI requirement) — 18 pre-existing errors across 5 files, unrelated to this batch, cited accurately in `ci.yml`'s comment rather than left as a dangling forward-reference. `pyproject.toml`/`ci.yml` both re-parsed with `tomli`/`PyYAML` after every edit. No CI run exists yet to independently confirm this (nothing pushed) — stated as a limitation, not glossed over.
**Broke/learned:** The first cut of the `mypy` fix for `llm/registry.py`'s factory call added a concrete `LLMProvider.__init__` — it silenced the diagnostic but was itself new, unexercised runtime code with no test, exactly the kind of scope creep a "smallest correct change" rule is meant to catch; a second look (prompted by review, not found unprompted) showed the diagnostic's real target was the one call site, not the ABC, and a scoped `type: ignore` there is strictly smaller and adds nothing untested. Two consecutive review passes over an unchanged diff reproduce identical findings — a review that finds nothing new the second time means it's time to fix, not re-review.
**Left open:**  Commit and push of this local work (explicitly not done this session, per instruction). `tests/` is not mypy-clean as a whole (18 pre-existing errors, 5 files, unrelated to this batch — CI checks `cv_agent` only, documented in `ci.yml`). #44, Q3, Q19 untouched — no `DECISIONS.md`/`OPEN_QUESTIONS.md` change (nothing was decided).

## 2026-09-23 — CI stabilization: dependency pin drift + cross-platform mypy fix (PR #51)
**Did:**        Committed and pushed the previously "local, uncommitted" Milestone-1 work as `34c8ba8`, giving this repo its first-ever real GitHub Actions run. That run failed at the Ruff step: `pyproject.toml`'s unpinned `ruff>=0.15` had resolved to `0.16.8` in CI, surfacing 112 new findings absent under the locally-validated `0.15.19`. Pinned `ruff==0.15.19` (`676e263`) — no rule changes, no fixes to the 112 findings, no `noqa`. Pushed; the next run's Ruff step passed but `mypy (cv_agent)` then failed the same way: unpinned `mypy>=2.0` had resolved `2.3.1` in CI vs. the locally-validated `2.1.0`. Pinned `mypy==2.1.0` (`ee384ca`). Pushed again; Ruff passed, but `mypy` still failed — now with 2 errors on the pre-existing `importlib.resources.abc` `type: ignore[import-untyped]` in `cv_agent/capabilities/registry.py`/`cv_agent/config/settings.py`, reported as `import-not-found` on CI's Linux runner. Investigated (read-only) before touching anything: typeshed's own `stdlib/VERSIONS` gates `importlib.resources.abc` to Python 3.11+; this is the first time `mypy cv_agent` had ever run in a clean, non-author environment, since `.github/workflows/ci.yml` did not exist before `34c8ba8`. Reproducing locally (Windows) with a cleared `.mypy_cache` showed mypy passing silently — until the ignore code was deliberately changed, which revealed Windows mypy reports a *different* code (`import-untyped`) than Linux mypy (`import-not-found`) for the identical import, identical mypy version, identical target Python version. Fixed on branch `fix/codehub1443/mypy-cross-platform-ignore`: both files' ignore widened to `# type: ignore[import-untyped, import-not-found]`, with the adjacent comment corrected to state the real, verified reason (typeshed's version gate) instead of the previous inaccurate "typeshed ships no stubs" guess. Validated clean on Windows (local, clean `.mypy_cache`) and Linux (`python:3.10` Docker, matching CI's runner). PR #51 opened, real GitHub Actions run confirmed green (Ruff, mypy, pytest all pass — the first fully green CI run in the repo's history), squash-merged as `ca6da85`.
**Why:**        `CLAUDE.md` §6/§7 (rolling state must reflect reality); `[P§29.5]` reproducibility — every prior "ruff/mypy/pytest clean" claim in this repo's history had been self-reported only, never independently checked, until this session's CI runs.
**Broke/learned:** Three independent root causes surfaced in sequence, not one: (1) `ruff>=0.15` and (2) `mypy>=2.0` are both unbounded-above version specs that silently drifted to newer releases in a fresh CI install than what any contributor had locally validated against — an unpinned lower bound is not a safe pin. (3) Even once both pins matched the locally-validated versions, mypy itself diagnoses the exact same version-gated stdlib import with a *different* error code depending on host OS (confirmed by direct Linux Docker reproduction, not inferred) — a genuine, if obscure, mypy/typeshed cross-platform behavior difference, not a version-resolution problem at all. The original `# type: ignore[import-untyped]` (added 2026-09-01, commits `b1092c1`/`9beb586`) was coincidentally correct for the original author's own machine, which is exactly why it had silently passed every local check for three weeks and only failed the moment a real, independent Linux CI environment first exercised it.
**Left open:**  None from this arc — CI is fully green end-to-end. #44, Q3, Q19 untouched. ADR-0002 (LLM gateway) remains blocked on `STATUS.md`'s "do not start yet" hold and `OPEN_QUESTIONS.md` Q7 — an owner decision, not attempted this session; no `DECISIONS.md` change (no genuine architectural/owner decision was made in this arc, only dependency pins and a diagnostic-annotation correction).

## 2026-09-23 — ADR-0002: LLM gateway, first real provider (Anthropic), branch feature/codehub1443/llm-gateway-anthropic
**Did:**        Owner (Tanvir) explicitly authorized and resolved the blocker from the previous entry: Anthropic is the first real provider, credentials available, single configured model with no automatic fallback, gateway stays provider-agnostic (recorded as D-033, answering `OPEN_QUESTIONS.md` Q7 and lifting `STATUS.md`'s "real LLM providers" hold for exactly this scope). Asked and confirmed the one remaining blocking detail per this task's own instruction (do not invent a model identifier): `claude-sonnet-4-5`. Wrote ADR-0002 (`docs/architecture/adr/ADR-0002-llm-gateway.md`) after inspecting the existing gateway (`cv_agent/llm/{base,mock,registry}.py`), the one existing call site (`RequirementsAnalyzer`'s mock-only narrative hook, ADR-0008/D-011), and confirming directly from ADR-0003 §10's text that the approval-integrity chain has zero relationship to the LLM layer. Implemented: `cv_agent/llm/anthropic_provider.py` (new) — `AnthropicProvider(LLMProvider)` against the real `anthropic` SDK (verified `0.125.0`'s actual `Messages.create()` signature, `Message`/`TextBlock`/`Usage` response shapes, and the full `APIError` exception hierarchy by reading the installed package directly, not assumed), reading `ANTHROPIC_API_KEY` from the environment only (never `AgentConfig`/TOML), with a `client=` constructor seam for dependency-injected tests and a `api_key=` override for direct construction; self-registers via `register_provider()` at import time. `cv_agent/llm/registry.py` gained a small `_LAZY_ADAPTERS` name→module map and a lazy `importlib.import_module()` call inside `get_provider()` so `"anthropic"` is discoverable without `cv_agent.llm` ever hard-importing the SDK; `list_providers()` now also reports known-but-not-yet-imported lazy names. `pyproject.toml` gained `anthropic>=0.40,<1` (in both `dev` and its own new `anthropic` extra). Both copies of `config/default.toml` had their commented example's stale `claude-opus-4-5` corrected to the actual decided model, `claude-sonnet-4-5` (comment-only, default provider stays `"mock"`). New `tests/test_llm_anthropic.py` (24 tests): construction/credential handling, `complete()`'s request/response mapping against an injected fake client, each real Anthropic exception class re-raised as `AnthropicRequestError` with a credential-free message, registry integration (`get_provider`, no-fallback), and a structural test mirroring ADR-0004's `sqlite3`-confinement pattern (`anthropic` imported nowhere outside `anthropic_provider.py`). Updated `docs/architecture/OVERVIEW.md` (LLM Gateway row: Planned → Partial) and `docs/roadmap/ROADMAP.md` (Phase 1's exit test item 2, "two providers swappable by config alone," now met and cited).
**Why:**        `docs/roadmap/ROADMAP.md` Phase 1's own named exit test; `[P§20]` ("the provider must therefore be replaceable"); owner authorization (D-033) explicitly unblocking the STATUS.md hold and Q7 that had stopped this exact work in the previous session.
**Verified:**   Focused `tests/test_llm_anthropic.py`: 24 passed, no real network call or credential in any test (confirmed by code review — every `complete()` test uses an injected fake client; the one test constructing a real `anthropic.Anthropic()` via `get_provider()` never calls `.complete()`, so no request is ever sent). Full suite: 622 → 646 passed, zero regressions. `ruff check cv_agent tests`: `All checks passed!`. `mypy cv_agent` (clean `.mypy_cache`): `Success: no issues found in 39 source files`. Explicitly re-ran the approval-integrity and real-skill-binding suites in isolation per this task's own instruction: `tests/test_approval_integrity.py` + `tests/test_execution.py` + `tests/test_execution_trt_perf_analysis.py` + `tests/test_cli_execute.py` → 200 passed, unchanged behavior.
**Broke/learned:** The real `anthropic` SDK's exception hierarchy is not flat — `AuthenticationError`/`RateLimitError` are `APIStatusError` subclasses (need `.status_code`/`.message`, constructed from a real `httpx.Response`), `APIConnectionError` is a sibling branch (not a subclass of `APIStatusError`), and `APIResponseValidationError` is a third, independent `APIError` subclass under neither — this shape was read directly from the installed package's source (`_exceptions.py`) rather than guessed, which is what caught that a naive `except (APIStatusError, APIConnectionError)` two-branch design would have missed the third case entirely. Deliberately did NOT build: a call/spend budget or a multi-provider routing policy (`OPEN_QUESTIONS.md` Q6/Q19 remain open placeholders; inventing either would be exactly the silent invention `[P§35]` forbids) — stated as an explicit, tracked limitation in ADR-0002 §6 rather than glossed over.
**Left open:**  Commit and push of `feature/codehub1443/llm-gateway-anthropic` and opening a PR — explicitly not done this session, per this task's own git-boundary instruction (no commit/push without Tanvir's separate, explicit authorization). Q6, Q19, Q3, #44 untouched, exactly as instructed. Next roadmap phase (Knowledge/RAG) not started.

## 2026-09-24 — PR #52 review correction: claude-sonnet-4-5 → claude-sonnet-5 (D-034)
**Did:**        PR #52 (ADR-0002) had been committed, pushed, and opened as a PR in the previous session. Before merge, Tanvir's review flagged that the configured model, `claude-sonnet-4-5` (an undated alias), should be verified against the real API rather than treated as production-ready, and that the adapter should keep model-specific request behavior isolated (already true structurally — confirmed and reported, no code change needed for that part). Verified the model claim directly rather than trusting or dismissing it: read the installed `anthropic` SDK's own `ModelParam` type literal (confirmed `claude-sonnet-4-5-20250929` is a real, recognized dated snapshot) and fetched Anthropic's live `platform.claude.com/docs/en/models/overview` page, which states pre-4.6-generation aliases (Sonnet 4.5 is one) "resolve to the dated ID" — confirming the review comment's technical claim. That same fetch surfaced a larger, unprompted fact: Claude Sonnet 4.5 is now a legacy model, superseded by Claude Sonnet 5, and 4.6+-generation model IDs (including Sonnet 5) are themselves already-pinned snapshots with no drift problem at all. Presented both options (date-pin the legacy family vs. move to the current-generation, inherently-pinned family) to Tanvir; Tanvir chose `claude-sonnet-5`. Updated the model-ID string everywhere it appeared: `cv_agent/llm/anthropic_provider.py` (docstring example only — the adapter never hardcoded a default model), both copies of `config/default.toml`'s example comment, `tests/test_llm_anthropic.py` (27 occurrences), and ADR-0002 (§3, §7, plus a new §9 documenting the correction with full reasoning, following the ADR-0003 §9 precedent of appending rather than silently rewriting). `docs/state/DECISIONS.md` gained D-034 recording the correction; D-033 itself was left unedited, per the ledger's append-only convention. `docs/state/STATUS.md` (a rolling document, not a ledger) was rewritten directly to reflect the corrected model.
**Why:**        `[P§29.5]` reproducibility and `[P§35]` (verify before asserting, don't invent) — a reviewer's technical claim about a production dependency is exactly the kind of thing to verify against a primary source before acting on it either way (blindly implementing it, or dismissing it).
**Verified:**   Full suite re-run after the string substitution: `ruff check cv_agent tests` clean, `mypy cv_agent` clean, `pytest` 646 passed (unchanged count — only literal string values changed in tests, no new/removed test). No behavioral change: `AnthropicProvider.__init__` never had a default `model` value, so this correction is purely which string a caller configures, not a code change to the adapter's logic.
**Broke/learned:** A code-review comment citing an external fact ("the API identifies X") is worth verifying against a primary source before either blindly implementing the suggested fix or dismissing it — in this case verification not only confirmed the reviewer's claim but surfaced a materially bigger, unprompted fact (the whole model generation being superseded) that a narrower "just add the date suffix" fix would have missed entirely, leaving the project pinned to a legacy model when a better-suited current one was one config value away.
**Left open:**  Commit/push of this correction — awaiting explicit authorization, same git-boundary posture as the original PR #52 work. Q3/Q6/Q19/#44 untouched.

## 2026-09-24 — Repository audit (read-only), then ADR-0005 drafted (docs-only, uncommitted)

**Did:**        Two tasks in sequence. (1) A full read-only, 20-step roadmap-to-repository gap audit (no files modified, nothing committed), covering requirements/canon, architecture completeness, LLM integration, skill discovery, execution bindings, approval gates, planning workflow, and every not-yet-started downstream phase (knowledge, dataset, training, optimization, deployment, validation, artifact management, production readiness, release) — findings reported to the owner, not recorded as a rolling-state artifact since it changed nothing. (2) The owner confirmed PR #52 (`1853e0a`, D-034's `claude-sonnet-5` correction) is committed and pushed, then asked for the next unblocked architecture task. Re-verified: `git log origin/main..HEAD` shows exactly `b486807`/`1853e0a` on the branch, PR #52 `state: OPEN`, `mergeable: MERGEABLE`, working tree clean. Analysis: of Q23/#44, Q6, Q19, Q3, Q16, Q10, Q2, none can be answered without the owner (each requires a value — a threshold, a backend choice, a physical execution target — this codebase has no authority to invent per `[P§35]`); drafting ADR-0005 (tool/MCP boundary) was identified as the one architecture task both named in `docs/architecture/OVERVIEW.md`'s own design sequence (step 5, right after project memory) and independent of all seven open questions. Read `AGENTS.md`, `docs/architecture/OVERVIEW.md`, `docs/roadmap/ROADMAP.md`, `docs/architecture/adr/ADR-0000-template.md`, ADR-0001, ADR-0007, ADR-0009, `spec/06-tooling-and-mcp.md`, and `docs/PROJECT.md` §15/§22/§23 before drafting, per the owner's explicit instruction. Wrote `docs/architecture/adr/ADR-0005-tool-mcp-boundary.md` (Status: Proposed) — `cv_agent.tools` boundary types (`ToolId`, `ToolSpec`, `ToolRequest`/`Result`/`Error`, `ToolInvoker` protocol, `ToolRegistry`, `ToolExecutor`), zero implementations, zero registered tools, no MCP SDK/vendor chosen, Q5's MCP-vs-skill half explicitly left open and `OPEN_QUESTIONS.md` left untouched (per instruction). Updated `docs/architecture/OVERVIEW.md`'s Tools/MCP row and `docs/roadmap/ROADMAP.md` Phase 2's status line to reference the draft; added D-035.

**Why:**        `[P§34]` boundary-first discipline; `AGENTS.md`/`CLAUDE.md` §5 ("architect sessions produce ADR + interface stubs only"); the owner's explicit scope (narrow architecture only, no MCP vendor, no wiring, no owner-decision invention).

**Broke:**      Nothing — no code touched, no tests run, no commits made.

**Learned:**    ADR-0001 §5 already named `ToolId`/`Skill.requires_tools` back on 2026-08-30, but ADR-0001's own §8a records it was never implemented (ADR-0001 itself is still `Proposed`, not `Accepted` — D-005) — so ADR-0005 is the first place `ToolId` actually gets defined, not a reuse of an existing type. `spec/06-tooling-and-mcp.md` (non-canonical) had already independently arrived at "the tool layer must not infer approval from the existence of a planning request" — the same posture ADR-0003 §10/ADR-0009 §14 already enforce for skills — cited directly in ADR-0005 §9 rather than restated as a new rule.

**Left open:**  ADR-0005 itself is Proposed only — owner review/accept/revise/reject needed before any `cv_agent/tools/` implementation. `OPEN_QUESTIONS.md` unchanged (Q5's MCP half, Q2, Q3, Q6, Q10, Q16, Q19, Q23 all untouched). Nothing committed or pushed this session.

## 2026-09-24 — ADR-0005 architecture review, revision, acceptance, and implementation (branch `feature/claude/adr-0005-tool-mcp-boundary`, issue #53)

**Did:** Four-step arc, each gated on the prior step's outcome, no implementation before acceptance. **(1) Review:** an owner-requested architecture review of the ADR-0005 draft (boundary correctness vs. every neighboring layer, safety/integrity of the proposed contracts, interface-by-interface findings, governance/doc consistency) found **zero BLOCKERs** and five IMPORTANT findings: no runtime/invoker registration-generation protection (reproducing D1/issue #43's defect class from scratch); no `binding_mismatch`-equivalent error category; `ToolInvoker.invoke()` returning the final `ToolResult` directly (collapsing the `RuntimeOutcome`/`SkillExecutionResult` trust boundary ADR-0009 deliberately keeps); `ToolResult` carrying no provenance/evidence; `ToolResultStatus` missing an in-progress state. Plus a citation error (ADR-0005 §1 wrongly claimed ROADMAP Phase 3 names ADR-0005; verified false — only Phase 2 does) and several MINOR findings. **(2) Revision:** same day, before acceptance — all five IMPORTANT findings fixed in the ADR's own interface (§5): `ToolRegistry.get_invoker_registration()`/`pin()` (generation tracking), new `tool_mismatch` category + `tool_pin_is_well_formed()`/`tool_pin_mismatch()` (mirroring `pin_is_well_formed`/`pin_mismatch`, ADR-0009 §14), new `ToolOutcome` type (mirrors `RuntimeOutcome`) so `ToolInvoker` can no longer set `tool_id`/`status`/evidence, new `ToolEvidence` (mirrors `ExecutionEvidence`, adds type-level-only `provenance`/`execution_metadata` placeholders), `started` added to `ToolResultStatus`. MINOR findings addressed per instruction (not expanding scope): `ToolId` used consistently, `ToolRequiredFieldGroup` added (`exactly_one` from the start, applying the Q20 lesson directly), `list_invokers()` added, `not_available` renamed to `not_executable`, `invalid_input` removed with inline rationale, `input_schema`'s non-enforcing role made explicit, `ApprovalPolicy` duplication kept (with a required drift-detection test) rather than adding a shared module. §11 appended recording every finding and its fix, mirroring ADR-0003 §9/ADR-0009 §9–14's amendment-section convention. **(3) Acceptance:** the owner (Tanvir) accepted ADR-0005 by instructing its implementation — Status flipped Proposed → Accepted, D-036 added recording the acceptance (D-035, the draft decision, left unedited per the ledger's append-only convention, mirroring how D-034 handled D-033). **(4) Implementation:** branch `feature/claude/adr-0005-tool-mcp-boundary` created from the tip of `feature/codehub1443/llm-gateway-anthropic` (carrying the uncommitted ADR-0005 doc work forward without altering that branch's own commit history — the LLM-gateway branch itself is untouched); GitHub issue #53 opened first, per `CLAUDE.md` §5's "no implementation code without an issue." Built `cv_agent/tools/` exactly per the accepted interface: `models.py` (`ToolId`, `ToolTransport`, `ToolResultStatus`, `ToolErrorCategory`, `ApprovalPolicy`, `ToolInputField`, `ToolRequiredFieldGroup`, `ToolSpec` with `pin()`, `ToolRequest`, `ToolError`, `ToolEvidence`, `ToolResult`, `ToolOutcome`), `invoker.py` (`ToolInvoker` protocol), `registry.py` (`ToolRegistry` with invoker-generation tracking, `pin()`, `tool_pin_is_well_formed()`, `tool_pin_mismatch()` — algorithms verified line-for-line against `cv_agent/execution/binding.py`'s equivalents), `executor.py` (`ToolExecutor`, fail-closed branching in the exact order ADR-0009 §14 specifies: no-spec → E1 pin-required check → pin-supplied mismatch check (any policy) → verified check → rejected-policy → approval-required-without-approval → no-invoker → invoke). Zero `ToolSpec`s/`ToolInvoker`s registered anywhere; no MCP SDK imported; nothing wired into `CVAgent`/`LangGraph`/`SkillExecutor`/existing execution bindings. 71 new tests (`tests/test_tools.py`), covering every scenario the task named plus the ADR's own §7 acceptance criteria: registration/duplicate-registration, generation tracking (first/re-register-same/replace/A→B→A), pin creation/well-formedness/mismatch, fail-closed paths, the `ToolOutcome`/`ToolResult` trust boundary (including a structural test that `ToolOutcome`'s only fields are `success`/`output`/`error_message`), evidence, `started` status, XOR field-group validation, registry listing, an `ApprovalPolicy` value-set-equality drift guard against `cv_agent.execution.models`, non-enforcing `input_schema` behavior, no-auto-registration, and three architecture-boundary tests (no forbidden-layer imports, no MCP SDK reference, no self-registration).

**Why:** `CLAUDE.md` §5 (architect produces ADR + interface stubs only; implementation is a separate, issue-gated session); `[P§24]`/`[P§34]` (the review's own five findings were exactly the class of gap — replayable approval bypass, collapsed trust boundary — this project has spent real effort (D-027 through D-032) getting right once already for skills, so getting it right the first time for tools mattered enough to review before implementing).

**Verified:** `ruff check cv_agent tests` clean; `mypy cv_agent` clean (44 source files, up from 39); full suite 646 → 717 passing (71 new), zero regressions. Two manual mutation checks on the highest-risk branches (mirroring the rigor `docs/state/DECISIONS.md` D-032 used for the skill-side approval-integrity work): disabling the E1 pin-required check made `test_approval_required_without_pin_is_rejected_regardless_of_approved` fail as expected; disabling the invoker-generation-mismatch comparison made both `test_detects_a_changed_invoker_generation` and `test_replaced_invoker_with_stale_pin_is_tool_mismatch_and_never_invoked` fail as expected — both mutations reverted before committing. `git diff --check` clean.

**Broke:** Two of my own architecture-boundary tests were initially too strict and false-failed: one flagged this package's own docstrings for *mentioning* `cv_agent.execution` in prose (not importing it) — fixed to check only lines starting with `import`/`from`; the other flagged `ToolRegistry`'s own `def register_spec(...)`/`def register_invoker(...)` *definitions* as if they were *calls* — fixed to require a leading `.` (an actual method call), which the method definitions don't have. Both caught immediately by running the suite, neither shipped.

**Learned:** `ExecutionBindingRegistry.pin()`/`ExecutionBinding.pin()`'s split (spec-only canonical snapshot vs. registry-level combination with the runtime/invoker generation) transferred cleanly to the tool boundary with no adaptation needed — the same two-method shape (`ToolSpec.pin()` + `ToolRegistry.pin(tool_id)`) was the right design here too, confirming the ADR-0005 §11 revision's own prediction that the generation-tracking fix would be a faithful mirror, not a redesign.

**Left open:** No real `ToolInvoker`/MCP client exists — the next natural step (not requested this session) would be the same kind of one-skill-at-a-time verification ADR-0009 §8/§9 used for `trt-perf-analysis`, applied to a first real tool, once the owner names a candidate. `cv_agent.tools` is not wired into `CVAgent`, `LangGraph`, or `SkillExecutor` — deliberately, per this task's own scope. `OPEN_QUESTIONS.md` untouched; Q2/Q3/Q5/Q6/Q10/Q16/Q19/Q23 all remain unresolved. PR review/merge pending.
