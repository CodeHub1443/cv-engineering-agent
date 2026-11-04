# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-30 · **Phase:** 5c — evaluation milestone COMPLETE ·
**Health:** green

## Where we are

D-043 evaluation milestone complete. yolo11n evaluated on COCO val2017 (5000 images,
truly held-out). EXP-20260930-01 written to ledger. Branch
`feature/claude/adr-0009-second-binding` ready for PR.

**EXP-20260929-01** — baseline (SELF): yolo11n + ByteTrack, RTX 3060, 2862 frames,
8.8ms inference/frame, 91% detection rate, val_metrics=NOT MEASURED (video-only baseline).

**EXP-20260930-01** — evaluation: yolo11n on COCO val2017, RTX 3060, 5000 images,
mAP@0.5:0.95=**0.459**, precision=0.791, recall=0.661, mAP@0.5=0.635,
FPS=99.9 e2e / 188.7 inf-only, VRAM peak=596 MiB.

1541 tests, 4 skipped. Ruff clean. Mypy clean. All new files linted.

## Completed this session (2026-09-30)

| D | Work |
|---|---|
| D-060 | `cv_agent/execution/jobs/runtimes/yolo_eval.py` — yolo-eval binding, `parse_metrics()` |
| D-061 | COCO val2017 selected as evaluation dataset; images downloaded + extracted |
| D-062 | EXP-20260930-01 — real mAP/FPS/VRAM metrics produced and written to ledger |
| Q26 | Opened: how to register standard benchmark datasets in DatasetManifest without pHash |

## Completed prior session (2026-09-29)

| D | Fix |
|---|---|
| D-058 | Pipe-buffer deadlock in `LinuxNvidiaJobRuntime` — drain threads in `start()` |
| D-059 | `open_ledger(DB_PATH)` → `open_ledger(db_path=DB_PATH)` + first real baseline |

## Next 3 actions

1. **Open PR** for `feature/claude/adr-0009-second-binding` (D-052 → D-062 inclusive)
2. **After merge:** close issue(s) for ADR-0009 second binding and D-043 eval milestone
3. **Next milestone:** tracking metrics (MOT metrics) require a labelled MOT dataset — open separate issue

## Blockers

- ANTHROPIC_API_KEY not set (FakeLLMProvider acceptable for current work)
- faster-coco-eval secondary check skipped (instances_val2017.json not downloaded); primary metrics are valid

## Do not start yet

Training, NAS, optimization, TensorRT, DeepStream, AgentState wiring for model
selection (requires ADR if shape changes), second LLM provider, embeddings/vector search `[P§34]`.
