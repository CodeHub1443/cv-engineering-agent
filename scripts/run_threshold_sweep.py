"""
scripts/run_threshold_sweep.py — Confidence-threshold sweep (D-065, issue #72).

Tests whether varying `conf` (the post-NMS filter) on a fixed yolo11n.pt /
COCO val2017 / same eval procedure as EXP-20260930-01 reveals whether the
17.5% near-threshold predictions (0.25–0.35) are recoverable TPs (recall ↑
at lower conf) or noise (precision ↑ at higher conf).

Only varies: conf ∈ {0.10, 0.15, 0.25, 0.50}.
Holds constant: model, dataset, device, imgsz=640, batch=1, classes=[0].
Baseline: EXP-20260930-01 (conf=0.25, P=0.791, R=0.661, mAP@.5:.95=0.459).

Modes
-----
prepare (default):
    Validates prerequisites. Generates exact yolo val commands. Writes
    4 proposed ExperimentRecords to the SQLite ledger. Prints the commands
    and exits 0 — NO GPU activity.

execute (--execute):
    Requires owner approval (--execute flag = explicit approval of GPU run).
    Runs 4 `yolo val` jobs sequentially via JobExecutor (approval gate).
    Writes completed/failed ExperimentRecords.

Usage
-----
    python3 scripts/run_threshold_sweep.py           # prepare
    python3 scripts/run_threshold_sweep.py --execute # execute (owner approval)

Governance
----------
    - NEVER overwrites EXP-20260930-01.
    - Does NOT change model weights, training, dataset, imgsz, or tracker.
    - Does NOT bypass JobExecutor or its pre-flight checks.
    - Approval gate: --execute flag = owner has approved the GPU run.
    - Issue: #72  |  ADR-0009, ADR-0011, ADR-0013
"""
# ruff: noqa: E402 — sys.path must be patched before cv_agent imports

from __future__ import annotations

import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cv_agent.execution.binding import ExecutionBindingRegistry
    from cv_agent.execution.jobs.executor import JobExecutor
    from cv_agent.experiments.models import ExperimentRecord
    from cv_agent.skills.models import Skill

REPO_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

# ── Dataset / model configuration ─────────────────────────────────────────

DATASETS_DIR = Path("/home/dev/Documents/data_cleaner/datasets")
COCO_ROOT = DATASETS_DIR / "coco"
VAL_IMAGES_DIR = COCO_ROOT / "images" / "val2017"
VAL_LABELS_DIR = COCO_ROOT / "labels" / "val2017"

MODEL_PATH = REPO_ROOT / ".cv_agent" / "models" / "yolo11n.pt"
OUTPUT_ROOT = REPO_ROOT / ".cv_agent" / "evaluations"
YAML_PATH = OUTPUT_ROOT / "coco-person-val.yaml"
DB_PATH = REPO_ROOT / ".cv_agent" / "experiments.sqlite"
YOLO_EXECUTABLE = "/home/dev/.local/bin/yolo"

BASELINE_EXP_ID = "EXP-20260930-01"  # never modify this record
SWEEP_CONFS = [0.10, 0.15, 0.25, 0.50]

COCO_NAMES = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 4: "airplane",
    5: "bus", 6: "train", 7: "truck", 8: "boat", 9: "traffic light",
    10: "fire hydrant", 11: "stop sign", 12: "parking meter", 13: "bench",
    14: "bird", 15: "cat", 16: "dog", 17: "horse", 18: "sheep", 19: "cow",
    20: "elephant", 21: "bear", 22: "zebra", 23: "giraffe", 24: "backpack",
    25: "umbrella", 26: "handbag", 27: "tie", 28: "suitcase", 29: "frisbee",
    30: "skis", 31: "snowboard", 32: "sports ball", 33: "kite", 34: "baseball bat",
    35: "baseball glove", 36: "skateboard", 37: "surfboard", 38: "tennis racket",
    39: "bottle", 40: "wine glass", 41: "cup", 42: "fork", 43: "knife",
    44: "spoon", 45: "bowl", 46: "banana", 47: "apple", 48: "sandwich",
    49: "orange", 50: "broccoli", 51: "carrot", 52: "hot dog", 53: "pizza",
    54: "donut", 55: "cake", 56: "chair", 57: "couch", 58: "potted plant",
    59: "bed", 60: "dining table", 61: "toilet", 62: "tv", 63: "laptop",
    64: "mouse", 65: "remote", 66: "keyboard", 67: "cell phone", 68: "microwave",
    69: "oven", 70: "toaster", 71: "sink", 72: "refrigerator", 73: "book",
    74: "clock", 75: "vase", 76: "scissors", 77: "teddy bear", 78: "hair drier",
    79: "toothbrush",
}


