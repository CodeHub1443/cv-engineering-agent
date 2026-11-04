"""Tests for cv_agent.experiments.acceptance (ADR-0019, D-077, D-078). Pure; no GPU, no I/O."""

from __future__ import annotations

import json

import pytest

from cv_agent.experiments.acceptance import (
    D077_PRECISION_FLOOR,
    OVERALL_AP_KEY,
    PRECISION_KEY,
    SMALL_AP_KEY,
    AcceptanceCriteria,
    evaluate_candidate,
)
from cv_agent.experiments.evaluation_records import PRECISION_FP32_REQUESTED, PRECISION_REQUESTED
from cv_agent.experiments.models import ExperimentRecord

SHA = "a" * 40
PROTOCOL = json.dumps({"confidence_protocol": "conf=0.001 (Q28/D-067) for mAP and AP@0.5/*"})
MODEL = "yolo11n (yolo11n.pt sha256 0123, 2,590,230 params, 6.4 GFLOPs as reported by ultralytics)"


def _record(exp_id: str, baseline_id: str, overall: float, small: float, fixed_precision: float, **over) -> ExperimentRecord:
    fields = dict(
        exp_id=exp_id,
        status="completed",
        hypothesis="h",
        success_criteria="s",
        baseline_id=baseline_id,
        created_at="2026-10-14T00:00:00+00:00",
        completed_at="2026-10-14T01:00:00+00:00",
        commit=SHA,
        approval_ref="OWNER-APPROVAL-1",
        dataset_version="coco-val2017-5k",
        precision="FP32",
        model=MODEL,
        input_resolution="640x640",
        val_metrics={OVERALL_AP_KEY: overall, SMALL_AP_KEY: small, PRECISION_KEY: fixed_precision},
        notes=PROTOCOL,
    )
    fields.update(over)
    return ExperimentRecord(**fields)  # type: ignore[arg-type]


BASE = _record("EXP-20261004-01", "SELF", 0.517, 0.3556, 0.7768)


def test_both_gains_and_floor_met_is_provisional_pass_not_winner() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.527, 0.3756, 0.76)
    report = evaluate_candidate(BASE, cand)
    assert report.verdict == "meets_provisional_criteria"
    assert report.ok and report.gains_provisional
    assert any("provisional" in c for c in report.caveats)


def test_only_overall_improves_fails() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.540, 0.3556, 0.80)
    report = evaluate_candidate(BASE, cand)
    assert report.verdict == "does_not_meet_criteria"
    failed = {c.name for c in report.criteria if not c.passed}
    assert failed == {SMALL_AP_KEY}


def test_only_small_improves_fails() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.517, 0.40, 0.80)
    failed = {c.name for c in evaluate_candidate(BASE, cand).criteria if not c.passed}
    assert failed == {OVERALL_AP_KEY}


def test_precision_floor_fails_even_when_both_aps_improve() -> None:
    # Mirrors the recorded imgsz-960 run: AP up, precision 0.727 < 0.75.
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.532, 0.4589, 0.7273)
    report = evaluate_candidate(BASE, cand)
    assert report.verdict == "does_not_meet_criteria"
    failed = {c.name for c in report.criteria if not c.passed}
    assert failed == {PRECISION_KEY}
    assert next(c for c in report.criteria if c.name == PRECISION_KEY).protocol.endswith("not mAP")


def test_protocols_are_labelled_separately() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.527, 0.3756, 0.76)
    protocols = {c.name: c.protocol for c in evaluate_candidate(BASE, cand).criteria}
    assert "full-curve AP" in protocols[OVERALL_AP_KEY]
    assert "full-curve AP" in protocols[SMALL_AP_KEY]
    assert "fixed-threshold" in protocols[PRECISION_KEY]


def test_precision_exactly_at_floor_passes() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.527, 0.3756, 0.75)
    assert evaluate_candidate(BASE, cand).ok


def test_missing_metric_is_invalid() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.527, 0.3756, 0.76,
                   val_metrics={OVERALL_AP_KEY: 0.527, SMALL_AP_KEY: 0.3756})
    report = evaluate_candidate(BASE, cand)
    assert report.verdict == "invalid"
    assert any(PRECISION_KEY in p for p in report.problems)


