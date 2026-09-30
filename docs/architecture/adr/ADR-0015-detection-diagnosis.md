# ADR-0015 — Detection Diagnosis: Evidence Collection from Evaluation Artifacts

**Status:** accepted  
**Date:** 2026-09-30  
**Issue:** #70  
**Supersedes:** —  
**Canon:** `[P§29.1]`, `[P§29.3]`, `[P§11]`, `[P§34]`

---

## 1. Problem statement `[P§29.1]`

EXP-20260930-01 produced top-line metrics (precision=0.791, recall=0.661,
mAP@0.5:0.95=0.459) but no structured failure-mode evidence. Before proposing
any optimization — threshold change, resolution increase, model swap — the agent
must be able to answer: *which failure modes are measurably present, and in what
proportion?* A proposal grounded only in top-line aggregate metrics violates
`[P§29.3]` (no improvement claim without quantitative comparison) and `[P§29.1]`
(problem must be characterized before a solution is proposed).

**Baseline measured evidence (EXP-20260930-01, 2026-09-30):**
- 9,297 person predictions; 10,777 GT persons
- 161 images with GT persons but zero predictions ("completely missed images")
- 344 GT persons in completely-missed images (3.2% of all GT)
- Of those: 63.4% are small (normalized bbox area < 0.0025)
- GT size distribution: small=24%, medium=34%, large=42%
- Prediction confidence distribution: 17.5% in 0.25–0.35 band (near-threshold)
- High-density images (>5 GT persons): 677 images, 63.7% of all GT persons

These facts are measurable from `predictions.json` and the YOLO-format GT label
files already on disk. No new downloads, no model re-runs, and no LLM are needed
to collect them.

## 2. Boundary question `[P§34]`

**What responsibility does `cv_agent/diagnosis/` own, and why does it not belong
to an existing layer?**

- **Knowledge layer** (`cv_agent/knowledge/`) stores literature-based claims about
  models and datasets, sourced from external URLs with provenance tracking. It does
  not read prediction files or GT label files.
- **Experiment layer** (`cv_agent/experiments/`) stores structured experiment
  records (ExperimentRecord). It stores *what was measured* but does not analyse
  artifacts to *discover failure modes*.
- **Execution layer** (`cv_agent/execution/`) governs how skills are invoked. It
  does not interpret outputs.
- **Model selection layer** (`cv_agent/model_selection/`) builds evidence-based
  comparisons of candidates. It consumes KnowledgeItems, not on-disk prediction
  artifacts.

None of these own the responsibility: *read evaluation artifacts from disk, compute
measurable failure-mode statistics, and return them as typed, deterministic evidence.*

`cv_agent/diagnosis/` owns exactly this and nothing else.

**It does NOT own:**
- LLM-based synthesis or explanation (that is the reasoning layer)
- Optimization decisions (that is the human + model-selection layer)
- Experiment record creation (that is experiment_wiring + ExperimentLedger)
- Job execution (that is the execution layer)

## 3. Design

### 3.1 Module structure

```
cv_agent/diagnosis/
  __init__.py
  models.py          — DetectionEvidence (frozen dataclass, fail-closed)
  evidence_collector.py — collect_detection_evidence() pure function
```

### 3.2 `DetectionEvidence`

A frozen dataclass of **measured facts only** — no conclusions, no LLM text.
Every field is either directly counted or directly derived from `predictions.json`
and GT label `.txt` files.

```python
@dataclass(frozen=True)
class DetectionEvidence:
    # Provenance
    predictions_path: str
    labels_dir: str

    # Counts
    total_gt_persons: int
    total_predictions: int
    images_with_gt: int
    images_with_predictions: int
    images_completely_missed: int
    gt_persons_in_missed_images: int

    # GT size breakdown (normalized bbox area thresholds per §4)
    gt_small: int      # area < 0.0025
    gt_medium: int     # 0.0025 <= area < 0.023
    gt_large: int      # area >= 0.023

    # Prediction size breakdown (pixel area, approximate)
    pred_small: int    # pixel area < 1024
    pred_medium: int   # 1024 <= area < 9216
    pred_large: int    # area >= 9216

    # Prediction confidence bands
    pred_conf_025_035: int
    pred_conf_035_050: int
    pred_conf_050_070: int
    pred_conf_070_090: int
    pred_conf_090_100: int

    # Derived ratios (computed, not invented)
    small_fraction_in_missed: float  # fraction of missed-image GT that are small
    high_density_image_count: int    # images with > 5 GT persons
    high_density_gt_fraction: float  # fraction of all GT in those images
```

