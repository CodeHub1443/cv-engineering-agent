# ADR-0004: Project memory

- **Status:** Accepted
- **Date:** 2026-09-15
- **Layer:** memory
- **Canon:** `[P§21]`, `[P§25]`, `[P§26]`, `[P§30]`, `[P§33]`, `[P§34]`, `[P§35]`
- **Supersedes / Superseded by:** —
- **Issue:** #TBD

## 1. Context

`docs/roadmap/ROADMAP.md` Phase 1 names this deliverable: "ADR-0004 project memory &
experiment ledger." `docs/PROJECT.md` §33 lists "Project Memory / Experiment History /
Dataset Knowledge" as a distinct subsystem alongside Reasoning/Knowledge/Execution, and
§25 states its purpose precisely: the agent must answer *"why did we choose this
model?"* **from record**, not from conversational memory. §30 narrates the product as
producing a written PROJECT UNDERSTANDING that the rest of the lifecycle builds on —
today that document only exists as `RequirementsAnalysis`, a plain return value
(ADR-0008) that a LangGraph node can carry through one interrupt/resume run (ADR-0003)
but that vanishes the moment that run's checkpoint is discarded (`MemorySaver`, in-
process only — confirmed in ADR-0003 §1).

`docs/state/OPEN_QUESTIONS.md` Q1 ("what is the unit of a project?") explicitly blocked
this ADR. It has been resolved by the project owner (2026-09-15, recorded in
`OPEN_QUESTIONS.md` and D-014):

1. V1 uses **one CV project per repository/workspace**.
2. **No** multi-project/multi-tenant support, project selection, or `project_id`
   abstraction in V1.
3. The workspace/repository **is** the project boundary.
4. Project Understanding is **persistent current state with recoverable revision
   history**.
5. Experiments are **immutable append-only records**.
6. Session identity remains **distinct** from project identity; sessions **belong to**
   the workspace/project.
7. No broader multi-repository workspace abstraction in V1.

A follow-up audit of this ADR's first draft found a real gap: it named a storage
*backend* as open (`OPEN_QUESTIONS.md` Q8) but never addressed whether persisted
Project Understanding is committed to Git or kept local, nor whether it is sensitive
data under `docs/APPROVALS.md` — a genuine risk given `docs/PROJECT.md` §5/§30's own
worked examples (prison security, factory floors) can surface operationally sensitive
facility detail. The project owner resolved this as a new question, Q15 (recorded in
`OPEN_QUESTIONS.md`, D-015):

8. Project Understanding is **potentially sensitive project data**, governed by
   `docs/APPROVALS.md`'s data/privacy rule.
9. Project Understanding and its revisions must be **durable across process
   restarts** (unchanged from item 4) — but must **NOT** be automatically stored in
   **Git-tracked** repository files.
10. V1 persistent storage is **local/project-scoped and gitignored by default**.
    Durability does not imply Git tracking.
11. The storage *backend/technology* (files vs. SQLite vs. a service) remains
    unresolved — `OPEN_QUESTIONS.md` Q8, unchanged, now narrowed to exclude
    "in-repo/tracked files" as an option. External-LLM transmission of any persisted
    data remains governed by the existing approval/privacy rules — persistence grants
    no new permission to send it externally.

With Q1 and Q15 settled, `OPEN_QUESTIONS.md` Q8 (item 11 above) was the one remaining
implementation blocker for this ADR. The project owner has now resolved it
(2026-09-15, recorded in `OPEN_QUESTIONS.md` and D-016):

12. **SQLite** is the V1 project-memory storage backend — local and project-scoped,
    the database file living in the gitignored persistent-state area item 10 already
    requires. Must survive process restarts (item 9, unchanged). SQLite is used
    strictly **behind** the `ProjectMemoryStore` `Protocol` (§5) — no module outside
    `cv_agent/memory/` may import a SQLite-specific type or depend on it directly, so
    a future backend can replace it without touching callers. No external
    database/service is required for V1. This resolves Q8 **for project memory
    only** — the experiment ledger's own backend question is split off as new
    `OPEN_QUESTIONS.md` Q16, still open, and does not block this ADR
    (`docs/state/EXPERIMENTS.md` is unchanged — item 5, unchanged).

