"""
cv_agent.experiments.evaluation_records — verify one measured `yolo val` run and record it.

Responsibility: turn a run directory written by scripts/run_yolo_val_measured.py into an
ExperimentRecord, or refuse. Nothing is recorded from a run that is missing, malformed, truncated,
off-protocol, or produced from a different commit than the one being recorded (ADR-0017).

Boundary: the experiments layer owns record creation from verified run artifacts. The metric
math lives in cv_agent.experiments.detection_metrics. The log regexes below mirror the ultralytics
`yolo val` output format; they are kept here so this layer does not depend on the execution layer.

Two kinds of metric, kept apart in val_metrics:
- standard keys ``mAP@0.5``, ``mAP@0.5:0.95``, ``AP@0.5/<size>``: full PR curve at conf=0.001 (Q28).
- reference keys ``fixed_thr@0.25/<name>``: fixed-threshold precision/recall. Reference only, not mAP,
  not an operating point (Q30 is open).

Nothing is fabricated. A value that was not measured is None or absent, and the notes say so.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cv_agent.experiments.detection_metrics import (
    MAP_PROTOCOL_CONF,
    assert_full_curve,
    evaluate,
    jpeg_size,
    load_person_gt,
    load_person_predictions,
    stratum_ap50,
)
from cv_agent.experiments.models import (
    ExperimentRecord,
    HardwareInfo,
    LatencyMeasurement,
    MemoryFootprint,
)

RUN_SCHEMA = "cv-agent/yolo-val-run/v1"
FIXED_THRESHOLD = 0.25
SERIES_ID = "EXP-20261004-01"
HYPOTHESIS = (
    "Measurement-only (EXP-20261004-01, proposal §2): how do threshold-free AP@0.5 by object size, "
    "mAP at conf=0.001, and reference fixed-threshold P/R at 0.25 change with inference image size "
    "for YOLO11n on COCO val2017 persons? Only imgsz varies."
)
SUCCESS_CRITERIA = (
    "Measurement-only (D-069): no pass/fail threshold. Reports threshold-free AP@0.5 by size, mAP at "
    "conf=0.001, and reference fixed-threshold P/R at 0.25."
)
QUANTIZE = 16
# What was REQUESTED, never what was measured: ultralytics does not log actual inference precision.
PRECISION_REQUESTED = "FP16 requested (quantize=16); actual inference precision is not logged"
LEGACY_REFERENCE = (
    "EXP-20260930-01 (and the 20261001 sweep rows) ran FP32: no precision argument was supplied, "
    "so ultralytics quantize defaulted to None. This series is FP16-requested and NOT like-for-like "
    "with those runs. Their mAP was also computed at conf=0.25 (truncated protocol, Q28)."
)
MODEL_NAME_EXPECTED = "yolo11n.pt"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SUMMARY_ROW = re.compile(
    r"^\s+(all|person)\s+(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+"
    r"(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*$",
    re.MULTILINE,
)
_SPEED = re.compile(
    r"Speed:\s+(\d+(?:\.\d+)?)ms preprocess,\s+(\d+(?:\.\d+)?)ms inference,\s+"
    r"(\d+(?:\.\d+)?)ms loss,\s+(\d+(?:\.\d+)?)ms postprocess per image"
)
_SUMMARY = re.compile(
    r"summary \(fused\):\s*\d+ layers,\s*([\d,]+) parameters,\s*\d+ gradients,\s*(\d+(?:\.\d+)?) GFLOPs"
)
_VERSION = re.compile(r"^Ultralytics\s+(\S+)", re.MULTILINE)


class RecordError(Exception):
    """Raised when a run cannot be verified or recorded. ``problems`` lists every reason found."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class DatasetExpectation:
    """Counts the dataset must have. Defaults are coco-val2017-5k; tests use small datasets."""

    images: int = 5000
    gt_persons: int = 10777


