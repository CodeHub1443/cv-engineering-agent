"""Read-only, deterministic IoU-matched failure analysis (ADR-0015 §9, issue #75).

Responsibility: read existing prediction artifacts and YOLO label files for one run and categorize
ground-truth persons and predictions at named **descriptive** thresholds. It discovers which error
categories are measured and in what share. It decides nothing: no acceptance criteria, no operating point,
no optimization choice (Q30 and D-069 remain OPEN).

Boundaries (ADR-0015 §9.2, §9.10):
- Matching is shared with the experiments layer: ``detection_metrics.greedy_match_pairs`` and ``iou``.
  This module never imports the experiments ledger, never touches a database, and runs no inference.
- Refuses the whole analysis on any integrity problem: prediction hash mismatch, missing or unreadable
  image size, malformed label or prediction, or an unlisted image (ADR-0015 §9.8). Problems are collected
  and reported together. Nothing is skipped silently.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cv_agent.experiments.detection_metrics import (
    MATCH_IOU,
    PERSON_CATEGORY_ID,
    GroundTruthBox,
    PredictedBox,
    density_bin,
    greedy_match_pairs,
    iou,
    jpeg_size,
    size_bin,
)

ANALYSIS_SCHEMA = "cv-agent/failure-analysis/v1"
SEED = 20261004
N_RESAMPLES = 1000
SAMPLE_PER_CLASS = 50
NEAR_MISS_LOW_IOU = 0.30  # descriptive: localization near-miss band lower edge (ADR-0015 §9.7)
REFERENCE_SCORE = 0.25  # descriptive: the existing fixed-threshold reference, not an operating point
HIGH_CONF_SCORE = 0.50  # descriptive: high-confidence false-positive review set
FULL_CURVE_SCORE = 0.001  # Q28 protocol: predictions must reach down to this score
NEAR_DUP_IOU = 0.90  # descriptive: near-duplicate GT pair candidate
DEGENERATE_MIN_PIXELS = 2.0  # descriptive: a GT box side below this is a degenerate-box candidate
MISSED_CATEGORIES = ("near_miss", "no_overlap", "competed")
LOCALIZATION_CATEGORIES = ("matched_at_reference", *MISSED_CATEGORIES)

LIMITATIONS = (
    "Box-area bins are descriptive normalized box-area bins. They are not official COCO size categories: "
    "COCO uses absolute annotation area in pixels (32^2 and 96^2). The ADR-0015 §3.4 cut-offs approximate "
    "those for roughly 640x480 images only.",
    "Official COCO size-stratified mAP is Q27. It needs instances_val2017.json, which is not downloaded. "
    "Q27 remains open. Nothing here closes it or supports a published claim.",
    "Crowd (iscrowd) annotations cannot be identified without instances_val2017.json. Crowd-related error "
    "is reported as not measured, never as zero.",
    "Matching is the greedy IoU >= 0.5 rule of cv_agent.experiments.detection_metrics. It is not the COCO evaluator.",
    "All thresholds (IoU 0.30, score 0.25, score 0.50, side < 2 px, IoU 0.90) are descriptive analysis "
    "parameters, not production criteria. Q30 and D-069 remain OPEN.",
    "Human review labels are not assigned by this analysis. Any agent-proposed label is preliminary only.",
)
NOT_MEASURED = (
    "occlusion and crowd (needs instances_val2017.json iscrowd): not measured",
    "blur: not measured",
    "illumination: not measured",
    "camera angle: not measured",
    "compression: not measured",
    "class confusion (runs are persons-only): not measured",
    "domain shift: not measured",
    "temporal instability: not measured",
)


class FailureAnalysisError(Exception):
    """The analysis was refused. ``problems`` lists every integrity problem found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Interval:
    """A count over a total, its share, and a seeded bootstrap interval for that share."""

    count: int
    total: int
    share: float
    low: float
    high: float


@dataclass(frozen=True)
class StratumSummary:
    """GT counts for one box-area bin or density class, with the missed-at-reference share."""

    name: str
    gt: int
    fully_missed: int
    missed_at_reference: int
    missed_at_reference_share: Interval