def test_ap_key_is_not_substituted_for_precision() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.9, 0.9, 0.9,
                   val_metrics={OVERALL_AP_KEY: 0.9, SMALL_AP_KEY: 0.9, "mAP@0.5": 0.99})
    assert evaluate_candidate(BASE, cand).verdict == "invalid"


def test_baseline_mismatch_is_invalid() -> None:
    cand = _record("EXP-20261014-01", "EXP-20261004-02", 0.6, 0.6, 0.9)
    assert evaluate_candidate(BASE, cand).verdict == "invalid"


def test_dataset_mismatch_is_invalid() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.6, 0.6, 0.9, dataset_version="other")
    assert evaluate_candidate(BASE, cand).verdict == "invalid"


def test_non_completed_candidate_is_invalid() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.6, 0.6, 0.9, status="running", completed_at=None)
    report = evaluate_candidate(BASE, cand)
    assert report.verdict == "invalid" and any("not 'completed'" in p for p in report.problems)


def test_missing_provenance_is_invalid() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.6, 0.6, 0.9, commit=None)
    report = evaluate_candidate(BASE, cand)
    assert report.verdict == "invalid" and any("commit" in p for p in report.problems)


def test_truncated_curve_protocol_is_invalid() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.6, 0.6, 0.9,
                   notes=json.dumps({"confidence_protocol": "conf=0.25 truncated"}))
    assert evaluate_candidate(BASE, cand).verdict == "invalid"


def test_same_record_is_invalid() -> None:
    assert evaluate_candidate(BASE, BASE).verdict == "invalid"


def test_criteria_validate() -> None:
    with pytest.raises(ValueError):
        AcceptanceCriteria(min_small_gain=0.0)
    with pytest.raises(ValueError):
        AcceptanceCriteria(min_precision=1.5)


# --- H2: like-for-like comparison ------------------------------------------------------------

def _ledger_pair() -> tuple[ExperimentRecord, ExperimentRecord]:
    """Shaped like EXP-20261004-01 (FP16 requested, 640) and EXP-20261004-04 (FP32 requested, 640)."""
    base = _record("EXP-20261004-01", "SELF", 0.517, 0.3556, 0.7768, precision=PRECISION_REQUESTED)
    cand = _record("EXP-20261004-04", "EXP-20261004-01", 0.518, 0.3547, 0.776,
                   precision=PRECISION_FP32_REQUESTED)
    return base, cand


def test_undeclared_precision_difference_is_invalid() -> None:
    base, cand = _ledger_pair()
    report = evaluate_candidate(base, cand)
    assert report.verdict == "invalid"
    assert any(p.startswith("precision differs") and "not the declared variable" in p for p in report.problems)


def test_declared_precision_difference_is_listed_not_ignored() -> None:
    base, cand = _ledger_pair()
    report = evaluate_candidate(base, cand, variable_under_test="precision")
    assert report.verdict == "does_not_meet_criteria"  # compared; the gains are too small
    assert report.variable_under_test == "precision"
    assert len(report.declared_differences) == 1 and "FP32 requested" in report.declared_differences[0]


@pytest.mark.parametrize("field_name,value", [("input_resolution", "960x960"), ("model", "yolo11s")])
def test_undeclared_resolution_or_model_difference_is_invalid(field_name: str, value: str) -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.6, 0.6, 0.9, **{field_name: value})
    report = evaluate_candidate(BASE, cand)
    assert report.verdict == "invalid"
    assert any(p.startswith(f"{field_name} differs") for p in report.problems)


def test_declared_resolution_in_imgsz_series_is_evaluated() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.532, 0.4589, 0.7273, input_resolution="960x960")
    report = evaluate_candidate(BASE, cand, variable_under_test="input_resolution")
    assert report.verdict == "does_not_meet_criteria"  # precision floor, not the comparison
    assert "640x640" in report.declared_differences[0] and "960x960" in report.declared_differences[0]


def test_declared_variable_that_does_not_differ_is_invalid() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.6, 0.6, 0.9)
    report = evaluate_candidate(BASE, cand, variable_under_test="precision")
    assert report.verdict == "invalid" and any("does not differ" in p for p in report.problems)


def test_dataset_version_cannot_be_declared_as_variable() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.6, 0.6, 0.9, dataset_version="other")
    report = evaluate_candidate(BASE, cand, variable_under_test="dataset_version")
    assert report.verdict == "invalid" and any("not declarable" in p for p in report.problems)


