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
- reference keys ``fixed_thr@0.25/<name>``: fixed-threshold precision/recall. The D-077 precision-floor
  measurement (conf 0.25, IoU>=0.5): never mAP, separate from full-curve AP.

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
from typing import Any, TypeGuard

from cv_agent.datasets.eval_ref import (
    EvalDatasetRef,
    EvalDatasetRefError,
    compute_label_digest,
    eval_items,
    load_eval_dataset_ref,
)
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
# The FP32 control (ADR-0018): quantize is left unset, so ultralytics runs with fp16=False.
PRECISION_FP32_REQUESTED = (
    "FP32 requested (quantize unset; ultralytics default None, fp16=False); "
    "actual inference precision is not logged"
)
FP32_CONTROL_SERIES_ID = "EXP-20261004-04"
FP32_CONTROL_BASELINE = "EXP-20261004-01"
LEGACY_REFERENCE = (
    "EXP-20260930-01 (and the 20261001 sweep rows) ran FP32: no precision argument was supplied, "
    "so ultralytics quantize defaulted to None. This series is FP16-requested and NOT like-for-like "
    "with those runs. Their mAP was also computed at conf=0.25 (truncated protocol, Q28)."
)
MODEL_NAME_EXPECTED = "yolo11n.pt"

# One owner-fixed candidate per approved proposal (ADR-0017 amendment 2026-11-15). The wrapper and the
# recorder share this contract so the rule is stated once.
CANDIDATE_IMGSZ_MIN = 320
CANDIDATE_IMGSZ_MAX = 1280
CANDIDATE_IMGSZ_STEP = 32
RESERVED_SERIES_IDS = frozenset(
    {SERIES_ID, "EXP-20261004-02", "EXP-20261004-03", FP32_CONTROL_SERIES_ID}
)
_EXP_ID_RE = re.compile(r"^EXP-\d{8}-\d{2}$")

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
    dataset_id: str
    dataset_version: str
    label_digest: str
    spec_sha256: str
    quantize: int | None = QUANTIZE
    environment: dict[str, str] | None = None
    vram_peak_above_idle_mib: int | None = None


def precision_label(quantize: int | None) -> str:
    """The requested-precision label for a verified quantize setting (never a measured precision)."""
    if quantize == QUANTIZE:
        return PRECISION_REQUESTED
    if quantize is None:
        return PRECISION_FP32_REQUESTED
    raise ValueError(f"no precision label for quantize={quantize!r}")


def is_exp_id(value: object) -> bool:
    """True for a well-formed experiment id (EXP-YYYYMMDD-NN)."""
    return isinstance(value, str) and _EXP_ID_RE.match(value) is not None


def candidate_problems(exp_id: str, imgsz: int) -> list[str]:
    """Why (exp_id, imgsz) cannot be an owner-fixed candidate. Empty means it can."""
    problems: list[str] = []
    if not is_exp_id(exp_id):
        problems.append(f"exp id {exp_id!r} must match EXP-YYYYMMDD-NN")
    elif exp_id in RESERVED_SERIES_IDS:
        problems.append(f"exp id {exp_id} is reserved for the EXP-20261004 series")
    if not _is_int(imgsz) or not (
        CANDIDATE_IMGSZ_MIN <= imgsz <= CANDIDATE_IMGSZ_MAX and imgsz % CANDIDATE_IMGSZ_STEP == 0
    ):
        problems.append(
            f"imgsz {imgsz!r} must be a multiple of {CANDIDATE_IMGSZ_STEP} "
            f"in [{CANDIDATE_IMGSZ_MIN}, {CANDIDATE_IMGSZ_MAX}]"
        )
    return problems


_DATASET_FRAGMENT = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")


def dataset_name_fragment(dataset_id: str) -> str:
    """The run-name fragment for a dataset: its id, if it is a safe path component (COCO: coco-val2017)."""
    if not isinstance(dataset_id, str) or not _DATASET_FRAGMENT.match(dataset_id):
        raise ValueError(f"dataset_id {dataset_id!r} cannot be a run-name fragment (lowercase, digits, '-' and '.')")
    return dataset_id