# ── Sweep configuration ────────────────────────────────────────────────────

@dataclass(frozen=True)
class SweepConfig:
    """One point in the confidence threshold sweep."""

    exp_id: str
    conf: float
    run_name: str


def _build_sweep_configs() -> list[SweepConfig]:
    """
    Return the 4 sweep configurations, ordered by conf ascending.

    exp_ids: EXP-20261001-01..04  (conf=0.10 / 0.15 / 0.25 / 0.50).
    EXP-20261001-03 (conf=0.25) is the control — same threshold as
    EXP-20260930-01.  Distinct run_name per conf so yolo val output
    directories never collide.
    """
    configs: list[SweepConfig] = []
    for i, conf in enumerate(SWEEP_CONFS, start=1):
        conf_tag = f"{conf:.2f}".replace(".", "")
        configs.append(SweepConfig(
            exp_id=f"EXP-20261001-{i:02d}",
            conf=conf,
            run_name=f"conf-sweep-yolo11n-coco-conf{conf_tag}",
        ))
    return configs


def _hypothesis(conf: float) -> str:
    is_control = abs(conf - 0.25) < 1e-9
    tag = " (control — same threshold as EXP-20260930-01)" if is_control else ""
    return (
        f"At conf={conf:.2f}{tag}, yolo11n on COCO val2017 (classes=[0], imgsz=640) "
        "reveals how the 17.5% near-threshold band (0.25–0.35; ADR-0015 finding 2) "
        "affects precision/recall. "
        "If lowering conf recovers TPs: recall↑, mAP≈stable. "
        "If noise: FP↑, precision↓, mAP↓. "
        f"Baseline: {BASELINE_EXP_ID} (conf=0.25, P=0.791, R=0.661, mAP@.5:.95=0.459)."
    )


def _success_criteria(exp_id: str) -> str:
    return (
        "yolo val exits 0; precision, recall, mAP@0.5, mAP@0.5:0.95 parsed and "
        f"non-zero; metrics written to ledger as {exp_id}."
    )


# ── YAML generation ────────────────────────────────────────────────────────

def _generate_coco_val_yaml(yaml_path: Path) -> None:
    """Write a minimal COCO val-only yaml with absolute paths."""
    names_lines = "\n".join(f"  {k}: {v}" for k, v in COCO_NAMES.items())
    yaml_content = (
        "# COCO val2017 evaluation yaml — generated by run_threshold_sweep.py (D-065)\n"
        "# Dataset: Microsoft COCO 2017 val split (5000 images, CC BY 4.0)\n"
        "# train key required by ultralytics check_det_dataset (eval-only run).\n"
        f"path: {COCO_ROOT}\n"
        "train: val2017.txt\n"
        "val: val2017.txt\n"
        f"names:\n{names_lines}\n"
    )
    yaml_path.write_text(yaml_content)


# ── VRAM monitor ───────────────────────────────────────────────────────────

def _poll_vram(accum: list[int], stop: threading.Event, interval: float = 2.0) -> None:
    """Daemon thread: poll nvidia-smi for used VRAM every `interval` seconds."""
    while not stop.is_set():
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                timeout=5.0,
            ).decode().strip()
            for line in out.splitlines():
                try:
                    accum.append(int(line.strip()))
                except ValueError:
                    pass
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        stop.wait(timeout=interval)


# ── Preflight ──────────────────────────────────────────────────────────────

