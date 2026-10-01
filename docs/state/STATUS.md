# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-10-01 · **Phase:** 5d — confidence-threshold sweep prepared ·
**Health:** green (awaiting owner approval for GPU execution)

## Where we are

Confidence-threshold sweep (D-065, issue #72) prepared. 4 proposed ExperimentRecords
written to `.cv_agent/experiments.sqlite`. Exact `yolo val` commands printed below.
GPU experiments NOT started — awaiting explicit owner approval to run `--execute`.

**EXP-20260930-01** (baseline): yolo11n, COCO val2017, conf=0.25, precision=0.791,
recall=0.661, mAP@0.5:0.95=0.459, FPS=99.9, VRAM peak=596 MiB.

**EXP-20261001-01..04** (proposed): conf=0.10/0.15/0.25/0.50, same model/dataset/device.

1576 tests, 4 skipped. Ruff clean. Mypy clean.

## Open PRs

| Branch | PRs | Contents |
|---|---|---|
| `feature/claude/adr-0009-second-binding` | #69 | D-050–D-062: 4 eval bindings, EXP-20260929-01, EXP-20260930-01, pipe-buffer fix. 1541 tests. |
| `feature/claude/diagnosis-baseline` | #71 | D-063–D-064: ADR-0015, cv_agent/diagnosis/, 33 tests. (from main) |
| `feature/claude/conf-threshold-sweep` | (new — this branch) | D-065: scripts/run_threshold_sweep.py, 35 tests. (from #69 branch) |

## Next 3 actions

1. **Owner approval** to execute: `python3 scripts/run_threshold_sweep.py --execute`
2. **After execution:** update EXPERIMENTS.md with completed rows (conf 0.10/0.15/0.25/0.50)
3. **PR:** open PR for `feature/claude/conf-threshold-sweep` → merge order: #69 first, then #71 (from main), then this branch

## Blockers

- GPU execution awaiting owner approval (docs/APPROVALS.md — GPU eval run)
- ANTHROPIC_API_KEY not set (FakeLLMProvider acceptable for current work)
- PR merge order: this branch needs #69 merged to main first (depends on yolo_eval.py)

## Do not start yet

Training, NAS, optimization, TensorRT, DeepStream, model changes, second LLM provider,
embeddings/vector search `[P§34]`.