@dataclass(frozen=True)
class FailureAnalysis:
    """Measured facts for one run. Descriptive only (ADR-0015 §9)."""

    schema: str
    predictions_path: str
    predictions_sha256: str
    expected_predictions_sha256: str
    image_list_path: str
    image_list_sha256: str
    images_dir: str
    labels_dir: str
    code_commit: str
    images_listed: int
    background_images: int
    gt_total: int
    person_predictions: int
    full_curve_min_score: float
    fully_missed: Interval
    missed_at_reference: Interval
    localization: dict[str, Interval]
    unmatched_pred_ref: Interval
    unmatched_pred_050: Interval
    size_strata: dict[str, StratumSummary]
    density_strata: dict[str, StratumSummary]
    bottleneck_ranking: tuple[tuple[str, Interval], ...]
    candidates: dict[str, int]
    limitations: tuple[str, ...] = LIMITATIONS
    not_measured: tuple[str, ...] = NOT_MEASURED
    descriptive_only: bool = True


@dataclass(frozen=True)
class RunOutcome:
    """The analysis plus the per-row evidence that the artifacts are written from."""

    analysis: FailureAnalysis
    gt_rows: list[dict[str, Any]]
    fp050_rows: list[dict[str, Any]]
    dup_rows: list[dict[str, Any]]
    degenerate_rows: list[dict[str, Any]]


def localization_class(best_iou: float) -> str:
    """Category for a GT that the reference matching left unmatched, from its best overlap (descriptive)."""
    if best_iou >= MATCH_IOU:
        return "competed"  # overlapped at IoU >= 0.5, but the greedy assignment went to another GT
    if best_iou >= NEAR_MISS_LOW_IOU:
        return "near_miss"
    return "no_overlap"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_resamples(n_items: int, *, seed: int, n: int) -> list[list[int]]:
    """Deterministic bootstrap index lists (with replacement), shared across metrics for one run."""
    rng = random.Random(seed)
    return [[rng.randrange(n_items) for _ in range(n_items)] for _ in range(n)]


def bootstrap_ratio_interval(
    num: list[int],
    den: list[int],
    *,
    seed: int = SEED,
    n: int = N_RESAMPLES,
    resamples: list[list[int]] | None = None,
) -> Interval:
    """Share = sum(num)/sum(den) with a 95% percentile bootstrap over items (images)."""
    if len(num) != len(den):
        raise ValueError("num and den must have one entry per item")
    count, total = sum(num), sum(den)
    share = count / total if total else 0.0
    if not num:
        return Interval(count=0, total=0, share=0.0, low=0.0, high=0.0)
    indices = resamples if resamples is not None else make_resamples(len(num), seed=seed, n=n)
    ratios = []
    for idx in indices:
        s_num = sum(num[i] for i in idx)
        s_den = sum(den[i] for i in idx)
        ratios.append(s_num / s_den if s_den else 0.0)
    ratios.sort()
    low = ratios[int(0.025 * (len(ratios) - 1))]
    high = ratios[int(0.975 * (len(ratios) - 1))]
    return Interval(count=count, total=total, share=share, low=low, high=high)


def sample_candidates(items: list[Any], rng: random.Random, k: int) -> list[Any]:
    """A fixed-size sample without replacement, returned in sorted order. Deterministic for a given rng state."""
    ordered = sorted(items)
    if len(ordered) <= k:
        return ordered
    return sorted(rng.sample(ordered, k))


def _fail(problems: list[str], message: str) -> None:
    problems.append(message)


def _load_list(list_path: Path, problems: list[str]) -> list[str]:
    text = list_path.read_text(encoding="utf-8")
    stems: list[str] = []
    seen: set[str] = set()
    for line_no, raw in enumerate(text.splitlines(), start=1):
        entry = raw.strip()
        if not entry:
            _fail(problems, f"{list_path.name} line {line_no} is blank (malformed image list)")
            continue
        path = Path(entry)
        if path.suffix != ".jpg":
            _fail(problems, f"{list_path.name} line {line_no} is not a .jpg entry: {entry!r}")
            continue
        stem = path.stem
        if stem in seen:
            _fail(problems, f"{list_path.name} lists {stem} more than once")
            continue
        seen.add(stem)
        stems.append(stem)
    return stems