def _preflight() -> None:
    """Validate all prerequisites. sys.exit on failure."""
    if not MODEL_PATH.exists():
        sys.exit(f"BLOCKED: model not found at {MODEL_PATH}")

    val_images = list(VAL_IMAGES_DIR.glob("*.jpg")) if VAL_IMAGES_DIR.exists() else []
    if len(val_images) < 4900:
        sys.exit(
            f"BLOCKED: COCO val2017 images not ready. "
            f"Expected ~5000 .jpg files in {VAL_IMAGES_DIR}, found {len(val_images)}."
        )

    val_labels = list(VAL_LABELS_DIR.glob("*.txt")) if VAL_LABELS_DIR.exists() else []
    if len(val_labels) < 4900:
        sys.exit(
            f"BLOCKED: COCO val2017 labels not ready. "
            f"Found {len(val_labels)} .txt files in {VAL_LABELS_DIR}."
        )

    print(f"  model           : {MODEL_PATH}  exists=True")
    print(f"  val images      : {len(val_images)} in {VAL_IMAGES_DIR}")
    print(f"  val labels      : {len(val_labels)} in {VAL_LABELS_DIR}")


# ── Command builder ────────────────────────────────────────────────────────

def _build_command(cfg: SweepConfig) -> list[str]:
    """Build the exact yolo val command for one sweep config."""
    from cv_agent.execution.jobs.runtimes.yolo_eval import build_command  # noqa: PLC0415

    return build_command({
        "data": str(YAML_PATH.absolute()),
        "output_dir": str(OUTPUT_ROOT.absolute()),
        "run_name": cfg.run_name,
        "model": str(MODEL_PATH.absolute()),
        "conf": cfg.conf,
        "imgsz": 640,
        "classes": [0],
        "device": "0",
        "batch": 1,
        "yolo_executable": YOLO_EXECUTABLE,
    })


# ── Proposed record builder ────────────────────────────────────────────────

def _make_proposed_record(
    cfg: SweepConfig, created_at: str, commit: str | None
) -> "ExperimentRecord":
    """Build a proposed ExperimentRecord for one sweep point."""
    from cv_agent.experiments.models import ExperimentRecord  # noqa: PLC0415

    return ExperimentRecord(
        exp_id=cfg.exp_id,
        status="proposed",
        hypothesis=_hypothesis(cfg.conf),
        success_criteria=_success_criteria(cfg.exp_id),
        baseline_id=BASELINE_EXP_ID,
        parent_exp_id=BASELINE_EXP_ID,
        created_at=created_at,
        commit=commit,
        model="yolo11n (yolo11n.pt, 2.6M params, 6.5 GFLOPs)",
        dataset_version="coco-val2017-5k",
        input_resolution="640×640",
        batch_size=1,
        precision="FP16 (torch+cu121)",
        notes=(
            f"conf={cfg.conf:.2f}, imgsz=640, classes=[0], device=0, batch=1. "
            f"run_name={cfg.run_name!r}. "
            "Prepared by scripts/run_threshold_sweep.py (D-065, issue #72). "
            f"Baseline: {BASELINE_EXP_ID}."
        ),
    )


# ── Get current git commit ─────────────────────────────────────────────────

def _current_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


# ── Prepare mode ───────────────────────────────────────────────────────────

