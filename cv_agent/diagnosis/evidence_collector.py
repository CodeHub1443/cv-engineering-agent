"""
cv_agent.diagnosis.evidence_collector — deterministic evidence collection
from evaluation artifacts.

collect_detection_evidence() is the only public entry point. It reads
predictions.json and YOLO-format GT label files and returns a DetectionEvidence
dataclass. No side effects. No LLM. No downloads. See ADR-0015 §3.3.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Sequence

from cv_agent.diagnosis.models import DetectionEvidence

# ── Size thresholds (ADR-0015 §3.4) ──────────────────────────────────────────
# GT labels: normalized area = w × h where w, h ∈ [0, 1]
_GT_SMALL_MAX = 0.0025    # approx < 32² px at 640×480
_GT_MEDIUM_MAX = 0.023    # approx < 96² px at 640×480

# Predictions: pixel area from COCO-format bbox [x, y, w, h]
_PRED_SMALL_MAX = 1024.0   # < 32² px
_PRED_MEDIUM_MAX = 9216.0  # < 96² px


def _load_predictions(
    predictions_path: Path,
    person_category_id: int,
) -> list[dict]:
    """Load and filter predictions to person_category_id."""
    with predictions_path.open() as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(
            f"predictions.json must be a JSON array, got {type(data).__name__}"
        )
    return [p for p in data if p.get("category_id") == person_category_id]


def _load_gt_persons(
    labels_dir: Path,
) -> dict[str, list[tuple[float, float, float, float]]]:
    """Load GT person annotations from YOLO-format label files.

    Returns {image_stem: [(cx, cy, w, h), ...]} for all images that have at
    least one person annotation. Malformed lines are silently skipped.
    """
    result: dict[str, list[tuple[float, float, float, float]]] = {}
    for label_file in labels_dir.glob("*.txt"):
        boxes: list[tuple[float, float, float, float]] = []
        for line in label_file.read_text().strip().splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                cls = int(parts[0])
            except ValueError:
                continue
            if cls != 0:  # person class in YOLO format
                continue
            try:
                cx, cy, w, h = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            except (ValueError, IndexError):
                continue
            boxes.append((cx, cy, w, h))
        if boxes:
            result[label_file.stem] = boxes
    return result


def _gt_size_category(w: float, h: float) -> str:
    """Classify GT bbox by normalized area into small/medium/large."""
    area = w * h
    if area < _GT_SMALL_MAX:
        return "small"
    if area < _GT_MEDIUM_MAX:
        return "medium"
    return "large"


def _pred_size_category(bbox: Sequence[float]) -> str:
    """Classify prediction bbox [x, y, w, h] by pixel area into small/medium/large."""
    area = float(bbox[2]) * float(bbox[3])
    if area < _PRED_SMALL_MAX:
        return "small"
    if area < _PRED_MEDIUM_MAX:
        return "medium"
    return "large"


def _conf_band(score: float) -> str:
    if score < 0.35:
        return "025_035"
    if score < 0.50:
        return "035_050"
    if score < 0.70:
        return "050_070"
    if score < 0.90:
        return "070_090"
    return "090_100"


def collect_detection_evidence(
    predictions_path: str | Path,
    labels_dir: str | Path,
    *,
    person_category_id: int = 1,
) -> DetectionEvidence:
    """Collect measurable detection failure-mode evidence from artifacts on disk.

    Reads predictions.json (COCO format) and YOLO-format GT label files.
    Returns a DetectionEvidence dataclass. Deterministic given the same files.

    Parameters
    ----------
    predictions_path:
        Path to predictions.json produced by yolo val (COCO format).
    labels_dir:
        Directory containing YOLO-format .txt label files (one per image).
        Person annotations are class 0.
    person_category_id:
        COCO category_id for person (default 1 for COCO 2017).

    Raises
    ------
    FileNotFoundError:
        If predictions_path or labels_dir does not exist.
    ValueError:
        If predictions_path is not a valid JSON array.
    """
    predictions_path = Path(predictions_path)
    labels_dir = Path(labels_dir)

    if not predictions_path.exists():
        raise FileNotFoundError(f"predictions_path not found: {predictions_path}")
    if not labels_dir.is_dir():
        raise FileNotFoundError(f"labels_dir not found: {labels_dir}")

    # ── Load data ─────────────────────────────────────────────────────────────
    person_preds = _load_predictions(predictions_path, person_category_id)
    gt_by_stem = _load_gt_persons(labels_dir)

    # ── Ground-truth stats ─────────────────────────────────────────────────────
    gt_size_counts: Counter[str] = Counter()
    gt_per_stem: dict[str, int] = {}
    total_gt = 0
    for stem, boxes in gt_by_stem.items():
        gt_per_stem[stem] = len(boxes)
        total_gt += len(boxes)
        for (_, _, w, h) in boxes:
            gt_size_counts[_gt_size_category(w, h)] += 1

    images_with_gt = len(gt_by_stem)

    # ── Prediction stats ──────────────────────────────────────────────────────
    pred_size_counts: Counter[str] = Counter()
    pred_conf_counts: Counter[str] = Counter()
    pred_per_stem: Counter[str] = Counter()

    for p in person_preds:
        stem = Path(p.get("file_name", "")).stem or str(p.get("image_id", ""))
        pred_per_stem[stem] += 1
        pred_size_counts[_pred_size_category(p["bbox"])] += 1
        pred_conf_counts[_conf_band(float(p["score"]))] += 1

    total_predictions = len(person_preds)
    images_with_predictions = len(pred_per_stem)

    # ── Completely-missed images ──────────────────────────────────────────────
    gt_stems = set(gt_by_stem.keys())
    pred_stems = set(pred_per_stem.keys())
    missed_stems = gt_stems - pred_stems

    images_completely_missed = len(missed_stems)
    gt_in_missed = sum(len(gt_by_stem[s]) for s in missed_stems)

    # Small fraction in missed images
    if gt_in_missed > 0:
        small_in_missed = sum(
            1
            for s in missed_stems
            for (_, _, w, h) in gt_by_stem[s]
            if _gt_size_category(w, h) == "small"
        )
        small_fraction_in_missed = small_in_missed / gt_in_missed
    else:
        small_fraction_in_missed = 0.0

    # ── High-density images ───────────────────────────────────────────────────
    high_density_stems = [s for s, cnt in gt_per_stem.items() if cnt > 5]
    high_density_gt = sum(gt_per_stem[s] for s in high_density_stems)
    high_density_gt_fraction = high_density_gt / total_gt if total_gt > 0 else 0.0

    return DetectionEvidence(
        predictions_path=str(predictions_path),
        labels_dir=str(labels_dir),
        total_gt_persons=total_gt,
        total_predictions=total_predictions,
        images_with_gt=images_with_gt,
        images_with_predictions=images_with_predictions,
        images_completely_missed=images_completely_missed,
        gt_persons_in_missed_images=gt_in_missed,
        gt_small=gt_size_counts["small"],
        gt_medium=gt_size_counts["medium"],
        gt_large=gt_size_counts["large"],
        pred_small=pred_size_counts["small"],
        pred_medium=pred_size_counts["medium"],
        pred_large=pred_size_counts["large"],
        pred_conf_025_035=pred_conf_counts["025_035"],
        pred_conf_035_050=pred_conf_counts["035_050"],
        pred_conf_050_070=pred_conf_counts["050_070"],
        pred_conf_070_090=pred_conf_counts["070_090"],
        pred_conf_090_100=pred_conf_counts["090_100"],
        small_fraction_in_missed=small_fraction_in_missed,
        high_density_image_count=len(high_density_stems),
        high_density_gt_fraction=high_density_gt_fraction,
    )