def series_run_name(imgsz: int, dataset_id: str, *, fp32: bool = False) -> str:
    """The EXP-20261004 series run directory name for a dataset."""
    return f"e1-yolo11n-{dataset_name_fragment(dataset_id)}-imgsz{imgsz}-conf0001{'-fp32' if fp32 else ''}"


def candidate_run_name(exp_id: str, imgsz: int, dataset_id: str) -> str:
    """The run directory name for a candidate: derived from the exp id and the dataset id, never free text."""
    return f"{exp_id.lower()}-yolo11n-{dataset_name_fragment(dataset_id)}-imgsz{imgsz}-conf0001"


def scoring_problems(ref: EvalDatasetRef) -> list[str]:
    """Why detection_metrics cannot score this reference yet. It scores class 0 only and has no ignore rule (I6)."""
    problems: list[str] = []
    if ref.target_class != 0:
        problems.append(f"target_class {ref.target_class} is not scorable: detection_metrics scores class 0 only (I6)")
    if ref.ignore_classes:
        problems.append("ignore_classes are not scorable: detection_metrics has no ignore rule yet (I6)")
    return problems


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


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


# Owner-directed exception (ADR-0018 §3.16, 2026-10-04): the NoMachine remote-desktop node holds a small
# amount of GPU memory and is not a workload. Matched by its exact process path, never by pid.
EXEMPT_GPU_PROCESS_NAMES = frozenset({"/usr/NX/bin/nxnode.bin"})


def is_exempt_process(proc: object) -> bool:
    """True only for an exact-name exempt process (ADR-0018 §3.16). Any other entry is blocking."""
    return isinstance(proc, dict) and proc.get("name") in EXEMPT_GPU_PROCESS_NAMES


def snapshot_foreign_pids(snapshot: object, own_pid: int) -> list[int] | None:
    """Pids in one GPU-process snapshot other than the run's own and exempt processes. None if unreadable."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("processes"), list):
        return None
    foreign: list[int] = []
    for proc in snapshot["processes"]:
        pid = proc.get("pid") if isinstance(proc, dict) else None
        if not _is_int(pid):
            return None
        if pid != own_pid and not is_exempt_process(proc):
            foreign.append(pid)
    return foreign


def foreign_process_seen(snapshots: object, own_pid: int) -> bool:
    """True if any readable snapshot (start, during, end) names a process other than the run's own."""
    if not isinstance(snapshots, dict):
        return False
    parts = [snapshots.get("start"), *(snapshots.get("during") or []), snapshots.get("end")]
    return any(snapshot_foreign_pids(part, own_pid) for part in parts)


def gpu_process_problems(run: dict) -> list[str]:
    """ADR-0018: GPU-process provenance. A run with a foreign GPU process at any point is not eligible."""
    snaps = run.get("gpu_process_snapshots")
    own = run.get("own_pid")
    if not isinstance(snaps, dict) or not _is_int(own):
        return ["run.json has no gpu_process_snapshots or own_pid: GPU-process provenance is required (ADR-0018)"]
    problems: list[str] = []
    start, during, end = snaps.get("start"), snaps.get("during"), snaps.get("end")
    if not isinstance(during, list) or not during:
        problems.append("GPU-process snapshots during polling are missing (ADR-0018)")
        during = []
    if not isinstance(start, dict) or not isinstance(start.get("processes"), list):
        problems.append("GPU-process snapshot at start is missing or unreadable: cannot read the GPU process list")
    elif [p for p in start["processes"] if not is_exempt_process(p)]:
        blocking = [p for p in start["processes"] if not is_exempt_process(p)]
        problems.append(f"GPU had {len(blocking)} compute process(es) before the run started")
    if not isinstance(end, dict) or not isinstance(end.get("processes"), list):
        problems.append("GPU-process snapshot at end is missing or unreadable")
    for index, snap in enumerate(during):
        if snapshot_foreign_pids(snap, own) is None:
            problems.append(f"GPU-process snapshot during[{index}] is unreadable")
    for index, snap in enumerate(during):
        foreign = snapshot_foreign_pids(snap, own)
        if foreign:
            problems.append(f"foreign GPU process during the run (pids {foreign}, sample {index})")
    end_foreign = snapshot_foreign_pids(end, own)
    if end_foreign:
        problems.append(f"foreign GPU process at end of the run (pids {end_foreign})")
    seen = foreign_process_seen(snaps, own)
    if run.get("foreign_process_seen") is not seen:
        problems.append(
            f"run.json foreign_process_seen={run.get('foreign_process_seen')!r} does not match the snapshots ({seen})"
        )
    return problems


