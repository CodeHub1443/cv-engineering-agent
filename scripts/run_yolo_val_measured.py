"""One controlled `yolo val` run: the EXP-20261004-01 series or one owner-fixed candidate.

Runs YOLO11n on COCO val2017 persons at conf=0.001 (Q28), batch=1, device 0, quantize=16, with
only --imgsz varying. It writes the artifacts that scripts/record_evaluation_runs.py verifies:

    <project>/<name>/predictions.json   written by ultralytics
    <project>/<name>.val.log            full stdout+stderr of the run
    <project>/<name>.run.json           how the run was executed (exit code, timing, hashes,
                                        approval reference, GPU identity, peak VRAM, peak RAM)

Series mode (no --exp-id): --imgsz is one of 640/960/1280 (measurement-only, D-069). Candidate mode
(--exp-id EXP-YYYYMMDD-NN): one owner-fixed candidate per approved proposal, imgsz a multiple of 32 in
[320, 1280], FP16 only; the run name and `series` derive from the exp id (ADR-0017 amendment 2026-11-15).

Operator-run exception (ADR-0017 §4): this wrapper runs `yolo val` directly, not through
JobExecutor. ADR-0013 and ADR-0009 remain authoritative for agent-initiated execution. The
approval reference is required here and recorded in run.json, so the GPU run cannot start
without one.

Refuses a dirty or uncommitted code tree (ADR-0016) and refuses to overwrite an existing run
directory. A non-zero exit is recorded in run.json and returned; the writer will then refuse it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cv_agent.execution.jobs.runtimes.yolo_eval import (  # noqa: E402
    DEFAULT_YOLO_EXECUTABLE,
    build_command,
)
from cv_agent.experiments.evaluation_records import (  # noqa: E402
    candidate_problems,
    candidate_run_name,
    FP32_CONTROL_SERIES_ID,
    QUANTIZE,
    RUN_SCHEMA,
    EXEMPT_GPU_PROCESS_NAMES,
    foreign_process_seen,
    is_exempt_process,
    precision_label,
)
from cv_agent.experiments.provenance import (  # noqa: E402
    ProvenanceError,
    repository_state_root,
    require_clean_worktree,
)

APPROVED_IMGSZ = (640, 960, 1280)
CONF = 0.001
BATCH = 1
DEVICE = "0"
CLASSES = [0]
MODEL_NAME = "yolo11n.pt"
DATA_YAML_NAME = "coco-person-val.yaml"
VRAM_POLL_SECONDS = 1.0
# Ultralytics' auto-install gate: `AUTOINSTALL = str(os.getenv("YOLO_AUTOINSTALL", True)).lower() == "true"`
# (ultralytics/utils/__init__.py:45, read at utils/checks.py:472), so any value but "true" disables it (Q70).
AUTOINSTALL_ENV = "YOLO_AUTOINSTALL"
ENVIRONMENT_KEYS = ("python_version", "torch_version", "torch_cuda_version", "ultralytics_version", "pip_freeze_sha256")


FP32_CONTROL_IMGSZ = 640
PRECISIONS = {"fp16": QUANTIZE, "fp32": None}


def run_name(imgsz: int, quantize: int | None = QUANTIZE, exp_id: str | None = None) -> str:
    if exp_id is not None:
        return candidate_run_name(exp_id, imgsz)
    suffix = "" if quantize is not None else "-fp32"
    return f"e1-yolo11n-coco-val2017-imgsz{imgsz}-conf0001{suffix}"


def build_argv(
    imgsz: int,
    *,
    state_root: Path,
    executable: str = DEFAULT_YOLO_EXECUTABLE,
    quantize: int | None = QUANTIZE,
    exp_id: str | None = None,
) -> list[str]:
    """The `yolo val` argv: the binding's builder, plus the settings it does not expose.

    ``quantize=16`` requests FP16 through the current ultralytics key. ``quantize=None`` (the FP32
    control, ADR-0018) omits the argument, so ultralytics runs FP32. ``half`` is deprecated in
    8.4.138 and is mapped to ``quantize``, so it is not used. ``exist_ok=True`` makes ultralytics
    write to exactly ``name``; this script refuses an existing directory before the run.
    """
    inputs = {
        "model": str(state_root / "models" / MODEL_NAME),
        "data": str(state_root / "evaluations" / DATA_YAML_NAME),
        "output_dir": str(state_root / "evaluations"),
        "run_name": run_name(imgsz, quantize, exp_id),
        "conf": CONF,
        "imgsz": imgsz,
        "classes": CLASSES,
        "device": DEVICE,
        "batch": BATCH,
        "yolo_executable": executable,
    }
    precision_args = [] if quantize is None else [f"quantize={quantize}"]
    return [*build_command(inputs), *precision_args, "exist_ok=True"]


def ru_maxrss_to_mib(ru_maxrss: int) -> float:
    """getrusage reports ru_maxrss in KiB on Linux. Convert to MiB (1024 KiB per MiB)."""
    return ru_maxrss / 1024.0


def parse_memory_used(text: str) -> int | None:
    """The first line of `nvidia-smi --query-gpu=memory.used ... nounits` as MiB, or None."""
    for line in text.strip().splitlines():
        value = line.strip()
        if value.isdigit():
            return int(value)
        return None
    return None


COMPUTE_APPS_ARGV = ["nvidia-smi", "--query-compute-apps=pid,process_name", "--format=csv,noheader,nounits"]


def parse_compute_apps(text: str) -> list[dict[str, int | str]] | None:
    """Compute processes from `nvidia-smi --query-compute-apps`. [] means none; None means unreadable.

    Any row whose pid is not a number (for example ``[Insufficient Permissions]``) makes the whole
    snapshot unreadable, so it cannot be mistaken for an idle GPU (fail closed, ADR-0018).
    """
    if "no running" in text.lower():
        return []
    processes: list[dict[str, int | str]] = []
    for line in text.strip().splitlines():
        if not line.strip():
            continue
        pid_text, _, name = line.partition(",")
        if not pid_text.strip().isdigit():
            return None
        processes.append({"pid": int(pid_text.strip()), "name": name.strip()})
    return processes


def snapshot_compute_apps(*, at: str) -> dict:
    """One GPU-process snapshot for run.json provenance. ``processes`` is None when unreadable."""
    try:
        out = subprocess.run(COMPUTE_APPS_ARGV, capture_output=True, text=True, check=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return {"at": at, "processes": None}
    return {"at": at, "processes": parse_compute_apps(out)}


class VramSampler:
    """Polls `nvidia-smi` memory.used in a background thread and keeps the peak.

    The baseline is one synchronous sample taken before the run. A failed poll is skipped, not
    invented. If no sample succeeds, the peak is None and the writer refuses the run.
    """

    def __init__(self, interval: float = VRAM_POLL_SECONDS) -> None:
        self.interval = interval
        self.baseline_mib: int | None = None
        self.samples: list[int] = []
        # ADR-0018: one GPU-process snapshot per poll, with the run's own pid excluded when judging it.
        self.own_pid: int | None = None
        self.process_snapshots: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def sample_once() -> int | None:
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        return parse_memory_used(out)

    def start(self, own_pid: int) -> None:
        """Begin polling. The baseline is taken by the caller before the run process starts."""
        self.own_pid = own_pid
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def _poll_once(self) -> None:
        value = self.sample_once()
        if value is not None:
            self.samples.append(value)
        self.process_snapshots.append(snapshot_compute_apps(at=datetime.now(timezone.utc).isoformat()))

    def _poll(self) -> None:
        while not self._stop.is_set():
            self._poll_once()
            self._stop.wait(self.interval)

    def stop(self) -> int | None:
        """Stop polling. Returns the peak MiB seen, or None when no sample succeeded."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        return max(self.samples) if self.samples else None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_val_split(data_yaml: Path) -> Path:
    """The absolute val list path, from the yaml's ``path`` and ``val`` keys (no YAML library needed)."""
    keys: dict[str, str] = {}
    for line in data_yaml.read_text(encoding="utf-8").splitlines():
        if line.startswith(("path:", "val:")):
            key, _, value = line.partition(":")
            keys[key] = value.strip()
    if "path" not in keys or "val" not in keys:
        raise ValueError(f"{data_yaml} must define 'path:' and 'val:'")
    return Path(keys["path"]) / keys["val"]