A post-implementation audit of `default_db_path()` (the helper that resolves item 10's
gitignored location) found it fell back to `Path.cwd()` with no contract guaranteeing
`Path.cwd()` is actually the workspace root — confirmed by inspection: no CLI flag, no
`CVAgent` parameter, and no other mechanism anywhere in the codebase ties process
execution to a specific directory, and the installed `cv-agent` console script is
invocable from anywhere. The project owner resolved this as an explicit clarification
of item 3 (recorded in D-018), not a new open question — it was always implied by "the
workspace IS the boundary" but never stated as a resolution *contract*:

13. **The application caller is responsible for resolving `workspace_root`.**
    `ProjectMemoryStore`/`default_db_path()` must never infer the workspace from their
    own execution context (`Path.cwd()`, `__file__`, git discovery, or otherwise).
    `default_db_path(workspace_root=...)` may keep `Path.cwd()` as a **convenience
    default for direct/standalone use only** — it is not, and must never be treated
    as, the application contract. The real application integration (`CVAgent`, the
    CLI — implemented, D-019, §9) resolves and passes `workspace_root` explicitly;
    `ProjectMemoryStore`/`default_db_path()` still never resolve it themselves.
    Automatic repository-root discovery (walking parent
    directories for a `.git`/marker file) is explicitly **out of scope for V1** — see
    the audit's alternatives comparison; nothing today demonstrates a need for it, and
    building it ahead of the actual integration would be exactly the speculative
    generality `[P§34]`/`CLAUDE.md` §3.12 reject.

Before designing anything, the existing state shapes were inspected directly:
`cv_agent/graph/state.py` (`AgentState.session_id` is a random UUID per run, no project
concept anywhere), `cv_agent/requirements/models.py` (`RequirementsAnalysis` has no
project field — just `original_request`, a single string), and
`docs/state/EXPERIMENTS.md` (its schema already has **no `project_id` column** — every
prior ADR independently built as if there is exactly one project per repository,
without anyone deciding it). This ADR formalizes what was already implicit, rather than
introducing a new shape — consistent with the owner's decision.

This ADR resolves the *scope* question (one project per workspace), the *boundary* of
a memory subsystem that can persist that project's understanding durably, and now the
*backend choice* (SQLite, item 12). It still does **not** build or implement that
backend — no `cv_agent/memory/` code exists; see §6/§9.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** the concept of "the project" as the workspace itself (no
  representation needed beyond that), the shape and lifecycle of **Project
  Understanding** (current state + recoverable revision history), the distinction
  between Project Understanding, sessions, and experiment records, and a minimal
  storage **interface** (`cv_agent.memory`) that a future backend implements.
- **This does NOT own:**
  - producing a requirements analysis → `RequirementsAnalyzer` (ADR-0008), called
    by whoever writes a new Project Understanding revision, not reimplemented;
  - orchestration state, interrupt/resume mechanics, or the LangGraph checkpointer
    used *within* one run → `cv_agent.graph.workflow` (ADR-0003) — that checkpointer
    remains keyed by `session_id` and is a separate concern from this ADR's durable,
    cross-session store; whether they eventually share a storage backend is a revisit
    trigger (§8), not a decision made here;
  - the experiment ledger's schema or rules → `docs/state/EXPERIMENTS.md`, already
    fully specified per `[P§25]`; this ADR defines *where an experiment record's home
    is relative to a project* and a storage interface it could persist through, not a
    new schema;
  - execution, skill discovery, or capability resolution → ADR-0007/0009, unchanged;
  - **implementing** the chosen storage technology → SQLite is now decided (§1
    item 12, Q8/D-016) but not built — no `cv_agent/memory/` code, no database file,
    no query logic exists in this codebase. Writing that implementation, and keeping
    SQLite strictly internal to `cv_agent/memory/` (never imported or depended on by
    `CVAgent`, the graph, or the CLI directly), is a separate, later PR against the
    `ProjectMemoryStore` `Protocol` this ADR defines;
  - multi-project selection, isolation, or a `project_id` type → explicitly out of
    scope per the owner's decision (item 2 above); there is nothing to select because
    there is exactly one project;
  - **resolving *which* directory is the workspace** (§1 item 13) → the calling
    application (`CVAgent`/the CLI, implemented — D-019, §9). `ProjectMemoryStore` and
    `default_db_path()` accept `workspace_root` as an explicit value; they never
    discover it themselves. `Path.cwd()` is `default_db_path()`'s convenience default
    for direct/standalone use only, not a resolution mechanism this package owns.