def verify_run(
    run_dir: Path,
    *,
    imgsz: int,
    dataset_spec: Path,
    head_commit: str,
    quantize: int | None = QUANTIZE,
) -> VerifiedRun:
    """Verify one run directory end to end. Raises RecordError listing every problem found.

    ``dataset_spec`` is the ``eval_dataset_ref.json`` at the dataset root (ADR-0025): layout, list file,
    expected counts and target class come from it, and the label digest is recomputed from the files.

    ``quantize`` is the protocol the run must have been executed under: 16 for the FP16 series,
    None for the FP32 control (ADR-0018).
    """
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

    try:
        ref = load_eval_dataset_ref(Path(dataset_spec))
    except EvalDatasetRefError as exc:
        raise RecordError([f"dataset spec: {exc}"]) from exc
    dataset_root = Path(dataset_spec).resolve().parent
    problems.extend(scoring_problems(ref))
    for key, expected_value in (("spec_sha256", ref.spec_sha256), ("dataset_id", ref.dataset_id)):
        if run.get(key) != expected_value:
            problems.append(f"run.json {key}={run.get(key)!r}, the dataset spec has {expected_value!r}")

    protocol = {
        "imgsz": imgsz,
        "conf": MAP_PROTOCOL_CONF,
        "quantize": quantize,
        "batch": 1,
        "device": "0",
        "classes": [ref.target_class],
        "model": MODEL_NAME_EXPECTED,
    }
    for key, expected in protocol.items():
        if run.get(key) != expected:
            problems.append(f"run.json {key}={run.get(key)!r}, protocol requires {expected!r}")
    if run.get("precision_requested") != precision_label(quantize):
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
    problems.extend(gpu_process_problems(run))
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
    expected_list = (dataset_root / ref.list_file).resolve()
    if val_txt.resolve() != expected_list:
        problems.append(f"run.json val_txt {str(val_txt)!r} is not the dataset spec's list file {str(expected_list)!r}")
    for label, path, key in (
        ("weights", model_path, "model_sha256"),
        ("data yaml", data_yaml, "data_yaml_sha256"),
        ("val list", val_txt, "val_txt_sha256"),
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
        if images != ref.expected_images or instances != ref.expected_instances:
            problems.append(
                f"val.log counts images={images} instances={instances}; "
                f"dataset expects {ref.expected_images}/{ref.expected_instances}"
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
    if not (dataset_root / ref.images_dir).is_dir() or not (dataset_root / ref.labels_dir).is_dir():
        problems.append(f"dataset images/labels not found under {dataset_root}")
    if problems:
        raise RecordError(problems)
    commit_text = str(run["commit"])

    size_by_stem: dict[str, tuple[int, int]] = {}
    gt_by_stem = {}
    try:
        items = eval_items(ref, dataset_root)
        label_digest = compute_label_digest(ref, dataset_root)
        for stem, image, label_path in items:
            width, height = jpeg_size(image)
            size_by_stem[stem] = (width, height)
            gt_by_stem[stem] = load_person_gt(label_path, width, height)
    except (EvalDatasetRefError, OSError, ValueError) as exc:
        raise RecordError([f"dataset under {dataset_root} is unreadable: {exc}"]) from exc
    n_images = len(size_by_stem)
    n_gt = sum(len(v) for v in gt_by_stem.values())
    if n_images != ref.expected_images or n_gt != ref.expected_instances:
        raise RecordError(
            [f"dataset under {dataset_root} has {n_images} images / {n_gt} GT persons; "
             f"expected {ref.expected_images} / {ref.expected_instances}"]
        )
    digest_problems: list[str] = []
    if run.get("label_digest") != label_digest:
        digest_problems.append(
            f"run.json label_digest={run.get('label_digest')!r} != the labels now on disk ({label_digest}): "
            "labels changed since the run, or the run recorded none"
        )
    if ref.label_digest is not None and ref.label_digest != label_digest:
        digest_problems.append(f"labels on disk ({label_digest}) differ from the spec's label_digest ({ref.label_digest})")
    if digest_problems:
        raise RecordError(digest_problems)

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
        quantize=quantize,
        dataset_id=str(ref.dataset_id),
        dataset_version=ref.render_ledger_label(list_sha256=str(run["val_txt_sha256"])),
        label_digest=label_digest,
        spec_sha256=ref.spec_sha256,
        ram_peak_mib=ram_peak,
        environment=run.get("environment") if isinstance(run.get("environment"), dict) else None,
        vram_peak_above_idle_mib=above if isinstance(above := run.get("vram_peak_above_idle_mib"), int) else None,
    )


def build_record(
    run: VerifiedRun,
    *,
    exp_id: str,
    baseline_id: str,
    approval_ref: str,
    hypothesis: str = HYPOTHESIS,
    success_criteria: str = SUCCESS_CRITERIA,
    series_note: str | None = None,
) -> ExperimentRecord:
    """The ExperimentRecord for one verified run. Only measured values are populated.

    ``hypothesis``, ``success_criteria`` and ``series_note`` default to the EXP-20261004 series text; a
    candidate record passes the text of its proposal (ADR-0017 amendment 2026-11-15).
    """
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
    is_control = run.quantize is None
    notes = {
        "series": series_note
        if series_note is not None
        else (
            f"{FP32_CONTROL_SERIES_ID} FP32 control (measurement-only, D-069, ADR-0018)"
            if is_control
            else f"{SERIES_ID} measurement-only (D-069); this record is one image size of the series"
        ),
        **({"legacy_reference": LEGACY_REFERENCE} if baseline_id == "SELF" else {}),
        **(
            {
                "precision_control": (
                    f"Compared with {baseline_id} (FP16 requested, quantize=16) at identical imgsz, conf, "
                    "dataset, batch, device and code. quantize is the only intended difference. "
                    "Reference for the precision question only; not a decision (D-069)."
                )
            }
            if is_control
            else {}
        ),
        "confidence_protocol": (
            f"conf={MAP_PROTOCOL_CONF} (Q28/D-067) for mAP and AP@0.5/* (full PR curve). "
            f"fixed_thr@{FIXED_THRESHOLD}/* is the D-077 floor measurement (conf 0.25, IoU>=0.5): never mAP, separate from full-curve AP."
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
        "precision_requested": precision_label(run.quantize),
        "approval_ref": run.approval_ref,
        "units": {"memory": "MiB (peak VRAM from nvidia-smi; peak RAM from getrusage ru_maxrss)"},
        "derived": {
            "gpu_hours": f"wall_seconds / 3600 = {run.wall_seconds:.3f} s / 3600 (one GPU; derived, not a separate meter)"
        },
        "not_measured": ["train_time", "power", "flops (ultralytics reports GFLOPs only; see notes)"],
        "vram_baseline_mib": run.vram_baseline_mib,
        **({"vram_peak_above_idle_mib": run.vram_peak_above_idle_mib} if run.vram_peak_above_idle_mib is not None else {}),
        **({"environment": run.environment} if run.environment is not None else {}),
        "omitted_metrics": list(run.omitted_strata),
        "predictions_min_person_score": run.min_person_score,
        "dataset_ref": f"{run.dataset_id} (version label {run.dataset_version})",
        "label_digest": run.label_digest,
        "spec_sha256": run.spec_sha256,
        "artifacts": run.artifacts,
    }
    target = run.gpu_name if not run.driver_version else f"{run.gpu_name}, driver {run.driver_version}"
    return ExperimentRecord(
        exp_id=exp_id,
        status="completed",
        hypothesis=hypothesis,
        success_criteria=success_criteria,
        baseline_id=baseline_id,
        created_at=run.started_at,
        completed_at=run.ended_at,
        commit=run.commit,
        approval_ref=approval_ref,
        model=(
            f"yolo11n ({run.model_name} sha256 {run.model_sha256}, "
            f"{run.params:,} params, {run.gflops} GFLOPs as reported by ultralytics)"
        ),
        dataset_version=run.dataset_version,
        input_resolution=f"{run.imgsz}x{run.imgsz}",
        batch_size=1,
        precision=precision_label(run.quantize),
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
