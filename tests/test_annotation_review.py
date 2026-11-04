"""Annotation-label review workflow (issue #75). Synthetic fixtures only: no real review, no GPU, no ledger."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest
from PIL import Image

from cv_agent.diagnosis import annotation_review as ar

REPO = Path(__file__).resolve().parent.parent
PER_GT_HEADER = [
    "image_stem", "gt_index", "x1", "y1", "x2", "y2", "norm_area", "size_bin", "density",
    "fully_missed", "missed_at_reference", "best_iou_any", "best_iou_reference", "localization",
    "degenerate", "near_dup_partners",
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def fixture_tree(tmp_path: Path) -> dict[str, Path]:
    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGB", (100, 100), (90, 120, 60)).save(images / "img1.jpg", "JPEG")
    per_gt = tmp_path / "per_gt.csv"
    with per_gt.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(PER_GT_HEADER)
        writer.writerow(["img1", 0, 10, 10, 11.5, 11, 0.0002, "small", "sparse", True, True, 0.0, 0.0, "no_overlap", True, ""])
        writer.writerow(["img1", 1, 40, 40, 60, 60, 0.04, "medium", "sparse", False, False, 0.9, 0.9, "matched_at_reference", False, "2;"])
        writer.writerow(["img1", 2, 41, 41, 61, 61, 0.04, "medium", "sparse", False, True, 0.8, 0.5, "competed", False, "1;"])
    sample = tmp_path / "annotation_review_sample.csv"
    with sample.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(ar.ORIGINAL_COLUMNS))
        writer.writerow(["high_conf_fp", 1, "img1", "img1:0", "[[70, 70, 90, 90]]", "crop1.png", "", ""])
        writer.writerow(["near_dup_gt_pair", 1, "img1", "img1:1:2", "[[40, 40, 60, 60], [41, 41, 61, 61]]", "crop2.png", "", ""])
        writer.writerow(["degenerate_gt", 1, "img1", "img1:0", "[[10, 10, 11.5, 11]]", "crop3.png", "", ""])
    return {"images": images, "per_gt": per_gt, "sample": sample, "views": tmp_path / "review_views"}


def _prepare(tree: dict[str, Path]) -> ar.PrepareResult:
    return ar.prepare_review(
        sample_csv=tree["sample"],
        per_gt_csv=tree["per_gt"],
        images_dir=tree["images"],
        views_dir=tree["views"],
    )


# ── enlarged review views ─────────────────────────────────────────────────────────────


def test_enlarged_views_are_generated_for_every_candidate(fixture_tree: dict[str, Path]) -> None:
    result = _prepare(fixture_tree)
    assert result.views == 3
    names = sorted(p.name for p in fixture_tree["views"].glob("*.png"))
    assert names == [
        "degenerate_gt_001_img1.png",
        "high_conf_fp_001_img1.png",
        "near_dup_gt_pair_001_img1.png",
    ]


def test_each_view_has_full_image_and_a_larger_enlarged_panel(fixture_tree: dict[str, Path]) -> None:
    _prepare(fixture_tree)
    view = Image.open(fixture_tree["views"] / "degenerate_gt_001_img1.png")
    # full image (100 px) + gap + enlarged region: the composite must be wider than the full image alone
    assert view.width > 100 + 16
    assert view.height > 26  # header strip present


def test_candidate_boxes_are_drawn_in_a_distinct_colour(fixture_tree: dict[str, Path]) -> None:
    _prepare(fixture_tree)
    view = Image.open(fixture_tree["views"] / "high_conf_fp_001_img1.png").convert("RGB")
    colours = {colour for _, colour in view.getcolors(maxcolors=10**7)}
    assert ar.CANDIDATE_COLOR in colours and ar.GT_COLOR in colours


def test_source_images_are_not_modified(fixture_tree: dict[str, Path]) -> None:
    before = _sha(fixture_tree["images"] / "img1.jpg")
    _prepare(fixture_tree)
    assert _sha(fixture_tree["images"] / "img1.jpg") == before


def test_view_name_mapping_is_deterministic() -> None:
    row = {"candidate_class": "near_dup_gt_pair", "rank": "1", "image_stem": "img1"}
    assert ar.review_view_name(row) == "near_dup_gt_pair_001_img1.png"
    assert ar.review_view_name(row) == ar.review_view_name(dict(row))


def test_views_are_identical_when_regenerated(fixture_tree: dict[str, Path]) -> None:
    _prepare(fixture_tree)
    first = _sha(fixture_tree["views"] / "high_conf_fp_001_img1.png")
    fixture_tree["sample"].unlink()
    # rebuild the input and regenerate: the same candidate must map to the same view with the same pixels
    with fixture_tree["sample"].open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(ar.ORIGINAL_COLUMNS))
        writer.writerow(["high_conf_fp", 1, "img1", "img1:0", "[[70, 70, 90, 90]]", "crop1.png", "", ""])
    (fixture_tree["views"] / "high_conf_fp_001_img1.png").unlink()
    _prepare(fixture_tree)
    assert _sha(fixture_tree["views"] / "high_conf_fp_001_img1.png") == first


# ── CSV schema, reviewer metadata, no automatic labels ─────────────────────────────────


def test_csv_keeps_original_columns_and_appends_the_new_ones(fixture_tree: dict[str, Path]) -> None:
    _prepare(fixture_tree)
    with fixture_tree["sample"].open(newline="") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or [])
        rows = list(reader)
    assert header == [*ar.ORIGINAL_COLUMNS, *ar.ADDED_COLUMNS]
    assert [r["candidate_class"] for r in rows] == ["high_conf_fp", "near_dup_gt_pair", "degenerate_gt"]
    assert rows[0]["boxes"] == "[[70, 70, 90, 90]]"  # original values are unchanged


def test_prepare_writes_no_human_label_and_no_suggestion(fixture_tree: dict[str, Path]) -> None:
    _prepare(fixture_tree)
    rows = ar.load_review_rows(fixture_tree["sample"])
    assert all(r["human_label"] == "" for r in rows)
    assert all(r["human_notes"] == "" for r in rows)
    assert all(r["suggested_label_preliminary"] == "" for r in rows)
    assert all(r["review_date"] == "" for r in rows)
    assert ar.validate_rows(rows) == []


def test_reviewer_and_rubric_metadata_are_recorded(fixture_tree: dict[str, Path]) -> None:
    _prepare(fixture_tree)
    rows = ar.load_review_rows(fixture_tree["sample"])
    assert all(r["reviewer_id"] == "Tanvir" for r in rows)
    assert all(r["rubric_version"] == ar.RUBRIC_VERSION for r in rows)


def test_crowd_status_reflects_unresolved_q27(fixture_tree: dict[str, Path]) -> None:
    _prepare(fixture_tree)
    rows = ar.load_review_rows(fixture_tree["sample"])
    assert all(r["crowd_status"] == ar.CROWD_STATUS_UNRESOLVED for r in rows)


def test_prepare_refuses_to_overwrite_existing_human_entries(fixture_tree: dict[str, Path]) -> None:
    _prepare(fixture_tree)
    rows = ar.load_review_rows(fixture_tree["sample"])
    rows[0]["human_label"] = "valid_annotation"
    with fixture_tree["sample"].open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ar.ReviewError, match="already contain human entries"):
        _prepare(fixture_tree)


def test_prepare_refuses_a_changed_schema(fixture_tree: dict[str, Path]) -> None:
    text = fixture_tree["sample"].read_text().replace("candidate_class", "class_name", 1)
    fixture_tree["sample"].write_text(text)
    with pytest.raises(ar.ReviewError, match="do not match"):
        _prepare(fixture_tree)


# ── allowed labels, reviewer requirement, Q27, suggestions ─────────────────────────────


def _row(**overrides: str) -> dict[str, str]:
    base = {
        "candidate_class": "high_conf_fp",
        "rank": "1",
        "image_stem": "img1",
        "human_label": "",
        "human_notes": "",
        "reviewer_id": "Tanvir",
        "review_date": "2026-10-06",
        "rubric_version": ar.RUBRIC_VERSION,
        "crowd_status": ar.CROWD_STATUS_UNRESOLVED,
        "suggested_label_preliminary": "",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("label", list(ar.ALLOWED_LABELS))
def test_each_allowed_label_is_admissible_with_reviewer_metadata(label: str) -> None:
    assert ar.validate_rows([_row(human_label=label)]) == []


def test_a_label_outside_the_allowed_set_is_refused() -> None:
    problems = ar.validate_rows([_row(human_label="maybe")])
    assert any("not an allowed label" in p for p in problems)


def test_a_label_without_reviewer_or_date_is_refused() -> None:
    problems = ar.validate_rows([_row(human_label="annotation_error", reviewer_id="", review_date="")])
    assert any("reviewer_id" in p for p in problems)
    assert any("review_date" in p for p in problems)


def test_a_label_under_another_rubric_version_is_refused() -> None:
    problems = ar.validate_rows([_row(human_label="ambiguous", rubric_version="v0")])
    assert any("rubric_version" in p for p in problems)


def test_crowd_exclusion_is_refused_while_q27_is_unresolved() -> None:
    problems = ar.validate_rows([_row(crowd_status="crowd_annotation_excluded")])
    assert any("not allowed while Q27 is unresolved" in p for p in problems)


def test_a_suggestion_cannot_become_the_human_label() -> None:
    problems = ar.validate_rows([_row(human_label="annotation_error", suggested_label_preliminary="annotation_error")])
    assert any("must not be copied" in p for p in problems)


# ── report generation (pending state) ─────────────────────────────────────────────────


def test_report_states_scope_limits_and_open_gates(fixture_tree: dict[str, Path]) -> None:
    _prepare(fixture_tree)
    text = ar.render_review_report(ar.load_review_rows(fixture_tree["sample"]))
    for needle in (
        "does not test the small-box bottleneck directly",
        "not a representative sample",
        "Q27",
        "Q30",
        "D-069",
        "No production decision is made",
        "pending",
        ar.RUBRIC_VERSION,
    ):
        assert needle in text


def test_report_counts_by_class_and_pending_labels(fixture_tree: dict[str, Path]) -> None:
    _prepare(fixture_tree)
    text = ar.render_review_report(ar.load_review_rows(fixture_tree["sample"]))
    assert "- high_conf_fp: 1" in text
    assert "- near_dup_gt_pair: 1" in text
    assert "- degenerate_gt: 1" in text
    assert "- pending: 3" in text
    assert "Candidates with crowd status `q27_unresolved`: 3 of 3" in text


def test_report_does_not_claim_a_crowd_exclusion(fixture_tree: dict[str, Path]) -> None:
    _prepare(fixture_tree)
    text = ar.render_review_report(ar.load_review_rows(fixture_tree["sample"]))
    assert "crowd_annotation_excluded" not in text
    assert "instances_val2017.json` has not been downloaded" in text


# ── no ledger access; CLI module ───────────────────────────────────────────────────────


def test_no_ledger_access_during_prepare_or_report(fixture_tree: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    def no_db(*_a, **_k):
        raise AssertionError("the review workflow must not open a database")

    monkeypatch.setattr(sqlite3, "connect", no_db)
    _prepare(fixture_tree)
    ar.render_review_report(ar.load_review_rows(fixture_tree["sample"]))
    assert "sqlite" not in Path(ar.__file__).read_text(encoding="utf-8")


def test_cli_is_read_only_with_respect_to_the_ledger_and_coco_download() -> None:
    spec = importlib.util.spec_from_file_location("run_annotation_review", REPO / "scripts" / "run_annotation_review.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    source = (REPO / "scripts" / "run_annotation_review.py").read_text(encoding="utf-8")
    for write_statement in ("INSERT INTO", "UPDATE EXPERIMENTS", "DELETE FROM"):
        assert write_statement not in source.upper()
    assert "urllib" not in source and "requests" not in source  # no network access, so no COCO download
    assert "sqlite" not in source.lower()


def test_a_candidate_on_a_background_image_gets_a_view_with_zero_gt_context(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGB", (100, 100), (90, 120, 60)).save(images / "bg1.jpg", "JPEG")
    per_gt = tmp_path / "per_gt.csv"
    per_gt.write_text(",".join(PER_GT_HEADER) + "\n")  # no GT rows at all
    sample = tmp_path / "annotation_review_sample.csv"
    with sample.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(ar.ORIGINAL_COLUMNS))
        writer.writerow(["high_conf_fp", 1, "bg1", "bg1:0", "[[30, 30, 50, 50]]", "crop.png", "", ""])
    result = ar.prepare_review(sample_csv=sample, per_gt_csv=per_gt, images_dir=images, views_dir=tmp_path / "v")
    assert result.views == 1
    assert (tmp_path / "v" / "high_conf_fp_001_bg1.png").is_file()
