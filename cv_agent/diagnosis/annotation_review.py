"""Annotation-label review workflow for the primary failure-analysis sample (issue #75).

Responsibility: prepare the human-review inputs for the candidates in the existing primary-run review sample,
validate what a human reviewer records, and render the descriptive review report. It never decides a label.

Boundaries:
- Read-only on the source images, predictions, labels and the existing 42×46 crops. It writes review views and
  an extended review CSV in the analysis state root, and the committed report in docs/experiments.
- Human labels are authoritative only when entered by the named reviewer. This module refuses to overwrite any
  existing human label, and it never copies a suggestion into ``human_label``.
- No ExperimentLedger access. No GPU. No COCO annotation download. Q27 remains unresolved in this gate.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

RUBRIC_VERSION = "annotation-review-rubric/v1 (2026-10-06)"
REVIEWER_ID = "Tanvir"
ALLOWED_LABELS = ("annotation_error", "valid_annotation", "ambiguous", "not_reviewable", "crowd_region_unresolved")
CROWD_STATUS_UNRESOLVED = "q27_unresolved"
CROWD_STATUSES = (CROWD_STATUS_UNRESOLVED,)  # Q27 is unresolved for this gate: no other status may be written
ORIGINAL_COLUMNS = (
    "candidate_class",
    "rank",
    "image_stem",
    "source_key",
    "boxes",
    "crop_path",
    "human_label",
    "human_notes",
)
ADDED_COLUMNS = (
    "reviewer_id",
    "review_date",
    "rubric_version",
    "evidence_viewed",
    "crowd_status",
    "suggested_label_preliminary",
)
VIEW_CONTEXT_MIN_PX = 48  # the enlarged region keeps at least this much context around the candidate boxes
VIEW_MAX_SIDE_PX = 600  # the enlarged panel is scaled so its longer side is at most this (nearest neighbour)
VIEW_MAX_SCALE = 8
GT_COLOR = (220, 0, 0)
CANDIDATE_COLOR = (0, 110, 255)


class ReviewError(Exception):
    """A review step was refused. ``problems`` lists every issue found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class PrepareResult:
    rows: int
    views: int
    views_dir: str


def review_view_name(row: dict[str, str]) -> str:
    """The deterministic view file for one candidate: class, rank and image stem."""
    return f"{row['candidate_class']}_{int(row['rank']):03d}_{row['image_stem']}.png"


def _load_gt_context(per_gt_csv: Path) -> dict[str, list[tuple[float, float, float, float]]]:
    by_stem: dict[str, list[tuple[float, float, float, float]]] = {}
    with per_gt_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            box = (float(row["x1"]), float(row["y1"]), float(row["x2"]), float(row["y2"]))
            by_stem.setdefault(row["image_stem"], []).append(box)
    return by_stem


