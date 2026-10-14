"""
cv_agent.experiments.acceptance — does a candidate record beat its named baseline?

Responsibility: compare a candidate ExperimentRecord with its baseline ExperimentRecord against
AcceptanceCriteria and report each criterion separately. Pure: no I/O, no execution, no storage.

Rules encoded (docs/state/DECISIONS.md, ADR-0019):
- D-077 (approved): fixed-threshold precision at conf 0.25 must be >= 0.75.
- D-078: BOTH overall AP@0.5:0.95 and small-person AP@0.5 must improve. The deltas
  (+0.010 / +0.020) are PROVISIONAL (Q32), so a pass is reported as ``meets_provisional_criteria``
  and never as a winner.
- Q28/D-067: standard AP is full-curve (conf=0.001); ``fixed_thr@0.25/*`` keys are a separate
  measurement and are never read as AP. The two key families are not interchangeable.

Fails closed: a missing metric, a non-completed record, a baseline mismatch or a record that does
not declare the full-curve protocol yields verdict ``invalid``, never a pass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from cv_agent.experiments.models import ExperimentRecord

OVERALL_AP_KEY = "mAP@0.5:0.95"
SMALL_AP_KEY = "AP@0.5/small"
FIXED_CONF = 0.25
PRECISION_KEY = f"fixed_thr@{FIXED_CONF}/precision"
FULL_CURVE_CONF = 0.001

Verdict = Literal["meets_provisional_criteria", "does_not_meet_criteria", "invalid"]

_REQUIRED_PROVENANCE = ("commit", "approval_ref", "dataset_version", "precision", "val_metrics")
_GAIN_TOLERANCE = 1e-9  # float representation of exact-threshold gains (0.527 - 0.517)

_CAVEATS = (
    "overall and small-person AP gains are provisional acceptance thresholds (D-078, Q32); "
    "run-to-run variance is not measured",
    "a pass is not a production decision and does not promote a model ([P§24])",
)


@dataclass(frozen=True)
class AcceptanceCriteria:
    """Thresholds. Gains are provisional (D-078, Q32); the precision floor is approved (D-077)."""

    min_overall_gain: float = 0.010
    min_small_gain: float = 0.020
    min_precision: float = 0.75
    gains_provisional: bool = True

    def __post_init__(self) -> None:
        for name in ("min_overall_gain", "min_small_gain"):
            if getattr(self, name) <= 0:
                raise ValueError(f"AcceptanceCriteria.{name} must be > 0 (both APs must improve)")
        if not 0.0 < self.min_precision <= 1.0:
            raise ValueError("AcceptanceCriteria.min_precision must be in (0, 1]")


@dataclass(frozen=True)
class CriterionResult:
    name: str
    protocol: str
    """Which measurement protocol the value comes from, so AP and P/R stay labelled apart."""
    baseline: float | None
    candidate: float
    delta: float | None
    required: float
    passed: bool


@dataclass(frozen=True)
class AcceptanceReport:
    verdict: Verdict
    candidate_id: str
    baseline_id: str
    criteria: tuple[CriterionResult, ...] = ()
    problems: tuple[str, ...] = ()
    gains_provisional: bool = True
    caveats: tuple[str, ...] = _CAVEATS

    @property
    def ok(self) -> bool:
        return self.verdict == "meets_provisional_criteria"


def _declared_protocol(record: ExperimentRecord) -> str:
    try:
        parsed = json.loads(record.notes) if record.notes else {}
    except json.JSONDecodeError:
        return ""
    return str(parsed.get("confidence_protocol", "")) if isinstance(parsed, dict) else ""


def _validity_problems(record: ExperimentRecord, role: str) -> list[str]:
    problems: list[str] = []
    if record.status != "completed":
        problems.append(f"{role} {record.exp_id} status is {record.status!r}, not 'completed'")
    for name in _REQUIRED_PROVENANCE:
        if getattr(record, name) is None:
            problems.append(f"{role} {record.exp_id} is missing {name} (provenance incomplete, [P§25])")
    if f"conf={FULL_CURVE_CONF}" not in _declared_protocol(record):
        problems.append(
            f"{role} {record.exp_id} does not declare the full-curve protocol "
            f"conf={FULL_CURVE_CONF} (Q28/D-067)"
        )
    return problems


def _metric(record: ExperimentRecord, key: str) -> float | None:
    return (record.val_metrics or {}).get(key)


def evaluate_candidate(
    baseline: ExperimentRecord,
    candidate: ExperimentRecord,
    criteria: AcceptanceCriteria | None = None,
) -> AcceptanceReport:
    """Compare ``candidate`` with ``baseline``. Bad evidence returns ``invalid``; it does not raise."""
    crit = criteria or AcceptanceCriteria()
    problems: list[str] = []
    if candidate.exp_id == baseline.exp_id:
        problems.append("candidate and baseline are the same record")
    if candidate.baseline_id != baseline.exp_id:
        problems.append(
            f"candidate {candidate.exp_id} names baseline {candidate.baseline_id!r}, not {baseline.exp_id!r}"
        )
    if candidate.dataset_version != baseline.dataset_version:
        problems.append("dataset_version differs between candidate and baseline (comparison void, [P§29.3])")
    problems += _validity_problems(baseline, "baseline")
    problems += _validity_problems(candidate, "candidate")
    for key in (OVERALL_AP_KEY, SMALL_AP_KEY):
        if _metric(baseline, key) is None or _metric(candidate, key) is None:
            problems.append(f"metric {key!r} missing on baseline or candidate")
    precision = _metric(candidate, PRECISION_KEY)
    if precision is None:
        problems.append(f"metric {PRECISION_KEY!r} missing on candidate")

    if problems or precision is None:
        return AcceptanceReport(
            "invalid", candidate.exp_id, baseline.exp_id,
            problems=tuple(problems), gains_provisional=crit.gains_provisional,
        )

    results: list[CriterionResult] = []
    for key, required in ((OVERALL_AP_KEY, crit.min_overall_gain), (SMALL_AP_KEY, crit.min_small_gain)):
        base = _metric(baseline, key)
        cand = _metric(candidate, key)
        assert base is not None and cand is not None
        delta = cand - base
        results.append(CriterionResult(
            key, f"full-curve AP (conf={FULL_CURVE_CONF})", base, cand, delta, required,
            delta >= required - _GAIN_TOLERANCE,
        ))
    results.append(CriterionResult(
        PRECISION_KEY, f"fixed-threshold P/R (conf={FIXED_CONF}, IoU>=0.5), not mAP",
        _metric(baseline, PRECISION_KEY), precision, None, crit.min_precision,
        precision >= crit.min_precision,
    ))
    verdict: Verdict = (
        "meets_provisional_criteria" if all(r.passed for r in results) else "does_not_meet_criteria"
    )
    return AcceptanceReport(
        verdict, candidate.exp_id, baseline.exp_id, tuple(results),
        gains_provisional=crit.gains_provisional,
    )