@dataclass(frozen=True)
class VerifiedRun:
    """A run whose artifacts passed every check. Only this type may be turned into a record."""

    imgsz: int
    run_dir: Path
    commit: str
    started_at: str
    ended_at: str
    wall_seconds: float
    model_name: str
    model_sha256: str
    data_yaml_sha256: str
    val_txt_sha256: str
    gpu_name: str
    driver_version: str | None
    ultralytics_version: str
    params: int
    gflops: float
    map50: float
    map50_95: float
    pre_ms: float
    inf_ms: float
    post_ms: float
    ap50: dict[str, float]
    omitted_strata: tuple[str, ...]
    fixed: dict[str, float]
    images: int
    gt_persons: int
    min_person_score: float
    artifacts: dict[str, dict[str, str]]
    approval_ref: str
    vram_baseline_mib: int | None
    vram_peak_mib: int
    ram_peak_mib: float


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_paths(run_dir: Path) -> tuple[Path, Path, Path]:
    """(run.json, val.log, predictions.json) for a run directory named <project>/<name>."""
    return (
        run_dir.parent / f"{run_dir.name}.run.json",
        run_dir.parent / f"{run_dir.name}.val.log",
        run_dir / "predictions.json",
    )


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _num(value: object) -> float:
    """The value as a float, or NaN when it is not a finite number (so comparisons are False)."""
    return float(value) if _finite(value) else float("nan")  # type: ignore[arg-type]


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _check_predictions_shape(path: Path, problems: list[str]) -> None:
    """Every item must be a well-formed COCO detection. Malformed input is refused, not repaired."""
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"predictions.json unreadable or invalid JSON: {exc}")
        return
    if not isinstance(records, list) or not records:
        problems.append("predictions.json must be a non-empty list")
        return
    for index, rec in enumerate(records):
        if not isinstance(rec, dict):
            problems.append(f"predictions.json item {index} is not an object")
            return
        if not isinstance(rec.get("image_id"), int) or not isinstance(rec.get("category_id"), int):
            problems.append(f"predictions.json item {index} has a non-integer image_id/category_id")
            return
        if not isinstance(rec.get("file_name"), str):
            problems.append(f"predictions.json item {index} has no file_name")
            return
        bbox = rec.get("bbox")
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or not all(_finite(v) for v in bbox)
            or bbox[2] < 0
            or bbox[3] < 0
        ):
            problems.append(f"predictions.json item {index} has a malformed bbox")
            return
        score = rec.get("score")
        if not 0.0 <= _num(score) <= 1.0:
            problems.append(f"predictions.json item {index} has a non-finite or out-of-range score")
            return


