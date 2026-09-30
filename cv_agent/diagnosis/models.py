"""
cv_agent.diagnosis.models — DetectionEvidence: measured facts only.

All fields are directly counted or directly derived from predictions.json and
YOLO-format GT label files. No LLM-generated text. No invented metrics.
See ADR-0015 §3.2 and §3.4 for size threshold rationale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _require_nonneg_int(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative int, got {value!r}")


def _require_nonneg_float(value: float, field: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field} must be a number, got {value!r}")
    if not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"{field} must be a finite non-negative float, got {value!r}")


def _require_nonblank(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-blank string, got {value!r}")


@dataclass(frozen=True)
class DetectionEvidence:
    """
    Measured facts from a detection evaluation run's artifacts.

    All fields are counts or ratios computed deterministically from
    predictions.json and YOLO-format GT label files. Nothing is invented or
    LLM-inferred. See ADR-0015 §3.2 for field definitions and §3.4 for the
    size threshold rationale.

    Limitations (documented in ADR-0015 §5):
    - No per-prediction TP/FP/FN (requires image dims or instances_val2017.json)
    - No size-stratified mAP (requires COCO API + instances_val2017.json)
    - No crowd/occlusion breakdown (requires instances_val2017.json iscrowd flags)
    """

    # ── Provenance ────────────────────────────────────────────────────────────
    predictions_path: str
    labels_dir: str

    # ── Raw counts ────────────────────────────────────────────────────────────
    total_gt_persons: int
    """Total person annotations in the GT label files (YOLO class 0)."""
    total_predictions: int
    """Total predictions that match person_category_id at or above the eval conf."""
    images_with_gt: int
    """Images that have at least one GT person annotation."""
    images_with_predictions: int
    """Images that have at least one person prediction at or above eval conf."""
    images_completely_missed: int
    """Images with GT persons but zero person predictions at eval conf."""
    gt_persons_in_missed_images: int
    """GT person count in completely-missed images."""

    # ── GT size breakdown (normalized bbox area, see ADR-0015 §3.4) ──────────
    gt_small: int
    """GT persons with normalized area < 0.0025 (approx COCO small, <32² at 640px)."""
    gt_medium: int
    """GT persons with 0.0025 ≤ normalized area < 0.023 (approx COCO medium)."""
    gt_large: int
    """GT persons with normalized area ≥ 0.023 (approx COCO large, ≥96² at 640px)."""

    # ── Prediction size breakdown (pixel area from predictions.json bbox) ─────
    pred_small: int
    """Person predictions with pixel bbox area < 1024 (< 32² px)."""
    pred_medium: int
    """Person predictions with 1024 ≤ pixel bbox area < 9216 (32²–96² px)."""
    pred_large: int
    """Person predictions with pixel bbox area ≥ 9216 (≥ 96² px)."""

    # ── Prediction confidence distribution (bands) ────────────────────────────
    pred_conf_025_035: int
    """Person predictions with confidence in [0.25, 0.35)."""
    pred_conf_035_050: int
    """Person predictions with confidence in [0.35, 0.50)."""
    pred_conf_050_070: int
    """Person predictions with confidence in [0.50, 0.70)."""
    pred_conf_070_090: int
    """Person predictions with confidence in [0.70, 0.90)."""
    pred_conf_090_100: int
    """Person predictions with confidence in [0.90, 1.00]."""

    # ── Derived ratios ────────────────────────────────────────────────────────
    small_fraction_in_missed: float
    """Fraction of GT persons in completely-missed images that are small (area < 0.0025).
    0.0 if images_completely_missed == 0."""
    high_density_image_count: int
    """Images with more than 5 GT persons."""
    high_density_gt_fraction: float
    """Fraction of all GT persons that are in high-density images.
    0.0 if total_gt_persons == 0."""

    def __post_init__(self) -> None:
        _require_nonblank(self.predictions_path, "DetectionEvidence.predictions_path")
        _require_nonblank(self.labels_dir, "DetectionEvidence.labels_dir")

        for field in (
            "total_gt_persons",
            "total_predictions",
            "images_with_gt",
            "images_with_predictions",
            "images_completely_missed",
            "gt_persons_in_missed_images",
            "gt_small",
            "gt_medium",
            "gt_large",
            "pred_small",
            "pred_medium",
            "pred_large",
            "pred_conf_025_035",
            "pred_conf_035_050",
            "pred_conf_050_070",
            "pred_conf_070_090",
            "pred_conf_090_100",
            "high_density_image_count",
        ):
            _require_nonneg_int(getattr(self, field), f"DetectionEvidence.{field}")

        _require_nonneg_float(
            self.small_fraction_in_missed, "DetectionEvidence.small_fraction_in_missed"
        )
        _require_nonneg_float(
            self.high_density_gt_fraction, "DetectionEvidence.high_density_gt_fraction"
        )

        # Consistency: missed images cannot exceed images with GT
        if self.images_completely_missed > self.images_with_gt:
            raise ValueError(
                "DetectionEvidence.images_completely_missed cannot exceed "
                f"images_with_gt ({self.images_completely_missed} > {self.images_with_gt})"
            )
        # GT size counts must sum to total
        gt_size_sum = self.gt_small + self.gt_medium + self.gt_large
        if gt_size_sum != self.total_gt_persons:
            raise ValueError(
                "DetectionEvidence GT size counts must sum to total_gt_persons: "
                f"{self.gt_small}+{self.gt_medium}+{self.gt_large}={gt_size_sum} "
                f"!= {self.total_gt_persons}"
            )
        # Prediction size counts must sum to total
        pred_size_sum = self.pred_small + self.pred_medium + self.pred_large
        if pred_size_sum != self.total_predictions:
            raise ValueError(
                "DetectionEvidence prediction size counts must sum to total_predictions: "
                f"{self.pred_small}+{self.pred_medium}+{self.pred_large}={pred_size_sum} "
                f"!= {self.total_predictions}"
            )
        # Confidence band counts must sum to total
        conf_sum = (
            self.pred_conf_025_035
            + self.pred_conf_035_050
            + self.pred_conf_050_070
            + self.pred_conf_070_090
            + self.pred_conf_090_100
        )
        if conf_sum != self.total_predictions:
            raise ValueError(
                "DetectionEvidence confidence band counts must sum to total_predictions: "
                f"{conf_sum} != {self.total_predictions}"
            )

    # ── Convenience properties ─────────────────────────────────────────────────

    @property
    def recall_gap(self) -> float | None:
        """Fraction of GT persons that are in completely-missed images.
        None if total_gt_persons == 0."""
        if self.total_gt_persons == 0:
            return None
        return self.gt_persons_in_missed_images / self.total_gt_persons

    @property
    def near_threshold_fraction(self) -> float | None:
        """Fraction of all person predictions in the 0.25-0.35 confidence band.
        None if total_predictions == 0."""
        if self.total_predictions == 0:
            return None
        return self.pred_conf_025_035 / self.total_predictions

    @property
    def gt_small_fraction(self) -> float | None:
        """Fraction of GT persons that are small. None if total_gt_persons == 0."""
        if self.total_gt_persons == 0:
            return None
        return self.gt_small / self.total_gt_persons
