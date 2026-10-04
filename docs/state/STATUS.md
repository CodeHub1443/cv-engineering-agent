# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-10-04 · **Phase:** 5d — record-writing path for EXP-20261004-01 built and tested;
**no GPU run** · **Health:** green on repository tests; amber on experiment readiness

## Where we are

Branch `feature/claude/experiment-provenance-recovery` (worktree `/home/dev/cv-engineering-agent-sweep`).
Committed on the branch; **not pushed, not merged.**

**Done:**
- **Record-writing path (ADR-0017, proposed):** `cv_agent/experiments/evaluation_records.py` verifies a
  measured run directory and builds an ExperimentRecord, or refuses. Writes are all-or-nothing.
  `cv_agent/experiments/detection_metrics.py` holds the shared metric math.
- **Wrapper and writer:** `scripts/run_yolo_val_measured.py --imgsz N` (one `yolo val` run, refuses a
  dirty tree and overwriting) and `scripts/record_evaluation_runs.py` (verify three runs, dry-run or write).
- **Ledger, provenance, path, Q28 protocol:** unchanged from the previous session (ADR-0016, Q29 recovered).

**Validation:** full pytest **1688 passed, 4 skipped, 0 failed** (35 new record-writer tests).
`ruff check .` clean. `mypy cv_agent` clean (81 files). New scripts and tests clean.

## Next (owner)

1. **Accept ADR-0017** (recording boundary) before the first real run.
2. **Approve the GPU run** for EXP-20261004-01 with an approval id, and only then run the wrapper three times.
3. Review the record output with `--dry-run` before writing.
4. Q30, Q31, Q27 and D-069 stay OPEN and are not needed for the measurement.

## Blockers

- The writer has been tested only on synthetic runs. The first real run is the first end-to-end check.
- VRAM, GPU hours and power are not measured for this series.
- Six historical rows keep NULL `commit_sha` (no SHA fabricated).

## Do not start yet

EXP-20261004-01 execution before owner approval and ADR-0017 acceptance. Training. Model swaps (Q25).
NMS or crowd experiments. Any precision floor, recall target, or operating point (Q30). TensorRT,
DeepStream, Model Optimizer. Pushing or merging this branch without owner review.
