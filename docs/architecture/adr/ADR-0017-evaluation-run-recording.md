# ADR-0017: Recording measured evaluation runs as ExperimentRecords

- **Status:** Proposed. Implemented on `feature/claude/experiment-provenance-recovery`. Owner acceptance is required before the first real evaluation run is recorded (CLAUDE.md §5).
- **Date:** 2026-10-04
- **Layer:** experiments (cross-cutting provenance, ADR-0016)
- **Canon:** `[P§25]` (reproducibility metadata), `[P§29.3]` (no claim without a quantitative comparison), `[P§29.5]` (no result valid without the full metadata), `[P§34]` (boundaries)
- **Supersedes / Superseded by:** —
- **Issue:** — (raised by the EXP-20261004-01 preparation review)

## 1. Context

EXP-20261004-01 measures YOLO11n at three image sizes (640, 960, 1280) on COCO val2017 at conf=0.001, with only the image size varying (measurement-only, D-069). Until now a finished `yolo val` run left only prediction files and console output. Nothing turned it into an ExperimentRecord, so those files were not evidence. Two rules also needed enforcing in code: a record must name the commit that produced it (ADR-0016), and mAP must be computed on a full PR curve (Q28, D-067).

## 2. Responsibility `[P§34]`

- **This owns:** turning a *verified* measured run directory into an ExperimentRecord, or refusing. It also owns the rule that nothing is recorded from an unverified, truncated, off-protocol or uncommitted run.
- **This does NOT own:**
  - running `yolo val`: the wrapper `scripts/run_yolo_val_measured.py` does, with the binding's argv builder (execution layer, ADR-0009);
  - the metric mathematics: `cv_agent/experiments/detection_metrics.py` (shared with the analysis CLI);
  - the record schema and storage: `ExperimentRecord` and the SQLite ledger (ADR-0011, ADR-0016);
  - approval: `docs/APPROVALS.md` decides whether a run may happen. The approval id is recorded, not checked here.
- **Why this does not belong to an existing component:** nothing existing turns artifacts into records. The ledger stores records but does not read run directories. The execution layer runs jobs but does not own experiment metadata. Splitting the metric math out keeps it reusable by the analysis CLI.

## 3. Decision

1. **Two entry points, one verifier.** The wrapper produces a run directory: `<project>/<name>/predictions.json`, `<project>/<name>.val.log` and `<project>/<name>.run.json`. The writer verifies that directory and records it. The writer never runs a model.
2. **Fail closed, all or nothing.** The writer verifies all three runs before touching the ledger. Any problem refuses the whole batch and lists every problem. A failed row would be terminal and would lock its experiment id, so a failed batch writes nothing.
3. **Measured values only.** A value that was not measured is absent or None, and the notes say so. Unmeasured fields are `gpu_hours`, `train_time`, `memory`, `power`, and `flops`. The ultralytics max-F1 precision and recall from the log are not recorded.
4. **Two metric kinds, kept apart.** Standard keys (`mAP@0.5`, `mAP@0.5:0.95`, `AP@0.5/<size>`) are full-curve at conf=0.001. Reference keys `fixed_thr@0.25/<name>` are fixed-threshold precision and recall, labelled reference-only and not an operating point (Q30 open). The prefix is the only separation; see `docs/EVALUATION.md`.
5. **Full-curve gate.** The writer refuses any predictions file whose lowest person score exceeds 0.002. Threshold-free AP and mAP are invalid on a truncated curve (Q28).
6. **Same code as the record.** The run's recorded commit must equal the writer's HEAD, and the tree must be clean (ADR-0016). Weights, data yaml and val list are hashed before the run and again at recording, so a swap between the two is refused.
7. **Series ids are owner-fixed.** 640 → `EXP-20261004-01` (baseline `SELF`, the new-protocol control). 960 → `EXP-20261004-02`, and 1280 → `EXP-20261004-03`, each with baseline `EXP-20261004-01`. Historical records are never modified; an existing id is refused.
8. **No schema change.** The record uses existing fields. Artifact paths, hashes and the confidence protocol go in `notes` as JSON. The `fixed_thr@` keys live in `val_metrics`.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Add `fixed_threshold_metrics` and `artifacts` fields to `ExperimentRecord` | Cleanest separation; queryable | A schema change to `[P§25]` needs its own decision; the six historical rows would need migration | The owner chose prefixed `val_metrics` keys (no schema change). Revisit if the schema is ever revised. |
| Write a `failed` row for an invalid run | Keeps a trace of the attempt | The terminal lock would burn the experiment id, and rerunning would need a new id | Owner chose all-or-nothing. A failed attempt is reported on stderr. |
| Run `yolo` through `JobExecutor` (ADR-0013) | VRAM sampling; the job boundary | More code and more tests; the job boundary records a `JobResult`, which is a different shape | Owner chose direct subprocess. VRAM is therefore not measured and is recorded as not measured. |
| Parse the log with `yolo_eval.parse_metrics` | No duplicated regex | The experiments layer would depend on the execution layer (CLAUDE.md §3.7) | Regexes mirror the ultralytics format here, so the experiments layer stays free of the execution layer. |

## 5. Interface

```python
class RecordError(Exception): problems: list[str]
@dataclass(frozen=True) class DatasetExpectation: images: int; gt_persons: int
@dataclass(frozen=True) class VerifiedRun: ...   # only verified runs; carries measured values and artifact hashes
def verify_run(run_dir: Path, *, imgsz: int, coco_root: Path, head_commit: str,
               dataset: DatasetExpectation = ...) -> VerifiedRun: ...
def build_record(run: VerifiedRun, *, exp_id: str, baseline_id: str, approval_ref: str) -> ExperimentRecord: ...
def preflight_new_ids(ledger, exp_ids: list[str]) -> None: ...
def write_records(ledger, records: list[ExperimentRecord]) -> list[str]: ...
```

## 6. Consequences

- Only a clean, committed tree can produce a recordable run. The owner commits reviewed changes before running.
- The three records can be written by a single command after all three verify. The ledger's own rules still apply.
- A failed batch leaves no trace in the ledger. The stderr listing and the run directories are the only record of the attempt.
- VRAM, GPU hours and power are not recorded. A future VRAM sampler is a separate, owner-approved change.

## 7. Verification

- `tests/test_evaluation_records.py` (35 tests): a complete record from a verified run; standard and reference metric keys kept apart; notes carrying artifact hashes; three series written with history untouched; a missing stratum omitted and noted; an existing id refused; a missing ledger not created; truncated, malformed, missing, non-zero-exit, off-protocol, wrong-commit, changed-weights, bad-log, dataset-mismatch and no-GPU-identity runs all refused; the wrapper's argv and its refusal on a dirty tree; an unapproved image size rejected.
- `tests/test_fixed_threshold_strata.py` continues to cover the shared metric code.
- No GPU run is part of the test suite.
