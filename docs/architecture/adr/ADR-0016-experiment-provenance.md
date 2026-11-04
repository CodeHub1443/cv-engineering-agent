# ADR-0016: Experiment provenance — commit capture, dirty-worktree refusal, write-once commit_sha

- **Status:** Accepted 2026-10-04 (owner approved implementation). Implemented on branch `feature/claude/experiment-provenance-recovery`; committed, **not pushed or merged**.
- **Date:** 2026-10-04
- **Layer:** cross-cutting (experiments)
- **Canon:** `[P§25]` (reproducibility metadata), `[P§29.5]` (reproducibility; no result valid without the full metadata schema), `[P§34]` (boundaries)
- **Supersedes / Superseded by:** —
- **Issue:** — (no issue opened; raised by owner review of EXP-20260930-01 and EXP-20261001-01..04)

## 1. Context

`docs/state/EXPERIMENTS.md` rule 4 says every run links to its config, dataset version and commit SHA, and that a run without them is void. In practice:

- All six ledger rows have `commit_sha` NULL (verified read-only, 2026-10-04).
- The sweep's prepare step wrote the commit SHA into the proposed rows. The execute step's upsert then overwrote every column with NULL (`cv_agent/experiments/sqlite_store.py`, `ON CONFLICT DO UPDATE`). The prepare-time value was lost.
- The baseline EXP-20260930-01 ran from code that was **not committed at run time**. The `yolo_eval` binding first appears in commit `8f29618`, which was committed five minutes after the run. No single commit reproduces it.
- The ledger file lived in the gitignored `.cv_agent/` and was lost when the working directory was replaced (see `docs/experiments/LEDGER-RECOVERY.md`).

## 2. Responsibility `[P§34]`

- **This owns:** answering "which committed code produced this evidence?", refusing to produce evidence from an uncommitted worktree, and guaranteeing that a stored `commit_sha` is not erased by a later write.
- **This does NOT own:**
  - job execution (execution layer, ADR-0009 / ADR-0013), which runs the job but does not record what produced it;
  - the record schema and storage (experiments layer, ADR-0011), which this ADR amends only for the write rule;
  - approval gating (`docs/APPROVALS.md`), which decides whether a run may happen at all.
- **Why this does not belong to an existing component:** provenance is a property of an `ExperimentRecord`. Execution cannot own it without recording experiment metadata. The ledger cannot own it without calling git. A module that only reads git and answers the question keeps both layers clean.

## 3. Decision

Add `cv_agent/experiments/provenance.py`, a read-only module with three functions. `current_commit(repo_root)` returns HEAD as a 40-character SHA. `dirty_entries(repo_root)` lists tracked changes and untracked, non-ignored files. `require_clean_worktree(repo_root)` returns HEAD's SHA, or raises `ProvenanceError` listing the dirty entries.

Every evidence-producing execute path calls `require_clean_worktree` **before** any GPU job starts, and passes the returned SHA as `ExperimentContext.commit`. This covers `scripts/run_threshold_sweep.py` (execute mode), `scripts/run_evaluation.py` and `scripts/run_baseline.py`.

The SQLite ledger's upsert treats `commit_sha` as write-once against NULL. A later write with `commit_sha = NULL` keeps the stored value (`COALESCE(excluded.commit_sha, experiments.commit_sha)`). A non-null incoming value still takes effect.

**No exception flag exists.** A dirty tree is refused. A run from uncommitted code cannot be reproduced from its record. If an exception is ever needed, it requires an owner decision recorded in `docs/state/DECISIONS.md` first, and this ADR is revised.

**Historical SHAs are never fabricated.** Existing rows are not edited. Inferred commits for past runs are recorded only as labelled inferences in EXPERIMENTS.md and LEDGER-RECOVERY.md, never in `commit_sha`.

