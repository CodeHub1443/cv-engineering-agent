# ADR-0018: FP32 control for the image-size series (precision as the only variable)

- **Status:** Proposed (2026-10-04). Implemented to run the one owner-approved FP32 640 control. Committed on the branch, not pushed or merged. Acceptance does not approve any GPU run; each run needs its own owner approval reference (ADR-0017 §3b).
- **Date:** 2026-10-04
- **Layer:** experiments (provenance and recording, ADR-0016, ADR-0017)
- **Canon:** `[P§25]` (reproducibility metadata), `[P§29.2]` (baseline discipline), `[P§29.3]` (no claim without a quantitative comparison), `[P§29.5]` (metadata completeness)
- **Supersedes / Superseded by:** — (amends ADR-0017 §3a, which fixed the protocol to FP16)
- **Issue:** — (owner-directed measurement; no GitHub issue exists for this control. Recorded here, not hidden.)

## 1. Context

EXP-20261004-01 records FP16 requested (`quantize=16`) at conf=0.001. The historical records (EXP-20260930-01 and the sweep rows) ran FP32 at conf=0.25. The two differ in both precision and conf, so no record isolates the precision effect. EVALUATION.md requires a re-measurement before any optimization (quantization) is accepted, and the FP16 accuracy cost is therefore unmeasured.

## 2. Responsibility `[P§34]`

- **This owns:** the rule that one additional measured run, FP32 at imgsz 640 on the same protocol as EXP-20261004-01, is recorded as its own ExperimentRecord. It also owns the protocol difference between the two precisions (`quantize` set or unset) and the requested-precision label for each.
- **This does NOT own:** whether any precision choice is good (Q30, open; no pass/fail, D-069); running `yolo val` (the wrapper, ADR-0017 §4a); the metric mathematics or the record schema (unchanged).
- **Why not an existing component:** ADR-0017 fixes one precision for one series. A separate control with its own id and protocol is an amendment of that fixed protocol, not a new series.

## 3. Decision

1. **Scope.** One control run: YOLO11n, COCO val2017 persons, imgsz 640, conf 0.001, batch 1, device 0, classes [0], `quantize` unset (FP32). Only the precision differs from EXP-20261004-01.
2. **Protocol.** `quantize` is not passed, so ultralytics uses its default `None` (`fp16=False`). The wrapper accepts `--precision fp32` only at imgsz 640. Any other size is refused before the git check.
3. **Label.** `precision_requested` is `FP32 requested (quantize unset; ultralytics default None, fp16=False); actual inference precision is not logged`. As in ADR-0017 §3a, the label records the request, not a measurement.
4. **Identity.** Experiment id `EXP-20261004-04`, baseline `EXP-20261004-01` (the FP16 640 record, the like-for-like comparison). Run name carries a `-fp32` suffix so it cannot collide with the FP16 run directory.
5. **Approval.** The run and the record each carry the owner approval reference, given exactly as the owner provided it. The writer requires the run's reference to equal `--approval-ref`. No reference is chosen or substituted by the agent.
6. **Measurement only (D-069).** No pass/fail threshold and no production selection. The record's notes say so.
7. **Verification.** The FP32 run is verified under the FP32 protocol (`quantize` must be unset). An FP16 run is refused under that protocol, and an FP32 run is refused under the FP16 protocol. Everything else in ADR-0017 §3 and §5 applies unchanged.
8. **Writer.** `scripts/record_evaluation_runs.py --fp32-control <run dir> --approval-ref <ref>` records one run. The three-run series mode is unchanged.

## 4. Alternatives considered

| Alternative | Why not chosen |
|---|---|
| Re-run FP16 at 640 with a new id and compare | Does not isolate precision; it only repeats EXP-20261004-01. |
| Put the FP32 run into the EXP-20261004-01 series | The series ids are owner-fixed and the series is written as one batch. Adding a fourth member would change the approved batch. |
| Change the precision of EXP-20260930-01 or the sweep rows | Historical rows are never edited (ADR-0016). |

## 5. Consequences

- The FP32 640 record can be compared with EXP-20261004-01 on precision alone, at identical conf and protocol. It can still not be compared with EXP-20260930-01 on mAP, because that record used conf=0.25.
- The FP32 control does not decide whether FP16 is acceptable. Q30 remains open.
- The control adds one new id (`EXP-20261004-04`) and one new run directory. No existing row or run is changed.

## 6. Verification

- `tests/test_evaluation_records.py`: 86 tests, including the FP32 control verification and label, FP16 refused under the FP32 protocol and FP32 refused under the FP16 protocol, argv without `quantize`, the `-fp32` run name, refusal of FP32 at sizes other than 640 before the git check, and the writer's control dry run and approval refusal.
- No GPU run is part of the test suite.