@pytest.mark.parametrize("field_name", ["model", "input_resolution"])
def test_unrecorded_comparison_field_is_invalid(field_name: str) -> None:
    base = _record("EXP-20261004-01", "SELF", 0.517, 0.3556, 0.7768, **{field_name: None})
    cand = _record("EXP-20261014-01", base.exp_id, 0.6, 0.6, 0.9, **{field_name: None})
    report = evaluate_candidate(base, cand)
    assert report.verdict == "invalid" and any(f"missing {field_name}" in p for p in report.problems)


# --- M1: the D-077 / D-078 basis cannot be silently changed ----------------------------------

def _passing_candidate() -> ExperimentRecord:
    return _record("EXP-20261014-01", BASE.exp_id, 0.527, 0.3756, 0.76)


def test_default_floor_is_the_named_d077_constant_and_has_no_deviation() -> None:
    assert D077_PRECISION_FLOOR == 0.75 and AcceptanceCriteria().min_precision == D077_PRECISION_FLOOR
    report = evaluate_candidate(BASE, _passing_candidate())
    assert report.deviations == () and report.ok


def test_weakened_floor_is_a_deviation_and_never_reads_as_the_basis() -> None:
    report = evaluate_candidate(BASE, _passing_candidate(), AcceptanceCriteria(min_precision=0.70))
    assert report.verdict == "meets_criteria_with_deviations"
    assert not report.ok
    assert any("D-077" in d for d in report.deviations)
    assert any("not the approved D-077 floor" in c for c in report.caveats)


def test_non_provisional_flag_is_a_deviation_and_caveat_follows_the_flag() -> None:
    report = evaluate_candidate(BASE, _passing_candidate(), AcceptanceCriteria(gains_provisional=False))
    assert report.verdict == "meets_criteria_with_deviations" and not report.ok
    assert any("gains_provisional=False" in d for d in report.deviations)
    assert not any("are provisional acceptance thresholds" in c for c in report.caveats)
    assert any("NOT the D-078 basis" in c for c in report.caveats)


def test_changed_gain_is_a_deviation() -> None:
    report = evaluate_candidate(BASE, _passing_candidate(), AcceptanceCriteria(min_overall_gain=0.005))
    assert not report.ok and any("D-078" in d for d in report.deviations)


def test_failing_candidate_with_deviation_still_lists_it() -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.517, 0.3556, 0.76)
    report = evaluate_candidate(BASE, cand, AcceptanceCriteria(min_precision=0.70))
    assert report.verdict == "does_not_meet_criteria" and report.deviations


# --- L1: exact protocol token ----------------------------------------------------------------

@pytest.mark.parametrize("text", ["conf=0.0015 full curve", "conf=0.00100001", "conf=10.001"])
def test_near_miss_protocol_token_is_rejected(text: str) -> None:
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.6, 0.6, 0.9,
                   notes=json.dumps({"confidence_protocol": text}))
    assert evaluate_candidate(BASE, cand).verdict == "invalid"


def test_real_ledger_protocol_text_is_accepted() -> None:
    text = ("conf=0.001 (Q28/D-067) for mAP and AP@0.5/* (full PR curve). "
            "fixed_thr@0.25/* are REFERENCE ONLY: not mAP, not an operating point (Q30 open).")
    cand = _record("EXP-20261014-01", BASE.exp_id, 0.527, 0.3756, 0.76,
                   notes=json.dumps({"confidence_protocol": text}))
    assert evaluate_candidate(BASE, cand).ok


# --- L2: a non-finite metric is invalid evidence ---------------------------------------------

@pytest.mark.parametrize("role,key", [("candidate", PRECISION_KEY), ("candidate", OVERALL_AP_KEY),
                                      ("baseline", SMALL_AP_KEY)])
def test_nan_metric_is_invalid_not_a_failed_criterion(role: str, key: str) -> None:
    base = _record("EXP-20261004-01", "SELF", 0.517, 0.3556, 0.7768)
    cand = _passing_candidate()
    target = cand if role == "candidate" else base
    assert target.val_metrics is not None
    target.val_metrics[key] = float("nan")  # the dict is mutable after validation
    report = evaluate_candidate(base, cand)
    assert report.verdict == "invalid" and any("not a finite number" in p for p in report.problems)