def verify_run(
    run_dir: Path,
    *,
    imgsz: int,
    coco_root: Path,
    head_commit: str,
    dataset: DatasetExpectation = DatasetExpectation(),
) -> VerifiedRun:
    """Verify one run directory end to end. Raises RecordError listing every problem found."""
    run_dir = Path(run_dir)
    run_json, val_log, predictions = run_paths(run_dir)
    problems: list[str] = []

    for label, path in (("run.json", run_json), ("val.log", val_log), ("predictions.json", predictions)):
        if not path.is_file():
            problems.append(f"{label} is missing: {path}")
    if problems:
        raise RecordError(problems)

    # ── run.json: how the run was executed ───────────────────────────────────────
    try:
        run = json.loads(run_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecordError([f"run.json is not valid JSON: {exc}"]) from exc
    if not isinstance(run, dict) or run.get("schema") != RUN_SCHEMA:
        raise RecordError([f"run.json schema is not {RUN_SCHEMA}"])

    protocol = {
        "imgsz": imgsz,
        "conf": MAP_PROTOCOL_CONF,
        "quantize": QUANTIZE,
        "batch": 1,
        "device": "0",
        "classes": [0],
        "model": MODEL_NAME_EXPECTED,
    }
    for key, expected in protocol.items():
        if run.get(key) != expected:
            problems.append(f"run.json {key}={run.get(key)!r}, protocol requires {expected!r}")
    if run.get("precision_requested") != PRECISION_REQUESTED:
        problems.append("run.json precision_requested must be the exact requested-precision label")
    approval = run.get("approval_ref")
    if not isinstance(approval, str) or not approval.strip():
        problems.append("run.json has no approval_ref (GPU runs require an owner approval reference)")
    vram_peak = run.get("vram_peak_mib")
    if not (isinstance(vram_peak, int) and not isinstance(vram_peak, bool) and vram_peak > 0):
        problems.append("run.json vram_peak_mib is missing or not a positive integer (system metric required)")
    ram_peak = _num(run.get("ram_peak_mib"))
    if not ram_peak > 0:
        problems.append("run.json ram_peak_mib is missing or not positive (system metric required)")
    if run.get("exit_code") != 0:
        problems.append(f"yolo val exit_code={run.get('exit_code')!r} (must be 0)")
    if run.get("commit") != head_commit:
        problems.append(
            f"run commit {run.get('commit')!r} != HEAD {head_commit!r}: "
            "the code that ran must be the code being recorded"
        )
    if not isinstance(run.get("commit"), str) or not _SHA_RE.match(run.get("commit", "")):
        problems.append("run.json commit is not a 40-character SHA")
    started = _parse_iso(run.get("started_at"))
    ended = _parse_iso(run.get("ended_at"))
    wall = run.get("wall_seconds")
    started_iso = started.isoformat() if started is not None else ""
    ended_iso = ended.isoformat() if ended is not None else ""
    if started is None or ended is None:
        problems.append("run.json started_at/ended_at are missing or malformed")
    elif ended < started:
        problems.append("run.json ended_at is before started_at")
    wall_s = _num(wall)
    if not wall_s > 0:
        problems.append("run.json wall_seconds is missing or not positive")
    gpu_name = run.get("gpu_name")
    gpu_text = gpu_name.strip() if isinstance(gpu_name, str) else ""
    if not gpu_text:
        problems.append("run.json has no GPU identity (hardware is required evidence)")

    model_path = Path(str(run.get("model_path", "")))
    data_yaml = Path(str(run.get("data_yaml", "")))
    val_txt = Path(str(run.get("val_txt", "")))
    for label, path, key in (
        ("weights", model_path, "model_sha256"),
        ("data yaml", data_yaml, "data_yaml_sha256"),
        ("val2017.txt", val_txt, "val_txt_sha256"),
    ):
        if not path.is_file():
            problems.append(f"{label} is missing: {path}")
        elif sha256_file(path) != run.get(key):
            problems.append(f"{label} changed since the run ({path}): sha256 differs from run.json")

    # ── val.log: what ultralytics measured ───────────────────────────────────────
    text = val_log.read_text(encoding="utf-8", errors="replace")
    if "Traceback (most recent call last)" in text:
        problems.append("val.log contains a Traceback")
    # The COCO aggregate row is the one named "all". The row named "person" is a per-class row that
    # ultralytics also prints; it is never used for the dataset counts (it reports 2693 images here).
    aggregate = [m for m in _SUMMARY_ROW.finditer(text) if m.group(1) == "all"]
    row = aggregate[0] if len(aggregate) == 1 else None
    if row is None:
        problems.append(f"val.log must contain exactly one 'all' aggregate row (found {len(aggregate)})")
        map50 = map50_95 = float("nan")
        images = instances = -1
    else:
        images, instances = int(row.group(2)), int(row.group(3))
        map50, map50_95 = float(row.group(6)), float(row.group(7))
        if not (0.0 <= map50 <= 1.0 and 0.0 <= map50_95 <= 1.0):
            problems.append("val.log mAP values are outside [0, 1]")
        if images != dataset.images or instances != dataset.gt_persons:
            problems.append(
                f"val.log counts images={images} instances={instances}; "
                f"dataset expects {dataset.images}/{dataset.gt_persons}"
            )
    speed = _SPEED.search(text)
    if speed is None:
        problems.append("val.log has no 'Speed:' line (no measured latency)")
        pre = inf_ms = post = float("nan")
    else:
        pre, inf_ms, post = float(speed.group(1)), float(speed.group(2)), float(speed.group(4))
    summary = _SUMMARY.search(text)
    if summary is None:
        problems.append("val.log has no YOLO model summary line (params/GFLOPs)")
        params, gflops = -1, float("nan")
    else:
        params, gflops = int(summary.group(1).replace(",", "")), float(summary.group(2))
    version = _VERSION.search(text)
    ultralytics_version = version.group(1) if version else ""

    # ── predictions.json: the curve must be full, and the shape must be sound ──────
    shape_problems: list[str] = []
    _check_predictions_shape(predictions, shape_problems)
    problems.extend(shape_problems)
    min_score = float("nan")
    if not shape_problems:  # the full-curve check only makes sense on a well-formed file
        try:
            min_score = assert_full_curve(predictions)
        except ValueError as exc:
            problems.append(str(exc))

    # ── dataset counts and per-stratum metrics (only when everything above passed) ──
    image_dir = coco_root / "images" / "val2017"
    label_dir = coco_root / "labels" / "val2017"
    if not image_dir.is_dir() or not label_dir.is_dir():
        problems.append(f"dataset images/labels not found under {coco_root}")
    if problems:
        raise RecordError(problems)
    commit_text = str(run["commit"])

    size_by_stem: dict[str, tuple[int, int]] = {}
    gt_by_stem = {}
    for image in sorted(image_dir.glob("*.jpg")):
        width, height = jpeg_size(image)
        size_by_stem[image.stem] = (width, height)
        gt_by_stem[image.stem] = load_person_gt(label_dir / f"{image.stem}.txt", width, height)
    n_images = len(size_by_stem)
    n_gt = sum(len(v) for v in gt_by_stem.values())
    if n_images != dataset.images or n_gt != dataset.gt_persons:
        raise RecordError(
            [f"dataset under {coco_root} has {n_images} images / {n_gt} GT persons; "
             f"expected {dataset.images} / {dataset.gt_persons}"]
        )

    full = load_person_predictions(predictions, MAP_PROTOCOL_CONF)
    ap50: dict[str, float] = {}
    omitted: list[str] = []
    for stratum in ("small", "medium", "large"):
        value = stratum_ap50(full, gt_by_stem, size_by_stem, stratum)
        if value is None:
            omitted.append(f"AP@0.5/{stratum}")
        else:
            ap50[stratum] = value

    fixed_preds = load_person_predictions(predictions, FIXED_THRESHOLD)
    report = evaluate(fixed_preds, gt_by_stem, FIXED_THRESHOLD)
    fixed: dict[str, float] = {
        "precision": report.precision(),
        "recall": report.recall(),
    }
    for key in ("small", "medium", "large", "dense", "sparse"):
        count = report.strata.get(key)
        if count is None or count.total == 0:
            omitted.append(f"fixed_thr@{FIXED_THRESHOLD}/recall_{key}")
        else:
            fixed[f"recall_{key}"] = count.recall()

    artifacts = {
        "val_log": {"path": str(val_log), "sha256": sha256_file(val_log)},
        "predictions_json": {"path": str(predictions), "sha256": sha256_file(predictions)},
        "run_json": {"path": str(run_json), "sha256": sha256_file(run_json)},
        "weights": {"path": str(model_path), "sha256": run["model_sha256"]},
        "data_yaml": {"path": str(data_yaml), "sha256": run["data_yaml_sha256"]},
        "val_txt": {"path": str(val_txt), "sha256": run["val_txt_sha256"]},
    }
    return VerifiedRun(
        imgsz=imgsz,
        run_dir=run_dir,
        commit=commit_text,
        started_at=started_iso,
        ended_at=ended_iso,
        wall_seconds=wall_s,
        model_name=MODEL_NAME_EXPECTED,
        model_sha256=str(run["model_sha256"]),
        data_yaml_sha256=str(run["data_yaml_sha256"]),
        val_txt_sha256=str(run["val_txt_sha256"]),
        gpu_name=gpu_text,
        driver_version=run.get("driver_version") if isinstance(run.get("driver_version"), str) else None,
        ultralytics_version=ultralytics_version,
        params=params,
        gflops=gflops,
        map50=map50,
        map50_95=map50_95,
        pre_ms=pre,
        inf_ms=inf_ms,
        post_ms=post,
        ap50=ap50,
        omitted_strata=tuple(omitted),
        fixed=fixed,
        images=n_images,
        gt_persons=n_gt,
        min_person_score=min_score,
        artifacts=artifacts,
        approval_ref=str(approval).strip(),
        vram_baseline_mib=run["vram_baseline_mib"] if isinstance(run.get("vram_baseline_mib"), int) else None,
        vram_peak_mib=int(vram_peak or 0),
        ram_peak_mib=ram_peak,
    )


def build_record(run: VerifiedRun, *, exp_id: str, baseline_id: str, approval_ref: str) -> ExperimentRecord:
    """The ExperimentRecord for one verified run. Only measured values are populated."""
    if run.approval_ref != approval_ref:
        raise RecordError(
            [f"run approval_ref {run.approval_ref!r} != requested {approval_ref!r}: "
             "every run in a series must carry the same approval"]
        )
    val_metrics: dict[str, float] = {"mAP@0.5": run.map50, "mAP@0.5:0.95": run.map50_95}
    for stratum, value in run.ap50.items():
        val_metrics[f"AP@0.5/{stratum}"] = value
    for name, value in run.fixed.items():
        val_metrics[f"fixed_thr@{FIXED_THRESHOLD}/{name}"] = value

    fps = run.images / run.wall_seconds
    notes = {
        "series": f"{SERIES_ID} measurement-only (D-069); this record is one image size of the series",
        **({"legacy_reference": LEGACY_REFERENCE} if baseline_id == "SELF" else {}),
        "confidence_protocol": (
            f"conf={MAP_PROTOCOL_CONF} (Q28/D-067) for mAP and AP@0.5/* (full PR curve). "
            f"fixed_thr@{FIXED_THRESHOLD}/* are REFERENCE ONLY: not mAP, not an operating point (Q30 open)."
        ),
        "imgsz": run.imgsz,
        "gflops_reported_by_ultralytics": run.gflops,
        "ultralytics_version": run.ultralytics_version,
        "derivations": {
            "latency_end_to_end_ms": "preprocess + inference + postprocess per image, from the val.log Speed line",
            "latency_inference_only_ms": "inference per image, from the val.log Speed line",
            "fps": f"{run.images} images / measured wall_seconds ({run.wall_seconds:.3f} s)",
            "params": "from the val.log YOLO model summary line",
        },
        "precision_requested": PRECISION_REQUESTED,
        "approval_ref": run.approval_ref,
        "units": {"memory": "MiB (peak VRAM from nvidia-smi; peak RAM from getrusage ru_maxrss)"},
        "derived": {
            "gpu_hours": f"wall_seconds / 3600 = {run.wall_seconds:.3f} s / 3600 (one GPU; derived, not a separate meter)"
        },
        "not_measured": ["train_time", "power", "flops (ultralytics reports GFLOPs only; see notes)"],
        "vram_baseline_mib": run.vram_baseline_mib,
        "omitted_metrics": list(run.omitted_strata),
        "predictions_min_person_score": run.min_person_score,
        "artifacts": run.artifacts,
    }
    target = run.gpu_name if not run.driver_version else f"{run.gpu_name}, driver {run.driver_version}"
    return ExperimentRecord(
        exp_id=exp_id,
        status="completed",
        hypothesis=HYPOTHESIS,
        success_criteria=SUCCESS_CRITERIA,
        baseline_id=baseline_id,
        created_at=run.started_at,
        completed_at=run.ended_at,
        commit=run.commit,
        approval_ref=approval_ref,
        model=(
            f"yolo11n ({run.model_name} sha256 {run.model_sha256}, "
            f"{run.params:,} params, {run.gflops} GFLOPs as reported by ultralytics)"
        ),
        dataset_version=f"coco-val2017-5k (val2017.txt sha256 {run.val_txt_sha256})",
        input_resolution=f"{run.imgsz}x{run.imgsz}",
        batch_size=1,
        precision=PRECISION_REQUESTED,
        memory=MemoryFootprint(vram=float(run.vram_peak_mib), ram=run.ram_peak_mib),
        gpu_hours=run.wall_seconds / 3600.0,
        hardware=HardwareInfo(training="N/A (inference only)", target=target),
        params=run.params,
        fps=fps,
        latency=LatencyMeasurement(
            end_to_end=run.pre_ms + run.inf_ms + run.post_ms,
            inference_only=run.inf_ms,
        ),
        val_metrics=val_metrics,
        notes=json.dumps(notes, sort_keys=True, ensure_ascii=False),
    )


def preflight_new_ids(ledger: Any, exp_ids: list[str]) -> None:
    """Refuse if any target id already exists in any status. Historical records are never modified."""
    taken = [e for e in exp_ids if ledger.get_experiment(e) is not None]
    if taken:
        raise RecordError([f"{e} already exists in the ledger; records are not modified" for e in taken])


def write_records(ledger: Any, records: list[ExperimentRecord]) -> list[str]:
    """Write records in order. On a ledger error, report exactly which were already written."""
    written: list[str] = []
    for record in records:
        try:
            ledger.record_experiment(record)
        except Exception as exc:  # noqa: BLE001 — surface every failure with the partial state
            raise RecordError(
                [f"failed writing {record.exp_id}: {exc}; already written: {written or 'none'}"]
            ) from exc
        written.append(record.exp_id)
    return written
