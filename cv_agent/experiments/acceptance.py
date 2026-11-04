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

Fails closed: a missing or non-finite metric, a non-completed record, a baseline mismatch, an
undeclared difference in dataset_version, precision, input_resolution or model, or a record that does
not declare the full-curve protocol yields verdict ``invalid``, never a pass. At most one of
precision / input_resolution / model may be declared as the variable under test; a declared
difference is listed in the report, never ignored. Criteria that differ from the D-077 / D-078 basis
are reported as deviations and can never yield ``meets_provisional_criteria``.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Literal

from cv_agent.experiments.models import ExperimentRecord

OVERALL_AP_KEY = "mAP@0.5:0.95"
SMALL_AP_KEY = "AP@0.5/small"
FIXED_CONF = 0.25
PRECISION_KEY = f"fixed_thr@{FIXED_CONF}/precision"
FULL_CURVE_CONF = 0.001
D077_PRECISION_FLOOR = 0.75
"""Approved owner floor (D-077): fixed-threshold precision at conf 0.25."""
D078_MIN_OVERALL_GAIN = 0.010
D078_MIN_SMALL_GAIN = 0.020
"""Provisional minimum gains (D-078; Q32 (a) and (c) open)."""

Verdict = Literal[
    "meets_provisional_criteria", "meets_criteria_with_deviations", "does_not_meet_criteria", "invalid"
]

_REQUIRED_PROVENANCE = (
    "commit", "approval_ref", "dataset_version", "precision", "input_resolution", "model", "val_metrics"
)
DECLARABLE_VARIABLES = ("precision", "input_resolution", "model")
"""Fields that may differ between candidate and baseline: one at a time, and only when declared."""
_GAIN_TOLERANCE = 1e-9  # float representation of exact-threshold gains (0.527 - 0.517)
_CONF_TOKEN = re.compile(r"(?<![\w.])conf=(\d+(?:\.\d+)?)(?![\d.])")
_NOT_A_PROMOTION = "a pass is not a production decision and does not promote a model ([P§24])"


@dataclass(frozen=True)
class AcceptanceCriteria:
    """Thresholds. Gains are provisional (D-078, Q32); the precision floor is approved (D-077)."""

    min_overall_gain: float = D078_MIN_OVERALL_GAIN
    min_small_gain: float = D078_MIN_SMALL_GAIN
    min_precision: float = D077_PRECISION_FLOOR
    gains_provisional: bool = True

    def __post_init__(self) -> None:
        for name in ("min_overall_gain", "min_small_gain"):
            if getattr(self, name) <= 0:
                raise ValueError(f"AcceptanceCriteria.{name} must be > 0 (both APs must improve)")
        if not 0.0 < self.min_precision <= 1.0:
            raise ValueError("AcceptanceCriteria.min_precision must be in (0, 1]")

    def deviations(self) -> tuple[str, ...]:
        """Every way these criteria differ from the D-077 / D-078 basis."""
        out: list[str] = []
        if self.min_precision != D077_PRECISION_FLOOR:
            out.append(f"min_precision={self.min_precision} is not the D-077 floor {D077_PRECISION_FLOOR}")
        if self.min_overall_gain != D078_MIN_OVERALL_GAIN or self.min_small_gain != D078_MIN_SMALL_GAIN:
            out.append(
                f"gains +{self.min_overall_gain}/+{self.min_small_gain} are not the D-078 provisional "
                f"gains +{D078_MIN_OVERALL_GAIN}/+{D078_MIN_SMALL_GAIN}"
            )
        if not self.gains_provisional:
            out.append("gains_provisional=False, but the D-078 gains stay provisional while Q32 is open")
        return tuple(out)

    def caveats(self) -> tuple[str, ...]:
        """Caveat text that follows the actual flags, never the default wording."""
        out: list[str] = []
        if self.gains_provisional:
            out.append(
                "overall and small-person AP gains are provisional acceptance thresholds (D-078, Q32); "
                "run-to-run variance is not measured"
            )
        else:
            out.append("AP gain thresholds were marked non-provisional by the caller: NOT the D-078 basis")
        if self.min_precision != D077_PRECISION_FLOOR:
            out.append(
                f"precision floor {self.min_precision} is not the approved D-077 floor {D077_PRECISION_FLOOR}"
            )
        out.append(_NOT_A_PROMOTION)
        return tuple(out)


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
    caveats: tuple[str, ...] = ()
    deviations: tuple[str, ...] = ()
    """How the criteria used differ from the D-077 / D-078 basis; non-empty means never ``ok``."""
    variable_under_test: str | None = None
    declared_differences: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.verdict == "meets_provisional_criteria" and not self.deviations


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
    tokens = _CONF_TOKEN.findall(_declared_protocol(record))
    if not any(float(t) == FULL_CURVE_CONF for t in tokens):
        problems.append(
            f"{role} {record.exp_id} does not declare the full-curve protocol "
            f"conf={FULL_CURVE_CONF} (Q28/D-067)"
        )
    for key in (OVERALL_AP_KEY, SMALL_AP_KEY, PRECISION_KEY):
        value = _metric(record, key)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
        ):
            problems.append(f"metric {key!r} on {role} {record.exp_id} is not a finite number ({value!r})")
    return problems