def _prepare_mode() -> None:
    """Write proposed records, print exact commands, exit 0. No GPU activity."""
    print("=" * 60)
    print("CONFIDENCE THRESHOLD SWEEP — PREPARE MODE")
    print("=" * 60)
    print(f"  baseline        : {BASELINE_EXP_ID}")
    print("  baseline metrics: P=0.791  R=0.661  mAP@.5:.95=0.459  (conf=0.25)")
    print(f"  sweep confs     : {SWEEP_CONFS}")

    print("\n=== 0. Preflight ===")
    _preflight()

    print("\n=== 1. Dataset yaml ===")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    if not YAML_PATH.exists():
        _generate_coco_val_yaml(YAML_PATH)
        print(f"  generated       : {YAML_PATH}")
    else:
        print(f"  reusing         : {YAML_PATH}")

    configs = _build_sweep_configs()
    created_at = datetime.now(timezone.utc).isoformat()
    commit = _current_commit()

    print("\n=== 2. Architecture setup ===")
    from cv_agent.execution.binding import ExecutionBindingRegistry
    from cv_agent.execution.host import LinuxNvidiaHostVerifier
    from cv_agent.execution.jobs.executor import JobExecutor
    from cv_agent.execution.jobs.runtimes.linux_nvidia import LinuxNvidiaJobRuntime
    from cv_agent.execution.jobs.runtimes.yolo_eval import SKILL_ID, register_binding

    registry = ExecutionBindingRegistry()
    register_binding(registry, skill_id=SKILL_ID, verified=True, approval_policy="approval_required")
    executor = JobExecutor(
        registry=registry,
        job_runtimes={LinuxNvidiaJobRuntime.RUNTIME_ID: LinuxNvidiaJobRuntime()},
        host_verifier=LinuxNvidiaHostVerifier(),
    )
    print(f"  binding         : {SKILL_ID}  can_start={executor.can_start(SKILL_ID)}")

    print("\n=== 3. Exact yolo val commands (GPU — require approval) ===\n")
    for cfg in configs:
        cmd = _build_command(cfg)
        print(f"  # {cfg.exp_id}  conf={cfg.conf:.2f}  run_name={cfg.run_name!r}")
        print("  " + " \\\n    ".join(cmd))
        print()

    print("=== 4. Write proposed ExperimentRecords ===")
    from cv_agent.experiments.store import open_ledger

    with open_ledger(db_path=DB_PATH) as ledger:
        for cfg in configs:
            existing = ledger.get_experiment(cfg.exp_id)
            if existing is not None and existing.is_terminal():
                print(f"  SKIP {cfg.exp_id} — already terminal ({existing.status})")
                continue
            record = _make_proposed_record(cfg, created_at=created_at, commit=commit)
            ledger.record_experiment(record)
            print(
                f"  wrote {cfg.exp_id}  status=proposed  conf={cfg.conf:.2f}"
                f"  run_name={cfg.run_name!r}"
            )

        # Confirm baseline record is untouched
        baseline = ledger.get_experiment(BASELINE_EXP_ID)
        if baseline is not None:
            assert baseline.status == "completed", (
                f"INTEGRITY ERROR: {BASELINE_EXP_ID} status changed to {baseline.status!r}"
            )
        print(f"\n  {BASELINE_EXP_ID} integrity check: {'OK — status=completed' if baseline else 'not in ledger (run run_evaluation.py first)'}")

    print()
    print("=" * 60)
    print("APPROVAL REQUIRED — GPU experiments NOT started")
    print("=" * 60)
    print()
    print("  The 4 proposed records above are status='proposed'.")
    print("  To execute the sweep after owner approval:")
    print()
    print("    python3 scripts/run_threshold_sweep.py --execute")
    print()
    print("  Estimated time  : ~4 × 50s ≈ 3–4 min total")
    print("  VRAM required   : ~596 MiB peak (EXP-20260930-01 measured 596 MiB)")
    print(f"  Expected outputs: EXP-20261001-01..04 in {DB_PATH}")
    print()
    print("  Governance: docs/APPROVALS.md — GPU eval run, approval_required.")
    print("  Issue: #72")


# ── Execute mode ───────────────────────────────────────────────────────────

