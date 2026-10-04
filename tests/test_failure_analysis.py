"""Read-only failure analysis (ADR-0015 §9, issue #75). Synthetic fixtures only; no GPU, no real artifacts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from dataclasses import fields
from pathlib import Path

import pytest
from PIL import Image

from cv_agent.diagnosis import failure_analysis as fa
from cv_agent.diagnosis.models import DetectionEvidence
from cv_agent.experiments.detection_metrics import density_bin, size_bin

REPO = Path(__file__).resolve().parent.parent
COMMIT = "a" * 40


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_coco(
    tmp: Path,
    images: dict[str, tuple[int, int]],
    labels: dict[str, list[str]],
    list_stems: list[str],
    predictions: list[dict],
) -> dict[str, Path]:
    """A COCO-like tree: images/val2017/<stem>.jpg, labels/val2017/<stem>.txt, val2017.txt, predictions.json."""
    images_dir = tmp / "images" / "val2017"
    labels_dir = tmp / "labels" / "val2017"
    images_dir.mkdir(parents=True)
    labels_dir.mkdir(parents=True)
    for stem, (w, h) in images.items():
        Image.new("RGB", (w, h), (0, 0, 0)).save(images_dir / f"{stem}.jpg", "JPEG")
    for stem, lines in labels.items():
        (labels_dir / f"{stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
    listing = tmp / "val2017.txt"
    listing.write_text("".join(f"./images/val2017/{s}.jpg\n" for s in list_stems))
    pred_path = tmp / "predictions.json"
    # Full-curve gate (Q28): a real run reaches down to 0.001. A sentinel that overlaps nothing supplies it.
    if list_stems and not any(p["score"] <= 0.002 for p in predictions):
        predictions = [*predictions, pred(list_stems[0], 0, 0, 1, 1, 0.001)]
    pred_path.write_text(json.dumps(predictions))
    return {"images": images_dir, "labels": labels_dir, "list": listing, "pred": pred_path}


def pred(stem: str, x: float, y: float, w: float, h: float, score: float) -> dict:
    return {"image_id": 0, "file_name": f"{stem}.jpg", "category_id": 1, "bbox": [x, y, w, h], "score": score}


def run(paths: dict[str, Path], *, expected: str | None = None) -> fa.RunOutcome:
    return fa.analyze_run(
        predictions_path=paths["pred"],
        expected_predictions_sha256=expected if expected is not None else _sha(paths["pred"]),
        image_list_path=paths["list"],
        images_dir=paths["images"],
        labels_dir=paths["labels"],
        code_commit=COMMIT,
    )


# ── one synthetic image covering every category ───────────────────────────────────────

# 100×100 image. Label lines are YOLO normalized: class cx cy w h.
S_LABELS = [
    "0 0.5 0.5 0.04 0.04",  # g0 small, px (48,48)-(52,52), matched at 0.25 by pB (score 0.3)
    "0 0.25 0.25 0.10 0.10",  # g1 medium, px (20,20)-(30,30), matched at 0.25 by pA (score 0.9)
    "0 0.75 0.75 0.40 0.40",  # g2 large, px (55,55)-(95,95), missed at 0.25; near-miss by pD (IoU 0.39)
    "0 0.12 0.12 0.03 0.03",  # g3 small, px (10.5,10.5)-(13.5,13.5), nothing overlaps: fully missed
]
S_PREDS = [
    pred("img1", 20, 20, 10, 10, 0.9),  # pA: exact on g1
    pred("img1", 48, 48, 4, 4, 0.3),  # pB: exact on g0 (score >= 0.25)
    pred("img1", 0, 80, 10, 10, 0.6),  # pC: no GT overlap, FP at >= 0.25 and >= 0.50
    pred("img1", 55, 55, 25, 25, 0.4),  # pD: IoU 0.39 with g2 (near-miss band)
    pred("img1", 55, 55, 40, 40, 0.05),  # pF: exact on g2 but below the reference threshold
]


@pytest.fixture()
def scenario(tmp_path: Path) -> fa.RunOutcome:
    paths = build_coco(tmp_path, {"img1": (100, 100)}, {"img1": S_LABELS}, ["img1"], S_PREDS)
    return run(paths)


def test_counts_cover_every_major_category(scenario: fa.RunOutcome) -> None:
    a = scenario.analysis
    assert a.gt_total == 4
    assert a.fully_missed.count == 1  # g3 only: g2 is overlapped by pF (score 0.05), so not fully missed
    assert a.missed_at_reference.count == 2  # g2 and g3
    assert a.localization["matched_at_reference"].count == 2  # g0, g1
    assert a.localization["near_miss"].count == 1  # g2
    assert a.localization["no_overlap"].count == 1  # g3
    assert a.localization["competed"].count == 0
    assert a.unmatched_pred_ref.count == 2  # pC and pD
    assert a.unmatched_pred_050.count == 1  # pC
    assert a.candidates["high_conf_fp"] == 1
    assert a.candidates["near_dup_pairs"] == 0
    assert a.candidates["degenerate_gt"] == 0


def test_reference_and_fully_missed_are_different_definitions(scenario: fa.RunOutcome) -> None:
    g2 = next(r for r in scenario.gt_rows if r["gt_index"] == 2)
    assert g2["missed_at_reference"] is True  # no prediction at score >= 0.25 matches it
    assert g2["fully_missed"] is False  # pF overlaps it at IoU 1 (score 0.05)
    assert g2["localization"] == "near_miss"


def test_size_and_density_strata(scenario: fa.RunOutcome) -> None:
    small = scenario.analysis.size_strata["small"]
    assert (small.gt, small.fully_missed, small.missed_at_reference) == (2, 1, 1)
    assert scenario.analysis.size_strata["medium"].gt == 1
    assert scenario.analysis.size_strata["large"].missed_at_reference == 1
    assert scenario.analysis.density_strata["sparse"].gt == 4
    assert scenario.analysis.density_strata["dense"].gt == 0


def test_bottleneck_ranking_is_descriptive_and_ordered(scenario: fa.RunOutcome) -> None:
    ranking = scenario.analysis.bottleneck_ranking
    names = [name for name, _ in ranking]
    assert names[0] == "near_miss"  # tie with no_overlap at 1 each: ties break by name, ascending
    assert set(names) == {"near_miss", "no_overlap", "competed"}
    counts = [iv.count for _, iv in ranking]
    assert counts == sorted(counts, reverse=True)


def test_shares_have_bootstrap_intervals_that_bracket_the_point_estimate(scenario: fa.RunOutcome) -> None:
    iv = scenario.analysis.fully_missed
    assert iv.share == pytest.approx(0.25)
    assert iv.low <= iv.share <= iv.high


# ── matching behaviour ─────────────────────────────────────────────────────────────────


def test_greedy_matching_gives_the_higher_score_the_gt(tmp_path: Path) -> None:
    labels = {"img2": ["0 0.5 0.5 0.4 0.4"]}  # one GT, px (30,30)-(70,70)
    preds = [pred("img2", 30, 30, 40, 40, 0.9), pred("img2", 31, 31, 40, 40, 0.8)]
    out = run(build_coco(tmp_path, {"img2": (100, 100)}, labels, ["img2"], preds))
    assert out.analysis.localization["matched_at_reference"].count == 1
    assert out.analysis.unmatched_pred_ref.count == 1  # the second, lower-score prediction is a false positive


def test_competed_gt_has_overlap_but_lost_the_greedy_assignment(tmp_path: Path) -> None:
    labels = {"img3": ["0 0.5 0.5 0.4 0.4", "0 0.5 0.5 0.4 0.4"]}  # two identical GT boxes
    preds = [pred("img3", 30, 30, 40, 40, 0.9)]
    out = run(build_coco(tmp_path, {"img3": (100, 100)}, labels, ["img3"], preds))
    assert out.analysis.localization["matched_at_reference"].count == 1
    assert out.analysis.localization["competed"].count == 1  # the other copy overlaps the prediction at IoU 1


# ── descriptive boundaries (no production criteria) ────────────────────────────────────


def test_localization_boundaries() -> None:
    assert fa.localization_class(0.50) == "competed"
    assert fa.localization_class(0.4999) == "near_miss"
    assert fa.localization_class(0.30) == "near_miss"
    assert fa.localization_class(0.2999) == "no_overlap"
    assert fa.localization_class(0.0) == "no_overlap"


def test_area_bin_boundaries_reuse_the_shared_definition() -> None:
    assert fa.size_bin is size_bin  # one definition, not a copy
    assert size_bin(0.0024999) == "small"
    assert size_bin(0.0025) == "medium"
    assert size_bin(0.0229999) == "medium"
    assert size_bin(0.023) == "large"


def test_dense_sparse_boundary_is_six_or_more() -> None:
    assert density_bin(5) == "sparse"
    assert density_bin(6) == "dense"


def test_descriptive_thresholds_are_the_agreed_values() -> None:
    assert fa.NEAR_MISS_LOW_IOU == 0.30
    assert fa.HIGH_CONF_SCORE == 0.50
    assert fa.REFERENCE_SCORE == 0.25
    assert fa.FULL_CURVE_SCORE == 0.001
    assert fa.SEED == 20261004
    assert fa.N_RESAMPLES == 1000
    assert fa.SAMPLE_PER_CLASS == 50


# ── complete image iteration (background images count as zero GT) ────────────────────────


def test_every_listed_image_is_iterated_including_backgrounds(tmp_path: Path) -> None:
    images = {"a1": (50, 50), "a2": (50, 50), "a3": (50, 50)}
    labels = {"a1": ["0 0.5 0.5 0.5 0.5"]}  # a2 and a3 have no label file: backgrounds
    preds = [pred("a1", 12, 12, 25, 25, 0.9)]
    out = run(build_coco(tmp_path, images, labels, ["a1", "a2", "a3"], preds))
    assert out.analysis.images_listed == 3
    assert out.analysis.background_images == 2
    assert out.analysis.gt_total == 1


# ── deterministic sampling and bootstrap ───────────────────────────────────────────────


def test_sampling_is_deterministic_sorted_and_capped() -> None:
    import random

    items = [("img", i) for i in range(120)]
    a = fa.sample_candidates(items, random.Random(fa.SEED), 50)
    b = fa.sample_candidates(items, random.Random(fa.SEED), 50)
    assert a == b
    assert len(a) == 50
    assert a == sorted(a)
    assert fa.sample_candidates(items[:3], random.Random(fa.SEED), 50) == items[:3]


def test_bootstrap_is_deterministic_and_brackets_the_estimate() -> None:
    num = [1, 0, 2, 0, 1, 3]
    den = [2, 2, 4, 1, 2, 5]
    a = fa.bootstrap_ratio_interval(num, den, seed=fa.SEED, n=fa.N_RESAMPLES)
    b = fa.bootstrap_ratio_interval(num, den, seed=fa.SEED, n=fa.N_RESAMPLES)
    assert a == b
    assert a.low <= a.share <= a.high
    assert 0.0 <= a.low and a.high <= 1.0


# ── refusals (never silently skipped) ───────────────────────────────────────────────────


def test_prediction_hash_mismatch_refuses_the_whole_analysis(tmp_path: Path) -> None:
    paths = build_coco(tmp_path, {"img1": (100, 100)}, {"img1": S_LABELS}, ["img1"], S_PREDS)
    with pytest.raises(fa.FailureAnalysisError, match="sha256"):
        run(paths, expected="0" * 64)


def test_missing_image_size_refuses_the_whole_analysis(tmp_path: Path) -> None:
    paths = build_coco(tmp_path, {"img1": (100, 100)}, {"img1": S_LABELS}, ["img1", "ghost"], S_PREDS)
    with pytest.raises(fa.FailureAnalysisError, match="ghost"):
        run(paths)


def test_unreadable_image_size_refuses_the_whole_analysis(tmp_path: Path) -> None:
    paths = build_coco(tmp_path, {"img1": (100, 100)}, {"img1": S_LABELS}, ["img1"], S_PREDS)
    (paths["images"] / "img1.jpg").write_bytes(b"not a jpeg")
    with pytest.raises(fa.FailureAnalysisError, match="img1"):
        run(paths)


def test_malformed_label_line_is_refused_not_skipped(tmp_path: Path) -> None:
    labels = {"img1": ["0 0.5 0.5 0.4"]}  # four fields, not five
    paths = build_coco(tmp_path, {"img1": (100, 100)}, labels, ["img1"], [])
    with pytest.raises(fa.FailureAnalysisError, match="malformed"):
        run(paths)


def test_prediction_for_an_unlisted_image_is_refused(tmp_path: Path) -> None:
    paths = build_coco(tmp_path, {"img1": (100, 100)}, {}, ["img1"], [pred("other", 1, 1, 2, 2, 0.9)])
    with pytest.raises(fa.FailureAnalysisError, match="other"):
        run(paths)


def test_zero_gt_images_are_not_refused_when_their_label_is_absent(tmp_path: Path) -> None:
    paths = build_coco(tmp_path, {"img1": (100, 100)}, {}, ["img1"], [])
    out = run(paths)
    assert out.analysis.gt_total == 0
    assert out.analysis.background_images == 1


# ── no ledger access; artifacts; limitations; DetectionEvidence preserved ──────────────


def test_analysis_never_touches_the_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_db(*_a, **_k):
        raise AssertionError("the analysis must not open any database")

    monkeypatch.setattr(sqlite3, "connect", no_db)
    paths = build_coco(tmp_path, {"img1": (100, 100)}, {"img1": S_LABELS}, ["img1"], S_PREDS)
    assert run(paths).analysis.gt_total == 4
    assert "sqlite" not in Path(fa.__file__).read_text(encoding="utf-8")


def test_required_coco_and_crowd_limitation_text_is_present() -> None:
    text = " ".join(fa.LIMITATIONS)
    assert "not official COCO" in text
    assert "instances_val2017.json" in text
    assert "iscrowd" in text
    assert "Q27" in text
    assert any("occlusion" in n and "crowd" in n for n in fa.NOT_MEASURED)


def test_detection_evidence_is_unchanged() -> None:
    names = [f.name for f in fields(DetectionEvidence)]
    assert names == [
        "predictions_path",
        "labels_dir",
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
        "small_fraction_in_missed",
        "high_density_image_count",
        "high_density_gt_fraction",
    ]


def test_failure_analysis_is_frozen_and_descriptive(scenario: fa.RunOutcome) -> None:
    assert scenario.analysis.descriptive_only is True
    with pytest.raises(Exception):
        scenario.analysis.gt_total = 99  # type: ignore[misc]


def test_report_states_descriptive_status_and_open_gates(scenario: fa.RunOutcome) -> None:
    text = fa.render_report({"EXP-20261004-01": scenario.analysis}, primary="EXP-20261004-01")
    for needle in ("descriptive", "Q30", "D-069", "not measured", "instances_val2017.json"):
        assert needle in text


def test_artifacts_are_written_without_claiming_human_labels(tmp_path: Path, scenario: fa.RunOutcome) -> None:
    out = tmp_path / "out"
    fa.write_artifacts(scenario, out, primary=True, images_dir=None)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["analysis"]["descriptive_only"] is True
    header = (out / "annotation_review_sample.csv").read_text().splitlines()[0]
    assert "human_label" in header.split(",") and "agent_label" not in header


def test_cli_module_is_importable_and_has_no_ledger_write() -> None:
    spec = importlib.util.spec_from_file_location("run_failure_analysis", REPO / "scripts" / "run_failure_analysis.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    source = (REPO / "scripts" / "run_failure_analysis.py").read_text(encoding="utf-8")
    assert "mode=ro" in source  # the only ledger read is read-only
    for write_statement in ("INSERT INTO", "UPDATE EXPERIMENTS", "DELETE FROM"):
        assert write_statement not in source.upper()
    assert "ExperimentLedger" not in source


def test_localization_categories_partition_every_gt_box(scenario: fa.RunOutcome) -> None:
    loc = scenario.analysis.localization
    assert sum(iv.count for iv in loc.values()) == scenario.analysis.gt_total
    assert loc["matched_at_reference"].count + loc["competed"].count + loc["near_miss"].count + loc["no_overlap"].count == 4
