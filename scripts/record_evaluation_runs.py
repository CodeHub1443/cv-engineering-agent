"""Verify the three EXP-20261004-01 image-size runs and record them in the experiment ledger.

    python3 scripts/record_evaluation_runs.py --approval-ref "<approval id>" \\
        --run 640=<run dir> --run 960=<run dir> --run 1280=<run dir> [--dry-run]
    python3 scripts/record_evaluation_runs.py --approval-ref "<approval id>" \\
        --fp32-control <run dir> [--dry-run]     (ADR-0018: one FP32 640 control record)
    python3 scripts/record_evaluation_runs.py --approval-ref "<approval id>" \\
        --candidate EXP-ID=<run dir> --baseline EXP-ID --proposal <path> [--dry-run]
                                                 (ADR-0017 amendment 2026-11-15: one owner-fixed candidate)

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
import re
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
    candidate_problems,
    candidate_run_name,
    is_exp_id,
    preflight_new_ids,
    run_paths,
    sha256_file,
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
# The one machine-readable line that binds a proposal to its candidate (owner, Issue B).
CANDIDATE_LINE = re.compile(r"^\*\*Candidate:\*\*\s+(\S+?),\s*imgsz\s+(\S+)\s*$", re.MULTILINE)
SECTION_PATTERNS = {
    "hypothesis": re.compile(r"^## \d+\.\s+Hypothesis[^\n]*\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL),
    "success criteria": re.compile(r"^## \d+\.\s+Success criteria[^\n]*\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL),
}


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
    parser.add_argument("--candidate", metavar="EXP-ID=RUN_DIR", help="one owner-fixed candidate run (needs --baseline, --proposal)")
    parser.add_argument("--baseline", metavar="EXP-ID", help="the candidate's baseline experiment, already in the ledger")
    parser.add_argument("--proposal", type=Path, metavar="PATH", help="the approved proposal that names this candidate")
    parser.add_argument("--dry-run", action="store_true", help="verify and print records; write nothing")
    parser.add_argument("--coco-root", type=Path, default=COCO_ROOT)
    args = parser.parse_args(argv)

    if not args.approval_ref.strip():
        print("REFUSED: --approval-ref must not be blank", file=sys.stderr)
        return 2
    if args.candidate is not None:
        if args.fp32_control is not None or args.run:
            print("REFUSED: --candidate, --run and --fp32-control are separate modes; give one", file=sys.stderr)
            return 2
        return record_candidate(args)
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


def finish(records: list, *, dry_run: bool, require_existing: tuple[str, ...] = ()) -> int:
    """Print the records, or preflight and write them. Shared by the series, the control and a candidate.

    ``require_existing`` names ledger ids that must already exist when writing (a candidate's baseline)."""
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
        missing = [e for e in require_existing if ledger.get_experiment(e) is None]
        if missing:
            raise RecordError([f"baseline {e} is not in the ledger; nothing recorded" for e in missing])
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


def read_proposal(path: Path, exp_id: str, imgsz: object) -> tuple[str, str, list[str]]:
    """(hypothesis, success criteria, problems) from a proposal. The size is bound by its one Candidate line."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return "", "", [f"proposal unreadable: {exc}"]
    problems: list[str] = []
    lines = CANDIDATE_LINE.findall(text)
    if len(lines) != 1:
        problems.append(
            f"proposal must carry exactly one '**Candidate:** EXP-ID, imgsz N' line (found {len(lines)})"
        )
    else:
        line_id, line_size = lines[0]
        if line_id != exp_id:
            problems.append(f"proposal Candidate line names {line_id}, not {exp_id}")
        if line_size != str(imgsz):
            problems.append(f"proposal Candidate line says imgsz {line_size}, run.json imgsz is {imgsz}")
    sections: dict[str, str] = {}
    for label, pattern in SECTION_PATTERNS.items():
        match = pattern.search(text)
        body = match.group(1).strip() if match else ""
        if not body:
            problems.append(f"proposal has no non-empty '## N. {label.capitalize()}' section")
        sections[label] = body
    return sections["hypothesis"], sections["success criteria"], problems


def record_candidate(args: argparse.Namespace) -> int:
    """One owner-fixed candidate record (ADR-0017 amendment 2026-11-15): the run, the proposal and the id agree."""
    exp_id, sep, run_text = args.candidate.partition("=")
    if not sep or not run_text:
        print("REFUSED: --candidate must look like EXP-20261115-01=<run dir>", file=sys.stderr)
        return 2
    if args.baseline is None or args.proposal is None:
        print("REFUSED: --candidate requires --baseline and --proposal", file=sys.stderr)
        return 2
    baseline = args.baseline.strip()
    if baseline in (exp_id, "SELF") or not is_exp_id(baseline):
        print(f"REFUSED: --baseline must be an existing experiment id other than the candidate, got {baseline!r}", file=sys.stderr)
        return 2
    try:
        head = require_clean_worktree(REPO_ROOT)
    except ProvenanceError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    run_dir = Path(run_text)
    problems: list[str] = []
    try:
        raw = json.loads(run_paths(run_dir)[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    imgsz = raw.get("imgsz")
    if raw.get("series") != exp_id:
        problems.append(f"run.json series {raw.get('series')!r} != candidate {exp_id!r}")
    size_problems = candidate_problems(exp_id, imgsz)  # type: ignore[arg-type]
    problems.extend(size_problems)
    if not size_problems and run_dir.name != candidate_run_name(exp_id, imgsz):  # type: ignore[arg-type]
        problems.append(f"run directory {run_dir.name!r} != {candidate_run_name(exp_id, imgsz)!r}")  # type: ignore[arg-type]
    hypothesis, criteria, proposal_problems = read_proposal(args.proposal, exp_id, imgsz)
    problems.extend(proposal_problems)

    run = None
    if not size_problems:
        try:
            run = verify_run(
                run_dir, imgsz=imgsz, coco_root=args.coco_root, head_commit=head, dataset=DatasetExpectation()  # type: ignore[arg-type]
            )
        except RecordError as exc:
            problems.extend(exc.problems)
        else:
            if run.approval_ref != args.approval_ref:
                problems.append(f"run approval {run.approval_ref!r} != --approval-ref {args.approval_ref!r}")
    if problems or run is None:
        print("REFUSED: nothing recorded. Problems:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    try:
        shown = args.proposal.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        shown = args.proposal.as_posix()
    note = (
        f"{exp_id} owner-fixed candidate vs {baseline} (ADR-0017 amendment 2026-11-15); "
        f"proposal {shown} sha256 {sha256_file(args.proposal)}"
    )
    try:
        record = build_record(
            run,
            exp_id=exp_id,
            baseline_id=baseline,
            approval_ref=args.approval_ref,
            hypothesis=hypothesis,
            success_criteria=criteria,
            series_note=note,
        )
    except RecordError as exc:
        print("REFUSED: nothing recorded:", "; ".join(exc.problems), file=sys.stderr)
        return 1
    return finish([record], dry_run=args.dry_run, require_existing=(baseline,))


if __name__ == "__main__":
    raise SystemExit(main())