def gpu_identity() -> dict[str, str | int | None]:
    """Name, memory and driver from nvidia-smi. Any field that cannot be read is None."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        ).stdout.strip().splitlines()[0]
        name, memory, driver = (part.strip() for part in out.split(","))
        return {"gpu_name": name, "gpu_memory_mib": int(memory), "driver_version": driver}
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return {"gpu_name": None, "gpu_memory_mib": None, "driver_version": None}


class FingerprintError(Exception):
    """A field of the environment fingerprint could not be determined (fail closed, Q70)."""


def child_env() -> dict[str, str]:
    """A copy of os.environ for the yolo child with Ultralytics auto-install off. The parent is not changed."""
    return {**os.environ, AUTOINSTALL_ENV: "False"}


def _installed_versions() -> dict[str, str | None]:
    """Python, torch, torch's CUDA and ultralytics versions. A package that cannot be imported gives None."""
    versions: dict[str, str | None] = {"python_version": platform.python_version()}
    try:
        import torch

        versions["torch_version"] = str(torch.__version__)
        versions["torch_cuda_version"] = torch.version.cuda
    except Exception:  # noqa: BLE001 - any import failure means the field is undeterminable
        versions["torch_version"] = versions["torch_cuda_version"] = None
    try:
        from importlib import metadata

        versions["ultralytics_version"] = metadata.version("ultralytics")
    except Exception:  # noqa: BLE001
        versions["ultralytics_version"] = None
    return versions


