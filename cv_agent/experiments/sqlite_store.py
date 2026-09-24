"""
cv_agent.experiments.sqlite_store — SqliteExperimentLedger.

The ONLY module in this codebase allowed to import `sqlite3` for the
Experiment Ledger (ADR-0011; `OPEN_QUESTIONS.md` Q16). Every other caller —
tests included, once a ledger is constructed — talks to this class only
through the `ExperimentLedger` `Protocol` it implements. Mirrors
`cv_agent/memory/sqlite_store.py`'s structure and idioms exactly: idempotent
`CREATE TABLE IF NOT EXISTS` schema, one transaction per write, exceptions
wrapped in a technology-neutral error type.

Schema is initialized on every open — safe against a fresh empty file or an
existing database. No separate migration/version-detection system (mirrors
ADR-0004's "simplest deterministic policy" choice) — one table is the entire
V1 schema.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from cv_agent.experiments.models import (
    ExperimentRecord,
    HardwareInfo,
    LatencyMeasurement,
    MemoryFootprint,
)
from cv_agent.experiments.store import ExperimentLedgerError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    exp_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN
        ('proposed', 'running', 'completed', 'failed', 'cancelled')),
    hypothesis TEXT NOT NULL,
    success_criteria TEXT NOT NULL,
    baseline_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    parent_exp_id TEXT,
    completed_at TEXT,
    commit_sha TEXT,
    approval_ref TEXT,
    model TEXT,
    dataset_version TEXT,
    input_resolution TEXT,
    batch_size INTEGER,
    optimizer TEXT,
    lr REAL,
    scheduler TEXT,
    augmentations TEXT,
    epochs INTEGER,
    precision TEXT,
    hardware TEXT,
    params REAL,
    flops REAL,
    train_time REAL,
    gpu_hours REAL,
    val_metrics TEXT,
    test_metrics TEXT,
    latency TEXT,
    fps REAL,
    memory TEXT,
    power REAL,
    failure_analysis TEXT,
    decision TEXT,
    notes TEXT NOT NULL DEFAULT ''
);
"""

