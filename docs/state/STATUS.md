# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-10-04 · **Phase:** 5d — EXP-20261004-01 series completed and persisted
(measurement only); documentation reconciled · **Health:** green on repository tests; open
decisions remain (see below)

## Where we are

Branch `feature/claude/experiment-provenance-recovery` (worktree `/home/dev/cv-engineering-agent-sweep`).
Committed on the branch. **Not pushed, not merged.**

**Done:**
- **EXP-20261004-01 series persisted** (measurement only; no pass/fail decision):
  - `EXP-20261004-01` (imgsz 640, baseline SELF), `EXP-20261004-02` (960), `EXP-20261004-03` (1280, both baseline `EXP-20261004-01`).
  - YOLO11n / COCO val2017 / GPU 0 / batch 1 / conf 0.001 / `quantize=16` (FP16 requested, not measured).
  - Approval `EXP-20261004-01-OWNER-20261004`; commit `ab686f3`.
  - mAP@0.5:0.95 = 0.517 / 0.532 / 0.489.
  - Details and exact values: EXPERIMENTS.md, "EXP-20261004-01 series — completed".
- **Attempt-1 evidence archived**, not ledgered: `/home/dev/cv-engineering-evidence/EXP-20261004-01/attempt1-commit-8f9baaa/`. 45/45 checksums OK, read-only.
- **Ledger:** nine records. The six historical records are unchanged.
- **ADR-0017:** Accepted (D-073).

**Interpretation (descriptive only):** 960 has the highest mAP@0.5:0.95 of the three; 1280 is lower.
Small-object AP rises with size (0.356 → 0.459 → 0.483). Medium AP is non-monotonic. Large AP falls
monotonically. Throughput falls with size. **No production winner is declared, and no success threshold
is set.**

## Open (owner)

1. **D-069** — whether any AP change should drive a decision. Still OPEN.
2. **Q30** — operating point and precision target. Still OPEN. Needed before any production choice.
3. **Q31** — repository versus skill ownership of the trt-perf-analysis contract. Still OPEN.
4. **Q27** — official size-stratified mAP needs `instances_val2017.json`. Still OPEN.

## Blockers

None for the repository. Any production or optimization decision waits on Q30 and D-069.

## Do not start yet

New GPU experiments without an owner approval reference. Training. Model swaps (Q25). NMS or crowd
experiments. TensorRT, DeepStream, Model Optimizer. Pushing or merging this branch without owner review.
