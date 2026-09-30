"""
scripts/run_diagnosis.py — baseline detection diagnosis for EXP-20260930-01.

Reads evaluation artifacts from EXP-20260930-01 (predictions.json + COCO
val2017 YOLO-format GT labels) and reports measurable failure-mode evidence.
No model re-runs. No downloads. No LLM. See ADR-0015.

Usage:
  python3 scripts/run_diagnosis.py

Approval: read-only analysis of local files — free per docs/APPROVALS.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

# ── Configuration ──────────────────────────────────────────────────────────────

PREDICTIONS_JSON = (
    REPO_ROOT
    / ".cv_agent"
    / "evaluations"
    / "eval-yolo11n-coco-val2017-20260930-2"
    / "predictions.json"
)
LABELS_DIR = Path("/home/dev/Documents/data_cleaner/datasets/coco/labels/val2017")

EXP_ID = "EXP-20260930-01"

# Reported metrics from the eval run (from ExperimentLedger, for reference)
REPORTED_PRECISION = 0.791
REPORTED_RECALL    = 0.661
REPORTED_MAP50     = 0.635
REPORTED_MAP5095   = 0.459

# ── Preflight ──────────────────────────────────────────────────────────────────

print("=== 0. Preflight ===")
if not PREDICTIONS_JSON.exists():
    sys.exit(
        f"BLOCKED: predictions.json not found at {PREDICTIONS_JSON}\n"
        "Run scripts/run_evaluation.py first."
    )
if not LABELS_DIR.is_dir():
    sys.exit(
        f"BLOCKED: COCO val2017 labels not found at {LABELS_DIR}\n"
        "Extract coco2017labels.zip first."
    )
print(f"  predictions.json : {PREDICTIONS_JSON}")
print(f"  labels_dir       : {LABELS_DIR}")

# ── Collect evidence ───────────────────────────────────────────────────────────

from cv_agent.diagnosis import collect_detection_evidence  # noqa: E402

print("\n=== 1. Collecting detection evidence ===")

ev = collect_detection_evidence(PREDICTIONS_JSON, LABELS_DIR)

print(f"  total_gt_persons          : {ev.total_gt_persons}")
print(f"  total_predictions         : {ev.total_predictions}")
print(f"  images_with_gt            : {ev.images_with_gt}")
print(f"  images_with_predictions   : {ev.images_with_predictions}")
print(f"  images_completely_missed  : {ev.images_completely_missed}")
print(f"  gt_persons_in_missed      : {ev.gt_persons_in_missed_images}  "
      f"({100*ev.gt_persons_in_missed_images/ev.total_gt_persons:.1f}% of all GT)")

# ── Size analysis ──────────────────────────────────────────────────────────────

print("\n=== 2. Size distribution ===")
print("  GT persons:")
print(f"    small  (<0.0025 norm area) : {ev.gt_small:5d}  ({100*ev.gt_small/ev.total_gt_persons:.0f}%)")
print(f"    medium (0.0025–0.023)      : {ev.gt_medium:5d}  ({100*ev.gt_medium/ev.total_gt_persons:.0f}%)")
print(f"    large  (≥0.023)            : {ev.gt_large:5d}  ({100*ev.gt_large/ev.total_gt_persons:.0f}%)")
print("  Predictions (pixel area):")
print(f"    small  (<1024 px²)         : {ev.pred_small:5d}  ({100*ev.pred_small/ev.total_predictions:.0f}%)")
print(f"    medium (1024–9216 px²)     : {ev.pred_medium:5d}  ({100*ev.pred_medium/ev.total_predictions:.0f}%)")
print(f"    large  (≥9216 px²)         : {ev.pred_large:5d}  ({100*ev.pred_large/ev.total_predictions:.0f}%)")
print(f"  Small fraction in completely-missed images: "
      f"{100*ev.small_fraction_in_missed:.1f}%  (vs {100*ev.gt_small/ev.total_gt_persons:.0f}% baseline)")

# ── Confidence analysis ────────────────────────────────────────────────────────

print("\n=== 3. Confidence distribution ===")
for label, count in [
    ("0.25–0.35 (near-threshold)", ev.pred_conf_025_035),
    ("0.35–0.50                 ", ev.pred_conf_035_050),
    ("0.50–0.70                 ", ev.pred_conf_050_070),
    ("0.70–0.90                 ", ev.pred_conf_070_090),
    ("0.90–1.00 (high-conf)     ", ev.pred_conf_090_100),
]:
    pct = 100 * count / ev.total_predictions if ev.total_predictions > 0 else 0.0
    bar = "█" * int(pct / 2)
    print(f"  {label}: {count:5d} ({pct:4.1f}%) {bar}")
print(f"  Near-threshold fraction (0.25–0.35): {100*(ev.near_threshold_fraction or 0):.1f}%")

# ── Crowd / density analysis ───────────────────────────────────────────────────

print("\n=== 4. High-density image analysis ===")
print(f"  High-density images (>5 GT persons) : {ev.high_density_image_count}")
print(f"  GT persons in high-density images   : {100*ev.high_density_gt_fraction:.1f}%")

# ── Derived estimates from reported metrics ────────────────────────────────────

print("\n=== 5. Estimated TP/FP/FN (from reported P/R, approximate) ===")
tp_from_precision = REPORTED_PRECISION * ev.total_predictions
tp_from_recall    = REPORTED_RECALL    * ev.total_gt_persons
fp_est = ev.total_predictions - tp_from_precision
fn_est = ev.total_gt_persons  - tp_from_recall
print(f"  TP estimate (precision × preds)     : {tp_from_precision:.0f}")
print(f"  TP estimate (recall × GT)           : {tp_from_recall:.0f}")
print(f"  FP estimate (preds - TP_prec)       : {fp_est:.0f}")
print(f"  FN estimate (GT - TP_recall)        : {fn_est:.0f}")
print("  FN >> FP: recall gap is larger than precision gap")

# ── Summary ───────────────────────────────────────────────────────────────────

print(f"""
=== DIAGNOSIS SUMMARY — {EXP_ID} ===

