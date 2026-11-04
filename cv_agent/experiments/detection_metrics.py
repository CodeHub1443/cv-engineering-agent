"""
cv_agent.experiments.detection_metrics — threshold-free and fixed-threshold person metrics
computed from saved YOLO predictions and COCO val2017 ground truth.

Responsibility: pure functions only (no ledger, no git, no GPU). Shared by the analysis CLI
(scripts/run_fixed_threshold_strata.py) and the evaluation record writer
(cv_agent/experiments/evaluation_records.py, ADR-0017).

Two kinds of number, kept separate by callers:
- threshold-free AP@0.5 per size stratum (``stratum_ap50``): valid only on a full PR curve,
  i.e. predictions produced at the Q28 protocol (conf=0.001). ``assert_full_curve`` enforces it.
- fixed-threshold precision/recall (``evaluate``): a reference measurement at a named threshold.
  It is not mAP and not an operating point (Q30 is open).

The matcher is greedy by score at IoU >= 0.5. It is an approximation, not the COCO evaluator.
"""

from __future__ import annotations

import json
import math
import struct
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

PERSON_CATEGORY_ID = 1  # COCO predictions.json category id for "person"
MATCH_IOU = 0.5
# Q28 (accepted 2026-10-04, D-067): standard mAP protocol is conf=0.001. A predictions
# file whose lowest score is above 2x this value does not hold the full PR curve.
MAP_PROTOCOL_CONF = 0.001
SMALL_MAX = 0.0025  # normalized GT area, ADR-0015 §3.4
MEDIUM_MAX = 0.023
DENSE_MIN_GT = 6  # "> 5 GT persons" per ADR-0015 §1


@dataclass(frozen=True)
class GroundTruthBox:
    """A person GT box in pixel corners plus its normalized area (w*h)."""

    x1: float
    y1: float
    x2: float
    y2: float
    norm_area: float


@dataclass(frozen=True)
class PredictedBox:
    """A person prediction in pixel corners plus its confidence score."""

    x1: float
    y1: float
    x2: float
    y2: float
    score: float


def iou(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    """Intersection-over-union of two (x1, y1, x2, y2) boxes."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0.0:
        return 0.0
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union


def size_bin(norm_area: float) -> str:
    """ADR-0015 normalized size stratum for a GT box."""
    if norm_area < SMALL_MAX:
        return "small"
    if norm_area < MEDIUM_MAX:
        return "medium"
    return "large"


def density_bin(gt_count_in_image: int) -> str:
    """ADR-0015 density stratum: more than five GT persons in the image."""
    return "dense" if gt_count_in_image >= DENSE_MIN_GT else "sparse"


def greedy_match_pairs(preds: list[PredictedBox], gts: list[GroundTruthBox]) -> list[tuple[int, int]]:
    """Greedy score-ordered matching as (prediction index, GT index) pairs, in matching order.

    Indices refer to the input lists. Each GT box can match at most one prediction. A prediction
    takes the unmatched GT with the highest IoU, provided that IoU reaches ``MATCH_IOU``.
    """
    pairs: list[tuple[int, int]] = []
    matched: set[int] = set()
    for i in sorted(range(len(preds)), key=lambda k: -preds[k].score):
        pred = preds[i]
        pbox = (pred.x1, pred.y1, pred.x2, pred.y2)
        best_iou, best_j = MATCH_IOU, -1
        for j, gt in enumerate(gts):
            if j in matched:
                continue
            value = iou(pbox, (gt.x1, gt.y1, gt.x2, gt.y2))
            if value >= best_iou:
                best_iou, best_j = value, j
        if best_j >= 0:
            matched.add(best_j)
            pairs.append((i, best_j))
    return pairs


def match_predictions(preds: list[PredictedBox], gts: list[GroundTruthBox]) -> set[int]:
    """Greedy score-ordered matching; return the indices of matched GT boxes.

    Each GT box can match at most one prediction. A prediction takes the unmatched GT
    with the highest IoU, provided that IoU reaches ``MATCH_IOU``. Delegates to
    ``greedy_match_pairs`` so there is one matcher.
    """
    return {j for _, j in greedy_match_pairs(preds, gts)}


def load_person_gt(label_path: Path, width: int, height: int) -> list[GroundTruthBox]:
    """Read YOLO-format person boxes (class 0) and convert them to pixel corners."""
    if not label_path.exists():
        return []
    boxes: list[GroundTruthBox] = []
    for line in label_path.read_text().splitlines():
        parts = line.split()
        if len(parts) != 5 or parts[0] != "0":
            continue
        cx, cy, nw, nh = (float(v) for v in parts[1:])
        x1 = (cx - nw / 2) * width
        y1 = (cy - nh / 2) * height
        boxes.append(GroundTruthBox(x1, y1, x1 + nw * width, y1 + nh * height, nw * nh))
    return boxes


def load_person_predictions(
    predictions_path: Path, threshold: float
) -> dict[str, list[PredictedBox]]:
    """Person predictions with score >= threshold, grouped by image stem."""
    records = json.loads(predictions_path.read_text())
    grouped: dict[str, list[PredictedBox]] = defaultdict(list)
    for rec in records:
        if rec["category_id"] != PERSON_CATEGORY_ID or rec["score"] < threshold:
            continue
        x, y, w, h = rec["bbox"]
        stem = Path(rec["file_name"]).stem
        grouped[stem].append(PredictedBox(x, y, x + w, y + h, rec["score"]))
    return dict(grouped)


def jpeg_size(path: Path) -> tuple[int, int]:
    """Return (width, height) from a JPEG's SOF marker, using only the standard library."""
    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        raise ValueError(f"not a JPEG: {path}")
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        ):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
        i += 2 + seg_len
    raise ValueError(f"no SOF marker found in {path}")