_COLUMNS = (
    "exp_id",
    "status",
    "hypothesis",
    "success_criteria",
    "baseline_id",
    "created_at",
    "parent_exp_id",
    "completed_at",
    "commit_sha",
    "approval_ref",
    "model",
    "dataset_version",
    "input_resolution",
    "batch_size",
    "optimizer",
    "lr",
    "scheduler",
    "augmentations",
    "epochs",
    "precision",
    "hardware",
    "params",
    "flops",
    "train_time",
    "gpu_hours",
    "val_metrics",
    "test_metrics",
    "latency",
    "fps",
    "memory",
    "power",
    "failure_analysis",
    "decision",
    "notes",
)

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class SqliteExperimentLedger:
    """
    SQLite-backed `ExperimentLedger`. Local, gitignored, file-based, durable
    across process restarts. Every write is one transaction
    (`with self._conn:`), so a failure partway through cannot leave a
    partial row — identical discipline to `SqliteProjectMemoryStore`.

    `commit` (the code SHA field, docs/state/EXPERIMENTS.md's schema) is
    stored under the column name `commit_sha` — `COMMIT` is a reserved SQL
    keyword; the domain field name on `ExperimentRecord` is unchanged
    (`record.commit`), only the underlying SQL column is renamed to avoid a
    keyword collision with every other DDL/DML statement in this class.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_path))
            with self._conn:
                self._conn.executescript(_SCHEMA)
        except (OSError, sqlite3.Error) as exc:
            raise ExperimentLedgerError(
                f"Failed to initialize experiment ledger at {db_path}: {exc}"
            ) from exc

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SqliteExperimentLedger":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def record_experiment(self, record: ExperimentRecord) -> None:
        try:
            existing_status_row = self._conn.execute(
                "SELECT status FROM experiments WHERE exp_id = ?", (record.exp_id,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise ExperimentLedgerError(
                f"Failed to check existing status for '{record.exp_id}': {exc}"
            ) from exc

        if existing_status_row is not None and existing_status_row[0] in _TERMINAL_STATUSES:
            raise ExperimentLedgerError(
                f"Experiment '{record.exp_id}' is already terminal "
                f"({existing_status_row[0]!r}) — docs/state/EXPERIMENTS.md rule 1: "
                "\"never edit a row after the run completes; errors are corrected "
                "by a new row plus a note.\""
            )

        values = _record_to_row(record)
        placeholders = ", ".join("?" for _ in _COLUMNS)
        update_clause = ", ".join(
            f"{col}=excluded.{col}" for col in _COLUMNS if col != "exp_id"
        )
        try:
            with self._conn:
                self._conn.execute(
                    f"INSERT INTO experiments ({', '.join(_COLUMNS)}) "
                    f"VALUES ({placeholders}) "
                    f"ON CONFLICT(exp_id) DO UPDATE SET {update_clause}",
                    values,
                )
        except sqlite3.IntegrityError as exc:
            raise ExperimentLedgerError(
                f"Constraint violation recording experiment '{record.exp_id}': {exc}"
            ) from exc
        except sqlite3.Error as exc:
            raise ExperimentLedgerError(
                f"Failed to record experiment '{record.exp_id}': {exc}"
            ) from exc

    def get_experiment(self, exp_id: str) -> ExperimentRecord | None:
        try:
            row = self._conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM experiments WHERE exp_id = ?",
                (exp_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise ExperimentLedgerError(f"Failed to read experiment '{exp_id}': {exc}") from exc
        return _row_to_record(row) if row is not None else None

    def list_experiments(self) -> list[ExperimentRecord]:
        try:
            rows = self._conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM experiments "
                "ORDER BY created_at ASC, exp_id ASC"
            ).fetchall()
        except sqlite3.Error as exc:
            raise ExperimentLedgerError(f"Failed to list experiments: {exc}") from exc
        return [_row_to_record(row) for row in rows]


def _record_to_row(record: ExperimentRecord) -> tuple[Any, ...]:
    return (
        record.exp_id,
        record.status,
        record.hypothesis,
        record.success_criteria,
        record.baseline_id,
        record.created_at,
        record.parent_exp_id,
        record.completed_at,
        record.commit,
        record.approval_ref,
        record.model,
        record.dataset_version,
        record.input_resolution,
        record.batch_size,
        record.optimizer,
        record.lr,
        record.scheduler,
        record.augmentations,
        record.epochs,
        record.precision,
        json.dumps(_asdict(record.hardware), sort_keys=True) if record.hardware else None,
        record.params,
        record.flops,
        record.train_time,
        record.gpu_hours,
        json.dumps(record.val_metrics, sort_keys=True) if record.val_metrics else None,
        json.dumps(record.test_metrics, sort_keys=True) if record.test_metrics else None,
        json.dumps(_asdict(record.latency), sort_keys=True) if record.latency else None,
        record.fps,
        json.dumps(_asdict(record.memory), sort_keys=True) if record.memory else None,
        record.power,
        record.failure_analysis,
        record.decision,
        record.notes,
    )


def _asdict(value: HardwareInfo | LatencyMeasurement | MemoryFootprint) -> dict[str, Any]:
    if isinstance(value, HardwareInfo):
        return {"training": value.training, "target": value.target}
    if isinstance(value, LatencyMeasurement):
        return {"end_to_end": value.end_to_end, "inference_only": value.inference_only}
    return {"vram": value.vram, "ram": value.ram}


def _row_to_record(row: tuple[Any, ...]) -> ExperimentRecord:
    (
        exp_id,
        status,
        hypothesis,
        success_criteria,
        baseline_id,
        created_at,
        parent_exp_id,
        completed_at,
        commit_sha,
        approval_ref,
        model,
        dataset_version,
        input_resolution,
        batch_size,
        optimizer,
        lr,
        scheduler,
        augmentations,
        epochs,
        precision,
        hardware_json,
        params,
        flops,
        train_time,
        gpu_hours,
        val_metrics_json,
        test_metrics_json,
        latency_json,
        fps,
        memory_json,
        power,
        failure_analysis,
        decision,
        notes,
    ) = row
    return ExperimentRecord(
        exp_id=exp_id,
        status=status,
        hypothesis=hypothesis,
        success_criteria=success_criteria,
        baseline_id=baseline_id,
        created_at=created_at,
        parent_exp_id=parent_exp_id,
        completed_at=completed_at,
        commit=commit_sha,
        approval_ref=approval_ref,
        model=model,
        dataset_version=dataset_version,
        input_resolution=input_resolution,
        batch_size=batch_size,
        optimizer=optimizer,
        lr=lr,
        scheduler=scheduler,
        augmentations=augmentations,
        epochs=epochs,
        precision=precision,
        hardware=HardwareInfo(**json.loads(hardware_json)) if hardware_json else None,
        params=params,
        flops=flops,
        train_time=train_time,
        gpu_hours=gpu_hours,
        val_metrics=json.loads(val_metrics_json) if val_metrics_json else None,
        test_metrics=json.loads(test_metrics_json) if test_metrics_json else None,
        latency=LatencyMeasurement(**json.loads(latency_json)) if latency_json else None,
        fps=fps,
        memory=MemoryFootprint(**json.loads(memory_json)) if memory_json else None,
        power=power,
        failure_analysis=failure_analysis,
        decision=decision,
        notes=notes,
    )
