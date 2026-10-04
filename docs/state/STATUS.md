# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-10-04 · **Phase:** 5d — FP32 640 control: implementation under issue #74;
rerun gated on owner inputs · **Health:** green on repository tests (see JOURNAL for the last run)

## Where we are

Branch `feature/claude/experiment-provenance-recovery` (worktree `/home/dev/cv-engineering-agent-sweep`).
Committed on the branch. **Not pushed, not merged.**

**Done:**
- **EXP-20261004-01 series** persisted (measurement only): `-01` (640, SELF), `-02` (960), `-03` (1280),
  baseline `-01` for both. Commit `ab686f3`. Details: EXPERIMENTS.md.
- **Ledger: 9 rows.** No row written in this stage. SHA-256 of `experiments.sqlite` was `0d910b01…cfc1`
  before quarantine and is re-checked before any future write.
- **Issue #74** created (authorized). Scope: contaminated-run quarantine, GPU-process provenance,
  writer eligibility, FP32 control path. It is not closed.
- **Contaminated FP32 attempt quarantined** (rename, not copy): `/home/dev/cv-engineering-evidence/EXP-20261004-FP32-640/contaminated-concurrent-gpu/`.
  Contains the run directory, `run.json`, `val.log`, pre/post-move hashes, `MANIFEST.sha256` (15 files, verified),
  `CONTAMINATED.md`. Read-only. **Not ledger-eligible, permanently.** Its owner approval reference is consumed.
- **GPU-process provenance implemented:** `nvidia-smi --query-compute-apps` snapshots at start (must be
  empty), at every VRAM poll (own pid excluded), and at end, recorded in run.json. The wrapper refuses an
  unreadable or busy start. The writer rejects any run with a missing, unreadable or foreign snapshot,
  or a mismatched `foreign_process_seen`. The 1-second polling limit is documented.
- **ADR-0018:** Proposed, linked to #74. Not accepted.

**Interpretation:** unchanged from EXP-20261004-01 (descriptive only). No winner, no threshold.

## Open (owner)

1. **ADR-0018 acceptance.** Owner decision. Requires issue #74 linkage (done) and review of the implementation.
2. **Fresh approval reference** for the clean FP32 640 rerun. Not supplied; the agent does not invent one.
3. **D-069** (measurement-only scope for the next series) — answered for this control only; stays OPEN generally.
4. **Q30** — precision floor / operating point — "not yet", stays OPEN.
5. **Q31**, **Q27** — unchanged, OPEN.

## Blockers

- **Rerun blocked** until items 1 and 2 above are supplied and the gate in ADR-0018 §6 holds.
- **GPU busy:** another project's training job (`models/7_train_single_task.py --task lung`, pid 308159)
  was on the device at the last check. The agent does not stop or control it. The rerun waits for an idle GPU.

## Next actions (in order)

1. Owner: review ADR-0018 and supply a fresh approval reference, or ask for changes.
2. Agent: when the owner supplies both, re-run the gate in ADR-0018 §6 (clean tree, empty GPU process list,
   no concurrent workload), write the approval record to JOURNAL, then run the FP32 640 control.
3. Agent: after the run, dry-run the writer; write `EXP-20261004-04` only if the run is eligible.

## Do not start yet

Any GPU job without a fresh approval reference. Training. Model swaps (Q25). NMS or crowd experiments.
TensorRT, DeepStream, Model Optimizer. Stopping or controlling another project's processes. Pushing or
merging this branch without owner review.