def _run_one(
    cfg: SweepConfig,
    created_at: str,
    commit: str | None,
    executor: "JobExecutor",
    registry: "ExecutionBindingRegistry",
    skill: "Skill",
) -> None:
    """Run a single sweep point and write its ExperimentRecord."""
    from cv_agent.execution.models import ExecutionEvidence, SkillExecutionRequest
    from cv_agent.execution.jobs.models import JobResult
    from cv_agent.execution.host import HostRequirement
    from cv_agent.execution.jobs.runtimes.yolo_eval import SKILL_ID, parse_metrics
    from cv_agent.graph.experiment_wiring import ExperimentContext, job_result_to_experiment_record
    from cv_agent.experiments.models import LatencyMeasurement, MemoryFootprint
    from cv_agent.experiments.store import open_ledger
    from dataclasses import replace

    print(f"\n{'='*50}")
    print(f"{cfg.exp_id}  conf={cfg.conf:.2f}  run_name={cfg.run_name!r}")
    print(f"{'='*50}")

    cmd = _build_command(cfg)
    inputs: dict = {
        "command": cmd,
        "data": str(YAML_PATH.absolute()),
        "output_dir": str(OUTPUT_ROOT.absolute()),
        "run_name": cfg.run_name,
        "model": str(MODEL_PATH.absolute()),
        "conf": cfg.conf,
        "imgsz": 640,
        "classes": [0],
        "device": "0",
        "batch": 1,
        "yolo_executable": YOLO_EXECUTABLE,
    }

    pin = registry.pin(SKILL_ID)
    assert pin is not None

    request = SkillExecutionRequest(
        inputs=inputs,
        task=(
            f"Confidence threshold sweep point {cfg.exp_id}: "
            f"yolo11n COCO val2017 conf={cfg.conf:.2f} (D-065, issue #72)"
        ),
        requested_by="agent",
        approved=True,  # owner approved via --execute flag
        expected_binding_pin=pin,
    )
    host_req = HostRequirement(os="linux", gpu_vendor="nvidia", min_vram_mb=2048)

    # VRAM monitor
    vram_samples: list[int] = []
    vram_stop = threading.Event()
    vram_thread = threading.Thread(
        target=_poll_vram, args=(vram_samples, vram_stop), daemon=True,
        name=f"vram-monitor-{cfg.exp_id}",
    )
    vram_thread.start()
    time.sleep(2.0)
    vram_baseline_mb = vram_samples[-1] if vram_samples else None

    print(f"  command         : {' '.join(cmd[:4])} conf={cfg.conf:.2f} ...")
    print(f"  VRAM baseline   : {vram_baseline_mb} MiB")

    t_start = time.monotonic()
    handle, start_result = executor.start_job(skill, request, host_req)

    print(f"  start status    : {start_result.status}")
    if start_result.error:
        print(f"  error           : [{start_result.error.category}] {start_result.error.message}")

    if start_result.status != "started":
        vram_stop.set()
        print(f"  FAILED: job did not start — {cfg.exp_id} skipped")
        return

    print(f"  job_id          : {handle.job_id}")
    print("  polling ...")

    poll_n = 0
    while True:
        status = executor.poll_job(handle)
        poll_n += 1
        if poll_n % 15 == 0:
            elapsed = time.monotonic() - t_start
            print(f"    ...{elapsed:.0f}s  status={status}")
        if status in ("completed", "failed", "cancelled"):
            break
        time.sleep(2)

    wall_time_s = time.monotonic() - t_start
    vram_stop.set()
    vram_thread.join(timeout=5.0)
    peak_vram_mb = max(vram_samples) if vram_samples else None

    print(f"  final status    : {status}  wall_time={wall_time_s:.1f}s")
    print(f"  VRAM peak       : {peak_vram_mb} MiB")

    outcome = executor.collect_job(handle)
    print(f"  exit_code       : {outcome.exit_code}")

    metrics: dict = {}
    if outcome.stdout:
        metrics = parse_metrics(outcome.stdout)

    fps_e2e: float | None = None
    if wall_time_s > 0:
        fps_e2e = 5000.0 / wall_time_s

    completed_at = datetime.now(timezone.utc).isoformat()
    terminal_result = JobResult(
        skill_id=SKILL_ID,
        job_id=handle.job_id,
        status="completed" if outcome.success else "failed",
        evidence=ExecutionEvidence(
            binding_id=start_result.evidence.binding_id,
            runtime_id=start_result.evidence.runtime_id,
            started_at=start_result.evidence.started_at,
            completed_at=completed_at,
        ),
        outcome=outcome,
    )

    context = ExperimentContext(
        exp_id=cfg.exp_id,
        baseline_id=BASELINE_EXP_ID,
        dataset_version="coco-val2017-5k",
        hypothesis=_hypothesis(cfg.conf),
        success_criteria=_success_criteria(cfg.exp_id),
        model="yolo11n (yolo11n.pt, 2.6M params, 6.5 GFLOPs)",
        approval_ref="Tanvir instruction — --execute flag (D-065, issue #72)",
        hardware_training="N/A (inference only)",
        hardware_target=(
            "NVIDIA GeForce RTX 3060 12GB, driver 535.309.01 / CUDA 12.1 "
            "(yolo subprocess: Python-3.10, torch-2.5.1+cu121)"
        ),
        notes=(
            f"conf={cfg.conf:.2f}, imgsz=640, classes=[0], device=0, batch=1. "
            f"run_name={cfg.run_name!r}. wall_time={wall_time_s:.1f}s. "
            f"FPS e2e={f'{fps_e2e:.1f}' if fps_e2e is not None else 'N/A'}. "
            f"VRAM peak={peak_vram_mb} MiB, baseline={vram_baseline_mb} MiB. "
            f"parent_exp_id={BASELINE_EXP_ID}. "
            "Sweep: D-065, issue #72."
        ),
    )

    record = job_result_to_experiment_record(terminal_result, context=context)

    if metrics:
        _mk = ("precision", "recall", "map50", "map50_95")
        _val = {k: float(metrics[k]) for k in _mk if k in metrics}
        record = replace(
            record,
            val_metrics=_val if _val else None,
            fps=fps_e2e,
            latency=LatencyMeasurement(
                end_to_end=(
                    metrics.get("speed_preprocess_ms", 0.0)
                    + metrics.get("speed_inference_ms", 0.0)
                    + metrics.get("speed_postprocess_ms", 0.0)
                ),
                inference_only=metrics.get("speed_inference_ms", 0.0),
            ),
            memory=MemoryFootprint(
                vram=float(peak_vram_mb) if peak_vram_mb else 0.0,
                ram=0.0,
            ),
        )

    with open_ledger(db_path=DB_PATH) as ledger:
        ledger.record_experiment(record)
        print(f"  ledger          : {cfg.exp_id}  status={record.status}  val_metrics={record.val_metrics}")

    if metrics:
        print(f"  precision={metrics.get('precision', '?')}  "
              f"recall={metrics.get('recall', '?')}  "
              f"mAP@.5:{metrics.get('map50', '?')}  "
              f"mAP@.5:.95={metrics.get('map50_95', '?')}")