- **Why this responsibility does not belong to an existing component:** `AgentState`
  (ADR-0003) is a **single-run** structure by design — it is discarded when its
  checkpoint is discarded, and extending it to persist across runs would recouple
  orchestration state to durability concerns ADR-0003 explicitly deferred to "whenever
  a persistent checkpointer is wired in" (ADR-0003 §8). `RequirementsAnalysis`
  (ADR-0008) is a stateless return value with no storage concept at all. Neither module
  can own "remember this across process restarts" without taking on a responsibility
  its own ADR explicitly declined. `[P§21]` requires memory to be a distinct
  layer from orchestration and reasoning for exactly this reason.

## 3. Decision

`cv_agent/memory/` (new package, **interface only** — no concrete backend, per
`CLAUDE.md` §5: architectural ADRs ship types and signatures, implementation is a
separate, later session):

**Project Understanding** is the durable, current-state document describing this
workspace's CV project — derived from the latest accepted `RequirementsAnalysis` (plus
any human-supplied clarification answers/assumptions). It has exactly one **current**
value at any time, and every change to it is captured as an immutable **revision**:
appended, never edited or deleted, so "why does the project understanding say X" is
always answerable from the revision log, mirroring the "never edit a row" rule
`docs/state/EXPERIMENTS.md` already applies to experiments.

**Sessions** (one LangGraph run each, `AgentState.session_id`) are recorded as
lightweight index entries — identifying metadata only (`session_id`,
timestamps, and which Project Understanding revision, if any, that session produced) —
not full conversation transcripts or graph checkpoints, which remain ADR-0003's
concern. A session's identity never becomes a project's identity: there is one project
(the workspace) and many sessions belonging to it, never the reverse.

**Experiment records** stay exactly what `docs/state/EXPERIMENTS.md` already defines:
immutable, append-only rows. This ADR does not change that schema. It only states where
an experiment record's identity sits relative to "the project": since there is exactly
one project per workspace, an experiment record needs no `project_id` field to be
unambiguous — it belongs to *the* project by virtue of living in this workspace, exactly
as `EXPERIMENTS.md` rule 2 ("the first run in a project is the baseline") already
assumed informally before this ADR made it explicit.

