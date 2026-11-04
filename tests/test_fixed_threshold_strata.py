"""
tests/test_fixed_threshold_strata.py — Unit tests for scripts/run_fixed_threshold_strata.py.

Covers the IoU matcher, ADR-0015 size and density bins, YOLO label and predictions.json
parsing, and the stdlib JPEG size reader. Uses only tmp_path; no GPU, no COCO data.
"""

from __future__ import annotations

import importlib.util
import json
import struct
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "run_fixed_threshold_strata", _SCRIPTS_DIR / "run_fixed_threshold_strata.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


strata = _load_module()


def test_iou_identical_boxes_is_one():
    assert strata.iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)


def test_iou_disjoint_boxes_is_zero():
    assert strata.iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0


def test_iou_half_overlap():
    # Intersection 5x10=50, union 100+100-50=150 -> 1/3.
    assert strata.iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(50 / 150)


@pytest.mark.parametrize(
    ("norm_area", "expected"),
    [
        (0.0024, "small"),
        (0.0025, "medium"),
        (0.0229, "medium"),
        (0.023, "large"),
        (0.5, "large"),
    ],
)
def test_size_bin_boundaries_follow_adr_0015(norm_area, expected):
    assert strata.size_bin(norm_area) == expected


def test_density_bin_dense_means_more_than_five_gt():
    assert strata.density_bin(5) == "sparse"
    assert strata.density_bin(6) == "dense"


def test_match_predictions_each_gt_matches_at_most_once():
    gt = [strata.GroundTruthBox(0, 0, 10, 10, 0.01)]
    preds = [
        strata.PredictedBox(0, 0, 10, 10, 0.9),
        strata.PredictedBox(0, 0, 10, 10, 0.8),  # duplicate of the same GT
    ]
    assert strata.match_predictions(preds, gt) == {0}


def test_match_predictions_respects_iou_threshold():
    gt = [strata.GroundTruthBox(0, 0, 10, 10, 0.01)]
    # IoU = 25/175 ~ 0.14 < 0.5, so no match.
    preds = [strata.PredictedBox(5, 5, 15, 15, 0.9)]
    assert strata.match_predictions(preds, gt) == set()


def test_match_predictions_higher_score_claims_gt_first():
    gt = [strata.GroundTruthBox(0, 0, 10, 10, 0.01)]
    preds = [
        strata.PredictedBox(1, 1, 11, 11, 0.5),  # lower score, slightly worse IoU
        strata.PredictedBox(0, 0, 10, 10, 0.9),  # higher score, perfect IoU
    ]
    assert strata.match_predictions(preds, gt) == {0}


def test_load_person_gt_keeps_class_zero_and_converts_to_pixels(tmp_path):
    label = tmp_path / "img.txt"
    # cx=0.5 cy=0.5 w=0.2 h=0.4 on a 100x50 image -> x 40..60, y 15..35
    label.write_text("0 0.5 0.5 0.2 0.4\n3 0.1 0.1 0.1 0.1\n")
    boxes = strata.load_person_gt(label, 100, 50)
    assert len(boxes) == 1
    box = boxes[0]
    assert (box.x1, box.y1, box.x2, box.y2) == pytest.approx((40, 15, 60, 35))
    assert box.norm_area == pytest.approx(0.2 * 0.4)


def test_load_person_gt_missing_file_is_empty(tmp_path):
    assert strata.load_person_gt(tmp_path / "absent.txt", 100, 100) == []


def test_load_person_predictions_filters_category_and_threshold(tmp_path):
    path = tmp_path / "predictions.json"
    path.write_text(
        json.dumps(
            [
                {
                    "image_id": 1,
                    "file_name": "000000000001.jpg",
                    "category_id": 1,
                    "bbox": [10, 20, 30, 40],
                    "score": 0.6,
                },
                {
                    "image_id": 1,
                    "file_name": "000000000001.jpg",
                    "category_id": 1,
                    "bbox": [0, 0, 5, 5],
                    "score": 0.2,
                },
                {
                    "image_id": 1,
                    "file_name": "000000000001.jpg",
                    "category_id": 2,
                    "bbox": [0, 0, 5, 5],
                    "score": 0.9,
                },
            ]
        )
    )
    grouped = strata.load_person_predictions(path, 0.25)
    assert list(grouped) == ["000000000001"]
    assert len(grouped["000000000001"]) == 1
    box = grouped["000000000001"][0]
    assert (box.x1, box.y1, box.x2, box.y2) == (10, 20, 40, 60)