def _execute_mode() -> None:
    """Execute the sweep — runs 4 GPU jobs sequentially via JobExecutor."""
    print("=" * 60)
    print("CONFIDENCE THRESHOLD SWEEP — EXECUTE MODE")
    print("=" * 60)
    print(f"  baseline        : {BASELINE_EXP_ID}")
    print(f"  sweep confs     : {SWEEP_CONFS}")
    print()
    print("  Owner approved via --execute flag (D-065, issue #72).")

    print("\n=== 0. Preflight ===")
    _preflight()

    print("\n=== 1. Dataset yaml ===")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    if not YAML_PATH.exists():
        _generate_coco_val_yaml(YAML_PATH)
        print(f"  generated       : {YAML_PATH}")
    else:
        print(f"  reusing         : {YAML_PATH}")

    from cv_agent.execution.binding import ExecutionBindingRegistry
    from cv_agent.execution.host import LinuxNvidiaHostVerifier
    from cv_agent.execution.jobs.executor import JobExecutor
    from cv_agent.execution.jobs.runtimes.linux_nvidia import LinuxNvidiaJobRuntime
    from cv_agent.execution.jobs.runtimes.yolo_eval import SKILL_ID, register_binding
    from cv_agent.skills.models import Skill

    registry = ExecutionBindingRegistry()
    register_binding(registry, skill_id=SKILL_ID, verified=True, approval_policy="approval_required")
    executor = JobExecutor(
        registry=registry,
        job_runtimes={LinuxNvidiaJobRuntime.RUNTIME_ID: LinuxNvidiaJobRuntime()},
        host_verifier=LinuxNvidiaHostVerifier(),
    )

    skill = Skill(
        skill_id=SKILL_ID,
        name="yolo-eval",
        description="YOLO11n person detection evaluation — confidence threshold sweep",
        source="local",
        location="/home/dev/.local/lib/python3.10/site-packages/ultralytics",
        tags=("person-detection", "evaluation", "yolo", "coco", "threshold-sweep"),
        executable=True,
    )

    configs = _build_sweep_configs()
    created_at = datetime.now(timezone.utc).isoformat()
    commit = _current_commit()

    for cfg in configs:
        _run_one(cfg, created_at, commit, executor, registry, skill)

    print("\n" + "=" * 60)
    print("SWEEP COMPLETE")
    print("=" * 60)
    print(f"  Records: EXP-20261001-01..04 in {DB_PATH}")
    print(f"  Baseline {BASELINE_EXP_ID} was not modified.")
    print()
    print("  Next: update docs/state/EXPERIMENTS.md with completed rows.")


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute the GPU sweep (owner approval required). Default: prepare only.",
    )
    args = parser.parse_args()

    if args.execute:
        _execute_mode()
    else:
        _prepare_mode()