def _comparison_problems(
    baseline: ExperimentRecord, candidate: ExperimentRecord, variable: str | None
) -> tuple[list[str], list[str]]:
    """(problems, declared differences) for the like-for-like fields ([P§29.3])."""
    problems: list[str] = []
    declared: list[str] = []
    if candidate.dataset_version != baseline.dataset_version:
        problems.append("dataset_version differs between candidate and baseline (comparison void, [P§29.3])")
    if variable is not None and variable not in DECLARABLE_VARIABLES:
        problems.append(f"variable_under_test {variable!r} is not declarable; use one of {DECLARABLE_VARIABLES}")
    for name in DECLARABLE_VARIABLES:
        base, cand = getattr(baseline, name), getattr(candidate, name)
        if base is None or cand is None:
            continue  # reported as missing provenance
        if base == cand:
            if name == variable:
                problems.append(f"declared variable under test {name!r} does not differ ({base!r})")
        elif name == variable:
            declared.append(f"{name}: {base!r} -> {cand!r} (declared variable under test)")
        else:
            problems.append(
                f"{name} differs ({base!r} vs {cand!r}) and is not the declared variable under test "
                "(comparison void, [P§29.3])"
            )
    return problems, declared


def _metric(record: ExperimentRecord, key: str) -> float | None:
    return (record.val_metrics or {}).get(key)


def evaluate_candidate(
    baseline: ExperimentRecord,
    candidate: ExperimentRecord,
    criteria: AcceptanceCriteria | None = None,
    *,
    variable_under_test: str | None = None,
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
    comparison, declared = _comparison_problems(baseline, candidate, variable_under_test)
    problems += comparison
    problems += _validity_problems(baseline, "baseline")
    problems += _validity_problems(candidate, "candidate")
    for key in (OVERALL_AP_KEY, SMALL_AP_KEY):
        if _metric(baseline, key) is None or _metric(candidate, key) is None:
            problems.append(f"metric {key!r} missing on baseline or candidate")
    precision = _metric(candidate, PRECISION_KEY)
    if precision is None:
        problems.append(f"metric {PRECISION_KEY!r} missing on candidate")

    def report(verdict: Verdict, results: tuple[CriterionResult, ...] = ()) -> AcceptanceReport:
        return AcceptanceReport(
            verdict, candidate.exp_id, baseline.exp_id, results, tuple(problems),
            gains_provisional=crit.gains_provisional, caveats=crit.caveats(),
            deviations=crit.deviations(), variable_under_test=variable_under_test,
            declared_differences=tuple(declared),
        )

    if problems or precision is None:
        return report("invalid")

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
    verdict: Verdict = "does_not_meet_criteria"
    if all(r.passed for r in results):
        verdict = "meets_criteria_with_deviations" if crit.deviations() else "meets_provisional_criteria"
    return report(verdict, tuple(results))
