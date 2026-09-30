"""
cv_agent.execution.jobs.runtimes.yolo_eval — YOLO11n person detection evaluation
binding for LinuxNvidiaJobRuntime (ADR-0009 §8, ADR-0013).

Binding for the `yolo-eval` skill using the `yolo val` CLI to evaluate YOLO11n
person detection accuracy on a labelled dataset (D-043 reference task).

ADR-0009 §8 discipline — why verified=True:

CLI location: `/home/dev/.local/bin/yolo` (same as yolo_inference binding, D-055).
  Confirmed present and executable; version 8.4.138 via `yolo version`.

Model: `yolo11n.pt` — same model as yolo_inference, D-055.

CLI contract (verified empirically via `yolo val --help` and the coco8.yaml run
completed 2026-09-30):
  Mode: `val` — evaluates detection on a labelled dataset split.
  Syntax: `yolo val <key=value ...>` (no leading dashes; KEY=VALUE pairs).
  Required args: `model=<path>`, `data=<yaml_path>`.
  Optional relevant args:
    classes=[0]           — filter to COCO class 0 (person) only
    conf=0.25             — detection confidence threshold
    imgsz=640             — inference resolution
    device=0              — GPU device
    project=<dir>         — output root directory
    name=<run_name>       — output subdirectory

Exit codes: 0 = success; non-zero = failure.

Stdout metrics table format (ANSI-stripped):
  Class     Images  Instances      Box(P          R      mAP50  mAP50-95)
    all       5000      36335      0.685      0.574      0.615      0.439
  person      5000      36335      0.685      0.574      0.615      0.439
Speed: 0.5ms preprocess, 2.3ms inference, 0.0ms loss, 1.1ms postprocess per image

parse_metrics() extracts these values from stdout by regex.

Dataset: COCO val2017 (5000 images, truly held-out from yolo11n's training set)
  — see D-061 and EXP-20260930-01.

What this binding does NOT claim:
  - Does not compute tracking metrics (MOTA, IDF1 — those require GT tracking data).
  - Does not perform training or fine-tuning.
  - Does not modify the model or dataset.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cv_agent.execution.binding import ExecutionBinding, ExecutionBindingRegistry, InputField
from cv_agent.execution.jobs.runtimes.linux_nvidia import (
    RUNTIME_ID as _LINUX_NVIDIA_RUNTIME_ID,
)
from cv_agent.execution.models import ApprovalPolicy

SKILL_ID = "yolo-eval"
BINDING_ID = "yolo11n-person-val-linux-job-v1"
RUNTIME_ID = _LINUX_NVIDIA_RUNTIME_ID

DEFAULT_MODEL = "yolo11n.pt"
DEFAULT_CONF = 0.25
DEFAULT_IMGSZ = 640
DEFAULT_CLASSES = [0]  # COCO class 0 = person
DEFAULT_YOLO_EXECUTABLE = "yolo"
DEFAULT_BATCH = 1

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[mK]")


# ---------------------------------------------------------------------------
# Command builder
# ---------------------------------------------------------------------------


def build_command(inputs: dict[str, Any]) -> list[str]:
    """
    Build the `yolo val` command list from request inputs.

    Required inputs:
        data: str       — absolute path to dataset YAML (e.g. coco-person-val.yaml)
        output_dir: str — absolute path for output root (project= argument)
        run_name: str   — output subdirectory name (name= argument)

    Optional inputs:
        model: str        — model name or path (default: "yolo11n.pt")
        conf: float       — confidence threshold (default: 0.25)
        imgsz: int        — inference image size (default: 640)
        classes: list[int]— class IDs to evaluate (default: [0] = person)
        device: str       — compute device: "0" for GPU 0, "cpu" (default: "0")
        batch: int        — validation batch size (default: 1)
        yolo_executable: str — yolo CLI executable (default: "yolo")

    Returns a list[str] suitable for subprocess.Popen(command, ...).
    """
    data = inputs.get("data")
    output_dir = inputs.get("output_dir")
    run_name = inputs.get("run_name")

    if not data:
        raise ValueError("yolo_eval binding: inputs['data'] is required (path to dataset YAML).")
    if not output_dir:
        raise ValueError("yolo_eval binding: inputs['output_dir'] is required.")
    if not run_name:
        raise ValueError("yolo_eval binding: inputs['run_name'] is required.")

    model = inputs.get("model", DEFAULT_MODEL)
    conf = inputs.get("conf", DEFAULT_CONF)
    imgsz = inputs.get("imgsz", DEFAULT_IMGSZ)
    classes: list[int] = inputs.get("classes", DEFAULT_CLASSES)
    device = inputs.get("device", "0")
    batch = inputs.get("batch", DEFAULT_BATCH)
    exe = inputs.get("yolo_executable", DEFAULT_YOLO_EXECUTABLE)

    classes_str = "[" + ",".join(str(c) for c in classes) + "]"

    return [
        exe,
        "val",
        f"model={model}",
        f"data={data}",
        f"classes={classes_str}",
        f"conf={conf}",
        f"imgsz={imgsz}",
        f"batch={batch}",
        f"project={output_dir}",
        f"name={run_name}",
        f"device={device}",
    ]


# ---------------------------------------------------------------------------
# Metrics parser
# ---------------------------------------------------------------------------


def parse_metrics(stdout: str) -> dict[str, float]:
    """
    Parse `yolo val` stdout to extract per-class and speed metrics.

    Expects the standard ultralytics val output format.  Strips ANSI escape
    codes before matching.  Returns an empty dict if neither the metrics table
    row nor the speed line can be parsed — the caller must treat an empty dict
    as a parse failure, not as "zero metrics".

    Parsed keys (all float):
      precision       — Box(P) for person class (or "all" if person not found)
      recall          — Box(R)
      map50           — mAP@0.5
      map50_95        — mAP@0.5:0.95
      speed_preprocess_ms  — preprocess time per image (ms)
      speed_inference_ms   — inference time per image (ms)
      speed_postprocess_ms — postprocess time per image (ms)
    """
    clean = _ANSI_ESCAPE.sub("", stdout)
    result: dict[str, float] = {}

    # metrics table row: "  person   IMAGES   INSTANCES   P   R   mAP50   mAP50-95"
    # class name may be "all" or "person" — prefer "person"
    row_re = re.compile(
        r"^\s+(person|all)\s+\d+\s+\d+\s+"
        r"(\d+(?:\.\d+)?)\s+"   # P
        r"(\d+(?:\.\d+)?)\s+"   # R
        r"(\d+(?:\.\d+)?)\s+"   # mAP50
        r"(\d+(?:\.\d+)?)"      # mAP50-95
        r"\s*$",
        re.MULTILINE,
    )
    # Prefer person row; fall back to all
    person_match = None
    all_match = None
    for m in row_re.finditer(clean):
        if m.group(1) == "person":
            person_match = m
        elif m.group(1) == "all":
            all_match = m
    row = person_match or all_match
    if row:
        result["precision"] = float(row.group(2))
        result["recall"] = float(row.group(3))
        result["map50"] = float(row.group(4))
        result["map50_95"] = float(row.group(5))

    # Speed line: "Speed: 0.5ms preprocess, 2.3ms inference, 0.0ms loss, 1.1ms postprocess per image"
    speed_re = re.compile(
        r"Speed:\s+"
        r"(\d+(?:\.\d+)?)ms preprocess,\s+"
        r"(\d+(?:\.\d+)?)ms inference,\s+"
        r"(\d+(?:\.\d+)?)ms loss,\s+"
        r"(\d+(?:\.\d+)?)ms postprocess per image"
    )
    sm = speed_re.search(clean)
    if sm:
        result["speed_preprocess_ms"] = float(sm.group(1))
        result["speed_inference_ms"] = float(sm.group(2))
        result["speed_postprocess_ms"] = float(sm.group(4))

    return result


# ---------------------------------------------------------------------------
# Artifact path helper
# ---------------------------------------------------------------------------


def expected_artifact_paths(inputs: dict[str, Any]) -> dict[str, str]:
    """
    Compute the absolute artifact paths `yolo val` will write for the given
    inputs (PR curves, confusion matrix, etc.).

    Returns expected paths — the caller must verify existence after the job.
    """
    output_dir = inputs.get("output_dir", "")
    run_name = inputs.get("run_name", "run")
    run_dir = Path(output_dir) / run_name
    return {"eval_dir": str(run_dir)}


# ---------------------------------------------------------------------------
# Binding / registration helpers
# ---------------------------------------------------------------------------


def build_binding(
    skill_id: str = SKILL_ID,
    *,
    verified: bool = True,
    approval_policy: ApprovalPolicy = "approval_required",
    binding_id: str = BINDING_ID,
    runtime_id: str = RUNTIME_ID,
) -> ExecutionBinding:
    """
    Build the ExecutionBinding for YOLO11n person detection evaluation.

    `verified` defaults to True — this binding was personally inspected per
    ADR-0009 §8 (see module docstring).
    """
    return ExecutionBinding(
        skill_id=skill_id,
        binding_id=binding_id,
        runtime_id=runtime_id,
        approval_policy=approval_policy,
        verified=verified,
        description=(
            "YOLO11n person detection evaluation on a labelled dataset, "
            "run as a subprocess via the `yolo val` CLI on a Linux/NVIDIA host. "
            "Command is built by build_command() from request.inputs. "
            "Required inputs: data (dataset YAML path), output_dir (str), run_name (str). "
            "Metrics are parsed from stdout by parse_metrics(). "
            "Dataset: COCO val2017 (5000 images, held-out from yolo11n training). "
            "See ADR-0013, D-060, D-061."
        ),
        input_schema=(
            InputField(
                name="command",
                required=True,
                description=(
                    "Non-empty list[str] passed directly to subprocess.Popen. "
                    "Build with build_command(inputs) from this module."
                ),
            ),
            InputField(
                name="data",
                required=True,
                description="Absolute path to the dataset YAML file (coco.yaml format).",
            ),
            InputField(
                name="output_dir",
                required=True,
                description="Absolute path for output root (yolo val project=).",
            ),
            InputField(
                name="run_name",
                required=True,
                description="Output subdirectory name for this evaluation run (yolo val name=).",
            ),
            InputField(
                name="model",
                required=False,
                default=DEFAULT_MODEL,
                description="Model name or absolute path. Default: 'yolo11n.pt'.",
            ),
            InputField(
                name="conf",
                required=False,
                default=DEFAULT_CONF,
                description="Detection confidence threshold (default: 0.25).",
            ),
            InputField(
                name="imgsz",
                required=False,
                default=DEFAULT_IMGSZ,
                description="Inference image size (default: 640).",
            ),
            InputField(
                name="classes",
                required=False,
                default=DEFAULT_CLASSES,
                description="Class IDs to evaluate (default: [0] = COCO person class).",
            ),
            InputField(
                name="device",
                required=False,
                default="0",
                description="Compute device: '0' for GPU 0, 'cpu' for CPU.",
            ),
            InputField(
                name="batch",
                required=False,
                default=DEFAULT_BATCH,
                description="Validation batch size (default: 1).",
            ),
            InputField(
                name="yolo_executable",
                required=False,
                default=DEFAULT_YOLO_EXECUTABLE,
                description=(
                    "yolo CLI executable name or absolute path. "
                    "Confirmed at /home/dev/.local/bin/yolo on the reference host."
                ),
            ),
        ),
    )


def register_binding(
    registry: ExecutionBindingRegistry,
    *,
    skill_id: str = SKILL_ID,
    verified: bool = True,
    approval_policy: ApprovalPolicy = "approval_required",
) -> None:
    """
    Explicit, opt-in registration — never called automatically.

    Registers the YOLO11n person detection evaluation binding in the registry.
    The caller must also pass a LinuxNvidiaJobRuntime instance in job_runtimes
    when constructing JobExecutor (same runtime as yolo_inference).
    """
    registry.register_binding(
        build_binding(skill_id, verified=verified, approval_policy=approval_policy)
    )
