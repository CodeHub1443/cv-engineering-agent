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