def _load_predictions(
    predictions_path: Path, listed: set[str], problems: list[str]
) -> tuple[dict[str, list[PredictedBox]], float, int]:
    try:
        records = json.loads(predictions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FailureAnalysisError([f"predictions.json is unreadable: {exc}"]) from exc
    if not isinstance(records, list):
        raise FailureAnalysisError(["predictions.json must be a list of detections"])
    by_stem: dict[str, list[PredictedBox]] = {}
    lowest = math.inf
    person_count = 0
    for index, rec in enumerate(records):
        if not isinstance(rec, dict) or "file_name" not in rec or "bbox" not in rec or "score" not in rec:
            _fail(problems, f"predictions.json record {index} is malformed")
            continue
        if rec.get("category_id") != PERSON_CATEGORY_ID:
            continue
        stem = Path(str(rec["file_name"])).stem
        if stem not in listed:
            _fail(problems, f"prediction for {stem}, which is not in the image list")
            continue
        bbox, score = rec["bbox"], rec["score"]
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in bbox)
            or bbox[2] < 0
            or bbox[3] < 0
        ):
            _fail(problems, f"prediction for {stem} has a malformed bbox")
            continue
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) or not 0 <= score <= 1:
            _fail(problems, f"prediction for {stem} has a non-finite or out-of-range score")
            continue
        x, y, w, h = (float(v) for v in bbox)
        by_stem.setdefault(stem, []).append(PredictedBox(x, y, x + w, y + h, float(score)))
        lowest = min(lowest, float(score))
        person_count += 1
    if person_count == 0:
        lowest = 0.0
    elif lowest > 2 * FULL_CURVE_SCORE:
        raise FailureAnalysisError(
            [f"predictions.json is TRUNCATED: lowest person score {lowest:.4f} > {2 * FULL_CURVE_SCORE} (Q28 full-curve gate)"]
        )
    return by_stem, lowest, person_count


def _load_gt(
    label_path: Path, width: int, height: int, stem: str, problems: list[str]
) -> list[GroundTruthBox]:
    if not label_path.exists():
        return []  # a listed image with no label file is a background image: zero GT (ADR-0015 §9.8)
    boxes: list[GroundTruthBox] = []
    for line_no, raw in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        parts = raw.split()
        ok = len(parts) == 5
        if ok:
            try:
                cls = int(parts[0])
                cx, cy, nw, nh = (float(v) for v in parts[1:])
            except ValueError:
                ok = False
        if not ok or not all(math.isfinite(v) for v in (cx, cy, nw, nh)) or not (0 <= nw <= 1 and 0 <= nh <= 1):
            _fail(problems, f"malformed label line {line_no} in {stem}.txt: {raw!r}")
            continue
        if cls != 0:
            continue  # only class 0 (person) is analysed
        x1 = (cx - nw / 2) * width
        y1 = (cy - nh / 2) * height
        boxes.append(GroundTruthBox(x1, y1, x1 + nw * width, y1 + nh * height, nw * nh))
    return boxes


def analyze_run(
    *,
    predictions_path: Path,
    expected_predictions_sha256: str | None,
    image_list_path: Path,
    images_dir: Path,
    labels_dir: Path,
    code_commit: str,
) -> RunOutcome:
    """Analyse one run read-only. Refuses the whole analysis on any integrity problem."""
    problems: list[str] = []
    pred_sha = sha256_of(predictions_path)
    if expected_predictions_sha256 is None or pred_sha != expected_predictions_sha256:
        raise FailureAnalysisError(
            [
                f"predictions.json sha256 {pred_sha} does not match recorded provenance "
                f"{expected_predictions_sha256!r}; refusing the analysis"
            ]
        )
    stems = _load_list(image_list_path, problems)
    if not stems:
        problems.append("the image list is empty")
    listed = set(stems)
    by_stem, lowest, person_count = _load_predictions(predictions_path, listed, problems)

    per_image: list[dict[str, Any]] = []
    gt_rows: list[dict[str, Any]] = []
    fp050_rows: list[dict[str, Any]] = []
    dup_rows: list[dict[str, Any]] = []
    degenerate_rows: list[dict[str, Any]] = []
    background = 0

    for stem in stems:
        image_path = images_dir / f"{stem}.jpg"
        if not image_path.is_file():
            problems.append(f"image {stem}.jpg is missing from {images_dir}; its size cannot be read")
            continue
        try:
            width, height = jpeg_size(image_path)
        except (OSError, ValueError) as exc:
            problems.append(f"image {stem}.jpg has an unreadable size: {exc}")
            continue
        label_path = labels_dir / f"{stem}.txt"
        if not label_path.exists():
            background += 1
        gts = _load_gt(label_path, width, height, stem, problems)
        preds = by_stem.get(stem, [])
        if problems:
            continue  # collect every problem before refusing; per-image results are discarded then
        image = _analyze_image(stem, width, height, gts, preds, gt_rows, fp050_rows, dup_rows, degenerate_rows)
        per_image.append(image)

    if problems:
        raise FailureAnalysisError(problems)

    analysis = _summarize(
        per_image=per_image,
        predictions_path=predictions_path,
        pred_sha=pred_sha,
        expected=expected_predictions_sha256 or "",
        image_list_path=image_list_path,
        list_sha=sha256_of(image_list_path),
        images_dir=images_dir,
        labels_dir=labels_dir,
        code_commit=code_commit,
        images_listed=len(stems),
        background=background,
        person_count=person_count,
        lowest=lowest,
        dup_count=len(dup_rows),
        fp_count=len(fp050_rows),
        degenerate_count=len(degenerate_rows),
    )
    return RunOutcome(analysis, gt_rows, fp050_rows, dup_rows, degenerate_rows)