**New evidence records must name their commit (owner decision, 2026-10-04).** The SQLite ledger rejects any record whose status is not `proposed` unless `commit_sha` is a 40-character lowercase SHA. The dataclass field stays optional, so the six historical rows (NULL, documented) still load. They are not rewritten.

**Ledger location (owner decision, 2026-10-04).** The default ledger is `<main checkout>/.cv_agent/experiments.sqlite`. It is resolved from the package location through `git rev-parse --git-common-dir`, never from the current directory, so every worktree of the repository maps to the same file. Scripts take their model, output and database paths from the same state root. Resolution fails closed outside a git repository. Opening the default ledger requires the file to exist unless the caller passes `create=True`, so a worktree cannot create an empty ledger. The persistence convention is unchanged: `.cv_agent/` is gitignored SQLite state (D-015).

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Record `HEAD` plus a `dirty:<diff sha256>` note and allow dirty runs | Runs can proceed during development | A dirty SHA does not identify the executed code. The baseline case shows the note would not have been enough to reproduce it. | Violates rule 4 ("reproducible or void"). Revisit only with an owner decision. |
| Add a `dirty` field to `ExperimentRecord` | Explicit schema | A schema change to the `[P§25]` model, larger than the problem | Not needed once dirty runs are refused. Deferred. |
| Make `commit_sha` a required field in the schema | Enforced at construction | Breaks reading the six existing rows, which have NULL | Partly adopted: enforced at the ledger write boundary for every non-proposed record. The dataclass field stays optional so historical rows load. |
| Git hook or CI to block commits of evidence | Automatic | Does not stop an unversioned local run | Out of scope; this ADR governs execution. |
| Commit the SQLite database | Durable across checkouts | Binary, unreviewable, against D-015 | Rejected (LEDGER-RECOVERY.md §3). |

## 5. Interface

```python
class ProvenanceError(RuntimeError): ...

def current_commit(repo_root: Path) -> str: ...
def dirty_entries(repo_root: Path) -> tuple[str, ...]: ...
def require_clean_worktree(repo_root: Path) -> str: ...
```

```python
def repository_state_root(start: Path | None = None) -> Path: ...   # main checkout's .cv_agent/
def default_db_path(workspace_root: Path | None = None) -> Path: ...  # state root unless workspace_root given
def open_ledger(*, workspace_root=None, db_path=None, create: bool = False) -> ExperimentLedger: ...
```

Ledger write rules: a non-`proposed` record requires a valid `commit_sha` (ExperimentLedgerError otherwise). The upsert assigns `commit_sha` as `COALESCE(excluded.commit_sha, experiments.commit_sha)`, so a later NULL cannot erase a stored SHA.

## 6. Consequences

- Evidence runs can only start from a clean, committed tree. The owner must commit reviewed changes before any GPU run.
- The six existing rows remain NULL. They are documented, not rewritten.
- A run from a linked worktree reads and writes the **main** checkout's ledger. Its evidence still records the worktree's HEAD, so the owner must commit before any evidence run.
- Opening a missing default ledger is an error with a clear message, not a silent creation.
- The provenance check is a guard, not a proof: it cannot detect a commit that later proves wrong. It does prevent the untracked-state case that caused the baseline gap.

## 7. Verification

- `tests/test_experiment_provenance.py`: clean repo returns HEAD; tracked modification, untracked file, and a non-repo are refused; gitignored state is not counted; the error lists at most ten entries.
- Ledger: a completed write with NULL commit keeps the prepared SHA (fails on the pre-fix code, verified); NULL-then-SHA records the SHA.
- The sweep execute path refuses before preflight (test, with the provenance function patched).
- `tests/test_ledger_path.py`: worktree maps to the main state root; the result does not depend on the current directory; a missing default ledger is refused and nothing is created; a run from a worktree reads the main ledger and creates nothing in the worktree; a non-repository fails closed.
- `tests/test_experiments.py`, `tests/test_baseline_wiring.py`: non-proposed records without a SHA are rejected.
