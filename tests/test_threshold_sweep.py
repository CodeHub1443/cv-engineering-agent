"""
tests/test_threshold_sweep.py — Unit tests for confidence-threshold sweep (D-065, issue #72).

Tests the sweep configuration functions and proposed-record construction
without any GPU activity or real filesystem access.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import sweep helpers without executing __main__ block
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _load_sweep_module():
    """Load run_threshold_sweep.py as a module without running its __main__."""
    spec = importlib.util.spec_from_file_location(
        "run_threshold_sweep", _SCRIPTS_DIR / "run_threshold_sweep.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("run_threshold_sweep", mod)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_sweep = _load_sweep_module()

SweepConfig = _sweep.SweepConfig
_build_sweep_configs = _sweep._build_sweep_configs
_hypothesis = _sweep._hypothesis
_success_criteria = _sweep._success_criteria
_make_proposed_record = _sweep._make_proposed_record
BASELINE_EXP_ID = _sweep.BASELINE_EXP_ID
SWEEP_CONFS = _sweep.SWEEP_CONFS


# ---------------------------------------------------------------------------
# TestBuildSweepConfigs
# ---------------------------------------------------------------------------


class TestBuildSweepConfigs:
    def test_returns_four_configs(self):
        configs = _build_sweep_configs()
        assert len(configs) == 4

    def test_exp_ids_are_distinct(self):
        configs = _build_sweep_configs()
        ids = [c.exp_id for c in configs]
        assert len(set(ids)) == 4

    def test_exp_ids_match_format(self):
        import re
        pattern = re.compile(r"^EXP-\d{8}-\d{2}$")
        for cfg in _build_sweep_configs():
            assert pattern.match(cfg.exp_id), f"bad exp_id: {cfg.exp_id!r}"

    def test_exp_ids_use_20261001_date(self):
        for cfg in _build_sweep_configs():
            assert cfg.exp_id.startswith("EXP-20261001-"), cfg.exp_id

    def test_exp_ids_numbered_01_through_04(self):
        ids = [c.exp_id for c in _build_sweep_configs()]
        assert ids == [
            "EXP-20261001-01",
            "EXP-20261001-02",
            "EXP-20261001-03",
            "EXP-20261001-04",
        ]

    def test_confs_match_sweep_confs(self):
        configs = _build_sweep_configs()
        confs = [c.conf for c in configs]
        assert confs == pytest.approx(SWEEP_CONFS)

    def test_confs_ordered_ascending(self):
        confs = [c.conf for c in _build_sweep_configs()]
        assert confs == sorted(confs)

    def test_run_names_are_distinct(self):
        configs = _build_sweep_configs()
        names = [c.run_name for c in configs]
        assert len(set(names)) == 4

    def test_run_names_contain_conf_tag(self):
        mapping = {0.10: "010", 0.15: "015", 0.25: "025", 0.50: "050"}
        for cfg in _build_sweep_configs():
            expected_tag = mapping[cfg.conf]
            assert expected_tag in cfg.run_name, (
                f"run_name={cfg.run_name!r} should contain tag {expected_tag!r}"
            )

    def test_control_is_conf_025(self):
        configs = _build_sweep_configs()
        control = next((c for c in configs if abs(c.conf - 0.25) < 1e-9), None)
        assert control is not None, "no control config at conf=0.25"
        assert control.exp_id == "EXP-20261001-03"

    def test_configs_are_frozen(self):
        cfg = _build_sweep_configs()[0]
        with pytest.raises((AttributeError, TypeError)):
            cfg.conf = 0.99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestHypothesisAndCriteria
# ---------------------------------------------------------------------------


class TestHypothesisAndCriteria:
    def test_hypothesis_non_blank(self):
        for conf in SWEEP_CONFS:
            h = _hypothesis(conf)
            assert h and h.strip()

    def test_hypothesis_mentions_baseline(self):
        for conf in SWEEP_CONFS:
            assert BASELINE_EXP_ID in _hypothesis(conf)

    def test_hypothesis_mentions_conf(self):
        for conf in SWEEP_CONFS:
            assert f"conf={conf:.2f}" in _hypothesis(conf)

    def test_hypothesis_control_mentions_control(self):
        h = _hypothesis(0.25)
        assert "control" in h.lower()

    def test_non_control_does_not_say_control(self):
        for conf in [0.10, 0.15, 0.50]:
            assert "control" not in _hypothesis(conf).lower()

    def test_success_criteria_mentions_exp_id(self):
        for cfg in _build_sweep_configs():
            sc = _success_criteria(cfg.exp_id)
            assert cfg.exp_id in sc

    def test_success_criteria_non_blank(self):
        for cfg in _build_sweep_configs():
            sc = _success_criteria(cfg.exp_id)
            assert sc and sc.strip()


# ---------------------------------------------------------------------------
# TestProposedRecordConstruction
# ---------------------------------------------------------------------------


class TestProposedRecordConstruction:
    _created_at = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat()

    def _records(self):
        return [
            _make_proposed_record(cfg, created_at=self._created_at, commit="abc1234")
            for cfg in _build_sweep_configs()
        ]

    def test_all_four_records_valid(self):
        records = self._records()
        assert len(records) == 4

    def test_status_is_proposed(self):
        for rec in self._records():
            assert rec.status == "proposed"

    def test_baseline_id_is_correct(self):
        for rec in self._records():
            assert rec.baseline_id == BASELINE_EXP_ID

    def test_parent_exp_id_is_baseline(self):
        for rec in self._records():
            assert rec.parent_exp_id == BASELINE_EXP_ID

    def test_exp_ids_are_distinct(self):
        ids = [r.exp_id for r in self._records()]
        assert len(set(ids)) == 4

    def test_no_completed_at_for_proposed(self):
        for rec in self._records():
            assert rec.completed_at is None

    def test_dataset_version_is_coco_val2017(self):
        for rec in self._records():
            assert rec.dataset_version == "coco-val2017-5k"

    def test_model_is_yolo11n(self):
        for rec in self._records():
            assert rec.model is not None
            assert "yolo11n" in rec.model

    def test_batch_size_is_one(self):
        for rec in self._records():
            assert rec.batch_size == 1

    def test_input_resolution_640(self):
        for rec in self._records():
            assert rec.input_resolution is not None
            assert "640" in rec.input_resolution

    def test_commit_stored(self):
        for rec in self._records():
            assert rec.commit == "abc1234"

    def test_commit_none_allowed(self):
        cfg = _build_sweep_configs()[0]
        rec = _make_proposed_record(cfg, created_at=self._created_at, commit=None)
        assert rec.commit is None

    def test_notes_mention_conf(self):
        for cfg, rec in zip(_build_sweep_configs(), self._records()):
            assert f"conf={cfg.conf:.2f}" in rec.notes

    def test_notes_mention_baseline(self):
        for rec in self._records():
            assert BASELINE_EXP_ID in rec.notes

    def test_baseline_exp_id_not_in_exp_ids(self):
        """EXP-20260930-01 must not be overwritten — records use 20261001 IDs."""
        for rec in self._records():
            assert rec.exp_id != BASELINE_EXP_ID

    def test_val_metrics_none_for_proposed(self):
        for rec in self._records():
            assert rec.val_metrics is None

    def test_records_are_frozen(self):
        rec = self._records()[0]
        with pytest.raises((AttributeError, TypeError)):
            rec.status = "running"  # type: ignore[misc]
