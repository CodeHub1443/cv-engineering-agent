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
