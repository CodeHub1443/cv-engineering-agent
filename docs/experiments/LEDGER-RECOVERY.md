# Experiment ledger recovery (Q29): findings and proposal

**Status:** investigation complete. **Recovery EXECUTED 2026-10-04 under owner approval** (§4a, Part 1 and Part 2). The Trash copy was not modified. The database was not committed. Persistence stays SQLite under `.cv_agent/` (gitignored, D-015).
**Owner:** Tanvir (decisions in §3 and §5). **Date:** 2026-10-04.

## 1. What happened (verified facts)

| Fact | Evidence |
|---|---|
| The whole repository directory was moved to Trash. | `~/.local/share/Trash/info/cv-engineering-agent.trashinfo`: `Path=/home/dev/cv-engineering-agent`, `DeletionDate=2026-10-04T15:53:12`. |
| A new repository directory was created 42 s later. | `stat -c %w /home/dev/cv-engineering-agent` = 15:53:54. Its `.git` also has a 15:53:54 birth time, and it still contains the `docs/claude/sweep-results-next-proposal` worktree registration. |
| The ledger went with the old directory because it is gitignored state, not versioned content. | `.gitignore`: `/.cv_agent/`, with the comment "Never Git-tracked — see OPEN_QUESTIONS.md Q15/D-015". |
| The repository's own code does not delete directories. | Search of `cv_agent/`, `scripts/` and `tests/` for `rmtree`, `os.remove`, `unlink(`, `shutil.move`, `send2trash`: no matches outside `tmp_path` use. |
| The trashed database is intact. | Trash path `files/cv-engineering-agent/.cv_agent/experiments.sqlite`: `PRAGMA integrity_check = ok`, 6 rows, `journal_mode = delete` (no WAL sidecar), sha256 `d7ff167e51b25054facf72893bd9148f895beee65d9703fa4ec1a59640804c19`. Last write 2026-10-02 08:26 local. |

**Who or what moved the directory is not determinable from the repository or from this session.**
The timestamps show a directory replacement, not an agent action.

## 2. Persistence convention, and what it implies

- **Design intent:** the ledger (and project memory) is local, durable, and gitignored
  (ADR-0011, D-015, Q15/Q16). It is not meant to be committed.
- **Consequence:** the only copy of the historical rows lives in the working directory. Nothing
  else in the repository reproduces it. A directory replacement loses it, which is exactly what happened.
- **Hazard (cwd-relative path):** `cv_agent/experiments/store.py::default_db_path()` resolves
  `Path.cwd()` when no root is given. A command run from a worktree (or any other directory)
  silently creates a new, empty `experiments.sqlite` there. The sweep script avoids this by
  using its own `REPO_ROOT`. The default does not.
- **Hazard (upsert):** `SqliteExperimentLedger.record_experiment` uses
  `INSERT … ON CONFLICT(exp_id) DO UPDATE SET <every column>=excluded.<column>`. A later write
  overwrites every field, including fields that were already populated.

## 3. Options (owner decision)

| Option | What it means | Assessment |
|---|---|---|
| **A. Restore only** | Copy the verified file to `<repo>/.cv_agent/experiments.sqlite`. | Matches D-015. A single local copy, so the same loss can recur. Minimum acceptable. |
| **B. Restore + verified backup outside the repo** (recommended) | A, plus a dated backup directory outside the repository, with a sha256 manifest. Also backs up the artifacts the records cite (§4 step 1). | Matches D-015 and survives a repo replacement. No change to the persistence convention. |
| **C. B + committed per-run JSON snapshot** | Export each row to `docs/experiments/records/<exp_id>.json` and commit it. | Gives git durability and cross-checkout reproducibility. **Changes the Q15/D-015 convention**, so it needs an owner decision. Recommended for the longer term. |
| D. Commit the `.sqlite` | Track the binary database in git. | **Not recommended.** It contradicts D-015, binary diffs are unreviewable, and it adds nothing that C would not. |
| E. Regenerate | Re-run the experiments to recreate rows. | **Not valid.** Re-running produces new evidence with new timestamps and new runs. It cannot recreate the historical rows (`created_at`, `approval_ref`, and the historical code state all differ). |

**Recommendation:** B now, after approval. Decide C separately, since it changes a convention.

## 4. Proposed recovery procedure (NOT EXECUTED; each step needs approval)

