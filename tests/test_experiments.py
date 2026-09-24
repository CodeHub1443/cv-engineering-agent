"""Tests for cv_agent.experiments (ADR-0011, Q16 SQLite Experiment Ledger)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cv_agent.experiments.models import (
    ExperimentRecord,
    HardwareInfo,
    LatencyMeasurement,
    MemoryFootprint,
)
from cv_agent.experiments.sqlite_store import SqliteExperimentLedger
from cv_agent.experiments.store import (
    ExperimentLedger,
    ExperimentLedgerError,
    default_db_path,
    open_ledger,
)


def _record(**overrides: object) -> ExperimentRecord:
    fields: dict[str, object] = {
        "exp_id": "EXP-20260901-01",
        "status": "proposed",
        "hypothesis": "INT8 quantization halves latency with < 1pt mAP drop",
        "success_criteria": "mAP@.5:.95 drop <= 1.0pt, latency <= 50% of FP16 baseline",
        "baseline_id": "SELF",
        "created_at": "2026-09-01T10:00:00",
    }
    fields.update(overrides)
    return ExperimentRecord(**fields)  # type: ignore[arg-type]


def _completed_record(**overrides: object) -> ExperimentRecord:
    fields: dict[str, object] = {
        "status": "completed",
        "completed_at": "2026-09-01T12:00:00",
    }
    fields.update(overrides)
    return _record(**fields)


# ── Domain: ExperimentRecord validation ─────────────────────────────────────


class TestExperimentRecordValidation:
    def test_valid_minimal_record_constructs(self) -> None:
        record = _record()
        assert record.exp_id == "EXP-20260901-01"
        assert record.is_terminal() is False

    def test_valid_full_record_constructs(self) -> None:
        record = _completed_record(
            model="yolov8n",
            dataset_version="ds-v3",
            hardware=HardwareInfo(training="A100x1", target="Jetson Orin NX"),
            latency=LatencyMeasurement(end_to_end=42.0, inference_only=18.5),
            memory=MemoryFootprint(vram=1800.0, ram=512.0),
            val_metrics={"mAP@.5:.95": 0.41},
            test_metrics={"mAP@.5:.95": 0.40},
            gpu_hours=2.5,
            fps=55.0,
            power=12.3,
        )
        assert record.hardware.target == "Jetson Orin NX"  # type: ignore[union-attr]
        assert record.latency.inference_only == 18.5  # type: ignore[union-attr]
        assert record.is_terminal() is True

    @pytest.mark.parametrize(
        "exp_id",
        ["", "not-an-id", "EXP-2026-01", "EXP-202609011-01", "exp-20260901-01"],
    )
    def test_invalid_exp_id_rejected(self, exp_id: str) -> None:
        with pytest.raises(ValueError):
            _record(exp_id=exp_id)

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(status="in_progress")

    @pytest.mark.parametrize("field", ["hypothesis", "success_criteria", "baseline_id"])
    def test_required_field_blank_rejected(self, field: str) -> None:
        with pytest.raises(ValueError):
            _record(**{field: ""})

    def test_baseline_id_self_allowed(self) -> None:
        record = _record(baseline_id="SELF")
        assert record.baseline_id == "SELF"

    def test_baseline_id_valid_exp_reference_allowed(self) -> None:
        record = _record(exp_id="EXP-20260902-01", baseline_id="EXP-20260901-01")
        assert record.baseline_id == "EXP-20260901-01"

    def test_baseline_id_malformed_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(baseline_id="not-a-valid-id")

    def test_parent_exp_id_malformed_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(parent_exp_id="nope")

    def test_parent_exp_id_valid_allowed(self) -> None:
        record = _record(parent_exp_id="EXP-20260831-01")
        assert record.parent_exp_id == "EXP-20260831-01"

    def test_malformed_created_at_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(created_at="not-a-timestamp")

    def test_terminal_status_without_completed_at_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(status="completed")

    def test_terminal_status_with_completed_at_accepted(self) -> None:
        record = _completed_record()
        assert record.completed_at == "2026-09-01T12:00:00"

    def test_malformed_completed_at_rejected(self) -> None:
        with pytest.raises(ValueError):
            _completed_record(completed_at="garbage")

    def test_completed_at_before_created_at_rejected(self) -> None:
        with pytest.raises(ValueError):
            _completed_record(completed_at="2026-08-01T00:00:00")

    @pytest.mark.parametrize("field", ["batch_size", "epochs"])
    @pytest.mark.parametrize("value", [0, -1, -10])
    def test_non_positive_count_field_rejected(self, field: str, value: int) -> None:
        with pytest.raises(ValueError):
            _record(**{field: value})

    def test_non_positive_lr_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(lr=0.0)

    @pytest.mark.parametrize("field", ["params", "flops", "train_time", "gpu_hours", "fps", "power"])
    def test_negative_nonneg_field_rejected(self, field: str) -> None:
        with pytest.raises(ValueError):
            _record(**{field: -1.0})

    @pytest.mark.parametrize("field", ["params", "flops", "train_time", "gpu_hours", "fps", "power"])
    def test_zero_nonneg_field_accepted(self, field: str) -> None:
        record = _record(**{field: 0.0})
        assert getattr(record, field) == 0.0

    def test_val_metrics_nan_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(val_metrics={"mAP": float("nan")})

    def test_val_metrics_infinity_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(val_metrics={"mAP": float("inf")})

    def test_val_metrics_empty_dict_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(val_metrics={})

    def test_val_metrics_valid_accepted(self) -> None:
        record = _record(val_metrics={"mAP@.5:.95": 0.41, "recall": 0.62})
        assert record.val_metrics == {"mAP@.5:.95": 0.41, "recall": 0.62}

    def test_hardware_missing_target_rejected(self) -> None:
        with pytest.raises(ValueError):
            HardwareInfo(training="A100x1", target="")

    def test_latency_negative_component_rejected(self) -> None:
        with pytest.raises(ValueError):
            LatencyMeasurement(end_to_end=-1.0, inference_only=5.0)

    def test_memory_negative_component_rejected(self) -> None:
        with pytest.raises(ValueError):
            MemoryFootprint(vram=-1.0, ram=100.0)

    def test_wrong_type_hardware_rejected(self) -> None:
        with pytest.raises(ValueError):
            _record(hardware={"training": "x", "target": "y"})

    @pytest.mark.parametrize(
        "field",
        [
            "commit",
            "approval_ref",
            "model",
            "dataset_version",
            "input_resolution",
            "optimizer",
            "scheduler",
            "augmentations",
            "precision",
            "failure_analysis",
            "decision",
        ],
    )
    def test_blank_optional_string_field_rejected(self, field: str) -> None:
        with pytest.raises(ValueError):
            _record(**{field: "   "})

    def test_notes_default_empty_string(self) -> None:
        record = _record()
        assert record.notes == ""


# ── SQLite: SqliteExperimentLedger ───────────────────────────────────────


class TestSqliteExperimentLedgerInit:
    def test_initializes_schema_on_fresh_nested_path(self, tmp_path: Path) -> None:
        db_path = tmp_path / "a" / "b" / "experiments.sqlite"
        ledger = SqliteExperimentLedger(db_path)
        try:
            assert db_path.exists()
        finally:
            ledger.close()

    def test_reopening_existing_database_does_not_error(self, tmp_path: Path) -> None:
        db_path = tmp_path / "experiments.sqlite"
        SqliteExperimentLedger(db_path).close()
        ledger = SqliteExperimentLedger(db_path)
        ledger.close()

    def test_init_failure_raises_experiment_ledger_error(self, tmp_path: Path) -> None:
        blocking_file = tmp_path / "not_a_directory"
        blocking_file.write_text("x")
        with pytest.raises(ExperimentLedgerError):
            SqliteExperimentLedger(blocking_file / "experiments.sqlite")

    def test_satisfies_experiment_ledger_protocol_surface(self, tmp_path: Path) -> None:
        ledger: ExperimentLedger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        try:
            assert hasattr(ledger, "record_experiment")
            assert hasattr(ledger, "get_experiment")
            assert hasattr(ledger, "list_experiments")
        finally:
            ledger.close()  # type: ignore[attr-defined]


class TestEmptyLedgerBehavior:
    def test_get_experiment_is_none_when_empty(self, tmp_path: Path) -> None:
        ledger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        try:
            assert ledger.get_experiment("EXP-20260901-01") is None
        finally:
            ledger.close()

    def test_list_experiments_is_empty_list(self, tmp_path: Path) -> None:
        ledger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        try:
            assert ledger.list_experiments() == []
        finally:
            ledger.close()


class TestRecordAndRead:
    def test_record_then_get_round_trip(self, tmp_path: Path) -> None:
        ledger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        try:
            record = _record()
            ledger.record_experiment(record)
            fetched = ledger.get_experiment(record.exp_id)
            assert fetched == record
        finally:
            ledger.close()

    def test_full_record_with_nested_fields_round_trips_exactly(self, tmp_path: Path) -> None:
        ledger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        try:
            record = _completed_record(
                model="yolov8n",
                dataset_version="ds-v3",
                hardware=HardwareInfo(training="A100x1", target="Jetson Orin NX"),
                latency=LatencyMeasurement(end_to_end=42.0, inference_only=18.5),
                memory=MemoryFootprint(vram=1800.0, ram=512.0),
                val_metrics={"mAP@.5:.95": 0.41},
                test_metrics={"mAP@.5:.95": 0.40},
                gpu_hours=2.5,
                fps=55.0,
                power=12.3,
                notes="baseline run",
            )
            ledger.record_experiment(record)
            fetched = ledger.get_experiment(record.exp_id)
            assert fetched == record
        finally:
            ledger.close()

    def test_commit_field_round_trips_despite_sql_keyword_column_rename(
        self, tmp_path: Path
    ) -> None:
        ledger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        try:
            record = _record(commit="a1b2c3d4")
            ledger.record_experiment(record)
            fetched = ledger.get_experiment(record.exp_id)
            assert fetched is not None
            assert fetched.commit == "a1b2c3d4"
        finally:
            ledger.close()

    def test_list_experiments_ordered_by_created_at_then_id(self, tmp_path: Path) -> None:
        ledger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        try:
            second = _record(exp_id="EXP-20260902-01", created_at="2026-09-02T10:00:00")
            first = _record(exp_id="EXP-20260901-01", created_at="2026-09-01T10:00:00")
            ledger.record_experiment(second)
            ledger.record_experiment(first)
            ids = [r.exp_id for r in ledger.list_experiments()]
            assert ids == ["EXP-20260901-01", "EXP-20260902-01"]
        finally:
            ledger.close()


class TestUpsertAndImmutability:
    def test_non_terminal_record_can_be_updated(self, tmp_path: Path) -> None:
        ledger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        try:
            proposed = _record(status="proposed")
            ledger.record_experiment(proposed)
            running = _record(status="running")
            ledger.record_experiment(running)
            fetched = ledger.get_experiment(proposed.exp_id)
            assert fetched is not None
            assert fetched.status == "running"
        finally:
            ledger.close()

    def test_terminal_record_rejects_further_writes(self, tmp_path: Path) -> None:
        ledger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        try:
            completed = _completed_record()
            ledger.record_experiment(completed)
            with pytest.raises(ExperimentLedgerError):
                ledger.record_experiment(_record(status="running"))
        finally:
            ledger.close()

    def test_original_terminal_row_untouched_after_rejected_write(self, tmp_path: Path) -> None:
        ledger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        try:
            completed = _completed_record(notes="final")
            ledger.record_experiment(completed)
            try:
                ledger.record_experiment(_record(status="running", notes="attempted overwrite"))
            except ExperimentLedgerError:
                pass
            fetched = ledger.get_experiment(completed.exp_id)
            assert fetched is not None
            assert fetched.notes == "final"
            assert fetched.status == "completed"
        finally:
            ledger.close()

    @pytest.mark.parametrize("terminal_status", ["completed", "failed", "cancelled"])
    def test_every_terminal_status_locks_the_row(
        self, tmp_path: Path, terminal_status: str
    ) -> None:
        ledger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        try:
            record = _record(
                status=terminal_status, completed_at="2026-09-01T12:00:00"
            )
            ledger.record_experiment(record)
            with pytest.raises(ExperimentLedgerError):
                ledger.record_experiment(_record(status="running"))
        finally:
            ledger.close()

    def test_two_different_exp_ids_do_not_conflict(self, tmp_path: Path) -> None:
        ledger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        try:
            ledger.record_experiment(_completed_record(exp_id="EXP-20260901-01"))
            ledger.record_experiment(_record(exp_id="EXP-20260901-02"))
            assert len(ledger.list_experiments()) == 2
        finally:
            ledger.close()


class TestConstraintViolations:
    def test_status_check_constraint_enforced_at_db_level(self, tmp_path: Path) -> None:
        db_path = tmp_path / "e.sqlite"
        ledger = SqliteExperimentLedger(db_path)
        ledger.close()
        # Bypass the domain layer entirely to prove the DB-level CHECK constraint
        # is real defense-in-depth, not merely duplicated Python validation.
        raw = sqlite3.connect(str(db_path))
        try:
            with pytest.raises(sqlite3.IntegrityError):
                with raw:
                    raw.execute(
                        "INSERT INTO experiments "
                        "(exp_id, status, hypothesis, success_criteria, baseline_id, "
                        "created_at, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            "EXP-20260901-01",
                            "not_a_real_status",
                            "h",
                            "s",
                            "SELF",
                            "2026-09-01T10:00:00",
                            "",
                        ),
                    )
        finally:
            raw.close()


class TestPersistenceAcrossRestart:
    def test_records_survive_close_and_reopen(self, tmp_path: Path) -> None:
        db_path = tmp_path / "e.sqlite"
        record = _record()
        ledger = SqliteExperimentLedger(db_path)
        ledger.record_experiment(record)
        ledger.close()

        reopened = SqliteExperimentLedger(db_path)
        try:
            fetched = reopened.get_experiment(record.exp_id)
            assert fetched == record
        finally:
            reopened.close()

    def test_three_sequential_restart_cycles_accumulate_correctly(self, tmp_path: Path) -> None:
        db_path = tmp_path / "e.sqlite"
        for i in range(3):
            ledger = SqliteExperimentLedger(db_path)
            ledger.record_experiment(
                _record(exp_id=f"EXP-2026090{i + 1}-01", created_at=f"2026-09-0{i + 1}T10:00:00")
            )
            ledger.close()

        final = SqliteExperimentLedger(db_path)
        try:
            assert len(final.list_experiments()) == 3
        finally:
            final.close()


class TestErrorHandlingDoesNotSwallow:
    def test_read_against_closed_connection_raises_experiment_ledger_error(
        self, tmp_path: Path
    ) -> None:
        ledger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        ledger.close()
        with pytest.raises(ExperimentLedgerError):
            ledger.get_experiment("EXP-20260901-01")

    def test_write_against_closed_connection_raises_experiment_ledger_error(
        self, tmp_path: Path
    ) -> None:
        ledger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        ledger.close()
        with pytest.raises(ExperimentLedgerError):
            ledger.record_experiment(_record())

    def test_experiment_ledger_error_chains_underlying_sqlite_error(
        self, tmp_path: Path
    ) -> None:
        ledger = SqliteExperimentLedger(tmp_path / "e.sqlite")
        ledger.close()
        try:
            ledger.get_experiment("EXP-20260901-01")
        except ExperimentLedgerError as exc:
            assert isinstance(exc.__cause__, sqlite3.Error)
        else:
            pytest.fail("expected ExperimentLedgerError")


class TestDefaultDbPathAndFactory:
    def test_default_db_path_uses_explicit_workspace_root(self, tmp_path: Path) -> None:
        path = default_db_path(workspace_root=tmp_path)
        assert path == tmp_path / ".cv_agent" / "experiments.sqlite"

    def test_default_db_path_differs_from_memory_db_filename(self) -> None:
        from cv_agent.memory.store import DEFAULT_DB_FILENAME as MEMORY_DB_FILENAME
        from cv_agent.experiments.store import DEFAULT_DB_FILENAME as EXPERIMENTS_DB_FILENAME

        assert MEMORY_DB_FILENAME != EXPERIMENTS_DB_FILENAME

    def test_open_ledger_with_explicit_workspace_root(self, tmp_path: Path) -> None:
        ledger = open_ledger(workspace_root=tmp_path)
        try:
            expected = tmp_path / ".cv_agent" / "experiments.sqlite"
            assert expected.exists()
        finally:
            ledger.close()  # type: ignore[attr-defined]

    def test_open_ledger_with_explicit_db_path_bypasses_default(self, tmp_path: Path) -> None:
        custom_path = tmp_path / "custom" / "ledger.db"
        ledger = open_ledger(db_path=custom_path)
        try:
            assert custom_path.exists()
        finally:
            ledger.close()  # type: ignore[attr-defined]

    def test_open_ledger_satisfies_protocol_and_persists(self, tmp_path: Path) -> None:
        db_path = tmp_path / "e.sqlite"
        ledger: ExperimentLedger = open_ledger(db_path=db_path)
        record = _record()
        ledger.record_experiment(record)
        ledger.close()  # type: ignore[attr-defined]

        reopened: ExperimentLedger = open_ledger(db_path=db_path)
        try:
            assert reopened.get_experiment(record.exp_id) == record
        finally:
            reopened.close()  # type: ignore[attr-defined]


# ── Architecture boundary ────────────────────────────────────────────────


class TestArchitectureBoundary:
    def test_sqlite_import_confined_to_sqlite_store_module(self) -> None:
        root = Path(__file__).resolve().parent.parent / "cv_agent" / "experiments"
        offending = []
        for path in sorted(root.glob("*.py")):
            if path.name == "sqlite_store.py":
                continue
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("import sqlite3") or stripped.startswith(
                    "from sqlite3"
                ):
                    offending.append(str(path))
        assert offending == []

    _FORBIDDEN_PREFIXES = (
        "cv_agent.execution",
        "cv_agent.graph",
        "cv_agent.tools",
        "cv_agent.llm",
        "cv_agent.knowledge",
    )

    def test_cv_agent_experiments_imports_nothing_from_forbidden_layers(self) -> None:
        root = Path(__file__).resolve().parent.parent / "cv_agent" / "experiments"
        for path in sorted(root.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    continue
                for forbidden in self._FORBIDDEN_PREFIXES:
                    assert forbidden not in stripped, (
                        f"{path} imports from forbidden layer {forbidden!r}: {stripped!r}"
                    )