def _pip_freeze() -> str | None:
    """`python -m pip freeze` from this interpreter, or None when it fails."""
    try:
        done = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True, timeout=120, env=child_env())
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def environment_fingerprint(*, versions=_installed_versions, pip_freeze=_pip_freeze) -> dict[str, str]:
    """The five-key environment fingerprint for run.json. Raises FingerprintError if any field is missing."""
    found: dict[str, str | None] = dict(versions())
    freeze = pip_freeze()
    found["pip_freeze_sha256"] = hashlib.sha256(freeze.encode("utf-8")).hexdigest() if freeze else None
    missing = [k for k in ENVIRONMENT_KEYS if not found.get(k)]
    if missing:
        raise FingerprintError(f"cannot determine {', '.join(missing)}")
    return {k: str(found[k]) for k in ENVIRONMENT_KEYS}


def vram_above_idle(peak_mib: int | None, idle_mib: int | None) -> int | None:
    """Peak minus the idle sample taken before the run; None when either is missing. No comparison rule (D-125)."""
    return None if peak_mib is None or idle_mib is None else peak_mib - idle_mib


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--imgsz",
        type=int,
        required=True,
        help=f"{'/'.join(map(str, APPROVED_IMGSZ))} for the series; any other multiple of 32 in [320, 1280] needs --exp-id",
    )
    parser.add_argument(
        "--exp-id",
        help="the owner-fixed candidate id (EXP-YYYYMMDD-NN) from the approved proposal; required outside the series sizes",
    )
    parser.add_argument(
        "--approval-ref",
        required=True,
        help="owner approval id for this GPU run; recorded in run.json and required by the writer",
    )
    parser.add_argument(
        "--precision",
        choices=tuple(PRECISIONS),
        default="fp16",
        help="fp16 (quantize=16, the EXP-20261004-01 series) or fp32 (quantize unset, the ADR-0018 control)",
    )
    args = parser.parse_args(argv)
    approval_ref = args.approval_ref.strip()
    if not approval_ref:
        print("REFUSED: --approval-ref must not be blank", file=sys.stderr)
        return 2
    quantize = PRECISIONS[args.precision]
    exp_id = args.exp_id.strip() if args.exp_id is not None else None
    if exp_id is not None:
        if quantize is None:
            print("REFUSED: fp32 is only the approved 640 control (ADR-0018), not a candidate", file=sys.stderr)
            return 2
        bad = candidate_problems(exp_id, args.imgsz)
        if bad:
            print(f"REFUSED: {'; '.join(bad)}", file=sys.stderr)
            return 2
    elif args.imgsz not in APPROVED_IMGSZ:
        print(f"REFUSED: imgsz {args.imgsz} needs --exp-id (the series sizes are {list(APPROVED_IMGSZ)})", file=sys.stderr)
        return 2
    if quantize is None and args.imgsz != FP32_CONTROL_IMGSZ:
        print("REFUSED: fp32 is only the approved 640 control (ADR-0018)", file=sys.stderr)
        return 2

    try:
        commit = require_clean_worktree(REPO_ROOT)
    except ProvenanceError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    state = repository_state_root()
    project = state / "evaluations"
    name = run_name(args.imgsz, quantize, exp_id)
    run_dir = project / name
    run_json = project / f"{name}.run.json"
    val_log = project / f"{name}.val.log"
    for existing in (run_dir, run_json, val_log):
        if existing.exists():
            print(f"REFUSED: {existing} already exists; measured runs are never overwritten", file=sys.stderr)
            return 2

    model = state / "models" / MODEL_NAME
    data_yaml = state / "evaluations" / DATA_YAML_NAME
    for path in (model, data_yaml):
        if not path.is_file():
            print(f"REFUSED: required input is missing: {path}", file=sys.stderr)
            return 2
    val_txt = read_val_split(data_yaml)
    if not val_txt.is_file():
        print(f"REFUSED: val list is missing: {val_txt}", file=sys.stderr)
        return 2

    # Inputs are hashed before the run and again by the writer, so a swap in between is caught.
    hashes = {
        "model_sha256": sha256_file(model),
        "data_yaml_sha256": sha256_file(data_yaml),
        "val_txt_sha256": sha256_file(val_txt),
    }
    command = build_argv(args.imgsz, state_root=state, quantize=quantize, exp_id=exp_id)
    print(f"running from commit {commit}")
    print("command:", " ".join(command))

    # ADR-0018 preflight: refuse to start unless the GPU has no compute process and the list is readable.
    start_snapshot = snapshot_compute_apps(at=datetime.now(timezone.utc).isoformat())
    if start_snapshot["processes"] is None:
        print("REFUSED: cannot read the GPU process list (nvidia-smi); no run started", file=sys.stderr)
        return 2
    blocking = [p for p in start_snapshot["processes"] if not is_exempt_process(p)]
    if blocking:
        pids = [p["pid"] for p in blocking]
        print(f"REFUSED: GPU has {len(pids)} compute process(es) before the run, pids {pids}; no run started", file=sys.stderr)
        return 2

    try:
        environment = environment_fingerprint()
    except FingerprintError as exc:
        print(f"REFUSED: {exc}; no run started", file=sys.stderr)
        return 2

    sampler = VramSampler()
    sampler.baseline_mib = sampler.sample_once()  # before the run process exists
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    with val_log.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=child_env())
        sampler.start(proc.pid)
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            log.write(line)
        exit_code = proc.wait()
    wall = time.monotonic() - t0
    ended = datetime.now(timezone.utc)
    vram_peak = sampler.stop()
    end_snapshot = snapshot_compute_apps(at=datetime.now(timezone.utc).isoformat())
    gpu_snapshots = {"start": start_snapshot, "during": sampler.process_snapshots, "end": end_snapshot}
    ram_peak_mib = ru_maxrss_to_mib(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)

    run = {
        "schema": RUN_SCHEMA,
        "series": exp_id or (FP32_CONTROL_SERIES_ID if quantize is None else "EXP-20261004-01"),
        "imgsz": args.imgsz,
        "conf": CONF,
        "batch": BATCH,
        "device": DEVICE,
        "classes": CLASSES,
        "quantize": quantize,
        "precision_requested": precision_label(quantize),
        "approval_ref": approval_ref,
        "model": MODEL_NAME,
        "model_path": str(model),
        "data_yaml": str(data_yaml),
        "val_txt": str(val_txt),
        **hashes,
        "run_dir": str(run_dir),
        "command": command,
        "exit_code": exit_code,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "wall_seconds": round(wall, 3),
        "commit": commit,
        "vram_baseline_mib": sampler.baseline_mib,
        "vram_peak_mib": vram_peak,
        "vram_peak_above_idle_mib": vram_above_idle(vram_peak, sampler.baseline_mib),
        "environment": environment,
        "vram_samples": len(sampler.samples),
        "own_pid": proc.pid,
        "gpu_process_snapshots": gpu_snapshots,
        "foreign_process_seen": foreign_process_seen(gpu_snapshots, proc.pid),
        "gpu_exempt_process_names": sorted(EXEMPT_GPU_PROCESS_NAMES),
        "gpu_process_measurement": (
            "nvidia-smi --query-compute-apps at start (must be empty), every VRAM poll, and at end; "
            f"polled every {VRAM_POLL_SECONDS}s, so a process that starts and exits between polls is not seen"
        ),
        "vram_measurement": f"nvidia-smi memory.used polled every {VRAM_POLL_SECONDS}s; peak in MiB",
        "ram_peak_mib": round(ram_peak_mib, 1),
        "ram_measurement": (
            "resource.getrusage(RUSAGE_CHILDREN).ru_maxrss: max resident set of the largest waited "
            "child (includes small nvidia-smi polls; yolo dominates), Linux KiB converted to MiB"
        ),
        **gpu_identity(),
    }
    run_json.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(f"exit_code={exit_code} wall={wall:.1f}s vram_peak={vram_peak} MiB ram_peak={ram_peak_mib:.0f} MiB")
    print(f"run metadata written to {run_json}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
