"""scripts/compare_candidate.py: ledger-backed acceptance report (Issue #160, D-113).

Exit 0 meets criteria, 1 judged and failed, 2 cannot be judged. The ledger is never written.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from cv_agent.experiments.acceptance import OVERALL_AP_KEY, PRECISION_KEY, SMALL_AP_KEY
from cv_agent.experiments.models import ExperimentRecord
from cv_agent.experiments.store import open_ledger

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("compare_candidate", REPO / "scripts" / "compare_candidate.py")
assert _spec is not None and _spec.loader is not None
compare_candidate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_candidate)

SHA = "a" * 40
PROTOCOL = json.dumps({"confidence_protocol": "conf=0.001 (Q28/D-067) for mAP and AP@0.5/*"})
MODEL = "yolo11n (yolo11n.pt sha256 0123, 2,590,230 params, 6.4 GFLOPs as reported by ultralytics)"
BASE_ID = "EXP-20261004-01"
CAND_ID = "EXP-20261115-01"


def _record(exp_id: str, baseline_id: str, overall: float, small: float, fixed_p: float, **over: object) -> ExperimentRecord:
    fields: dict[str, object] = dict(
        exp_id=exp_id, status="completed", hypothesis="h", success_criteria="s", baseline_id=baseline_id,
        created_at="2026-10-14T00:00:00+00:00", completed_at="2026-10-14T01:00:00+00:00",
        commit=SHA, approval_ref="OWNER-APPROVAL-1", dataset_version="coco-val2017-5k",
        precision="FP16 requested", model=MODEL, input_resolution="640x640",
        val_metrics={OVERALL_AP_KEY: overall, SMALL_AP_KEY: small, PRECISION_KEY: fixed_p},
        notes=PROTOCOL,
    )
    fields.update(over)
    return ExperimentRecord(**fields)  # type: ignore[arg-type]


def _ledger(tmp_path: Path, *records: ExperimentRecord) -> Path:
    db = tmp_path / "experiments.sqlite"
    with open_ledger(db_path=db, create=True) as ledger:  # type: ignore[attr-defined]
        for record in records:
            ledger.record_experiment(record)
    return db


BASE = _record(BASE_ID, "SELF", 0.517, 0.3556, 0.7768)


def _cand(overall: float = 0.527, small: float = 0.3756, fixed_p: float = 0.76, **over: object) -> ExperimentRecord:
    over.setdefault("input_resolution", "960x960")
    return _record(CAND_ID, BASE_ID, overall, small, fixed_p, **over)


def _run(db: Path, *extra: str) -> int:
    return int(compare_candidate.main(["--candidate", CAND_ID, "--db", str(db), *extra]))


def _digest(db: Path) -> tuple[str, int]:
    return hashlib.sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns


def test_pass_exits_0_and_prints_verdict_and_margins(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = _ledger(tmp_path, BASE, _cand())
    assert _run(db) == 0
    out = capsys.readouterr().out
    assert "meets_provisional_criteria" in out
    for key in (OVERALL_AP_KEY, SMALL_AP_KEY, PRECISION_KEY):
        assert key in out
    assert "margin" in out and "D-113" in out
    assert "input_resolution" in out


def test_fail_on_precision_floor_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(_ledger(tmp_path, BASE, _cand(fixed_p=0.74))) == 1
    assert "does_not_meet_criteria" in capsys.readouterr().out


def test_fail_on_overall_gain_exits_1(tmp_path: Path) -> None:
    assert _run(_ledger(tmp_path, BASE, _cand(overall=0.521))) == 1


def test_fail_on_small_gain_exits_1(tmp_path: Path) -> None:
    assert _run(_ledger(tmp_path, BASE, _cand(small=0.3600))) == 1


@pytest.mark.parametrize("missing", ["candidate", "baseline"])
def test_missing_row_exits_2_and_names_the_id(tmp_path: Path, capsys: pytest.CaptureFixture[str], missing: str) -> None:
    rows = [BASE] if missing == "candidate" else [_cand()]
    assert _run(_ledger(tmp_path, *rows)) == 2
    err = capsys.readouterr().err
    assert (CAND_ID if missing == "candidate" else BASE_ID) in err


@pytest.mark.parametrize(
    "over",
    [{"precision": "FP32 requested"}, {"dataset_version": "other-set"}, {"model": "yolo11s (other)"}],
)
def test_difference_other_than_input_resolution_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str], over: dict[str, str]) -> None:
    assert _run(_ledger(tmp_path, BASE, _cand(**over))) == 2
    assert "invalid" in capsys.readouterr().out


def test_unchanged_input_resolution_is_not_a_valid_variable_exits_2(tmp_path: Path) -> None:
    assert _run(_ledger(tmp_path, BASE, _cand(input_resolution="640x640"))) == 2


def test_ledger_is_byte_unchanged_by_every_outcome(tmp_path: Path) -> None:
    db = _ledger(tmp_path, BASE, _cand())
    before = _digest(db)
    assert _run(db) == 0
    assert _digest(db) == before
    (tmp_path / "b").mkdir()
    db2 = _ledger(tmp_path / "b", BASE, _cand(fixed_p=0.5))
    before2 = _digest(db2)
    assert _run(db2) == 1
    assert _digest(db2) == before2


def test_missing_ledger_file_exits_2_and_creates_nothing(tmp_path: Path) -> None:
    db = tmp_path / "nope" / "experiments.sqlite"
    assert _run(db) == 2
    assert not db.exists() and not db.parent.exists()
