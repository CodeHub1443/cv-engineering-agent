"""Tests for cv_agent.experiments.acceptance (ADR-0019, D-077, D-078). Pure; no GPU, no I/O."""

from __future__ import annotations

import json

import pytest

from cv_agent.experiments.acceptance import (
    OVERALL_AP_KEY,
    PRECISION_KEY,
    SMALL_AP_KEY,
    AcceptanceCriteria,
    evaluate_candidate,
)
from cv_agent.experiments.models import ExperimentRecord

SHA = "a" * 40
PROTOCOL = json.dumps({"confidence_protocol": "conf=0.001 (Q28/D-067) for mAP and AP@0.5/*"})


def _record(exp_id: str, baseline_id: str, overall: float, small: float, precision: float, **over) -> ExperimentRecord:
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
        val_metrics={OVERALL_AP_KEY: overall, SMALL_AP_KEY: small, PRECISION_KEY: precision},
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