### 4a. Exact command (EXECUTED 2026-10-04 under owner approval)

The first half only copies and verifies. It does not touch the repository. The second half
restores, and runs only after the owner approves. Source checksums were recorded on 2026-10-04.

```bash
TRASH=/home/dev/.local/share/Trash/files/cv-engineering-agent/.cv_agent
REPO=/home/dev/cv-engineering-agent          # the main checkout, never a worktree
BK=/home/dev/cv-engineering-backups/ledger-20261004

# --- Part 1: copy and verify (no repository change) ---
mkdir -p "$BK"
cp -p "$TRASH/experiments.sqlite" "$BK/experiments.sqlite"          # copy, never mv
cp -a "$TRASH/models" "$BK/models"
cp -a "$TRASH/evaluations" "$BK/evaluations"
cp -a "$TRASH/baselines" "$BK/baselines"
( cd "$BK" && sha256sum experiments.sqlite models/yolo11n.pt \
    evaluations/coco-person-val.yaml \
    evaluations/eval-yolo11n-coco-val2017-20260930-2/predictions.json > MANIFEST.sha256 )
cat > "$BK/expected.sha256" <<'EOF'
d7ff167e51b25054facf72893bd9148f895beee65d9703fa4ec1a59640804c19  experiments.sqlite
0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1  models/yolo11n.pt
27d2702ad12452589014ea219ad1eac8b9298041fcd5dc4a055716a3df626c76  evaluations/coco-person-val.yaml
0fd16d1e2b921330f91158c9cabe0de42585c77f956daf4d111c192e0d674e75  evaluations/eval-yolo11n-coco-val2017-20260930-2/predictions.json
EOF
( cd "$BK" && sha256sum -c expected.sha256 )                        # every line must be OK
python3 - "$BK/experiments.sqlite" <<'PY'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
assert c.execute("pragma integrity_check").fetchone()[0] == "ok"
ids = [r[0] for r in c.execute("select exp_id from experiments order by exp_id")]
expected = ["EXP-20260929-01", "EXP-20260930-01", "EXP-20261001-01",
            "EXP-20261001-02", "EXP-20261001-03", "EXP-20261001-04"]
assert ids == expected, ids
print("ledger verified:", len(ids), "records")
PY

# --- Part 2: restore (ONLY after Part 1 prints all OK and the owner approves) ---
mkdir -p "$REPO/.cv_agent/models" "$REPO/.cv_agent/evaluations"
cp -p "$BK/experiments.sqlite" "$REPO/.cv_agent/experiments.sqlite"
cp -p "$BK/models/yolo11n.pt" "$REPO/.cv_agent/models/yolo11n.pt"
cp -a "$BK/evaluations/." "$REPO/.cv_agent/evaluations/"
( cd "$REPO/.cv_agent" && sha256sum -c "$BK/expected.sha256" )     # every restored file must be OK
git -C "$REPO" check-ignore -q .cv_agent/experiments.sqlite && echo "gitignored: OK"
```

Restore is by copy only. The Trash copy stays in place until the owner confirms. The
backed-up `baselines/` directory is kept only in the backup, not restored into the repository.

1. **Back up first, read-only.** Copy (never move) from the Trash to
   `/home/dev/cv-engineering-backups/ledger-20261004/` with `cp -p`:
   - `experiments.sqlite`
   - `evaluations/` (includes `predictions.json` for the baseline and each sweep point, and `coco-person-val.yaml`)
   - `baselines/` (the artifacts cited by EXP-20260929-01, the video tracking baseline)
   - `models/yolo11n.pt` (gitignored `*.pt`; not regenerable from this repo)
   Leave the Trash copy in place until steps 2–4 pass; the Trash can be emptied independently.
2. **Verify the backup.** sha256 must equal `d7ff167e…4c19`; `PRAGMA integrity_check` = `ok`;
   `SELECT exp_id FROM experiments` returns exactly the six ids (EXP-20260929-01,
   EXP-20260930-01, EXP-20261001-01..04). Write the manifest (sha256 of every copied file).
3. **Restore by copy** to `/home/dev/cv-engineering-agent/.cv_agent/` (the main checkout only,
   not a worktree), then re-verify the same checks on the restored file.