def _analyze_image(
    stem: str,
    width: int,
    height: int,
    gts: list[GroundTruthBox],
    preds: list[PredictedBox],
    gt_rows: list[dict[str, Any]],
    fp050_rows: list[dict[str, Any]],
    dup_rows: list[dict[str, Any]],
    degenerate_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Per-image outcome. Appends per-row evidence to the run-level lists."""
    ref_idx = [i for i, p in enumerate(preds) if p.score >= REFERENCE_SCORE]
    hi_idx = [i for i, p in enumerate(preds) if p.score >= HIGH_CONF_SCORE]
    ref_preds = [preds[i] for i in ref_idx]
    hi_preds = [preds[i] for i in hi_idx]
    ref_pairs = greedy_match_pairs(ref_preds, gts)
    hi_pairs = greedy_match_pairs(hi_preds, gts)
    matched_ref_gt = {j for _, j in ref_pairs}
    matched_hi_pred = {hi_idx[k] for k, _ in hi_pairs}

    density = density_bin(len(gts))
    counts: dict[str, Any] = {
        "gt": len(gts),
        "fully_missed": 0,
        "missed_at_ref": 0,
        "matched_ref": 0,
        "near_miss": 0,
        "no_overlap": 0,
        "competed": 0,
        "fp_ref": len(ref_preds) - len(ref_pairs),
        "pred_ref": len(ref_preds),
        "fp_050": len(hi_preds) - len(hi_pairs),
        "pred_050": len(hi_preds),
        "size": {b: {"gt": 0, "fully": 0, "missed": 0} for b in ("small", "medium", "large")},
        "density": {b: {"gt": 0, "fully": 0, "missed": 0} for b in ("sparse", "dense")},
    }
    for j, g in enumerate(gts):
        gbox = (g.x1, g.y1, g.x2, g.y2)
        best_any = max((iou(gbox, (p.x1, p.y1, p.x2, p.y2)) for p in preds), default=0.0)
        best_ref = max((iou(gbox, (p.x1, p.y1, p.x2, p.y2)) for p in ref_preds), default=0.0)
        fully = best_any < MATCH_IOU
        missed = j not in matched_ref_gt
        loc = localization_class(best_ref) if missed else "matched_at_reference"
        size = size_bin(g.norm_area)
        counts["fully_missed"] += int(fully)
        counts["missed_at_ref"] += int(missed)
        if missed:
            counts[loc] += 1
        else:
            counts["matched_ref"] += 1
        counts["size"][size]["gt"] += 1
        counts["size"][size]["fully"] += int(fully)
        counts["size"][size]["missed"] += int(missed)
        counts["density"][density]["gt"] += 1
        counts["density"][density]["fully"] += int(fully)
        counts["density"][density]["missed"] += int(missed)
        width_px, height_px = g.x2 - g.x1, g.y2 - g.y1
        degenerate = width_px < DEGENERATE_MIN_PIXELS or height_px < DEGENERATE_MIN_PIXELS
        gt_rows.append(
            {
                "image_stem": stem,
                "gt_index": j,
                "x1": round(g.x1, 3),
                "y1": round(g.y1, 3),
                "x2": round(g.x2, 3),
                "y2": round(g.y2, 3),
                "norm_area": round(g.norm_area, 8),
                "size_bin": size,
                "density": density,
                "fully_missed": fully,
                "missed_at_reference": missed,
                "best_iou_any": round(best_any, 6),
                "best_iou_reference": round(best_ref, 6),
                "localization": loc,
                "degenerate": degenerate,
                "near_dup_partners": "",
            }
        )
        if degenerate:
            degenerate_rows.append({"image_stem": stem, "gt_index": j, "width_px": round(width_px, 3), "height_px": round(height_px, 3)})

    for i in range(len(gts)):
        for k in range(i + 1, len(gts)):
            value = iou((gts[i].x1, gts[i].y1, gts[i].x2, gts[i].y2), (gts[k].x1, gts[k].y1, gts[k].x2, gts[k].y2))
            if value >= 0.90:
                dup_rows.append({"image_stem": stem, "gt_index_a": i, "gt_index_b": k, "iou": round(value, 6)})
                gt_rows[len(gt_rows) - len(gts) + i]["near_dup_partners"] += f"{k};"
                gt_rows[len(gt_rows) - len(gts) + k]["near_dup_partners"] += f"{i};"

    for pi in range(len(preds)):
        if pi in matched_hi_pred or preds[pi].score < HIGH_CONF_SCORE:
            continue
        p = preds[pi]
        fp050_rows.append(
            {
                "image_stem": stem,
                "pred_index": pi,
                "score": round(p.score, 6),
                "x1": round(p.x1, 3),
                "y1": round(p.y1, 3),
                "x2": round(p.x2, 3),
                "y2": round(p.y2, 3),
                "norm_area": round((p.x2 - p.x1) * (p.y2 - p.y1) / (width * height), 8),
                "pred_size_bin": size_bin((p.x2 - p.x1) * (p.y2 - p.y1) / (width * height)),
            }
        )
    return counts


def _summarize(
    *,
    per_image: list[dict[str, Any]],
    predictions_path: Path,
    pred_sha: str,
    expected: str,
    image_list_path: Path,
    list_sha: str,
    images_dir: Path,
    labels_dir: Path,
    code_commit: str,
    images_listed: int,
    background: int,
    person_count: int,
    lowest: float,
    dup_count: int,
    fp_count: int,
    degenerate_count: int,
) -> FailureAnalysis:
    def col(key: str) -> list[int]:
        return [int(img[key]) for img in per_image]

    gt_total = sum(col("gt"))
    resamples = make_resamples(len(per_image), seed=SEED, n=N_RESAMPLES)

    def interval(num_key: str, den_key: str) -> Interval:
        return bootstrap_ratio_interval(col(num_key), col(den_key), resamples=resamples)

    fully = interval("fully_missed", "gt")
    missed = interval("missed_at_ref", "gt")
    localization = {
        "matched_at_reference": interval("matched_ref", "gt"),
        "competed": interval("competed", "gt"),
        "near_miss": interval("near_miss", "gt"),
        "no_overlap": interval("no_overlap", "gt"),
    }
    unmatched_ref = interval("fp_ref", "pred_ref")
    unmatched_050 = interval("fp_050", "pred_050")

    def strata(group: str, names: tuple[str, ...]) -> dict[str, StratumSummary]:
        out: dict[str, StratumSummary] = {}
        for name in names:
            gt_list = [img[group][name]["gt"] for img in per_image]
            missed_list = [img[group][name]["missed"] for img in per_image]
            fully_list = [img[group][name]["fully"] for img in per_image]
            out[name] = StratumSummary(
                name=name,
                gt=sum(gt_list),
                fully_missed=sum(fully_list),
                missed_at_reference=sum(missed_list),
                missed_at_reference_share=bootstrap_ratio_interval(missed_list, gt_list, resamples=resamples),
            )
        return out

    ranking = sorted(
        ((name, localization[name]) for name in MISSED_CATEGORIES),
        key=lambda item: (-item[1].count, item[0]),
    )
    return FailureAnalysis(
        schema=ANALYSIS_SCHEMA,
        predictions_path=str(predictions_path),
        predictions_sha256=pred_sha,
        expected_predictions_sha256=expected,
        image_list_path=str(image_list_path),
        image_list_sha256=list_sha,
        images_dir=str(images_dir),
        labels_dir=str(labels_dir),
        code_commit=code_commit,
        images_listed=images_listed,
        background_images=background,
        gt_total=gt_total,
        person_predictions=person_count,
        full_curve_min_score=lowest,
        fully_missed=fully,
        missed_at_reference=missed,
        localization=localization,
        unmatched_pred_ref=unmatched_ref,
        unmatched_pred_050=unmatched_050,
        size_strata=strata("size", ("small", "medium", "large")),
        density_strata=strata("density", ("sparse", "dense")),
        bottleneck_ranking=tuple((name, iv) for name, iv in ranking),
        candidates={"high_conf_fp": fp_count, "near_dup_pairs": dup_count, "degenerate_gt": degenerate_count},
    )


def analysis_to_dict(analysis: FailureAnalysis) -> dict[str, Any]:
    """JSON-ready form of a FailureAnalysis."""
    return asdict(analysis)


def build_review_sample(outcome: RunOutcome) -> list[dict[str, Any]]:
    """The fixed, deterministic annotation-review sample: 50 per candidate class, seed 20261004.

    Each class is sampled from its own sorted candidate list, in the fixed order below, using one seeded
    generator. A class with fewer candidates contributes all of them. Human labels are never filled in here.
    """
    rng = random.Random(SEED)
    gt_by_key = {(r["image_stem"], r["gt_index"]): r for r in outcome.gt_rows}
    fp_by_key = {(r["image_stem"], r["pred_index"]): r for r in outcome.fp050_rows}
    dup_by_key = {(r["image_stem"], r["gt_index_a"], r["gt_index_b"]): r for r in outcome.dup_rows}
    deg_by_key = {(r["image_stem"], r["gt_index"]): r for r in outcome.degenerate_rows}

    def gt_box(stem: str, index: int) -> list[float]:
        row = gt_by_key[(stem, index)]
        return [row["x1"], row["y1"], row["x2"], row["y2"]]

    sample: list[dict[str, Any]] = []
    plan = (
        ("high_conf_fp", list(fp_by_key)),
        ("near_dup_gt_pair", list(dup_by_key)),
        ("degenerate_gt", list(deg_by_key)),
    )
    for klass, keys in plan:
        for rank, key in enumerate(sample_candidates(keys, rng, SAMPLE_PER_CLASS), start=1):
            if klass == "high_conf_fp":
                row = fp_by_key[key]
                boxes = [[row["x1"], row["y1"], row["x2"], row["y2"]]]
                stem = key[0]
            elif klass == "near_dup_gt_pair":
                stem = key[0]
                boxes = [gt_box(stem, key[1]), gt_box(stem, key[2])]
            else:
                stem = key[0]
                boxes = [gt_box(stem, key[1])]
            sample.append(
                {
                    "candidate_class": klass,
                    "rank": rank,
                    "image_stem": stem,
                    "source_key": ":".join(str(k) for k in key),
                    "boxes": boxes,
                    "crop_path": "",
                    "human_label": "",
                    "human_notes": "",
                }
            )
    return sample


def write_artifacts(
    outcome: RunOutcome,
    out_dir: Path,
    *,
    primary: bool,
    images_dir: Path | None,
) -> list[Path]:
    """Write the state-root artifacts. Only the primary run gets the review sample and crops."""
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = out_dir / "summary.json"
    summary.write_text(
        json.dumps({"analysis": analysis_to_dict(outcome.analysis), "primary": primary}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    written = [summary, _write_csv(out_dir / "per_gt.csv", outcome.gt_rows)]
    written.append(_write_csv(out_dir / "per_fp_high_conf.csv", outcome.fp050_rows))
    if primary:
        sample = build_review_sample(outcome)
        if images_dir is not None:
            _write_crops(sample, images_dir, out_dir / "crops")
        written.append(
            _write_csv(
                out_dir / "annotation_review_sample.csv",
                sample,
                fields=[
                    "candidate_class",
                    "rank",
                    "image_stem",
                    "source_key",
                    "boxes",
                    "crop_path",
                    "human_label",
                    "human_notes",
                ],
            )
        )
    return written


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> Path:
    columns = fields if fields is not None else (list(rows[0]) if rows else [])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _write_crops(sample: list[dict[str, Any]], images_dir: Path, crop_dir: Path) -> None:
    """Crops with the candidate boxes drawn on them. Review aids only; they are not labels."""
    from PIL import Image, ImageDraw

    crop_dir.mkdir(parents=True, exist_ok=True)
    pad = 20
    for row in sample:
        image = Image.open(images_dir / f"{row['image_stem']}.jpg").convert("RGB")
        boxes = row["boxes"]
        left = max(0, int(min(b[0] for b in boxes)) - pad)
        top = max(0, int(min(b[1] for b in boxes)) - pad)
        right = min(image.width, int(max(b[2] for b in boxes)) + pad)
        bottom = min(image.height, int(max(b[3] for b in boxes)) + pad)
        crop = image.crop((left, top, max(right, left + 1), max(bottom, top + 1)))
        draw = ImageDraw.Draw(crop)
        for color, box in zip(((255, 0, 0), (0, 128, 255)), boxes):
            draw.rectangle((box[0] - left, box[1] - top, box[2] - left, box[3] - top), outline=color, width=2)
        name = f"{row['candidate_class']}_{row['rank']:03d}_{row['image_stem']}.png"
        crop.save(crop_dir / name)
        row["crop_path"] = (crop_dir / name).as_posix()


def render_report(analyses: dict[str, FailureAnalysis], *, primary: str) -> str:
    """Descriptive markdown report. States the open gates and the limitations. Declares no winner."""

    def pct(iv: Interval) -> str:
        return f"{iv.count} ({iv.share:.1%}; 95% CI {iv.low:.1%}–{iv.high:.1%})"

    lines = [
        "# Failure analysis: EXP-20261004-01..04 (IoU-matched, descriptive)",
        "",
        "**Status: descriptive only.** No pass/fail criterion, no acceptance threshold, no operating point and no",
        "production choice. Q30 (operating point and precision floor) stays **OPEN**. D-069 stays **OPEN**. Q27 stays",
        "**OPEN**. The thresholds below are analysis parameters, not production criteria.",
        "",
        "Source: ADR-0015 §9 (issue #75). Read-only, deterministic, from existing prediction artifacts and YOLO labels.",
        "No GPU inference, no new ledger rows.",
        "",
        "## Provenance",
        "",
    ]
    for exp_id, a in analyses.items():
        lines.append(
            f"- {exp_id}: predictions sha256 `{a.predictions_sha256}` (matches recorded provenance), commit `{a.code_commit}`, "
            f"images listed {a.images_listed}, background images {a.background_images}, GT persons {a.gt_total}."
        )
    p = analyses[primary]
    lines += [
        "",
        f"## Bottleneck ranking, {primary} (descriptive)",
        "",
        "Share of **all GT persons** at the reference threshold 0.25. Ties break by name.",
        "",
    ]
    for name, iv in p.bottleneck_ranking:
        lines.append(f"- {name}: {pct(iv)}")
    lines += [
        "",
        "Fully missed (no prediction at any score overlaps at IoU >= 0.5): " + pct(p.fully_missed),
        "",
        "Missed at the reference threshold: " + pct(p.missed_at_reference),
        "",
        "## Size and density strata (box-area bins; descriptive)",
        "",
    ]
    for name, s in {**p.size_strata, **p.density_strata}.items():
        lines.append(
            f"- {name}: GT {s.gt}, fully missed {s.fully_missed}, missed at 0.25 {s.missed_at_reference} "
            f"(share of this stratum's GT {s.missed_at_reference_share.share:.1%}; "
            f"95% CI {s.missed_at_reference_share.low:.1%}–{s.missed_at_reference_share.high:.1%})"
        )
    lines += ["", "## Comparisons (descriptive, one run each)", ""]
    for exp_id, a in analyses.items():
        lines.append(f"- {exp_id}: fully missed {a.fully_missed.count}, missed at 0.25 {a.missed_at_reference.count}, "
                     f"unmatched predictions at 0.25 {a.unmatched_pred_ref.count}, at 0.50 {a.unmatched_pred_050.count}.")
    total_missed = p.missed_at_reference.count
    small = p.size_strata["small"]
    lines += [
        "",
        "## Key descriptive findings (computed from the tables; no production decision)",
        "",
        f"- Descriptive bottleneck under the agreed definition ({primary}): "
        f"`{p.bottleneck_ranking[0][0]}`, {p.bottleneck_ranking[0][1].count} GT persons "
        f"({p.bottleneck_ranking[0][1].share:.1%} of all GT at reference 0.25).",
        f"- Small boxes account for {small.missed_at_reference} of {total_missed} misses at 0.25 "
        f"({small.missed_at_reference / total_missed:.1%}), from {small.gt} of {p.gt_total} GT "
        f"({small.gt / p.gt_total:.1%}).",
        "- Fully missed rate by box-area bin (share of that bin's GT): "
        + ", ".join(
            f"{name} {(st.fully_missed / st.gt if st.gt else 0.0):.1%} ({st.fully_missed}/{st.gt})"
            for name, st in p.size_strata.items()
        )
        + ". By density: "
        + ", ".join(
            f"{name} {(st.fully_missed / st.gt if st.gt else 0.0):.1%} ({st.fully_missed}/{st.gt})"
            for name, st in p.density_strata.items()
        )
        + ".",
    ]
    if {"EXP-20261004-01", "EXP-20261004-04"} <= set(analyses):
        a, b = analyses["EXP-20261004-01"], analyses["EXP-20261004-04"]
        lines.append(
            f"- Precision check, 640 FP16 vs 640 FP32 (one run each): fully missed {a.fully_missed.count} vs "
            f"{b.fully_missed.count}; missed at 0.25 {a.missed_at_reference.count} vs {b.missed_at_reference.count}; "
            f"unmatched predictions at 0.50 {a.unmatched_pred_050.count} vs {b.unmatched_pred_050.count}. "
            "One run per condition: no run-to-run variance is estimated, so this comparison cannot show a precision "
            "effect either way."
        )
    if {"EXP-20261004-01", "EXP-20261004-02", "EXP-20261004-03"} <= set(analyses):
        r = [analyses[k] for k in ("EXP-20261004-01", "EXP-20261004-02", "EXP-20261004-03")]
        lines.append(
            "- Resolution, 640 -> 960 -> 1280 (FP16, one run each): fully missed "
            f"{r[0].fully_missed.count} -> {r[1].fully_missed.count} -> {r[2].fully_missed.count}; "
            f"unmatched predictions at 0.25 {r[0].unmatched_pred_ref.count} -> {r[1].unmatched_pred_ref.count} -> "
            f"{r[2].unmatched_pred_ref.count}; unmatched at 0.50 {r[0].unmatched_pred_050.count} -> "
            f"{r[1].unmatched_pred_050.count} -> {r[2].unmatched_pred_050.count}. Descriptive only; no winner is declared."
        )
    lines.append("")
    lines += [
        "",
        "## Method and accepted deviations (issue #75; owner decisions 2026-10-04)",
        "",
        "- **Read-only ledger lookup.** Each run's expected predictions sha256 is read from its recorded ledger notes over a "
        "read-only connection (`mode=ro`). No ledger row is written or altered.",
        "- **Strict label parsing.** A malformed GT line refuses the whole analysis. Nothing is skipped silently.",
        "- **Q28 full-curve gate (input-integrity and protocol, not a production criterion).** A run whose lowest person "
        "score is above 0.002 is refused as truncated, because the reference thresholds and the bins would not be "
        "computed on a full PR curve.",
        "- **Partition of GT boxes at the reference threshold 0.25.** Every GT box is exactly one of: matched at reference, "
        "competed, near-miss, or no-overlap. The `competed` category is a diagnostic sub-category of missed-at-reference: "
        "the box overlaps a score >= 0.25 prediction at IoU >= 0.5, but the greedy assignment went to another GT box. "
        "It does not replace fully-missed, missed-at-reference, near-miss or no-overlap.",
        "- **Fully missed** is a separate definition: no prediction at any score (>= 0.001) overlaps the GT box at IoU >= 0.5.",
        "- **Degenerate GT boxes (a side < 2 px)** are a descriptive review heuristic. They are not an annotation-quality standard.",
        "- **Near-duplicate GT pairs (IoU >= 0.90)** are a review heuristic. They are not an annotation-quality standard.",
        "",
    ]
    lines += ["", "## Limitations (required)", ""]
    lines += [f"- {text}" for text in p.limitations]
    lines += ["", "## Not measured (reported as not measured, never as zero)", ""]
    lines += [f"- {text}" for text in p.not_measured]
    lines += [
        "",
        "## Review candidates",
        "",
        "Candidate counts only. Nothing here labels an annotation as wrong. Human review results are recorded separately.",
        "",
        f"- high-confidence false positives (score >= 0.50, unmatched): {p.candidates['high_conf_fp']}",
        f"- near-duplicate GT pairs (IoU >= 0.90): {p.candidates['near_dup_pairs']}",
        f"- degenerate GT boxes (a side < 2 px): {p.candidates['degenerate_gt']}",
        "",
    ]
    return "\n".join(lines)
