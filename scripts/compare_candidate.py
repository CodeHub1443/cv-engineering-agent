"""Acceptance report for one candidate against its baseline, read from the experiment ledger.

    python3 scripts/compare_candidate.py --candidate EXP-20261115-01 \
        [--baseline EXP-20261004-01] [--db <ledger.sqlite>]

Reads two ledger rows and calls ``evaluate_candidate(..., variable_under_test="input_resolution")``.
Prints the verdict and each criterion with its margin (delta minus required). It never writes the
ledger. Exit codes: 0 meets the (provisional, D-113) criteria; 1 judged and failed; 2 cannot be
judged (invalid evidence, a missing row, an unreadable ledger).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cv_agent.experiments.acceptance import AcceptanceReport, evaluate_candidate  # noqa: E402
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", required=True, help="candidate exp_id")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE, help=f"baseline exp_id (default {DEFAULT_BASELINE})")
    parser.add_argument("--db", type=Path, default=None, help="ledger file (default: the repository ledger)")
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
    report = evaluate_candidate(baseline, candidate, variable_under_test=VARIABLE_UNDER_TEST)
    print(format_report(report))
    if report.verdict == "invalid":
        return EXIT_ERROR
    return EXIT_MEETS if report.ok else EXIT_FAILS


if __name__ == "__main__":
    raise SystemExit(main())
