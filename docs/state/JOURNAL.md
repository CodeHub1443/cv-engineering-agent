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

## 2026-09-01 — Phase 1 state reconciliation (docs/reconcile-dev-munna-phase1-state)

**Did:** Reconciled the project state onto the agreed `main` → `dev-munna` → short-lived
branch workflow; restored the Phase 1 status, restored ADR-0002 as a draft, recorded the
Q7/Q8 decisions as D-016/D-017, and added the current `AGENT_HANDOFF.md`.

**Why:** The active `dev-munna` state had reverted to Phase 0 wording and still described
the retired single-trunk workflow, while the project is continuing Phase 1 architecture
work. The repository state must describe the actual operating model before more ADR work
proceeds.

**Broke:** The existing `DECISIONS.md` update repeatedly returned a GitHub contents API
409 despite the blob SHA matching the fetched file. No overwrite or force update was made
to that file through the API; its existing content therefore remains unchanged on this
branch until it can be updated safely.

**Learned:** The prior ADR-0002 draft still exists on the historical short-lived branch
`docs/issue-11-adr-0002-llm-gateway` and can be recovered without reconstructing it from
memory.

**Left open:** `DECISIONS.md` still needs D-008 marked superseded and D-015–D-018 appended.
Q1–Q5 remain unanswered and therefore continue to block the dependent ADRs.

---

## 2026-09-01 — ADR-0003 Orchestration State & Checkpointing (docs/issue-adr-0003-orchestration-state)

**Did:** Drafted `docs/architecture/adr/ADR-0003-orchestration-state.md` specifying the
LangGraph orchestration state machine, typed `AgentState` schema, local SQLite checkpointer
backed persistence at `.cv_agent/state/checkpoints.sqlite` (Q1 / D-013, Q8 / D-018),
persistent human approval interrupt/resume mechanics surviving process restarts (Q3 / D-015,
`[P§24]`), and out-of-process asynchronous external job handles (Q2 / D-014). Updated
`STATUS.md`, `AGENT_HANDOFF.md`, and appended `D-017`, `D-018`, `D-019` to `DECISIONS.md`.

**Why:** `[P§21]`, `[P§24]`, `[P§25]`, `[P§34]` — the orchestration layer must own workflow
transitions, persistent checkpoints, approval gates, and error recovery contracts without
leaking domain reasoning, LLM provider specifics, or tool execution into the graph.

**Broke:** Nothing broken. Running tests and static analysis passed.

**Learned:** Scoping checkpoints to local workspace SQLite satisfies both Q1 (per-project
isolation) and Q3 (cross-process restart survival) cleanly without external network services.

**Left open:** ADR-0003 revised with dual-SQLite reconciliation and full acceptance criteria, awaiting PM review/acceptance. ADR-0004 (project memory / experiment ledger) is unblocked for drafting. Q5 remains deferred.

