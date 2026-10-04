"""Verify the three EXP-20261004-01 image-size runs and record them in the experiment ledger.

    python3 scripts/record_evaluation_runs.py --approval-ref "<approval id>" \\
        --run 640=<run dir> --run 960=<run dir> --run 1280=<run dir> [--dry-run]
    python3 scripts/record_evaluation_runs.py --approval-ref "<approval id>" \\
        --fp32-control <run dir> [--dry-run]     (ADR-0018: one FP32 640 control record)

Each --run points at the run directory written by scripts/run_yolo_val_measured.py. All three runs
are verified before anything is written. If any run fails, nothing is recorded and every problem
is listed (ADR-0017). --dry-run prints the records as JSON and writes nothing.

Records (ids and baselines fixed by the owner, 2026-10-04): 640 is the new-protocol control
(EXP-20261004-01, baseline SELF). 960 and 1280 are EXP-20261004-02 and -03, each with baseline
EXP-20261004-01. Historical records are never modified.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cv_agent.experiments.evaluation_records import (  # noqa: E402
    FP32_CONTROL_BASELINE,
    FP32_CONTROL_SERIES_ID,
    DatasetExpectation,
    RecordError,
    build_record,
    preflight_new_ids,
    verify_run,
    write_records,
)
from cv_agent.experiments.provenance import ProvenanceError, require_clean_worktree  # noqa: E402
from cv_agent.experiments.store import ExperimentLedgerError, open_ledger  # noqa: E402

SERIES = {
    640: ("EXP-20261004-01", "SELF"),
    960: ("EXP-20261004-02", "EXP-20261004-01"),
    1280: ("EXP-20261004-03", "EXP-20261004-01"),
}
COCO_ROOT = Path("/home/dev/Documents/data_cleaner/datasets/coco")
FP32_CONTROL_IMGSZ = 640


def parse_runs(items: list[str]) -> dict[int, Path]:
    runs: dict[int, Path] = {}
    for item in items:
        size_text, sep, path_text = item.partition("=")
        if not sep or not size_text.isdigit():
            raise ValueError(f"--run must look like 640=<run dir>, got {item!r}")
        size = int(size_text)
        if size in runs:
            raise ValueError(f"image size {size} given twice")
        runs[size] = Path(path_text)
    if set(runs) != set(SERIES):
        raise ValueError(f"exactly {sorted(SERIES)} are required, got {sorted(runs)}")
    return runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--approval-ref", required=True, help="the owner approval id for this run series")
    parser.add_argument("--run", action="append", metavar="IMGSZ=RUN_DIR")
    parser.add_argument("--fp32-control", type=Path, metavar="RUN_DIR", help="the FP32 640 control run (ADR-0018)")
    parser.add_argument("--dry-run", action="store_true", help="verify and print records; write nothing")
    parser.add_argument("--coco-root", type=Path, default=COCO_ROOT)
    args = parser.parse_args(argv)

    if not args.approval_ref.strip():
        print("REFUSED: --approval-ref must not be blank", file=sys.stderr)
        return 2
    if args.fp32_control is not None and args.run:
        print("REFUSED: --fp32-control and --run are separate series; give one", file=sys.stderr)
        return 2
    if args.fp32_control is not None:
        return record_fp32_control(args)
    if not args.run:
        print("REFUSED: give three --run IMGSZ=RUN_DIR entries, or --fp32-control RUN_DIR", file=sys.stderr)
        return 2
    try:
        runs = parse_runs(args.run)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    try:
        head = require_clean_worktree(REPO_ROOT)
    except ProvenanceError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    problems: list[str] = []
    verified = {}
    for size, run_dir in sorted(runs.items()):
        try:
            verified[size] = verify_run(
                run_dir,
                imgsz=size,
                coco_root=args.coco_root,
                head_commit=head,
                dataset=DatasetExpectation(),
            )
        except RecordError as exc:
            problems.extend(f"[{size}] {p}" for p in exc.problems)
            continue
        # Every run must carry exactly the approval the writer was given (ADR-0017 §3.3).
        if verified[size].approval_ref != args.approval_ref:
            problems.append(
                f"[{size}] run approval {verified[size].approval_ref!r} != --approval-ref {args.approval_ref!r}"
            )
    if problems:
        print("REFUSED: nothing recorded. Problems:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    records = []
    for size in sorted(verified):
        exp_id, baseline = SERIES[size]
        try:
            records.append(
                build_record(verified[size], exp_id=exp_id, baseline_id=baseline, approval_ref=args.approval_ref)
            )
        except RecordError as exc:
            print("REFUSED: nothing recorded:", "; ".join(exc.problems), file=sys.stderr)
            return 1

    return finish(records, dry_run=args.dry_run)


def finish(records: list, *, dry_run: bool) -> int:
    """Print the records, or preflight and write them. Shared by the series and the control."""
    if dry_run:
        print(json.dumps([dataclasses.asdict(r) for r in records], indent=2, default=str))
        print("dry run: nothing written")
        return 0

    try:
        ledger = open_ledger(create=False)
    except ExperimentLedgerError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    try:
        preflight_new_ids(ledger, [r.exp_id for r in records])
        written = write_records(ledger, records)
    except RecordError as exc:
        print("REFUSED:", "; ".join(exc.problems), file=sys.stderr)
        return 1
    finally:
        ledger.close()  # type: ignore[attr-defined]
    print("recorded:", ", ".join(written))
    return 0


def record_fp32_control(args: argparse.Namespace) -> int:
    """One FP32 640 control record, verified under the FP32 protocol (ADR-0018). Same approval rules."""
    try:
        head = require_clean_worktree(REPO_ROOT)
    except ProvenanceError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    try:
        run = verify_run(
            args.fp32_control,
            imgsz=FP32_CONTROL_IMGSZ,
            coco_root=args.coco_root,
            head_commit=head,
            dataset=DatasetExpectation(),
            quantize=None,
        )
    except RecordError as exc:
        print("REFUSED: nothing recorded. Problems:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    if run.approval_ref != args.approval_ref:
        print(
            f"REFUSED: run approval {run.approval_ref!r} != --approval-ref {args.approval_ref!r}",
            file=sys.stderr,
        )
        return 1
    try:
        record = build_record(
            run,
            exp_id=FP32_CONTROL_SERIES_ID,
            baseline_id=FP32_CONTROL_BASELINE,
            approval_ref=args.approval_ref,
        )
    except RecordError as exc:
        print("REFUSED: nothing recorded:", "; ".join(exc.problems), file=sys.stderr)
        return 1
    return finish([record], dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