### 3.3 `collect_detection_evidence(predictions_path, labels_dir, person_category_id)`

Pure function. Deterministic given the same files. No side effects.

- Reads `predictions.json` (COCO format: list of `{image_id, file_name, category_id, bbox, score}`)
- Reads all `.txt` files in `labels_dir` (YOLO format: `class_id cx cy w h` per line)
- Filters predictions to `person_category_id` (default: 1 for COCO)
- Filters GT to class 0 (person in YOLO format)
- Computes all `DetectionEvidence` fields
- Returns `DetectionEvidence`

**Failure modes:**
- Missing predictions file or labels dir → `FileNotFoundError`
- Malformed GT line → skipped with a counter; if all lines malformed → `ValueError`
- Empty predictions (all filtered out) → `DetectionEvidence` with zero counts
  (not an error — some eval runs genuinely produce no predictions above threshold)

### 3.4 Size thresholds

GT labels are in YOLO normalized format (cx, cy, w, h ∈ [0,1]). Normalized area = w×h.

COCO's canonical thresholds at 640×480 (most COCO images):
- small: 32²/(640×480) ≈ 0.0033 → rounded to 0.0025 for normalized units
- medium: 32²–96²px → 0.0025–0.023 normalized
- large: ≥ 96²px → ≥ 0.023 normalized

These thresholds deliberately approximate COCO's pixel-area thresholds without
requiring image dimension metadata. The approximation is documented here, not hidden.

Prediction sizes use pixel area from `predictions.json` bbox `[x, y, w, h]`:
- small: w×h < 1024 (< 32²)
- medium: 1024 ≤ w×h < 9216 (32²–96²)
- large: w×h ≥ 9216 (≥ 96²)

## 4. What this ADR does NOT change

- `ExperimentRecord` schema — diagnosis results are stored in `notes` or in a
  separate evidence file, not as new `ExperimentRecord` fields. Extending the
  schema requires a schema decision (new ADR or explicit owner decision).
- `ExperimentLedger` — not modified. The ledger stores experiment records, not
  diagnostic evidence files. Evidence files live next to artifacts on disk.
- Job/execution boundary — the diagnosis module is NOT a skill binding. It is
  called directly from scripts, not via `JobExecutor`.
- Approval gate — `collect_detection_evidence()` is read-only, local, and
  deterministic → `docs/APPROVALS.md` "Read-only research, retrieval, analysis → ✅ free"

## 5. Limitations documented at this boundary

1. **No IoU-level TP/FP/FN breakdown**: requires image dimensions to denormalize GT
   or `instances_val2017.json`. Both are absent. TP/FP/FN ratios are derived
   approximations from the reported precision/recall, not measured directly per-prediction.

2. **No size-stratified mAP (small/medium/large sub-mAP)**: requires COCO API +
   `instances_val2017.json`. Absent. Filed as Q27.

3. **No occlusion/crowd analysis**: requires `instances_val2017.json` for iscrowd
   flags. Absent.

4. **Non-person prediction FP analysis**: predictions.json contains 17,583 non-person
   predictions. These do NOT contribute to person mAP (eval filters to category_id=1)
   but represent additional model output. No further analysis without re-running with
   richer logging.

## 6. Open questions

- **Q27**: Size-stratified mAP (small/medium/large) requires downloading
  `instances_val2017.json` (~250 MB). Is this worth doing before the next
  optimization experiment? (Filed in OPEN_QUESTIONS.md.)

## 7. Proposed next experiment (evidence-backed, not yet authorized)

Based on `DetectionEvidence` from EXP-20260930-01:

**Experiment: confidence threshold sweep**
- Hypothesis: lower confidence threshold recovers persons missed at conf=0.25,
  moving up the precision-recall curve.
- Evidence: 17.5% of person predictions (1,623/9,297) are in the 0.25–0.35 band.
  This is a relatively dense population near the threshold. There are likely
  additional predictions just below 0.25 that would recover FNs.
- Protocol: run `yolo val` at conf ∈ {0.1, 0.15, 0.25, 0.50} on COCO val2017
  (same model, same dataset). Four `yolo val` invocations, each ≈50s.
- Expected outcome: recall increases as conf decreases; precision decreases.
  Identifies the optimal operating point for the target use case.
- Why smallest: no model change, no training, no new data. Uses the existing
  evaluation binding (D-060) and dataset. Cost: ~4 × 50s GPU time.
- Authorization required: owner approval per `docs/APPROVALS.md` (evaluation run,
  GPU compute).

This experiment is PROPOSED here. It is not started in this ADR's scope.
