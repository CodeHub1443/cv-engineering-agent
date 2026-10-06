"""Annotation-label review workflow for the primary failure-analysis sample (issue #75).

    python3 scripts/run_annotation_review.py prepare   # enlarged views + extended review CSV; no labels written
    python3 scripts/run_annotation_review.py check     # validate the human entries recorded so far
    python3 scripts/run_annotation_review.py report    # render docs/experiments/ANNOTATION-REVIEW-EXP-20261004-01.md

Reads the primary-run review sample from the analysis state root. Never writes to the ledger. Never downloads
instances_val2017.json. Human labels are entered by the reviewer, not by this script.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cv_agent.diagnosis.annotation_review import (  # noqa: E402
    ReviewError,
    load_review_rows,
    prepare_review,
    render_review_report,
    validate_rows,
)
from cv_agent.experiments.provenance import repository_state_root  # noqa: E402

COCO_ROOT = Path("/home/dev/Documents/data_cleaner/datasets/coco")
RUN_DIR_NAME = "EXP-20261004-01"
REPORT_PATH = REPO_ROOT / "docs" / "experiments" / "ANNOTATION-REVIEW-EXP-20261004-01.md"


def run_dir(state_root: Path) -> Path:
    return state_root / "analysis" / "failure-EXP-20261004" / RUN_DIR_NAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "check", "report"):
        p = sub.add_parser(name)
        p.add_argument("--coco-root", type=Path, default=COCO_ROOT)
    args = parser.parse_args(argv)

    state = repository_state_root()
    base = run_dir(state)
    sample_csv = base / "annotation_review_sample.csv"
    per_gt = base / "per_gt.csv"
    if not sample_csv.is_file() or not per_gt.is_file():
        print(f"REFUSED: review inputs are missing under {base}", file=sys.stderr)
        return 2

    try:
        if args.command == "prepare":
            result = prepare_review(
                sample_csv=sample_csv,
                per_gt_csv=per_gt,
                images_dir=args.coco_root / "images" / "val2017",
                views_dir=base / "review_views",
            )
            print(f"prepared {result.rows} candidates; wrote {result.views} enlarged views to {result.views_dir}")
            print("no human label was written")
            return 0
        if args.command == "check":
            problems = validate_rows(load_review_rows(sample_csv))
            if problems:
                for problem in problems:
                    print(f"  - {problem}", file=sys.stderr)
                return 1
            print("review entries are admissible")
            return 0
        report = render_review_report(load_review_rows(sample_csv))
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding="utf-8")
        print(f"wrote {REPORT_PATH}")
        return 0
    except ReviewError as exc:
        print("REFUSED:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