@dataclass
class StratumCount:
    """Matched and total GT counts for one stratum."""

    matched: int = 0
    total: int = 0

    def recall(self) -> float:
        return self.matched / self.total if self.total else 0.0


@dataclass
class RecallReport:
    """Fixed-threshold recall for one run, with overall, size and density strata."""

    threshold: float
    n_predictions: int
    matched_total: int
    gt_total: int
    strata: dict[str, StratumCount]

    def precision(self) -> float:
        return self.matched_total / self.n_predictions if self.n_predictions else 0.0

    def recall(self) -> float:
        return self.matched_total / self.gt_total if self.gt_total else 0.0


def evaluate(
    preds_by_stem: dict[str, list[PredictedBox]],
    gt_by_stem: dict[str, list[GroundTruthBox]],
    threshold: float,
) -> RecallReport:
    """Match every image and accumulate overall, size and density counts."""
    strata: dict[str, StratumCount] = defaultdict(StratumCount)
    matched_total = 0
    gt_total = 0
    n_predictions = sum(len(v) for v in preds_by_stem.values())
    for stem, gts in gt_by_stem.items():
        matched = match_predictions(preds_by_stem.get(stem, []), gts)
        dens = density_bin(len(gts))
        for j, gt in enumerate(gts):
            hit = 1 if j in matched else 0
            matched_total += hit
            gt_total += 1
            for key in ("overall", size_bin(gt.norm_area), dens):
                strata[key].total += 1
                strata[key].matched += hit
    return RecallReport(threshold, n_predictions, matched_total, gt_total, dict(strata))


def stratum_ap50(
    preds_by_stem: dict[str, list[PredictedBox]],
    gt_by_stem: dict[str, list[GroundTruthBox]],
    image_size_by_stem: dict[str, tuple[int, int]],
    stratum: str,
) -> float | None:
    """Threshold-free all-point AP@0.5 for one size stratum, from the full PR curve.

    Predictions are matched greedily per image in score order, so each prediction's
    TP/FP status does not depend on any confidence threshold. COCO-style area handling:
    a prediction matched to a GT outside ``stratum`` is ignored for this stratum, and an
    unmatched prediction counts as a false positive only if its own normalized area falls
    in ``stratum``. Returns None when the stratum has no GT boxes.

    Simplification: matching does not prioritise in-stratum GT, so for heavily overlapping
    boxes this can under-count in-stratum TPs. The official COCO evaluator would prioritise them.
    """
    n_gt = sum(
        1
        for gts in gt_by_stem.values()
        for g in gts
        if size_bin(g.norm_area) == stratum
    )
    if n_gt == 0:
        return None
    scored: list[tuple[float, int]] = []  # (score, 1 if TP else 0)
    for stem, gts in gt_by_stem.items():
        width, height = image_size_by_stem[stem]
        used: set[int] = set()
        for pred in sorted(preds_by_stem.get(stem, []), key=lambda p: -p.score):
            pbox = (pred.x1, pred.y1, pred.x2, pred.y2)
            best_iou, best_j = MATCH_IOU, -1
            for j, gt in enumerate(gts):
                if j in used:
                    continue
                value = iou(pbox, (gt.x1, gt.y1, gt.x2, gt.y2))
                if value >= best_iou:
                    best_iou, best_j = value, j
            if best_j >= 0:
                used.add(best_j)
                if size_bin(gts[best_j].norm_area) == stratum:
                    scored.append((pred.score, 1))
            else:
                pred_norm_area = (
                    (pred.x2 - pred.x1) * (pred.y2 - pred.y1) / (width * height)
                )
                if size_bin(pred_norm_area) == stratum:
                    scored.append((pred.score, 0))
    scored.sort(key=lambda t: -t[0])
    recalls: list[float] = []
    precisions: list[float] = []
    tp = fp = 0
    for _, is_tp in scored:
        tp += is_tp
        fp += 1 - is_tp
        recalls.append(tp / n_gt)
        precisions.append(tp / (tp + fp))
    # All-point interpolation (VOC-style): precision envelope integrated over recall.
    mrec = [0.0, *recalls, 1.0]
    mpre = [0.0, *precisions, 0.0]
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    ap = 0.0
    for i in range(1, len(mrec)):
        if mrec[i] != mrec[i - 1]:
            ap += (mrec[i] - mrec[i - 1]) * mpre[i]
    return ap


# Q28 / D-067: standard mAP protocol threshold. A predictions file whose lowest person score is
# above this bound does not hold the full PR curve and is not valid for threshold-free AP or mAP.
FULL_CURVE_MAX_MIN_SCORE = 0.002


def min_person_score(predictions_path: Path) -> float:
    """Lowest score among person predictions in a predictions.json file (fails closed if none)."""
    records = json.loads(predictions_path.read_text(encoding="utf-8"))
    scores = [
        float(r["score"]) for r in records if isinstance(r, dict) and r.get("category_id") == PERSON_CATEGORY_ID
    ]
    if not scores:
        raise ValueError(f"no person predictions in {predictions_path}")
    return min(scores)


def assert_full_curve(predictions_path: Path) -> float:
    """Return the lowest person score, or raise ValueError if the file is truncated.

    Called before any threshold-free AP or mAP is recorded as valid evidence.
    """
    lowest = min_person_score(predictions_path)
    if not math.isfinite(lowest) or lowest > FULL_CURVE_MAX_MIN_SCORE:
        raise ValueError(
            f"{predictions_path} is TRUNCATED: lowest person score {lowest:.4f} > "
            f"{FULL_CURVE_MAX_MIN_SCORE} (not a full PR curve; invalid for mAP, Q28)"
        )
    return lowest
