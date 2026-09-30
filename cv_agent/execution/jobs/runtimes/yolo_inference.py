"""
cv_agent.execution.jobs.runtimes.yolo_inference — YOLO11n person detection +
tracking binding for LinuxNvidiaJobRuntime (ADR-0009 §8, ADR-0013).

Binding for the `yolo-inference` skill using the `yolo track` CLI to run
YOLO11n person detection + ByteTrack multi-object tracking on a video source
as a long-running subprocess (D-043 reference task).

ADR-0009 §8 discipline — why verified=True:

CLI location: `/home/dev/.local/bin/yolo` (PATH alias: `yolo`).
  Confirmed present and executable; version 8.4.138 via `yolo version`.

Model: `yolo11n.pt` — Ultralytics YOLO11 nano detection checkpoint.
  Downloaded from https://github.com/ultralytics/assets/releases/download/
  v8.4.0/yolo11n.pt and cached at `.cv_agent/models/yolo11n.pt` (gitignored).
  Model summary confirmed: 100 layers, 2,616,248 parameters, 6.5 GFLOPs.
  This is the recommended candidate from the D-053 SelectionRecommendation
  (confidence: medium, baseline_id: SELF).

CLI contract (verified empirically via `yolo help` and `yolo cfg`):
  Mode: `track` — combines detection and ByteTrack/BoT-SORT/TrackTrack tracking.
  Syntax: `yolo track <key=value ...>` (no leading dashes; KEY=VALUE pairs).
  Required args: `model=<path_or_name>`, `source=<video_path>`.
  Optional relevant args (all confirmed via `yolo cfg`):
    classes=[0]           — filter to COCO class 0 (person) only
    tracker=bytetrack.yaml — ByteTrack algorithm (evidence: arXiv 2110.06864,
                             D-053 KnowledgeItem "bytetrack-paper")
    conf=0.25             — detection confidence threshold (default)
    imgsz=640             — inference resolution (default, from model checkpoint)
    save=True             — save annotated video to project/name/
    save_txt=True         — save per-frame detection/tracking labels (TXT format)
    project=<dir>         — output root directory
    name=<run_name>       — output subdirectory under project

Exit codes: 0 = success; non-zero = failure (standard subprocess semantics,
  confirmed by observing the CLI crash on invalid source returning exit 1).

Output artifacts (from `<project>/<name>/`):
  `annotated_video_dir`   — `<project>/<name>/` (may contain *.avi or *.mp4)
  `tracking_labels_dir`   — `<project>/<name>/labels/` (one TXT per frame)
  Label format: `<class_id> <x_center> <y_center> <width> <height> <track_id>`
    (YOLO tracking output format — confirmed in SKILL.md examples)

Known limitations (V1 — not defects):
  - GPU profiling (VRAM, gpu_hours) is not available from subprocess alone.
  - The `yolo` CLI is Python 3.10; the Agent uses a different interpreter.
    Both share the same site-packages on this host; torch 2.5.1+cu121 with
    CUDA available is confirmed in the yolo subprocess environment (D-058).

What this binding does NOT claim:
  - It does not make any other skill executable — verified=True is for exactly
    this one binding (ADR-0009 §8: "for one skill, not all of them at once").
  - It does not implement any approval workflow — approval is checked by
    JobExecutor.start_job() per ADR-0013 §3.2.
  - It does not pin a specific model weight file — the model path comes from
    request.inputs and is the caller's responsibility to supply correctly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cv_agent.execution.binding import ExecutionBinding, ExecutionBindingRegistry, InputField
from cv_agent.execution.jobs.runtimes.linux_nvidia import (
    RUNTIME_ID as _LINUX_NVIDIA_RUNTIME_ID,
)
from cv_agent.execution.models import ApprovalPolicy

SKILL_ID = "yolo-inference"
BINDING_ID = "yolo11n-person-track-linux-job-v1"
RUNTIME_ID = _LINUX_NVIDIA_RUNTIME_ID  # LinuxNvidiaJobRuntime handles subprocess

DEFAULT_MODEL = "yolo11n.pt"
DEFAULT_TRACKER = "bytetrack.yaml"
DEFAULT_CONF = 0.25
DEFAULT_IMGSZ = 640
DEFAULT_CLASSES = [0]  # COCO class 0 = person
DEFAULT_YOLO_EXECUTABLE = "yolo"


# ---------------------------------------------------------------------------
# Command builder
# ---------------------------------------------------------------------------

def build_command(inputs: dict[str, Any]) -> list[str]:
    """
    Build the `yolo track` command list from request inputs.

    Required inputs:
        source: str     — absolute path to input video file
        output_dir: str — absolute path for output root (project= argument)
        run_name: str   — output subdirectory name (name= argument)

    Optional inputs:
        model: str        — model name or path (default: "yolo11n.pt")
        tracker: str      — tracker config file (default: "bytetrack.yaml")
        conf: float       — confidence threshold (default: 0.25)
        imgsz: int        — inference image size (default: 640)
        classes: list[int]— class IDs to detect (default: [0] = person)
        device: str       — compute device, e.g. "0" for GPU 0, "cpu" (default: "0")
        yolo_executable: str — yolo CLI executable (default: "yolo")

    Returns a list[str] suitable for subprocess.Popen(command, ...).
    Each element is one argument; no shell interpretation.
    """
    source = inputs.get("source")
    output_dir = inputs.get("output_dir")
    run_name = inputs.get("run_name")
    if not source:
        raise ValueError(
            "yolo_inference binding: inputs['source'] is required "
            "(absolute path to input video file)."
        )
    if not output_dir:
        raise ValueError(
            "yolo_inference binding: inputs['output_dir'] is required "
            "(absolute path for output root directory)."
        )
    if not run_name:
        raise ValueError(
            "yolo_inference binding: inputs['run_name'] is required "
            "(output subdirectory name for this run)."
        )

    model = inputs.get("model", DEFAULT_MODEL)
    tracker = inputs.get("tracker", DEFAULT_TRACKER)
    conf = inputs.get("conf", DEFAULT_CONF)
    imgsz = inputs.get("imgsz", DEFAULT_IMGSZ)
    classes: list[int] = inputs.get("classes", DEFAULT_CLASSES)
    device = inputs.get("device", "0")
    exe = inputs.get("yolo_executable", DEFAULT_YOLO_EXECUTABLE)

    classes_str = "[" + ",".join(str(c) for c in classes) + "]"

    return [
        exe,
        "track",
        f"model={model}",
        f"source={source}",
        f"classes={classes_str}",
        f"tracker={tracker}",
        f"conf={conf}",
        f"imgsz={imgsz}",
        "save=True",
        "save_txt=True",
        f"project={output_dir}",
        f"name={run_name}",
        f"device={device}",
    ]


# ---------------------------------------------------------------------------
# Artifact path helper
# ---------------------------------------------------------------------------

def expected_artifact_paths(inputs: dict[str, Any]) -> dict[str, str]:
    """
    Compute the absolute artifact paths that `yolo track` will produce for the
    given inputs, based on the CLI's known output convention.

    The yolo CLI writes output to `<project>/<name>/`:
      annotated_video_dir  — <output_dir>/<run_name>/
      tracking_labels_dir  — <output_dir>/<run_name>/labels/

    The caller MUST verify these paths exist after the job completes — this
    function computes EXPECTED paths, not confirmed ones. Pass the returned
    dict as the basis for an artifact check or store the paths in the
    ExperimentRecord notes field via job_result_to_experiment_record().
    """
    output_dir = inputs.get("output_dir", "")
    run_name = inputs.get("run_name", "run")
    run_dir = Path(output_dir) / run_name
    return {
        "annotated_video_dir": str(run_dir),
        "tracking_labels_dir": str(run_dir / "labels"),
    }


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
    Build the ExecutionBinding for YOLO11n person detection + tracking.

    `verified` defaults to True — this binding has been personally inspected
    per ADR-0009 §8 (see module docstring). Pass False to construct an
    unverified draft; JobExecutor will refuse to start an unverified binding.

    `approval_policy` defaults to "approval_required" because running a GPU
    CV workload is an approval-gated action per docs/APPROVALS.md.
    """
    return ExecutionBinding(
        skill_id=skill_id,
        binding_id=binding_id,
        runtime_id=runtime_id,
        approval_policy=approval_policy,
        verified=verified,
        description=(
            "YOLO11n person detection + ByteTrack tracking on a video source, "
            "run as a subprocess via the `yolo track` CLI on a Linux/NVIDIA host. "
            "Command is built by build_command() from request.inputs. "
            "Required inputs: source (video path), output_dir (str), run_name (str). "
            "Outputs: annotated video + per-frame tracking labels in output_dir/run_name/. "
            "GPU inference confirmed on RTX 3060 (torch 2.5.1+cu121, CUDA 12.1). "
            "See ADR-0013, D-053, D-055, D-058."
        ),
        input_schema=(
            InputField(
                name="command",
                required=True,
                description=(
                    "Non-empty list[str] passed directly to subprocess.Popen. "
                    "Build with build_command(inputs) from this module. "
                    "First element is the yolo executable path or name."
                ),
            ),
            InputField(
                name="source",
                required=True,
                description="Absolute path to input video file for yolo track source=.",
            ),
            InputField(
                name="output_dir",
                required=True,
                description="Absolute path for output root (yolo track project=).",
            ),
            InputField(
                name="run_name",
                required=True,
                description="Output subdirectory name for this run (yolo track name=).",
            ),
            InputField(
                name="model",
                required=False,
                default=DEFAULT_MODEL,
                description=(
                    "Model name or absolute path. Default: 'yolo11n.pt' "
                    "(the D-053 SelectionRecommendation candidate). "
                    "If not cached locally, ultralytics auto-downloads from GitHub."
                ),
            ),
            InputField(
                name="tracker",
                required=False,
                default=DEFAULT_TRACKER,
                description=(
                    "Tracker config file name. Default: 'bytetrack.yaml' "
                    "(ByteTrack, arXiv 2110.06864, D-053 evidence item 'bytetrack-paper')."
                ),
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
                description="Inference image size (default: 640, from model checkpoint).",
            ),
            InputField(
                name="classes",
                required=False,
                default=DEFAULT_CLASSES,
                description="Class IDs to detect (default: [0] = COCO person class).",
            ),
            InputField(
                name="device",
                required=False,
                default="0",
                description=(
                    "Compute device: '0' for GPU 0, 'cpu' for CPU. "
                    "GPU confirmed: RTX 3060, torch 2.5.1+cu121, CUDA 12.1."
                ),
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
            InputField(
                name="cwd",
                required=False,
                description="Working directory for subprocess (None = inherited).",
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

    Registers the YOLO11n person detection + tracking binding in the registry.
    The caller must also pass a LinuxNvidiaJobRuntime instance in job_runtimes
    when constructing JobExecutor:

        from cv_agent.execution.jobs.runtimes.linux_nvidia import LinuxNvidiaJobRuntime
        from cv_agent.execution.jobs.runtimes.yolo_inference import register_binding
        from cv_agent.execution.host import LinuxNvidiaHostVerifier

        register_binding(agent.execution_bindings, skill_id="yolo-inference")
        executor = JobExecutor(
            registry=agent.execution_bindings,
            job_runtimes={LinuxNvidiaJobRuntime.RUNTIME_ID: LinuxNvidiaJobRuntime()},
            host_verifier=LinuxNvidiaHostVerifier(),
        )
    """
    registry.register_binding(
        build_binding(skill_id, verified=verified, approval_policy=approval_policy)
    )