def render_review_view(
    image_path: Path,
    candidate_boxes: list[list[float]],
    context_boxes: list[tuple[float, float, float, float]],
    out_path: Path,
    *,
    header: str,
) -> None:
    """One PNG: the full image on the left (GT in red, candidate in blue), an enlarged local region on the right.

    Reads the source image and writes only ``out_path``. Nearest-neighbour upscaling keeps the pixels honest.
    """
    source = Image.open(image_path).convert("RGB")
    width, height = source.size
    full = source.copy()
    draw_full = ImageDraw.Draw(full)
    for box in context_boxes:
        draw_full.rectangle(box, outline=GT_COLOR, width=1)
    for cbox in candidate_boxes:
        draw_full.rectangle(cbox, outline=CANDIDATE_COLOR, width=3)

    xs = [b[0] for b in candidate_boxes] + [b[2] for b in candidate_boxes]
    ys = [b[1] for b in candidate_boxes] + [b[3] for b in candidate_boxes]
    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    side = max(x2 - x1, y2 - y1, 1.0)
    pad = max(VIEW_CONTEXT_MIN_PX, side)
    left = max(0, math.floor(x1 - pad))
    top = max(0, math.floor(y1 - pad))
    right = min(width, math.ceil(x2 + pad))
    bottom = min(height, math.ceil(y2 + pad))
    region = source.crop((left, top, max(right, left + 1), max(bottom, top + 1)))
    scale = max(1, min(VIEW_MAX_SCALE, VIEW_MAX_SIDE_PX // max(region.size)))
    enlarged = region.resize((region.width * scale, region.height * scale), Image.Resampling.NEAREST)
    draw_big = ImageDraw.Draw(enlarged)
    for box in context_boxes:
        bx1, by1, bx2, by2 = box
        if bx2 < left or bx1 > right or by2 < top or by1 > bottom:
            continue
        draw_big.rectangle(
            ((bx1 - left) * scale, (by1 - top) * scale, (bx2 - left) * scale, (by2 - top) * scale),
            outline=GT_COLOR,
            width=2,
        )
    for cbox in candidate_boxes:
        draw_big.rectangle(
            ((cbox[0] - left) * scale, (cbox[1] - top) * scale, (cbox[2] - left) * scale, (cbox[3] - top) * scale),
            outline=CANDIDATE_COLOR,
            width=3,
        )

    header_h = 26
    canvas = Image.new("RGB", (full.width + 16 + enlarged.width, max(full.height, enlarged.height) + header_h), (255, 255, 255))
    canvas.paste(full, (0, header_h))
    canvas.paste(enlarged, (full.width + 16, header_h))
    ImageDraw.Draw(canvas).text((6, 6), header, fill=(0, 0, 0))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG")


def _candidate_boxes(row: dict[str, str]) -> list[list[float]]:
    boxes = json.loads(row["boxes"])
    if not boxes or not all(len(b) == 4 for b in boxes):
        raise ReviewError([f"{review_view_name(row)}: boxes are malformed"])
    return [[float(v) for v in b] for b in boxes]


def prepare_review(
    *,
    sample_csv: Path,
    per_gt_csv: Path,
    images_dir: Path,
    views_dir: Path,
    reviewer_id: str = REVIEWER_ID,
    rubric_version: str = RUBRIC_VERSION,
) -> PrepareResult:
    """Generate one enlarged review view per candidate and extend the review CSV. No label is written."""
    with sample_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        existing = list(reader.fieldnames or [])
        rows = list(reader)
    accepted = (tuple(ORIGINAL_COLUMNS), tuple([*ORIGINAL_COLUMNS, *ADDED_COLUMNS]))
    if tuple(existing) not in accepted:
        raise ReviewError([f"review CSV columns {existing} do not match the expected {list(ORIGINAL_COLUMNS)}"])
    filled = [r for r in rows if r["human_label"].strip() or r["human_notes"].strip()]
    if filled:
        raise ReviewError([f"{len(filled)} rows already contain human entries; preparation will not overwrite them"])
    context = _load_gt_context(per_gt_csv)

    views = 0
    for row in rows:
        stem = row["image_stem"]
        # An image with no GT rows is a background image (no label file): its context is zero GT boxes.
        render_review_view(
            images_dir / f"{stem}.jpg",
            _candidate_boxes(row),
            context.get(stem, []),
            views_dir / review_view_name(row),
            header=f"{row['candidate_class']} #{row['rank']}  {stem}   red = GT  blue = candidate",
        )
        views += 1
        row["reviewer_id"] = reviewer_id
        row["review_date"] = ""
        row["rubric_version"] = rubric_version
        row["evidence_viewed"] = ""
        row["crowd_status"] = CROWD_STATUS_UNRESOLVED
        row["suggested_label_preliminary"] = ""

    with sample_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*ORIGINAL_COLUMNS, *ADDED_COLUMNS])
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in [*ORIGINAL_COLUMNS, *ADDED_COLUMNS]})
    return PrepareResult(rows=len(rows), views=views, views_dir=str(views_dir))


def validate_rows(rows: list[dict[str, str]]) -> list[str]:
    """Every problem with the human-review entries. An empty list means the entries are admissible."""
    problems: list[str] = []
    for index, row in enumerate(rows, start=1):
        name = f"row {index} ({row.get('candidate_class')} #{row.get('rank')} {row.get('image_stem')})"
        label = (row.get("human_label") or "").strip()
        if label and label not in ALLOWED_LABELS:
            problems.append(f"{name}: human_label {label!r} is not an allowed label")
        if label:
            if not (row.get("reviewer_id") or "").strip():
                problems.append(f"{name}: a human label needs a reviewer_id")
            if not (row.get("review_date") or "").strip():
                problems.append(f"{name}: a human label needs a review_date")
            if row.get("rubric_version") != RUBRIC_VERSION:
                problems.append(f"{name}: rubric_version must be {RUBRIC_VERSION!r}")
        if (row.get("crowd_status") or "") not in CROWD_STATUSES:
            problems.append(f"{name}: crowd_status {row.get('crowd_status')!r} is not allowed while Q27 is unresolved")
        if (row.get("suggested_label_preliminary") or "").strip() and label == (row.get("suggested_label_preliminary") or "").strip():
            problems.append(f"{name}: a suggestion must not be copied into human_label")
    return problems


