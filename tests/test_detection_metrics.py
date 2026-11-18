"""
tests/test_detection_metrics.py — fail-closed YOLO label parsing and the ignore rule (I6a).

ADR-0025 §3.8: a label line whose column count is not 5 raises; it is never skipped silently.
ADR-0025 §3.7 (D-130): target-class GT matching first; then each unmatched prediction with
IoU >= 0.5 against any ignore box is discarded (many-to-one).
COCO must score identically: a frozen copy of the pre-I6 parser is the oracle (R1, EXP-20261118-01).
Pure functions, synthetic data only.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from cv_agent.experiments.detection_metrics import (
    YOLO_DETECT_COLUMNS,
    GroundTruthBox,
    PredictedBox,
    drop_ignored,
    evaluate,
    load_person_gt,
    parse_yolo_labels,
    stratum_ap50,
)


def _pre_i6_load_person_gt(label_path: Path, width: int, height: int) -> list[GroundTruthBox]:
    """Frozen copy of load_person_gt before I6 (detection_metrics.py:120-133 at f6880d9): the COCO oracle."""
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


def _labels(tmp_path: Path, text: str, name: str = "label.txt") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def _gt(x1: float, y1: float, x2: float, y2: float) -> GroundTruthBox:
    return GroundTruthBox(x1, y1, x2, y2, (x2 - x1) * (y2 - y1) / 10_000)


def _pred(x1: float, y1: float, x2: float, y2: float, score: float) -> PredictedBox:
    return PredictedBox(x1, y1, x2, y2, score)


# ── fail-closed parsing (ADR-0025 §3.8) ─────────────────────────────────────────────


def test_the_yolo_detection_layout_is_five_columns() -> None:
    assert YOLO_DETECT_COLUMNS == 5


@pytest.mark.parametrize(
    "bad_line, columns",
    [("0 0.5 0.5 0.2 0.2 0.9", 6), ("0 0.5 0.5 0.2", 4), ("0 0.1 0.1 0.2 0.1 0.2 0.2 0.1 0.1", 9)],
)
def test_a_line_that_is_not_five_columns_raises_and_names_file_and_line(
    tmp_path: Path, bad_line: str, columns: int
) -> None:
    path = _labels(tmp_path, f"0 0.5 0.5 0.1 0.1\n{bad_line}\n")
    with pytest.raises(ValueError) as info:
        parse_yolo_labels(path, 100, 100, target_class=0, ignore_classes=())
    message = str(info.value)
    assert f"{path}:2:" in message and f"{columns} columns, expected 5" in message


def test_a_wrong_column_count_raises_even_on_a_class_that_is_not_scored(tmp_path: Path) -> None:
    path = _labels(tmp_path, "17 0.5 0.5 0.1 0.1 0.3\n")
    with pytest.raises(ValueError, match="6 columns"):
        parse_yolo_labels(path, 100, 100, target_class=0, ignore_classes=())


def test_the_pre_i6_entry_point_fails_closed_too(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="6 columns"):
        load_person_gt(_labels(tmp_path, "0 0.5 0.5 0.2 0.2 0.9\n"), 100, 100)


@pytest.mark.parametrize("token", ["0.0", "x", "-1", "+0"])
def test_a_class_token_that_is_not_a_decimal_integer_raises(tmp_path: Path, token: str) -> None:
    path = _labels(tmp_path, f"{token} 0.5 0.5 0.1 0.1\n")
    with pytest.raises(ValueError, match="class"):
        parse_yolo_labels(path, 100, 100, target_class=0, ignore_classes=())


def test_whitespace_only_lines_are_skipped_like_the_label_digest(tmp_path: Path) -> None:
    path = _labels(tmp_path, "\n   \n0 0.5 0.5 0.2 0.2\n\t\n\n")
    targets, ignores = parse_yolo_labels(path, 100, 100, target_class=0, ignore_classes=())
    assert len(targets) == 1 and ignores == []


def test_a_missing_label_file_has_no_boxes(tmp_path: Path) -> None:
    assert parse_yolo_labels(tmp_path / "absent.txt", 100, 100, target_class=0, ignore_classes=(1,)) == ([], [])


def test_target_and_ignore_boxes_are_returned_apart_and_other_classes_are_filtered(tmp_path: Path) -> None:
    path = _labels(tmp_path, "0 0.5 0.5 0.2 0.2\n1 0.1 0.1 0.2 0.2\n2 0.9 0.9 0.1 0.1\n1 0.3 0.3 0.1 0.1\n")
    targets, ignores = parse_yolo_labels(path, 100, 50, target_class=0, ignore_classes=(1,))
    assert [(b.x1, b.y1, b.x2, b.y2) for b in targets] == [pytest.approx((40.0, 20.0, 60.0, 30.0))]
    assert [(b.x1, b.y1, b.x2, b.y2) for b in ignores] == [
        pytest.approx((0.0, 0.0, 20.0, 10.0)),
        pytest.approx((25.0, 12.5, 35.0, 17.5)),
    ]


# ── COCO is scored identically (R1 stays reproducible) ───────────────────────────────


def _coco_like_lines(rng: random.Random, n: int) -> str:
    lines = []
    for _ in range(n):
        cls = rng.choice([0, 0, 0, *range(1, 80)])
        values = [rng.uniform(0.0, 1.0) for _ in range(4)]
        lines.append(" ".join([str(cls), *(f"{v:.6f}" for v in values)]))
    return "\n".join(lines) + "\n"


def test_coco_five_column_labels_match_the_pre_i6_parser_exactly(tmp_path: Path) -> None:
    rng = random.Random(20261118)
    for index in range(50):
        path = _labels(tmp_path, _coco_like_lines(rng, rng.randint(0, 30)), name=f"{index:012d}.txt")
        width, height = rng.randint(64, 1280), rng.randint(64, 1280)
        expected = _pre_i6_load_person_gt(path, width, height)
        assert load_person_gt(path, width, height) == expected
        assert parse_yolo_labels(path, width, height, target_class=0, ignore_classes=()) == (expected, [])
    missing = tmp_path / "missing.txt"
    assert load_person_gt(missing, 10, 10) == _pre_i6_load_person_gt(missing, 10, 10)


# ── the ignore rule (ADR-0025 §3.7, D-130) ──────────────────────────────────────────


def test_a_prediction_on_both_gt_and_an_ignore_box_matches_the_gt_first() -> None:
    gt = {"a": [_gt(0, 0, 10, 10)]}
    ignore = {"a": [_gt(0, 0, 10, 10)]}
    preds = {"a": [_pred(0, 0, 10, 10, 0.9)]}
    assert drop_ignored(preds, gt, ignore) == preds


def test_a_lower_score_duplicate_left_unmatched_on_an_ignore_box_is_discarded() -> None:
    gt = {"a": [_gt(0, 0, 10, 10)]}
    ignore = {"a": [_gt(0, 0, 10, 10)]}
    first, duplicate = _pred(0, 0, 10, 10, 0.9), _pred(0, 0, 10, 10, 0.8)
    assert drop_ignored({"a": [duplicate, first]}, gt, ignore) == {"a": [first]}


def test_the_ignore_threshold_is_iou_at_least_one_half() -> None:
    ignore = {"a": [_gt(0, 0, 10, 10)]}
    at_half = _pred(0, 0, 10, 5, 0.6)  # IoU 50/100 = 0.5: discarded
    below = _pred(0, 0, 10, 4.9, 0.5)  # IoU 49/100 = 0.49: kept, a false positive
    assert drop_ignored({"a": [at_half, below]}, {}, ignore) == {"a": [below]}


def test_one_ignore_box_absorbs_several_predictions() -> None:
    ignore = {"a": [_gt(0, 0, 10, 10)]}
    preds = {"a": [_pred(0, 0, 10, 10, 0.7), _pred(0, 0, 10, 9, 0.6), _pred(50, 50, 60, 60, 0.5)]}
    assert drop_ignored(preds, {}, ignore) == {"a": [_pred(50, 50, 60, 60, 0.5)]}


def test_order_is_kept_and_images_without_ignore_boxes_pass_through() -> None:
    gt = {"a": [_gt(0, 0, 10, 10)], "b": [_gt(0, 0, 10, 10)]}
    ignore = {"a": [_gt(20, 20, 30, 30)]}
    a = [_pred(80, 80, 90, 90, 0.1), _pred(20, 20, 30, 30, 0.2), _pred(0, 0, 10, 10, 0.3)]
    b = [_pred(20, 20, 30, 30, 0.9), _pred(0, 0, 10, 10, 0.1)]
    assert drop_ignored({"a": a, "b": b}, gt, ignore) == {"a": [a[0], a[2]], "b": b}


def test_no_ignore_boxes_change_nothing_downstream() -> None:
    gt = {"a": [_gt(0, 0, 10, 10), _gt(40, 40, 60, 60)], "b": [_gt(0, 0, 50, 50)]}
    preds = {"a": [_pred(0, 0, 10, 10, 0.9), _pred(70, 70, 80, 80, 0.3)], "b": [_pred(0, 0, 50, 49, 0.6)]}
    kept = drop_ignored(preds, gt, {})
    assert kept == preds
    sizes = {"a": (100, 100), "b": (100, 100)}
    assert evaluate(kept, gt, 0.25) == evaluate(preds, gt, 0.25)
    for stratum in ("small", "medium", "large"):
        assert stratum_ap50(kept, gt, sizes, stratum) == stratum_ap50(preds, gt, sizes, stratum)


def test_discarded_predictions_leave_the_precision_denominator() -> None:
    gt = {"a": [_gt(0, 0, 10, 10)]}
    ignore = {"a": [_gt(50, 50, 70, 70)]}
    preds = {"a": [_pred(0, 0, 10, 10, 0.9), _pred(50, 50, 70, 70, 0.8)]}
    assert evaluate(preds, gt, 0.25).precision() == pytest.approx(0.5)
    report = evaluate(drop_ignored(preds, gt, ignore), gt, 0.25)
    assert report.n_predictions == 1 and report.precision() == pytest.approx(1.0)


def _random_box(rng: random.Random) -> tuple[float, float, float, float]:
    x, y = rng.uniform(0, 80), rng.uniform(0, 80)
    return x, y, x + rng.uniform(2, 20), y + rng.uniform(2, 20)


def test_filtering_the_full_curve_then_thresholding_equals_thresholding_then_filtering() -> None:
    rng = random.Random(160300831)
    for _ in range(200):
        gt = {"a": [_gt(*_random_box(rng)) for _ in range(rng.randint(0, 4))]}
        ignore = {"a": [_gt(*_random_box(rng)) for _ in range(rng.randint(0, 3))]}
        scores = [rng.choice([0.001, 0.1, 0.25, 0.5, 0.9, rng.random()]) for _ in range(rng.randint(0, 12))]
        preds = {"a": [_pred(*_random_box(rng), s) for s in scores]}
        full_then_cut = [p for p in drop_ignored(preds, gt, ignore)["a"] if p.score >= 0.25]
        cut = {"a": [p for p in preds["a"] if p.score >= 0.25]}
        assert full_then_cut == drop_ignored(cut, gt, ignore)["a"]