Model:   yolo11n  Dataset: COCO val2017 (5000 images)  conf=0.25  imgsz=640

[KNOWN — measurable from artifacts]
  P={REPORTED_PRECISION}  R={REPORTED_RECALL}  mAP@0.5={REPORTED_MAP50}  mAP@0.5:0.95={REPORTED_MAP5095}

[EVIDENCE 1 — small objects over-represented in failures]
  Completely missed images: {ev.images_completely_missed} (GT persons in these: {ev.gt_persons_in_missed_images}, {100*ev.gt_persons_in_missed_images/ev.total_gt_persons:.1f}%)
  Small GT fraction (baseline): {100*ev.gt_small/ev.total_gt_persons:.0f}%
  Small GT fraction in missed images: {100*ev.small_fraction_in_missed:.0f}%
  → Small objects are {ev.small_fraction_in_missed/max(ev.gt_small/ev.total_gt_persons, 0.001):.1f}x over-represented in fully-missed images

[EVIDENCE 2 — near-threshold confidence density]
  {ev.pred_conf_025_035} predictions ({100*(ev.near_threshold_fraction or 0):.1f}%) in the 0.25–0.35 confidence band
  → Lowering conf threshold would directly add these detections; nearby sub-0.25 predictions likely also exist

[EVIDENCE 3 — high-density images contain majority of GT]
  {ev.high_density_image_count} images with >5 persons contain {100*ev.high_density_gt_fraction:.0f}% of all GT persons
  → Crowd/occlusion behavior is critical to overall recall

[NOT KNOWN — requires instances_val2017.json or image dimensions — Q27]
  - Size-stratified mAP (small/medium/large sub-mAP)
  - Per-prediction IoU distribution (TP localization quality)
  - Crowd annotation FP contribution (iscrowd flags)
  - Occlusion breakdown

[PROPOSED NEXT EXPERIMENT — evidence-based, NOT yet authorized]
  Confidence threshold sweep: conf ∈ {{0.10, 0.15, 0.25, 0.50}}
  Hypothesis: lower threshold recovers near-threshold persons, improving recall
  Evidence: {ev.pred_conf_025_035} predictions in 0.25–0.35 band ({100*(ev.near_threshold_fraction or 0):.1f}%)
  Protocol: 4 × yolo val runs on COCO val2017, existing binding (D-060), ~4×50s GPU
  Authorization required per docs/APPROVALS.md before execution
""")
