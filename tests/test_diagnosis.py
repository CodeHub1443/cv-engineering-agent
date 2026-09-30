"""
Tests for cv_agent.diagnosis — DetectionEvidence model and collect_detection_evidence().

All tests use synthetic fixtures (no real COCO files). The real COCO files
(predictions.json + YOLO labels) are on disk only on the dev host and are NOT
part of the repo or CI fixtures.

See ADR-0015.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cv_agent.diagnosis.models import DetectionEvidence
from cv_agent.diagnosis.evidence_collector import collect_detection_evidence


# ── Synthetic fixture helpers ─────────────────────────────────────────────────

def _write_predictions(path: Path, predictions: list[dict]) -> None:
    path.write_text(json.dumps(predictions))


def _write_label(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines))


def _make_person_pred(
    image_id: int,
    file_name: str,
    score: float,
    bbox: tuple[float, float, float, float],  # x, y, w, h in pixels
) -> dict:
    return {
        "image_id": image_id,
        "file_name": file_name,
        "category_id": 1,
        "bbox": list(bbox),
        "score": score,
    }


# YOLO label line: "class_id cx cy w h" with normalized coords
def _person_label(cx: float = 0.5, cy: float = 0.5, w: float = 0.1, h: float = 0.2) -> str:
    return f"0 {cx} {cy} {w} {h}"


def _other_label(cls: int = 2, cx: float = 0.5, cy: float = 0.5, w: float = 0.1, h: float = 0.1) -> str:
    return f"{cls} {cx} {cy} {w} {h}"


# ── TestDetectionEvidenceModel ────────────────────────────────────────────────

class TestDetectionEvidenceModel:
    def _valid_kwargs(self) -> dict:
        return dict(
            predictions_path="/some/predictions.json",
            labels_dir="/some/labels/",
            total_gt_persons=10,
            total_predictions=8,
            images_with_gt=5,
            images_with_predictions=4,
            images_completely_missed=1,
            gt_persons_in_missed_images=2,
            gt_small=3,
            gt_medium=4,
            gt_large=3,
            pred_small=2,
            pred_medium=3,
            pred_large=3,
            pred_conf_025_035=1,
            pred_conf_035_050=2,
            pred_conf_050_070=2,
            pred_conf_070_090=2,
            pred_conf_090_100=1,
            small_fraction_in_missed=0.5,
            high_density_image_count=1,
            high_density_gt_fraction=0.4,
        )

    def test_valid_construction(self):
        ev = DetectionEvidence(**self._valid_kwargs())
        assert ev.total_gt_persons == 10
        assert ev.total_predictions == 8

    def test_gt_size_sum_mismatch_raises(self):
        kw = self._valid_kwargs()
        kw["gt_small"] = 4  # 4+4+3=11 != 10
        with pytest.raises(ValueError, match="GT size counts must sum to total_gt_persons"):
            DetectionEvidence(**kw)

    def test_pred_size_sum_mismatch_raises(self):
        kw = self._valid_kwargs()
        kw["pred_small"] = 3  # 3+3+3=9 != 8
        with pytest.raises(ValueError, match="prediction size counts must sum to total_predictions"):
            DetectionEvidence(**kw)

    def test_conf_band_sum_mismatch_raises(self):
        kw = self._valid_kwargs()
        kw["pred_conf_025_035"] = 2  # 2+2+2+2+1=9 != 8
        with pytest.raises(ValueError, match="confidence band counts must sum to total_predictions"):
            DetectionEvidence(**kw)

    def test_missed_gt_images_consistency_raises(self):
        kw = self._valid_kwargs()
        kw["images_completely_missed"] = 6  # > images_with_gt=5
        with pytest.raises(ValueError, match="images_completely_missed cannot exceed"):
            DetectionEvidence(**kw)

    def test_blank_predictions_path_raises(self):
        kw = self._valid_kwargs()
        kw["predictions_path"] = "  "
        with pytest.raises(ValueError):
            DetectionEvidence(**kw)

    def test_negative_int_raises(self):
        kw = self._valid_kwargs()
        kw["total_gt_persons"] = -1
        with pytest.raises(ValueError):
            DetectionEvidence(**kw)

    def test_nan_float_raises(self):
        kw = self._valid_kwargs()
        kw["small_fraction_in_missed"] = float("nan")
        with pytest.raises(ValueError):
            DetectionEvidence(**kw)

    def test_recall_gap_property(self):
        ev = DetectionEvidence(**self._valid_kwargs())
        # gt_persons_in_missed=2, total_gt=10
        assert ev.recall_gap == pytest.approx(0.2)

    def test_recall_gap_zero_gt(self):
        kw = self._valid_kwargs()
        kw.update(
            total_gt_persons=0,
            images_with_gt=0,
            images_completely_missed=0,
            gt_persons_in_missed_images=0,
            gt_small=0, gt_medium=0, gt_large=0,
        )
        ev = DetectionEvidence(**kw)
        assert ev.recall_gap is None

    def test_near_threshold_fraction_property(self):
        ev = DetectionEvidence(**self._valid_kwargs())
        # pred_conf_025_035=1, total_predictions=8
        assert ev.near_threshold_fraction == pytest.approx(1 / 8)

    def test_near_threshold_fraction_zero_preds(self):
        kw = self._valid_kwargs()
        kw.update(
            total_predictions=0,
            pred_small=0, pred_medium=0, pred_large=0,
            pred_conf_025_035=0, pred_conf_035_050=0, pred_conf_050_070=0,
            pred_conf_070_090=0, pred_conf_090_100=0,
        )
        ev = DetectionEvidence(**kw)
        assert ev.near_threshold_fraction is None

    def test_gt_small_fraction_property(self):
        ev = DetectionEvidence(**self._valid_kwargs())
        # gt_small=3, total_gt=10
        assert ev.gt_small_fraction == pytest.approx(0.3)

    def test_frozen(self):
        ev = DetectionEvidence(**self._valid_kwargs())
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            ev.total_gt_persons = 99  # type: ignore[misc]


# ── TestCollectDetectionEvidence ─────────────────────────────────────────────

class TestCollectDetectionEvidence:

    def test_basic_collection(self, tmp_path: Path):
        # 2 images: img001 has 2 GT persons, img002 has 1 GT person
        (tmp_path / "img001.txt").write_text(
            "0 0.5 0.5 0.2 0.4\n0 0.3 0.3 0.05 0.05\n"  # one medium, one small
        )
        (tmp_path / "img002.txt").write_text("0 0.5 0.5 0.3 0.4\n")  # one large

        preds = [
            _make_person_pred(1, "img001.jpg", 0.85, (200, 200, 128, 256)),  # medium
            _make_person_pred(2, "img002.jpg", 0.60, (100, 100, 192, 256)),  # large
        ]
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, preds)

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert ev.total_gt_persons == 3
        assert ev.total_predictions == 2
        assert ev.images_with_gt == 2
        assert ev.images_with_predictions == 2
        assert ev.images_completely_missed == 0
        assert ev.gt_persons_in_missed_images == 0

    def test_completely_missed_image(self, tmp_path: Path):
        # img001 has predictions; img002 has GT but no predictions
        (tmp_path / "img001.txt").write_text("0 0.5 0.5 0.2 0.3\n")
        (tmp_path / "img002.txt").write_text("0 0.3 0.3 0.04 0.04\n")  # small person

        preds = [
            _make_person_pred(1, "img001.jpg", 0.80, (200, 200, 100, 150)),
        ]
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, preds)

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert ev.images_completely_missed == 1
        assert ev.gt_persons_in_missed_images == 1
        # img002 has one small person (w=0.04, h=0.04 → area=0.0016 < 0.0025)
        assert ev.small_fraction_in_missed == pytest.approx(1.0)

    def test_gt_size_distribution(self, tmp_path: Path):
        # small: w*h = 0.04*0.04=0.0016 < 0.0025
        # medium: w*h = 0.05*0.06=0.003 ∈ [0.0025, 0.023)
        # large: w*h = 0.2*0.3=0.06 >= 0.023
        (tmp_path / "img001.txt").write_text(
            "0 0.5 0.5 0.04 0.04\n"   # small
            "0 0.5 0.5 0.05 0.06\n"   # medium (0.003)
            "0 0.5 0.5 0.2 0.3\n"     # large (0.06)
        )
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, [])

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert ev.gt_small == 1
        assert ev.gt_medium == 1
        assert ev.gt_large == 1
        assert ev.total_gt_persons == 3

    def test_prediction_size_distribution(self, tmp_path: Path):
        (tmp_path / "img001.txt").write_text("0 0.5 0.5 0.2 0.3\n")
        preds = [
            _make_person_pred(1, "img001.jpg", 0.9, (10, 10, 20, 30)),     # small: 20*30=600 < 1024
            _make_person_pred(1, "img001.jpg", 0.8, (10, 10, 40, 40)),     # medium: 40*40=1600
            _make_person_pred(1, "img001.jpg", 0.7, (10, 10, 100, 100)),   # large: 100*100=10000
        ]
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, preds)

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert ev.pred_small == 1
        assert ev.pred_medium == 1
        assert ev.pred_large == 1

    def test_confidence_band_distribution(self, tmp_path: Path):
        (tmp_path / "img001.txt").write_text("0 0.5 0.5 0.2 0.3\n")
        preds = [
            _make_person_pred(1, "img001.jpg", 0.30, (10, 10, 100, 100)),  # 025_035
            _make_person_pred(1, "img001.jpg", 0.45, (10, 10, 100, 100)),  # 035_050
            _make_person_pred(1, "img001.jpg", 0.60, (10, 10, 100, 100)),  # 050_070
            _make_person_pred(1, "img001.jpg", 0.80, (10, 10, 100, 100)),  # 070_090
            _make_person_pred(1, "img001.jpg", 0.95, (10, 10, 100, 100)),  # 090_100
        ]
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, preds)

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert ev.pred_conf_025_035 == 1
        assert ev.pred_conf_035_050 == 1
        assert ev.pred_conf_050_070 == 1
        assert ev.pred_conf_070_090 == 1
        assert ev.pred_conf_090_100 == 1
        assert ev.total_predictions == 5

    def test_ignores_non_person_predictions(self, tmp_path: Path):
        (tmp_path / "img001.txt").write_text("0 0.5 0.5 0.2 0.3\n")
        preds = [
            _make_person_pred(1, "img001.jpg", 0.9, (10, 10, 100, 100)),
            {
                "image_id": 1, "file_name": "img001.jpg",
                "category_id": 3,  # car
                "bbox": [10, 10, 100, 100],
                "score": 0.95,
            },
        ]
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, preds)

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert ev.total_predictions == 1  # only person

    def test_ignores_non_person_gt_labels(self, tmp_path: Path):
        # Mixed: 1 person + 1 car in GT
        (tmp_path / "img001.txt").write_text(
            "0 0.5 0.5 0.2 0.3\n"
            "2 0.3 0.3 0.4 0.2\n"
        )
        preds = [_make_person_pred(1, "img001.jpg", 0.9, (10, 10, 100, 100))]
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, preds)

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert ev.total_gt_persons == 1  # only person

    def test_high_density_images(self, tmp_path: Path):
        # img001 has 6 persons → high density (>5)
        # img002 has 3 persons → not high density
        lines_high = "\n".join("0 0.5 0.5 0.1 0.1" for _ in range(6))
        lines_normal = "\n".join("0 0.5 0.5 0.1 0.1" for _ in range(3))
        (tmp_path / "img001.txt").write_text(lines_high)
        (tmp_path / "img002.txt").write_text(lines_normal)
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, [])

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert ev.high_density_image_count == 1
        # 6 of 9 total GT persons are in high-density image
        assert ev.high_density_gt_fraction == pytest.approx(6 / 9)

    def test_empty_predictions(self, tmp_path: Path):
        (tmp_path / "img001.txt").write_text("0 0.5 0.5 0.2 0.3\n")
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, [])

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert ev.total_predictions == 0
        assert ev.images_with_predictions == 0
        assert ev.images_completely_missed == 1
        assert ev.near_threshold_fraction is None

    def test_empty_labels(self, tmp_path: Path):
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, [])

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert ev.total_gt_persons == 0
        assert ev.images_with_gt == 0
        assert ev.recall_gap is None

    def test_malformed_gt_line_skipped(self, tmp_path: Path):
        (tmp_path / "img001.txt").write_text(
            "0 0.5 0.5 0.2 0.3\n"
            "GARBAGE LINE\n"
            "0 0.3 0.3 0.1 0.1\n"
        )
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, [])

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert ev.total_gt_persons == 2  # malformed line skipped

    def test_empty_gt_file_not_counted(self, tmp_path: Path):
        # Label file exists but has no person annotations
        (tmp_path / "img001.txt").write_text("2 0.5 0.5 0.2 0.3\n")  # car, not person
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, [])

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert ev.total_gt_persons == 0
        assert ev.images_with_gt == 0

    def test_missing_predictions_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="predictions_path not found"):
            collect_detection_evidence(tmp_path / "nonexistent.json", tmp_path)

    def test_missing_labels_dir_raises(self, tmp_path: Path):
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, [])
        with pytest.raises(FileNotFoundError, match="labels_dir not found"):
            collect_detection_evidence(pred_file, tmp_path / "nonexistent/")

    def test_invalid_json_raises(self, tmp_path: Path):
        pred_file = tmp_path / "preds.json"
        pred_file.write_text('{"not": "a list"}')
        with pytest.raises(ValueError, match="JSON array"):
            collect_detection_evidence(pred_file, tmp_path)

    def test_custom_person_category_id(self, tmp_path: Path):
        # Pretend category_id=99 is person
        (tmp_path / "img001.txt").write_text("0 0.5 0.5 0.2 0.3\n")
        preds = [
            {"image_id": 1, "file_name": "img001.jpg",
             "category_id": 99, "bbox": [10, 10, 100, 100], "score": 0.9},
            _make_person_pred(1, "img001.jpg", 0.8, (10, 10, 100, 100)),  # cat_id=1, ignored
        ]
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, preds)

        ev = collect_detection_evidence(pred_file, tmp_path, person_category_id=99)

        assert ev.total_predictions == 1  # only category_id=99

    def test_small_fraction_in_missed_is_zero_when_no_missed(self, tmp_path: Path):
        (tmp_path / "img001.txt").write_text("0 0.5 0.5 0.2 0.3\n")
        preds = [_make_person_pred(1, "img001.jpg", 0.9, (100, 100, 200, 200))]
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, preds)

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert ev.images_completely_missed == 0
        assert ev.small_fraction_in_missed == 0.0

    def test_paths_stored_in_evidence(self, tmp_path: Path):
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, [])

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert str(pred_file) in ev.predictions_path
        assert str(tmp_path) in ev.labels_dir

    def test_multiple_images_various_conf(self, tmp_path: Path):
        """Integration-style: 3 images with different density and confidence."""
        (tmp_path / "imgA.txt").write_text(
            "0 0.5 0.5 0.1 0.1\n"   # medium: 0.01
            "0 0.5 0.5 0.03 0.03\n" # small: 0.0009
        )
        (tmp_path / "imgB.txt").write_text(
            "0 0.5 0.5 0.2 0.2\n"   # large: 0.04
        )
        (tmp_path / "imgC.txt").write_text(
            "0 0.5 0.5 0.05 0.05\n" # medium: 0.0025  (boundary: equals GT_SMALL_MAX, so medium)
        )

        preds = [
            _make_person_pred(1, "imgA.jpg", 0.28, (10, 10, 50, 50)),    # small, conf=025_035
            _make_person_pred(1, "imgA.jpg", 0.72, (10, 10, 50, 50)),    # small, conf=070_090
            _make_person_pred(2, "imgB.jpg", 0.55, (10, 10, 120, 120)),  # large (14400), conf=050_070
            # imgC has no predictions → completely missed
        ]
        pred_file = tmp_path / "preds.json"
        _write_predictions(pred_file, preds)

        ev = collect_detection_evidence(pred_file, tmp_path)

        assert ev.total_gt_persons == 4
        assert ev.total_predictions == 3
        assert ev.images_with_gt == 3
        assert ev.images_with_predictions == 2
        assert ev.images_completely_missed == 1  # imgC
        assert ev.gt_persons_in_missed_images == 1
        # imgC person: w=0.05, h=0.05, area=0.0025 — exactly at boundary
        # _gt_size_category: area < 0.0025? No. medium.
        assert ev.small_fraction_in_missed == pytest.approx(0.0)  # imgC's person is medium

        assert ev.gt_small == 1   # imgA's 0.03×0.03=0.0009
        assert ev.gt_medium == 2  # imgA's 0.1×0.1=0.01, imgC's 0.05×0.05=0.0025
        assert ev.gt_large == 1   # imgB's 0.2×0.2=0.04

        assert ev.pred_conf_025_035 == 1
        assert ev.pred_conf_050_070 == 1
        assert ev.pred_conf_070_090 == 1

        # High density: no image has > 5 persons
        assert ev.high_density_image_count == 0
        assert ev.high_density_gt_fraction == pytest.approx(0.0)