4. **Read-only check through the code path:** `open_ledger(db_path=…)` followed by `get_experiment`
   for each of the six ids. Do not call `record_experiment`.
5. **Record the restoration** in `JOURNAL.md` with the manifest hash. Do not add a ledger row for the restore itself.
6. **Only after 1–5 pass**, any new run may write to the ledger.

No step edits an existing row (Rule 1).

## 5. How `commit_sha` should be populated for future records

### 5.1 What went wrong, in code

- Prepare-mode (`scripts/run_threshold_sweep.py::_prepare_mode`) wrote proposed rows with
  `commit=_current_commit()` (correct).
- Execute-mode (`_run_one`) builds `ExperimentContext` **without** `commit`, so the completed
  record has `commit=None`.
- The upsert then overwrites the stored value with NULL. **The prepare-time SHA is therefore
  no longer in the database.** This is the mechanism behind all six NULL rows, and it is
  confirmed in code, not inferred.

### 5.2 What the historical SHAs can and cannot be

Do **not** fabricate these. Write them only as labelled inferences in the notes or in EXPERIMENTS.md.

- **Sweep EXP-20261001-01..04.** The sweep script was added in `1531344` (2026-10-01 14:21 +06),
  and no later commit exists on that branch. The execute run (2026-10-02) therefore most likely
  used `1531344`. **Inferred, unverified.** The working tree state at execution time is unknown, so it may have had uncommitted changes.
- **Baseline EXP-20260930-01.** Created 2026-09-30 14:05 +06. The `yolo_eval` binding and
  `scripts/run_evaluation.py` first appear in `8f29618`, committed 14:10 +06, five minutes
  **after** the run. The run therefore used code that was **not committed at run time**. No
  single commit reproduces it exactly. The nearest committed state, `6934bdb` (13:25 +06),
  does not contain the binding. **Inferred: `8f29618`, unverified.** The record must say "not
  reproducible from a single commit".

### 5.3 Rules for future records (R1–R3 implemented 2026-10-04; R4 needs an owner decision)

Status, on branch `docs/claude/sweep-results-next-proposal` (uncommitted, not merged):
R1, R2 and R3 are implemented, with tests, as ADR-0016 (`cv_agent/experiments/provenance.py`;
`scripts/run_threshold_sweep.py`, `scripts/run_evaluation.py`, `scripts/run_baseline.py`; the
`sqlite_store.py` upsert). R4 is not implemented.

- **R1 — refuse a dirty tree for evidence-bearing runs.** Before launching, capture
  `git rev-parse HEAD` and `git status --porcelain`. If the tree is dirty, refuse to run (fail
  closed). Alternative, if the owner prefers: record `commit=HEAD` plus a `dirty:<sha256 of
  git diff HEAD>` note. Recommended: refuse, because a dirty SHA is not reproducible.
- **R2 — pass the commit on every execute path** (`run_threshold_sweep`, `run_baseline`,
  `run_evaluation`, and any future `run_resolution_experiment`). Add a test that a completed
  record has a non-null `commit_sha`.
- **R3 — the upsert must not erase a stored value.** Change the update clause for `commit_sha`
  to `COALESCE(excluded.commit_sha, experiments.commit_sha)`, with a test. This fixes the mechanism in §5.1 without a schema change.
- **R4 — completed records require `commit_sha`** (validation in `ExperimentRecord`, or at the
  ledger boundary). Needs an owner decision because it changes the validity rule for writes.
- No schema change is required: `commit` already exists (stored as `commit_sha`).

## 6. Related hazards to fix at the same time

- Make the ledger path explicit everywhere. The cwd fallback creates silent empty ledgers.
  Propose: a script refuses to run when the expected ledger file is missing, rather than creating one.
- Worktrees have no `.cv_agent/`. Runs from a worktree must be pointed at the main checkout's
  ledger explicitly, or they write to an orphaned database.
- `baseline_id` of EXP-20260930-01 is `EXP-20260929-01`, not `SELF` (Rule 2). This cannot be
  changed in place; record it as a known deviation in EXPERIMENTS.md.

## 7. Owner decisions needed

1. Approve §4 (backup, verify, restore), or give an alternative.
2. Choose persistence: B alone, or B + C (committed per-run snapshot).
3. Choose R1 (refuse dirty tree, recommended) or the dirty-note alternative.
4. Approve R2–R4 as implementation work.
