"""Person detection analysis CLI: threshold-free AP and fixed-threshold reference recall.

Thin CLI over ``cv_agent.experiments.detection_metrics`` (the metric code lives there so the
evaluation record writer shares it). Output labels: AP lines are threshold-free; "fixed-threshold"
lines are a reference measurement, not mAP and not an operating point (Q30 open).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cv_agent.experiments.detection_metrics import (  # noqa: E402
    DENSE_MIN_GT,
    MAP_PROTOCOL_CONF,
    MATCH_IOU,
    MEDIUM_MAX,
    PERSON_CATEGORY_ID,
    SMALL_MAX,
    GroundTruthBox,
    PredictedBox,
    RecallReport,
    StratumCount,
    density_bin,
    evaluate,
    iou,
    jpeg_size,
    load_person_gt,
    load_person_predictions,
    match_predictions,
    size_bin,
    stratum_ap50,
)

__all__ = [
    "DENSE_MIN_GT", "MAP_PROTOCOL_CONF", "MATCH_IOU", "MEDIUM_MAX", "PERSON_CATEGORY_ID",
    "SMALL_MAX", "GroundTruthBox", "PredictedBox", "RecallReport", "StratumCount",
    "density_bin", "evaluate", "iou", "jpeg_size", "load_person_gt",
    "load_person_predictions", "match_predictions", "size_bin", "stratum_ap50", "main",
]


def main() -> None:
    """Print threshold-free stratified AP50 and fixed-threshold recall for each run."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--coco-root",
        type=Path,
        required=True,
        help="COCO root with images/val2017 and labels/val2017",
    )
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="NAME=PREDICTIONS_JSON",
        help="a run's predictions.json, e.g. EXP-20261001-01=.../predictions.json (repeatable)",
    )
    parser.add_argument(
        "--threshold",
        action="append",
        type=float,
        default=None,
        help="confidence threshold (repeatable)",
    )
    args = parser.parse_args()
    thresholds = args.threshold or [0.10, 0.25, 0.50]
    images_dir = args.coco_root / "images" / "val2017"
    labels_dir = args.coco_root / "labels" / "val2017"
    gt_by_stem: dict[str, list[GroundTruthBox]] = {}
    size_by_stem: dict[str, tuple[int, int]] = {}
    for image in sorted(images_dir.glob("*.jpg")):
        width, height = jpeg_size(image)
        size_by_stem[image.stem] = (width, height)
        gt_by_stem[image.stem] = load_person_gt(
            labels_dir / f"{image.stem}.txt", width, height
        )
    print(f"GT person boxes: {sum(len(v) for v in gt_by_stem.values())}")
    for item in args.run:
        name, _, raw_path = item.partition("=")
        path = Path(raw_path)
        all_preds = load_person_predictions(path, 0.0)
        min_score = min(
            (p.score for plist in all_preds.values() for p in plist),
            default=float("nan"),
        )
        # AP is only threshold-free if the file holds the full curve (conf=0.001 protocol).
        full_curve = min_score <= 2 * MAP_PROTOCOL_CONF
        curve_note = (
            "full-curve" if full_curve else "TRUNCATED (not valid for mAP, Q28)"
        )
        full = load_person_predictions(path, MAP_PROTOCOL_CONF)
        aps = {
            s: stratum_ap50(full, gt_by_stem, size_by_stem, s)
            for s in ("small", "medium", "large")
        }
        print(
            f"{name:24s} file_min_score={min_score:.4f} [{curve_note}] "
            + " ".join(
                f"AP50_{s}={'n/a' if v is None else f'{v:.3f}'}" for s, v in aps.items()
            )
        )
        for threshold in thresholds:
            preds = load_person_predictions(path, threshold)
            report = evaluate(preds, gt_by_stem, threshold)
            s = report.strata
            print(
                f"{'':24s} fixed-threshold t={threshold:.2f} (reference, not mAP) "
                f"P={report.precision():.3f} R={report.recall():.3f} "
                f"small={s['small'].recall():.3f} medium={s['medium'].recall():.3f} "
                f"large={s['large'].recall():.3f} dense={s['dense'].recall():.3f} "
                f"sparse={s['sparse'].recall():.3f}"
            )


if __name__ == "__main__":
    main()