The storage interface (`ProjectMemoryStore`, a `Protocol`, §5) is the one piece of code
this ADR introduces: method signatures for reading/appending Project Understanding
revisions and session index entries, shaped so a concrete backend can implement it
without this ADR being revised. The chosen V1 backend is **SQLite** (item 12, Q8/D-016)
— local, project-scoped, gitignored, durable across restarts — but **no
implementation of it exists in this codebase yet**: no `cv_agent/memory/` package, no
`.sqlite`/`.db` file, no query code. Nothing in `CVAgent`, the workflow graph, or the
CLI calls the protocol. This is the same "boundary with zero bindings" pattern
ADR-0009 used for execution — a decided backend is not the same thing as a built one.
When a future PR does implement it, the SQLite dependency must stay **internal** to
`cv_agent/memory/`: every other module continues to depend only on
`ProjectMemoryStore`, never on `sqlite3`/a SQLite-specific type directly, so the
backend can be swapped per the Protocol's own purpose.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Add a `project_id` field to `AgentState`/`RequirementsAnalysis` now, defaulted to a constant, "for future-proofing" | Would make a later multi-project migration marginally easier | The owner's decision explicitly forbids introducing a `project_id` abstraction in V1 (item 2); a field that is always the same constant value is dead weight that answers a question `[P§34]`'s boundary test would reject ("what responsibility does this own" — none, yet); `CLAUDE.md` §3.12 favors deleting speculative structure, not adding it | Rejected; no `project_id` anywhere in this ADR's interface |
| Fold Project Understanding persistence directly into `AgentState`/the LangGraph checkpointer (make `MemorySaver`/a persistent checkpointer *be* project memory) | One storage mechanism instead of two; less new code | Conflates a **single-run** structure (`AgentState`, discarded per ADR-0003 by design) with a **cross-session, project-lifetime** structure; a checkpointer swap for durability (ADR-0003 §8) is about *one run* surviving a restart mid-interrupt, not about *many runs* building one coherent project understanding over weeks — different retention/mutation semantics (revisions are intentionally immutable-append; a run's mid-execution state is not) | Rejected; kept as a separate memory layer, per `[P§21]`. Whether they eventually share one physical backend is left as a revisit trigger (§8), not decided now |
| Design and pick a concrete storage backend now (e.g., commit to SQLite) so ADR-0004 is "complete" | Unblocks implementation immediately; no follow-up ADR needed | `docs/state/OPEN_QUESTIONS.md` Q8 is explicitly unanswered and the task instructions for this ADR explicitly forbid adding a database; picking a backend without that answer would be exactly the "silent invention" `[P§35]` forbids — reproducibility (`[P§29.5]`) favors in-repo, scale favors otherwise, and nothing in this session resolves that tradeoff | Rejected; this ADR defines the interface a backend must satisfy and stops there (§9 names Q8 as the remaining blocker) |
| Treat "the project" as needing no explicit representation at all (not even a Protocol) — just write Project Understanding revisions to a hardcoded file path whenever needed | Simplest possible thing; matches "one project = one workspace" literally | Leaves no seam for `CVAgent`/future nodes to call against, and no seam for the eventual backend choice (Q8) to be substituted without touching every caller — the same reasoning ADR-0009 used to justify an `ExecutionRuntime` protocol over hardcoded skill paths applies here | Rejected; a minimal `Protocol` is defined even though zero implementations exist yet |

*Row 3 above ("design and pick a concrete storage backend now") reflects this ADR's
original context, when Q8 was unresolved. Q8 has since been resolved separately by the
project owner (SQLite, item 12, D-016) — through the same mechanism as Q1/Q15: an
explicit owner decision recorded in `OPEN_QUESTIONS.md`/`DECISIONS.md`, not silent
invention by this ADR. That table row is left as a historical record of the reasoning
at the time, not rewritten.*

## 5. Interface

```python
# module: cv_agent.memory.models
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class ProjectUnderstandingRevision:
    """One immutable, appended snapshot of the project's understanding.
    Never edited after creation — a correction is a new revision."""
    revision_id: str                       # e.g. "PU-YYYYMMDD-NN"
    created_at: str                        # ISO-8601
    session_id: str                        # which session produced this revision
    requirements_analysis: dict[str, Any]  # dataclasses.asdict(RequirementsAnalysis)
    supersedes: str | None = None          # prior revision_id, or None for the first
    note: str = ""                         # why this revision was made


@dataclass(frozen=True)
class SessionRecord:
    """Lightweight index entry for one orchestration session. Not a
    transcript or a checkpoint — those remain ADR-0003's concern."""
    session_id: str
    started_at: str                        # ISO-8601
    ended_at: str | None
    status: str                            # mirrors AgentState.status at last write
    produced_revision_id: str | None = None  # set if this session wrote a new PU revision


# module: cv_agent.memory.store
from typing import Protocol

class ProjectMemoryStore(Protocol):
    """Storage boundary for this workspace's one project. Implemented by
    SqliteProjectMemoryStore (Q8/D-016, ADR-0004 §1 item 12) and wired into
    CVAgent (D-019, ADR-0004 §9). Its data MUST default to a gitignored,
    local/project-scoped location — never a Git-tracked path — per
    Q15/D-015 (ADR-0004 §1). The concrete SQLite implementation stays
    internal to cv_agent.memory — no other module imports sqlite3 or a
    SQLite-specific type; every caller (CVAgent included) depends on this
    Protocol only, so a future backend can replace SQLite without changing
    a caller."""

    def get_current_understanding(self) -> ProjectUnderstandingRevision | None: ...
    """None means no revision has ever been written for this project."""

    def append_understanding_revision(
        self, revision: ProjectUnderstandingRevision,
    ) -> None: ...
    """Appends; never overwrites or deletes a prior revision."""

    def list_understanding_revisions(self) -> list[ProjectUnderstandingRevision]: ...
    """Ordered oldest -> newest. Full recoverable history."""

    def record_session(self, session: SessionRecord) -> None: ...
    """Upsert by session_id (a session's own record may be updated in place
    as it progresses — e.g. ended_at/status — unlike an understanding
    revision or an experiment row, which are immutable once written)."""

    def get_session(self, session_id: str) -> SessionRecord | None: ...

    def list_sessions(self) -> list[SessionRecord]: ...
    """Ordered oldest -> newest."""
```

`cv_agent.graph.workflow` imports no `cv_agent.memory.*` symbol, and never will by
design (§2) — no graph node calls this Protocol. `CVAgent` does (D-019, §9): it wraps
the graph invocation from outside, keeping ADR-0003's checkpoint/interrupt mechanics
and this store two separate concerns. No `sqlite3` import or SQLite-specific type
appears anywhere outside `cv_agent/memory/sqlite_store.py`, `CVAgent` included — it
depends on this `Protocol` (plus `open_store()`, below), never on
`SqliteProjectMemoryStore` directly.

**Workspace-root resolution contract (§1 item 13, D-018):** `default_db_path(
workspace_root: Path | None = None) -> Path` resolves `workspace_root` if given, and
falls back to `Path.cwd()` only when it isn't — that fallback is a **convenience for
direct/standalone use** (scripts, a REPL, tests), never a guarantee that `Path.cwd()`
is the actual project workspace. Neither this function nor `ProjectMemoryStore`
performs any discovery of its own (no `.git` walk, no `__file__`-relative lookup).
`CVAgent`/the CLI (D-019, implemented) resolve the correct `workspace_root` and pass
it explicitly — see immediately below; relying on the default without doing so is
only correct by coincidence.

**Runtime integration (D-019, implemented) — the shipped interface this ADR's
Protocol above enabled, kept brief here since D-019/the JOURNAL carry the full
rationale:**

```python
# module: cv_agent.memory.store (addition)
def open_store(
    *, workspace_root: Path | None = None, db_path: Path | None = None,
) -> ProjectMemoryStore: ...
    # Factory — callers ask for "the store," never import
    # SqliteProjectMemoryStore directly (mirrors get_provider()).

# module: cv_agent.config.settings (addition to AgentConfig)
workspace_root: Path | None = None
    # Caller-resolved (§1 item 13) — never read from a config file,
    # never computed here.

# module: cv_agent.runtime.agent (additions to CVAgent)
@property
def memory(self) -> ProjectMemoryStore: ...
    # Lazily constructed via open_store(workspace_root=self._config.
    # workspace_root) — health_check()/resolve()/analyze_requirements()/
    # execute() never trigger it; only start_workflow()/resume_workflow() do.

def _sync_memory_after_run(
    self, session_id: str, started_at: str | None, result: AgentState,
) -> None: ...
    # Called by start_workflow()/resume_workflow() after the graph
    # invocation returns: upserts the session's SessionRecord, and appends
    # a new ProjectUnderstandingRevision iff requirements_analysis's
    # factual content (excluding narrative_summary/llm_provider —
    # ADR-0008 §2/§3) differs from get_current_understanding().
```

`start_workflow()` writes a `SessionRecord(status="running")` *before* invoking the
graph and preserves `started_at`/`produced_revision_id` across a restart;
`_mark_session_error()` (called from both `start_workflow()` and `resume_workflow()`
if the graph invocation itself raises) marks the session `status="error"` with
`ended_at` set, then re-raises the original exception unchanged, so a crash cannot
leave a `SessionRecord` silently stuck at "running" forever.

## 6. Consequences

- **Enables:** a named, stable interface (`ProjectMemoryStore`) that a future backend
  can implement and that future `CVAgent`/graph-node code can be written against,
  without redesigning `AgentState` or `RequirementsAnalysis`; a resolved, documented
  answer to "what is a project" that every future ADR in this area can cite instead of
  re-deriving; a resolved, documented answer to "is it committed" — a future backend
  implementation must default to a gitignored location, not `docs/state/` or any
  other tracked path, and must treat its contents as sensitive per `docs/APPROVALS.md`;
  a resolved, documented backend choice (SQLite) so an implementation PR can start
  without a design discussion, while still keeping that choice swappable behind the
  `Protocol`.
- **Makes harder:** nothing removed; purely additive. No existing test, module, or CLI
  command is touched.
- **Costs:** one new package (`cv_agent/memory/`, interface-only — two dataclasses and
  one `Protocol`, no logic), no new dependency yet (SQLite is Python's standard-library
  `sqlite3` — no new third-party package — but even that import does not appear
  anywhere in this codebase as a result of this ADR).
- **Migration / blast radius if reversed:** contained and minimal — nothing calls
  `cv_agent.memory` yet, so removing the package affects nothing else in the
  codebase. Reversing the SQLite choice specifically (§1 item 12) before any
  implementation exists costs nothing beyond updating `OPEN_QUESTIONS.md`/
  `DECISIONS.md` again — no migration, because there is no data yet.
- **Explicitly NOT delivered by this ADR's original (pre-implementation) draft** (kept
  as a historical record of that draft's scope — see D-017/D-019 below for what was
  since delivered; two items in this list are now superseded, marked inline):
  - no concrete `ProjectMemoryStore` implementation — **no SQLite code, no `.sqlite`
    file, no schema/query logic** — the backend is *decided*, not *built* — ***superseded
    by D-017: implemented***;
  - no wiring into `CVAgent`, `cv_agent.graph.workflow`, or the CLI — Project
    Understanding still only exists as a single run's `AgentState`/return value until
    the SQLite backend is actually implemented and wired in — ***superseded by D-019:
    `CVAgent`/CLI wiring done; `cv_agent.graph.workflow` itself remains untouched, by
    design (§2's responsibility split still holds)***;
  - no migration of `docs/state/EXPERIMENTS.md` into SQLite or code/the store — its
    contract is explicitly unchanged (§1 item 5; its own backend is `OPEN_QUESTIONS.md`
    Q16, separate and still open) — still true, unaffected by D-019;
  - no persistent LangGraph checkpointer (that remains ADR-0003 §8's job, whether or
    not it later shares a backend with this store) — still true, unaffected by D-019;
  - no RAG, MCP, or real LLM provider — out of scope for this ADR entirely;
  - no multi-project, multi-tenant, or `project_id` abstraction of any kind;
  - no external database/service — SQLite is embedded/local only, per §1 item 12.

## 7. Acceptance test

**Implemented** (branch `feature/claude/project-memory`, D-017):
`tests/test_memory.py`, 28 tests — schema initialization on a fresh nested path,
reopening an existing database, initialization failure raising `ProjectMemoryError`
(never a raw `OSError`/`sqlite3.Error`), empty-store behavior for every read method,
append-then-read of a Project Understanding revision, exact round-trip of a nested
`requirements_analysis` dict, `get_current_understanding()` returning the most
recently appended revision, full revision history preserved and returned in
insertion order (not alphabetical), a duplicate `revision_id` rejected with the
original left untouched, auditability metadata (`session_id`/`supersedes`/`note`/
`created_at`) preserved verbatim, session record/read, session identity matching a
caller-supplied UUID-shaped string verbatim, session upsert (not duplication) on a
second `record_session()` call, session list ordering, a structural guarantee that
`SessionRecord` carries no transcript field, data surviving an explicit `close()` and
reopen (including three sequential restart cycles), a closed-connection read/write
raising `ProjectMemoryError` chained from the underlying `sqlite3.Error`, and a
structural test asserting `sqlite3` is imported nowhere in the codebase except
`cv_agent/memory/sqlite_store.py`. Full suite: 195 → 223 passing, zero regressions.

**Integration** (D-019, same branch): `tests/test_memory_integration.py`, 21 tests
through the real `CVAgent` (not fakes) — explicit `workspace_root` propagation, a
default (unset) config never touching disk, session-record creation/update through
the full pause/resume/done lifecycle, session identity matching `AgentState.
session_id` verbatim, a restart preserving the original `started_at`, first-analysis
persistence, clarification-resume producing a second superseding revision, a plain
restart with an identical task *not* duplicating a revision (the container-type/
prose-exclusion regression test — see D-019), an approval-only resume not duplicating
one either, persistence visible to a newly constructed `CVAgent`, two different
`workspace_root`s producing two genuinely separate database files, memory failures
raising `ProjectMemoryError` rather than failing silently, and `run()`/
`health_check()` behaving identically whether or not `workspace_root` is configured
(and never touching memory themselves). Plus 3 new `open_store()` tests in
`tests/test_memory.py`, and two pre-existing test files (`tests/test_workflow.py`'s
`TestCVAgentWorkflowWiring`, `tests/test_cli.py`'s subprocess `_run()` helper) fixed
to pin an explicit `workspace_root`/`cwd` — both had been silently creating a real
`.cv_agent/` in this repository's own working directory every time the suite ran,
undetected until this integration made it observable (see D-019). Full suite:
223 → 247 passing, zero regressions.

## 8. Revisit trigger

- If SQLite is found unsuitable during implementation (e.g., a real concurrency need
  `docs/state/OPEN_QUESTIONS.md` Q14 — multi-user/team usage — would introduce,
  currently deferrable and out of scope for V1) — at that point the backend choice
  (§1 item 12) is reopened as a new decision, not silently swapped.
- When a persistent LangGraph checkpointer is wired in for ADR-0003 §8 — at that point,
  decide explicitly whether it shares a physical backend with `ProjectMemoryStore` or
  stays separate; this ADR takes no position on that today (§4, alternative 2). Note:
  even if it does, that checkpointer's own choice of backend is a separate decision
  from §1 item 12, which is scoped to `ProjectMemoryStore` only.
- When the owner's decision in `OPEN_QUESTIONS.md` Q1 is ever revisited (e.g., this
  workspace is deliberately reused for a second, unrelated CV project) — at that point
  the "one project per workspace" boundary this ADR is built on no longer holds and a
  `project_id` abstraction becomes necessary; do not add one before that happens.
- When `docs/state/OPEN_QUESTIONS.md` Q16 (experiment-ledger backend) is answered —
  unrelated to this ADR's own backend choice, but relevant if a future decision wants
  the two ledgers to share infrastructure.
- If the future `CVAgent`/CLI integration (§9) finds that explicit `workspace_root`
  resolution at a single entry point is insufficient in practice (e.g. a real need to
  invoke from a subdirectory of the workspace) — at that point automatic
  repository-root discovery (§1 item 13) is reconsidered as a deliberate decision,
  not added silently.

## 9. Status

**Implemented** (D-017, branch `feature/claude/project-memory`): `cv_agent/memory/`
exists exactly as specified in §5 — `models.py`, `store.py`, and
`sqlite_store.py` (`SqliteProjectMemoryStore`). Q1 (unit of a project), Q15
(Git-tracking/sensitivity), and Q8 (project-memory backend = SQLite) are all resolved
— see `OPEN_QUESTIONS.md` and D-014/D-015/D-016. **Workspace-root resolution
clarified** (D-018, §1 item 13, §2, §5): the package never infers its own workspace;
`default_db_path()`'s `Path.cwd()` fallback is a convenience, not the application
contract. **Wired into `CVAgent`/the CLI** (D-019, branch `feature/claude/
project-memory`, still unmerged): `AgentConfig.workspace_root`, lazily-constructed
`CVAgent.memory` (via `open_store()`, never a SQLite-specific type), session
lifecycle in `start_workflow()`/`resume_workflow()`, and Project Understanding
persistence — see D-019 for the full account. Project Memory remains separate from
LangGraph's own checkpoint (`MemorySaver`, ADR-0003, unchanged) — it does not replace
or participate in run/orchestration-state resume, only durable project context.

The following remain genuinely open but are **implementation-level details**, not
blockers — each was either decided during the integration (marked below) or remains
deferred with a documented default, rather than requiring another owner decision:

- **Revision-trigger policy — decided (D-019):** a new `ProjectUnderstandingRevision`
  is appended iff a run produces `requirements_analysis` whose *factual* content
  (excluding `narrative_summary`/`llm_provider` — ADR-0008 §2/§3: LLM prose, never a
  source of fact) differs, by JSON-normalized structural equality, from
  `get_current_understanding()`. Not semantic diffing — a fixed comparison with a
  fixed exclusion list. See `CVAgent._sync_memory_after_run()`'s docstring for why
  both normalizations (container-type and prose-exclusion) were needed empirically,
  not assumed.
- **Retention / redaction** — `docs/APPROVALS.md`'s "Data and privacy" section requires
  minimizing sensitive project-data exposure; whether Project Understanding revisions
  ever need redaction before being sent to an external LLM provider is unaddressed.
  Not a blocker for building local SQLite persistence (no external transmission
  happens in this ADR's scope at all — §1 item 11/§6); must be resolved before any
  future ADR wires a real LLM provider to read Project Understanding (relates to Q7).
- **Relationship to a persistent LangGraph checkpointer** — named as a revisit trigger
  above (§8); genuinely open, not a detail to be assumed either way, but does not
  block `cv_agent/memory/` from being built independently of ADR-0003's own
  checkpointer question.
- **`OPEN_QUESTIONS.md` Q16 (experiment-ledger backend)** — explicitly out of scope for
  this ADR (§1 item 12, §6) and does not block it.
