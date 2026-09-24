"""
cv_agent.experiments.models — ExperimentRecord and the [P§25] schema.

Every field name below is taken verbatim from docs/state/EXPERIMENTS.md's
schema table — none renamed, none dropped, none silently simplified. Three
schema rows describe a value that is intrinsically two numbers/strings, not
one (`hardware`: "training hardware **and** target hardware"; `latency`:
"end-to-end **and** inference-only"; `memory`: "VRAM + RAM") — each is
represented as a small nested frozen dataclass under that same field name,
rather than inventing two new top-level field names or silently keeping only
one of the two required numbers.

Validates at construction (fail-closed) — mirrors ExecutionBinding/ToolSpec/
KnowledgeItem's established __post_init__ pattern in this codebase. Where
docs/state/EXPERIMENTS.md is silent on a constraint, only the smallest
deterministic integrity check is applied (documented per field below) — no
cross-reference validation against a dataset/model registry is performed,
because no dataset subsystem exists yet (ROADMAP.md Phase 5, not started).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ExperimentStatus = Literal["proposed", "running", "completed", "failed", "cancelled"]

_VALID_STATUSES: frozenset[str] = frozenset(
    {"proposed", "running", "completed", "failed", "cancelled"}
)
_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

# docs/state/EXPERIMENTS.md schema: "exp_id | `EXP-YYYYMMDD-NN`"
_EXP_ID_PATTERN = re.compile(r"^EXP-\d{8}-\d{2}$")


def _require_nonblank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string, got {value!r}")


def _require_exp_id_format(value: str, field_name: str) -> None:
    _require_nonblank(value, field_name)
    if not _EXP_ID_PATTERN.match(value):
        raise ValueError(
            f"{field_name} must match EXP-YYYYMMDD-NN (docs/state/EXPERIMENTS.md's "
            f"schema), got {value!r}"
        )


def _require_iso_timestamp(value: str, field_name: str) -> datetime:
    _require_nonblank(value, field_name)
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp, got {value!r}") from exc


def _require_finite(value: float, field_name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(
        float(value)
    ):
        raise ValueError(f"{field_name} must be a finite number, got {value!r}")


def _require_nonneg(value: float, field_name: str) -> None:
    _require_finite(value, field_name)
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0, got {value!r}")


def _require_positive(value: float, field_name: str) -> None:
    _require_finite(value, field_name)
    if value <= 0:
        raise ValueError(f"{field_name} must be > 0, got {value!r}")


@dataclass(frozen=True)
class HardwareInfo:
    """docs/state/EXPERIMENTS.md schema: `hardware` — "training hardware
    **and** target hardware." Both are required once `hardware` is present
    at all; the schema names two distinct pieces of information under one
    field, not one optional one."""

    training: str
    target: str

    def __post_init__(self) -> None:
        _require_nonblank(self.training, "HardwareInfo.training")
        _require_nonblank(self.target, "HardwareInfo.target")


@dataclass(frozen=True)
class LatencyMeasurement:
    """docs/state/EXPERIMENTS.md schema: `latency` — "end-to-end **and**
    inference-only, on target." Units are the caller's own convention (not
    codified anywhere else in this schema either, e.g. `fps`/`gpu_hours`)."""

    end_to_end: float
    inference_only: float

    def __post_init__(self) -> None:
        _require_nonneg(self.end_to_end, "LatencyMeasurement.end_to_end")
        _require_nonneg(self.inference_only, "LatencyMeasurement.inference_only")


@dataclass(frozen=True)
class MemoryFootprint:
    """docs/state/EXPERIMENTS.md schema: `memory` — "VRAM + RAM"."""

    vram: float
    ram: float

    def __post_init__(self) -> None:
        _require_nonneg(self.vram, "MemoryFootprint.vram")
        _require_nonneg(self.ram, "MemoryFootprint.ram")


@dataclass(frozen=True)
class ExperimentRecord:
    """
    One row of the Experiment Ledger — the [P§25] schema docs/state/
    EXPERIMENTS.md already defines, typed and validated.

    Required fields mirror what docs/state/EXPERIMENTS.md's own rules say is
    always known before or at the moment a run starts (rule 2: "every run
    names the baseline"; schema: hypothesis/success_criteria are "stated
    before it runs"). Every other field becomes known progressively as the
    run executes and is therefore optional here — see
    cv_agent.experiments.store.ExperimentLedger.record_experiment() for how
    a row is allowed to be updated while still non-terminal, and rejected
    once terminal (rule 1: "never edit a row after the run completes").
    """

    exp_id: str
    status: ExperimentStatus
    hypothesis: str
    success_criteria: str
    baseline_id: str
    """The run being compared against, or the literal string "SELF" for a
    baseline (docs/state/EXPERIMENTS.md rule 2)."""
    created_at: str

    parent_exp_id: str | None = None
    completed_at: str | None = None
    commit: str | None = None
    approval_ref: str | None = None
    model: str | None = None
    dataset_version: str | None = None
    input_resolution: str | None = None
    batch_size: int | None = None
    optimizer: str | None = None
    lr: float | None = None
    scheduler: str | None = None
    augmentations: str | None = None
    epochs: int | None = None
    precision: str | None = None
    hardware: HardwareInfo | None = None
    params: float | None = None
    flops: float | None = None
    train_time: float | None = None
    gpu_hours: float | None = None
    val_metrics: dict[str, float] | None = None
    test_metrics: dict[str, float] | None = None
    latency: LatencyMeasurement | None = None
    fps: float | None = None
    memory: MemoryFootprint | None = None
    power: float | None = None
    failure_analysis: str | None = None
    decision: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        _require_exp_id_format(self.exp_id, "ExperimentRecord.exp_id")
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                "ExperimentRecord.status must be one of "
                "'proposed'/'running'/'completed'/'failed'/'cancelled', "
                f"got {self.status!r}"
            )
        _require_nonblank(self.hypothesis, "ExperimentRecord.hypothesis")
        _require_nonblank(self.success_criteria, "ExperimentRecord.success_criteria")
        _require_nonblank(self.baseline_id, "ExperimentRecord.baseline_id")
        if self.baseline_id != "SELF" and not _EXP_ID_PATTERN.match(self.baseline_id):
            raise ValueError(
                "ExperimentRecord.baseline_id must be 'SELF' or match "
                f"EXP-YYYYMMDD-NN, got {self.baseline_id!r}"
            )
        created = _require_iso_timestamp(self.created_at, "ExperimentRecord.created_at")

        if self.parent_exp_id is not None:
            _require_exp_id_format(self.parent_exp_id, "ExperimentRecord.parent_exp_id")

        if self.status in _TERMINAL_STATUSES and self.completed_at is None:
            raise ValueError(
                f"ExperimentRecord.completed_at is required once status is "
                f"terminal ({self.status!r}) — docs/state/EXPERIMENTS.md: "
                "\"a run whose metadata is incomplete is not a valid result\""
            )
        if self.completed_at is not None:
            completed = _require_iso_timestamp(self.completed_at, "ExperimentRecord.completed_at")
            if completed < created:
                raise ValueError(
                    "ExperimentRecord.completed_at cannot precede created_at "
                    f"({self.completed_at!r} < {self.created_at!r})"
                )

        for field_name in (
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
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_nonblank(value, f"ExperimentRecord.{field_name}")

        if self.batch_size is not None:
            _require_positive(self.batch_size, "ExperimentRecord.batch_size")
        if self.epochs is not None:
            _require_positive(self.epochs, "ExperimentRecord.epochs")
        if self.lr is not None:
            _require_positive(self.lr, "ExperimentRecord.lr")

        for field_name in ("params", "flops", "train_time", "gpu_hours", "fps", "power"):
            value = getattr(self, field_name)
            if value is not None:
                _require_nonneg(value, f"ExperimentRecord.{field_name}")

        for metrics_field in ("val_metrics", "test_metrics"):
            metrics = getattr(self, metrics_field)
            if metrics is not None:
                if not isinstance(metrics, dict) or not metrics:
                    raise ValueError(
                        f"ExperimentRecord.{metrics_field} must be a non-empty mapping "
                        f"if provided, got {metrics!r}"
                    )
                for metric_name, metric_value in metrics.items():
                    _require_nonblank(metric_name, f"ExperimentRecord.{metrics_field} key")
                    _require_finite(
                        metric_value, f"ExperimentRecord.{metrics_field}[{metric_name!r}]"
                    )

        if self.hardware is not None and not isinstance(self.hardware, HardwareInfo):
            raise ValueError("ExperimentRecord.hardware must be a HardwareInfo instance")
        if self.latency is not None and not isinstance(self.latency, LatencyMeasurement):
            raise ValueError("ExperimentRecord.latency must be a LatencyMeasurement instance")
        if self.memory is not None and not isinstance(self.memory, MemoryFootprint):
            raise ValueError("ExperimentRecord.memory must be a MemoryFootprint instance")

    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES
