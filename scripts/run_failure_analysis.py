"""Read-only failure analysis for measured YOLO runs (ADR-0015 §9, issue #75).

    python3 scripts/run_failure_analysis.py --run EXP-20261004-01=<run dir> --run EXP-20261004-02=<run dir> ...
        [--primary EXP-20261004-01] [--report docs/experiments/FAILURE-ANALYSIS-EXP-20261004.md]

Each --run points at a run directory holding predictions.json. The expected predictions sha256 is read
from that experiment's recorded ledger notes, with a read-only connection (mode=ro). Nothing is written to the
ledger. Every run is analysed before anything is written. If any run is refused, nothing is written and every
problem is listed (ADR-0015 §9.8). No GPU inference runs.

Outputs (state root, outside the repository): .cv_agent/analysis/failure-EXP-20261004/<EXP id>/ for each run,
including the review sample and crops for the primary run only. The committed descriptive report is written only
when --report is given.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cv_agent.diagnosis.failure_analysis import (  # noqa: E402
    FailureAnalysisError,
    analyze_run,
    render_report,
    write_artifacts,
)
from cv_agent.experiments.provenance import ProvenanceError, current_commit, repository_state_root  # noqa: E402

COCO_ROOT = Path("/home/dev/Documents/data_cleaner/datasets/coco")
ANALYSIS_NAME = "failure-EXP-20261004"


def recorded_predictions_sha(db_path: Path, exp_id: str) -> str | None:
    """The predictions_json sha256 recorded in one experiment's ledger notes. Read-only connection."""
    if not db_path.is_file():
        return None
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT notes FROM experiments WHERE exp_id = ?", (exp_id,)).fetchone()
    finally:
        connection.close()
    if row is None or not row[0]:
        return None
    try:
        notes = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    sha = notes.get("artifacts", {}).get("predictions_json", {}).get("sha256")
    return sha if isinstance(sha, str) else None


def parse_runs(items: list[str]) -> dict[str, Path]:
    runs: dict[str, Path] = {}
    for item in items:
        exp_id, sep, path_text = item.partition("=")
        if not sep or not exp_id.strip():
            raise ValueError(f"--run must look like EXP-ID=<run dir>, got {item!r}")
        if exp_id in runs:
            raise ValueError(f"{exp_id} given twice")
        runs[exp_id] = Path(path_text)
    return runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", action="append", required=True, metavar="EXP-ID=RUN_DIR")
    parser.add_argument("--primary", default="EXP-20261004-01", help="the run that gets the review sample and crops")
    parser.add_argument("--coco-root", type=Path, default=COCO_ROOT)
    parser.add_argument("--report", type=Path, default=None, help="write the committed descriptive report here")
    args = parser.parse_args(argv)

    try:
        runs = parse_runs(args.run)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if args.primary not in runs:
        print(f"REFUSED: --primary {args.primary} is not one of the --run entries", file=sys.stderr)
        return 2

    try:
        commit = current_commit(REPO_ROOT)
    except ProvenanceError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    db_path = repository_state_root() / "experiments.sqlite"
    outcomes = {}
    problems: list[str] = []
    for exp_id, run_dir in runs.items():
        expected = recorded_predictions_sha(db_path, exp_id)
        if expected is None:
            problems.append(f"{exp_id}: no recorded predictions sha256 in the ledger notes; refusing")
            continue
        try:
            outcomes[exp_id] = analyze_run(
                predictions_path=run_dir / "predictions.json",
                expected_predictions_sha256=expected,
                image_list_path=args.coco_root / "val2017.txt",
                images_dir=args.coco_root / "images" / "val2017",
                labels_dir=args.coco_root / "labels" / "val2017",
                code_commit=commit,
            )
        except FailureAnalysisError as exc:
            problems.extend(f"{exp_id}: {p}" for p in exc.problems)

    if problems:
        print("REFUSED: nothing written. Problems:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    out_root = repository_state_root() / "analysis" / ANALYSIS_NAME
    for exp_id, outcome in outcomes.items():
        write_artifacts(
            outcome,
            out_root / exp_id,
            primary=exp_id == args.primary,
            images_dir=args.coco_root / "images" / "val2017" if exp_id == args.primary else None,
        )
        print(f"wrote {out_root / exp_id}")
    if args.report is not None:
        report = render_report({k: v.analysis for k, v in outcomes.items()}, primary=args.primary)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
        print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