def load_review_rows(sample_csv: Path) -> list[dict[str, str]]:
    with sample_csv.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def render_review_report(rows: list[dict[str, str]], *, rubric_version: str = RUBRIC_VERSION) -> str:
    """The committed review report. Labels that have not been entered are counted as pending."""
    problems = validate_rows(rows)
    if problems:
        raise ReviewError(problems)
    by_class = Counter(r["candidate_class"] for r in rows)
    labels = Counter((r["human_label"].strip() or "pending") for r in rows)
    reviewer = sorted({r["reviewer_id"] for r in rows if r["reviewer_id"].strip()}) or ["(none recorded)"]
    unresolved = sum(1 for r in rows if r["crowd_status"] == CROWD_STATUS_UNRESOLVED)
    lines = [
        "# Annotation-label review: EXP-20261004-01 primary-sample candidates",
        "",
        "**Descriptive review only.** No production decision is made. Q30 (operating point and precision floor)",
        "stays **OPEN**. D-069 stays **OPEN**. Q27 (official size-stratified mAP and crowd status) stays **OPEN**.",
        "",
        "## Scope and objective",
        "",
        "The 63 candidates come from the primary-run review sample of the failure analysis (`docs/experiments/"
        "FAILURE-ANALYSIS-EXP-20261004.md`, ADR-0015 §9.9). The review asks whether each candidate is an annotation "
        "error, a valid annotation, or cannot be decided from the evidence. It is the check that EVALUATION §27 requires "
        "before a model is blamed.",
        "",
        "**This review does not test the small-box bottleneck directly.** None of the 63 candidates is a missed GT box.",
        "**The 63 candidates are not a representative sample** for estimating population annotation-error rates. They "
        "were selected by fixed rules and a seeded draw, not at random from the population.",
        "",
        f"- Rubric version: `{rubric_version}`",
        f"- Reviewer(s): {', '.join(reviewer)}",
        "- Candidate selection: unchanged from the failure analysis (seed 20261004).",
        "",
        "## Candidate counts by class",
        "",
    ]
    for klass in ("high_conf_fp", "near_dup_gt_pair", "degenerate_gt"):
        lines.append(f"- {klass}: {by_class.get(klass, 0)}")
    lines += [f"- total: {len(rows)}", "", "## Human label counts", ""]
    for label in (*ALLOWED_LABELS, "pending"):
        lines.append(f"- {label}: {labels.get(label, 0)}")
    lines += [
        "",
        f"- ambiguous: {labels.get('ambiguous', 0)}; not_reviewable: {labels.get('not_reviewable', 0)}",
        "",
        "## Crowd status (Q27)",
        "",
        f"- Candidates with crowd status `{CROWD_STATUS_UNRESOLVED}`: {unresolved} of {len(rows)}.",
        "- `instances_val2017.json` has not been downloaded. Crowd status is unknown for every candidate.",
        "- No candidate is labelled as a crowd exclusion. A crowd-like region is recorded as "
        "`crowd_region_unresolved`, and it is never scored as an annotation error.",
        "",
        "## Rubric",
        "",
        "- **High-confidence FP:** `annotation_error` = a visible person at the predicted box that no GT covers. "
        "`valid_annotation` = no person is visible there.",
        "- **Near-duplicate GT pair:** `annotation_error` = both boxes mark the same person. `valid_annotation` = two "
        "visibly distinct people.",
        "- **Degenerate GT (a side < 2 px):** `annotation_error` = no person is visible at the box. `valid_annotation` = "
        "a person is visible and the small box is valid. A box is never erroneous merely because it is small.",
        "- `ambiguous` = the visual evidence cannot decide. `not_reviewable` = the evidence provided is insufficient.",
        "",
        "## Limitations",
        "",
        "- Single reviewer, no inter-rater check.",
        "- 63 candidates from fixed rules and a seeded draw. Not a representative sample of the population.",
        "- Review views are 2D image context. They cannot establish occlusion or depth.",
        "- Q27 unresolved: crowd-region candidates cannot be separated from missed persons.",
        "",
        "## Interpretation: what the review can and cannot establish",
        "",
        "- It can say how many of these 63 candidates are annotation errors, valid annotations, or undecidable, once "
        "entered by the reviewer.",
        "- If most sampled high-confidence FPs are `annotation_error`, the labels undercount persons in that sample. The "
        "FP counts in the failure analysis then need that caveat.",
        "- It cannot establish whether the 1,863 small-box misses at 0.25 are label errors or model errors. None is in "
        "the sample. Testing that needs a separate sample of fully missed small GT, which is out of scope here.",
        "- It makes no production decision. It sets no operating point, precision floor, tolerance or winner.",
        "",
        "## Status",
        "",
        "Human labels are pending. Nothing in this report was entered by the agent. The counts above change only when "
        "the reviewer enters labels.",
        "",
    ]
    return "\n".join(lines)
