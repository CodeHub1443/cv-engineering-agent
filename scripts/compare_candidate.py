"""Acceptance report for one candidate against its baseline, read from the experiment ledger.

    python3 scripts/compare_candidate.py --candidate EXP-20261115-01 \
        [--baseline EXP-20261004-01] [--db <ledger.sqlite>]

Reads two ledger rows and calls ``evaluate_candidate(..., variable_under_test="input_resolution")``.
Prints the verdict and each criterion with its margin (delta minus required). It never writes the
ledger. Exit codes: 0 meets the (provisional, D-113) criteria; 1 judged and failed; 2 cannot be
judged (invalid evidence, a missing row, an unreadable ledger).

``--replication`` (Q72) is an integrity check, not an acceptance judgement: both rows must share
dataset_version and identical precision, input_resolution and model (plus hardware and recorded input
hashes where present), and both must declare the full-curve conf=0.001 (the protocol, judged as in
acceptance.py; differing confidence_protocol wording is only noted). Then every val_metrics key in either
row is compared exactly. Exit 0 "replicates" (same keys, every delta == 0.0); 1 "differs" (a delta, a one-sided key,
NaN); 2 "invalid" (missing row, dataset_version, protocol mismatch or undeclared conf). Read-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cv_agent.experiments.acceptance import (  # noqa: E402
    FULL_CURVE_CONF,
    AcceptanceReport,
    declares_full_curve_protocol,
    evaluate_candidate,
)
from cv_agent.experiments.models import ExperimentRecord  # noqa: E402
from cv_agent.experiments.store import ExperimentLedgerError, open_ledger  # noqa: E402

DEFAULT_BASELINE = "EXP-20261004-01"  # D-082
VARIABLE_UNDER_TEST = "input_resolution"
EXIT_MEETS, EXIT_FAILS, EXIT_ERROR = 0, 1, 2


def format_report(report: AcceptanceReport) -> str:
    lines = [
        f"candidate {report.candidate_id} vs baseline {report.baseline_id}",
        f"verdict: {report.verdict}",
    ]
    lines += [f"declared difference: {d}" for d in report.declared_differences]
    for c in report.criteria:
        base = "n/a" if c.baseline is None else f"{c.baseline:.4f}"
        if c.delta is None:  # a floor on the candidate's own value
            margin = c.candidate - c.required
            detail = f"candidate {c.candidate:.4f} (floor {c.required:.4f}), baseline {base}"
        else:
            margin = c.delta - c.required
            detail = f"baseline {base} -> candidate {c.candidate:.4f}, delta {c.delta:+.4f} (need {c.required:+.4f})"
        lines.append(f"  [{'PASS' if c.passed else 'FAIL'}] {c.name} [{c.protocol}]: {detail}; margin {margin:+.4f}")
    lines += [f"problem: {p}" for p in report.problems]
    lines += [f"deviation: {d}" for d in report.deviations]
    lines += [f"caveat: {c}" for c in report.caveats]
    return "\n".join(lines)


INPUT_HASHES = ("weights", "data_yaml", "val_txt")  # recorded inputs; the other artifacts are outputs


def _notes(record: ExperimentRecord) -> dict[str, object]:
    try:
        parsed = json.loads(record.notes)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _input_hash(record: ExperimentRecord, name: str) -> object:
    artifacts = _notes(record).get("artifacts")
    entry = artifacts.get(name) if isinstance(artifacts, dict) else None
    return entry.get("sha256") if isinstance(entry, dict) else None


def _protocol_problems(base: ExperimentRecord, cand: ExperimentRecord) -> list[str]:
    problems: list[str] = []
    if base.dataset_version is None or base.dataset_version != cand.dataset_version:
        problems.append(f"dataset_version: {base.dataset_version!r} != {cand.dataset_version!r}")
    for name in ("precision", "input_resolution", "model"):
        if getattr(base, name) != getattr(cand, name):
            problems.append(f"{name}: {getattr(base, name)!r} != {getattr(cand, name)!r}")
    for role, record in (("baseline", base), ("candidate", cand)):
        if not declares_full_curve_protocol(record):
            problems.append(f"{role} {record.exp_id} does not declare the full-curve protocol conf={FULL_CURVE_CONF} (Q28/D-067)")
    # Optional evidence: absent on both sides is ignored; on one side only, or different, is invalid.
    optional: list[tuple[str, object, object]] = [("hardware", base.hardware, cand.hardware)]
    optional += [(f"input hash {n}", _input_hash(base, n), _input_hash(cand, n)) for n in INPUT_HASHES]
    for name, b, c in optional:
        if (b is not None or c is not None) and b != c:
            problems.append(f"{name}: baseline {b!r} != candidate {c!r}")
    if not base.val_metrics or not cand.val_metrics:
        problems.append("val_metrics missing on at least one record")
    return problems


def replication_verdict(base: ExperimentRecord, cand: ExperimentRecord) -> tuple[str, list[str]]:
    """Return ("replicates" | "differs" | "invalid", report lines). Exact comparison, no tolerance."""
    problems = _protocol_problems(base, cand)
    if problems:
        return "invalid", [f"problem: {p}" for p in problems]
    bm, cm = base.val_metrics or {}, cand.val_metrics or {}
    lines: list[str] = []
    if _notes(base).get("confidence_protocol") != _notes(cand).get("confidence_protocol"):
        lines.append("note: confidence_protocol wording differs (both declare the full-curve protocol)")
    differing: list[str] = []
    for key in sorted(bm.keys() | cm.keys()):
        if key not in bm or key not in cm:
            lines.append(f"  {key}: baseline {bm.get(key, 'MISSING')} candidate {cm.get(key, 'MISSING')} (key on one side only)")
            differing.append(key)
            continue
        delta = cm[key] - bm[key]
        lines.append(f"  {key}: baseline {bm[key]!r} candidate {cm[key]!r} delta {delta!r}")
        if delta != 0.0:  # NaN != 0.0, so a NaN is always "differs"
            differing.append(key)
    if differing:
        return "differs", lines + [f"differing keys: {', '.join(differing)}"]
    return "replicates", lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", required=True, help="candidate exp_id")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE, help=f"baseline exp_id (default {DEFAULT_BASELINE})")
    parser.add_argument("--db", type=Path, default=None, help="ledger file (default: the repository ledger)")
    parser.add_argument("--replication", action="store_true", help="integrity check: exact metric replication (Q72)")
    args = parser.parse_args(argv)
    try:
        ledger = open_ledger(db_path=args.db, create=False)
        try:
            candidate = ledger.get_experiment(args.candidate)
            baseline = ledger.get_experiment(args.baseline)
        finally:
            ledger.close()  # type: ignore[attr-defined]
    except ExperimentLedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    for role, exp_id, row in (("candidate", args.candidate, candidate), ("baseline", args.baseline, baseline)):
        if row is None:
            print(f"error: {role} {exp_id} is not in the ledger", file=sys.stderr)
            return EXIT_ERROR
    assert candidate is not None and baseline is not None
    if args.replication:
        verdict, lines = replication_verdict(baseline, candidate)
        print("\n".join([f"replication {args.candidate} vs {args.baseline}", f"verdict: {verdict}", *lines]))
        return {"replicates": EXIT_MEETS, "differs": EXIT_FAILS}.get(verdict, EXIT_ERROR)
    report = evaluate_candidate(baseline, candidate, variable_under_test=VARIABLE_UNDER_TEST)
    print(format_report(report))
    if report.verdict == "invalid":
        return EXIT_ERROR
    return EXIT_MEETS if report.ok else EXIT_FAILS


if __name__ == "__main__":
    raise SystemExit(main())