def test_evaluate_counts_overall_size_and_density(tmp_path):
    # Image A: one small GT (matched) and one large GT (missed); sparse (2 GT).
    # Image B: six GT boxes, all medium-free small; none predicted -> dense, all missed.
    small = strata.GroundTruthBox(0, 0, 4, 4, 0.0002)
    large = strata.GroundTruthBox(50, 50, 90, 90, 0.04)
    gt_by_stem = {
        "a": [small, large],
        "b": [
            strata.GroundTruthBox(float(i * 10), 0, float(i * 10 + 4), 4, 0.0002)
            for i in range(6)
        ],
    }
    preds_by_stem = {"a": [strata.PredictedBox(0, 0, 4, 4, 0.9)]}
    report = strata.evaluate(preds_by_stem, gt_by_stem, 0.25)
    assert report.gt_total == 8
    assert report.matched_total == 1
    assert report.n_predictions == 1
    assert report.strata["overall"].recall() == pytest.approx(1 / 8)
    assert report.strata["small"].total == 7
    assert report.strata["small"].matched == 1
    assert report.strata["large"].total == 1
    assert report.strata["large"].matched == 0
    assert report.strata["sparse"].total == 2
    assert report.strata["dense"].total == 6
    assert report.strata["dense"].matched == 0


def test_jpeg_size_reads_sof_after_metadata_segment(tmp_path):
    # SOI, APP0 (padding payload), SOF0 with height=480 width=640.
    app0 = b"\xff\xe0" + struct.pack(">H", 2 + 8) + b"\x00" * 8
    sof0 = (
        b"\xff\xc0"
        + struct.pack(">H", 8)
        + b"\x08"
        + struct.pack(">HH", 480, 640)
        + b"\x01"
    )
    path = tmp_path / "x.jpg"
    path.write_bytes(b"\xff\xd8" + app0 + sof0 + b"\xff\xd9")
    assert strata.jpeg_size(path) == (640, 480)


def test_jpeg_size_rejects_non_jpeg(tmp_path):
    path = tmp_path / "x.jpg"
    path.write_bytes(b"not a jpeg at all")
    with pytest.raises(ValueError):
        strata.jpeg_size(path)


# ── Threshold-free stratified AP50 (Q28 protocol) ─────────────────────────────

_SIZES_100 = {"img": (100, 100)}


def test_stratum_ap50_perfect_detection_is_one():
    gt = {"img": [strata.GroundTruthBox(0, 0, 4, 4, 0.0016)]}  # small: 4*4/10000
    preds = {"img": [strata.PredictedBox(0, 0, 4, 4, 0.9)]}
    assert strata.stratum_ap50(preds, gt, _SIZES_100, "small") == pytest.approx(1.0)


def test_stratum_ap50_false_positive_ranked_above_tp_halves_ap():
    gt = {"img": [strata.GroundTruthBox(0, 0, 4, 4, 0.0016)]}
    preds = {
        "img": [
            strata.PredictedBox(50, 50, 54, 54, 0.9),  # FP, small, ranked first
            strata.PredictedBox(0, 0, 4, 4, 0.5),  # TP
        ]
    }
    assert strata.stratum_ap50(preds, gt, _SIZES_100, "small") == pytest.approx(0.5)


def test_stratum_ap50_is_threshold_free_adding_low_scores_only_extends_curve():
    gt = {"img": [strata.GroundTruthBox(0, 0, 4, 4, 0.0016)]}
    high_only = {"img": [strata.PredictedBox(0, 0, 4, 4, 0.9)]}
    with_low_fp = {
        "img": [
            strata.PredictedBox(0, 0, 4, 4, 0.9),
            strata.PredictedBox(50, 50, 54, 54, 0.001),  # low-score FP after the TP
        ]
    }
    # The TP already reaches full recall before the low-score FP, so AP is unchanged.
    assert strata.stratum_ap50(high_only, gt, _SIZES_100, "small") == pytest.approx(
        strata.stratum_ap50(with_low_fp, gt, _SIZES_100, "small")
    )


def test_stratum_ap50_ignores_prediction_matched_to_out_of_stratum_gt():
    # A large GT matched by a small-area prediction: the prediction is ignored for
    # the small stratum, so the small stratum has no GT and returns None.
    gt = {"img": [strata.GroundTruthBox(0, 0, 50, 50, 0.25)]}  # large
    preds = {"img": [strata.PredictedBox(0, 0, 50, 50, 0.9)]}
    assert strata.stratum_ap50(preds, gt, _SIZES_100, "small") is None
    assert strata.stratum_ap50(preds, gt, _SIZES_100, "large") == pytest.approx(1.0)


def test_stratum_ap50_unmatched_prediction_counts_only_if_in_stratum():
    # Unmatched small-area FP is counted for "small"; an unmatched large-area FP is not.
    gt = {"img": [strata.GroundTruthBox(0, 0, 4, 4, 0.0016)]}
    preds = {"img": [strata.PredictedBox(50, 50, 90, 90, 0.9)]}  # large-area FP
    # No small FP is counted, and the small GT is never found, so AP is 0 (not undefined).
    assert strata.stratum_ap50(preds, gt, _SIZES_100, "small") == pytest.approx(0.0)
