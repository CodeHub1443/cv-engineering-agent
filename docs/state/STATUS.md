# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-10-14 · **Phase:** 5e — owner decisions Q30/D-069 recorded; issue #76 (approval-gated training
pipeline, no GPU run) in progress on its own branch. Annotation review paused (47 of 63 labelled).
**Health:** Last recorded full suite: 1755 passed, 4 skipped (JOURNAL, 2026-10-04). Not re-run this session. The #75
code (failure_analysis, annotation_review) has no recorded run in JOURNAL.

## Where we are

Branch `feature/claude/76-training-execution-pipeline`, cut from `feature/claude/experiment-provenance-recovery`.
That branch is pushed; remote tip is f745afe (verified 2026-10-14). Neither branch is merged.

**Ledger: 10 records, unchanged** (sha256 `9251eb0c…8fef8fa`, full value in JOURNAL; integrity ok). No #75 row.

**Done:**
- **EXP-20261004-01..04** persisted (measurement only): `-01` (640, SELF), `-02` (960), `-03` (1280), `-04` (FP32 640
  control, baseline `-01`, mAP@0.5:0.95 0.518, FPS 81.9). Details: EXPERIMENTS.md.
  - **Approval deviation:** the `-04` approval record was documented **after** the GPU run; nothing claims otherwise.
  - A contaminated FP32 attempt is quarantined, **permanently not ledger-eligible.** ADR-0018 (D-075), D-076.
- **Failure analysis** (#75): report and code committed; read-only, no GPU run. `docs/experiments/FAILURE-ANALYSIS-EXP-20261004.md`.
- **Annotation-label review** (63 candidates): valid 34, annotation_error 5, ambiguous 8, **unlabelled 16** (ranks
  011, 013, 027 noted but unlabelled; 051–063 unreviewed). Single reviewer; sample **not representative**, no
  error rate claimed; crowd status `q27_unresolved`. Report: `docs/experiments/ANNOTATION-REVIEW-EXP-20261004-01.md`.

## Decisions recorded 2026-10-14 (D-077, D-078)

- **Q30 answered:** precision floor **0.75** at conf=**0.25**, IoU >= 0.5. Fixed-threshold only; never mAP.
- **D-069 answered:** a candidate must improve **both** overall AP@0.5:0.95 and small-person AP@0.5 and meet the floor.
- Full-curve AP (conf=0.001) and fixed-threshold P/R stay separate. Truncated conf=0.25 history is not comparable.
- **Provisional, not approved gates:** +0.010 overall (0.517 → 0.527), +0.020 small (0.3556 → 0.3756). Baseline
  matches EXP-20261004-01. Missing: run-to-run variance, FP16 vs FP32 baseline choice, delta rationale (Q32).
- Observation: only imgsz 640 clears the 0.75 floor in the recorded series (0.777; 960 is 0.727); headroom 0.027.

## Open (owner)

1. **Q32** — validity of the provisional AP deltas (variance, baseline precision, rationale).
2. **Q27** — official size-stratified mAP and crowd status need `instances_val2017.json`.
3. **Q31** — repository versus skill ownership of the trt-perf-analysis contract.
4. Labels for ranks 011, 013, 027; whether to review ranks 051–063; issue #74 and any further GPU series.

**Blockers:** none for #76 implementation. Any real training run waits on separate owner approval and Q32.

## Next actions

1. Implement #76 in small commits: typed job lifecycle, approval gate, provenance, fake-runtime tests.
2. Owner: review the #76 PR; answer Q32.
3. Owner: approve (or not) any real GPU training run separately; none is authorized.

## Do not start yet

Any GPU job without a fresh owner approval reference. Training. Model swaps (Q25). NMS or crowd experiments.
TensorRT, DeepStream, Model Optimizer. Stopping or controlling another project's processes.
Pushing or merging this branch without owner review.
