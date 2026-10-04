"""One controlled `yolo val` run for EXP-20261004-01 (measurement-only, D-069).

Runs YOLO11n on COCO val2017 persons at conf=0.001 (Q28), batch=1, device 0, quantize=16, with
only --imgsz varying. It writes the artifacts that scripts/record_evaluation_runs.py verifies:

    <project>/<name>/predictions.json   written by ultralytics
    <project>/<name>.val.log            full stdout+stderr of the run
    <project>/<name>.run.json           how the run was executed (exit code, timing, hashes,
                                        approval reference, GPU identity, peak VRAM, peak RAM)

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
    FP32_CONTROL_SERIES_ID,
    QUANTIZE,
    RUN_SCHEMA,
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


FP32_CONTROL_IMGSZ = 640
PRECISIONS = {"fp16": QUANTIZE, "fp32": None}


def run_name(imgsz: int, quantize: int | None = QUANTIZE) -> str:
    suffix = "" if quantize is not None else "-fp32"
    return f"e1-yolo11n-coco-val2017-imgsz{imgsz}-conf0001{suffix}"


def build_argv(
    imgsz: int,
    *,
    state_root: Path,
    executable: str = DEFAULT_YOLO_EXECUTABLE,
    quantize: int | None = QUANTIZE,
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
        "run_name": run_name(imgsz, quantize),
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


class VramSampler:
    """Polls `nvidia-smi` memory.used in a background thread and keeps the peak.

    The baseline is one synchronous sample taken before the run. A failed poll is skipped, not
    invented. If no sample succeeds, the peak is None and the writer refuses the run.
    """

    def __init__(self, interval: float = VRAM_POLL_SECONDS) -> None:
        self.interval = interval
        self.baseline_mib: int | None = None
        self.samples: list[int] = []
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

    def start(self) -> None:
        self.baseline_mib = self.sample_once()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def _poll(self) -> None:
        while not self._stop.is_set():
            value = self.sample_once()
            if value is not None:
                self.samples.append(value)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--imgsz", type=int, required=True, choices=APPROVED_IMGSZ)
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
    name = run_name(args.imgsz, quantize)
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
    command = build_argv(args.imgsz, state_root=state, quantize=quantize)
    print(f"running from commit {commit}")
    print("command:", " ".join(command))

    sampler = VramSampler()
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    sampler.start()
    with val_log.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            log.write(line)
        exit_code = proc.wait()
    wall = time.monotonic() - t0
    ended = datetime.now(timezone.utc)
    vram_peak = sampler.stop()
    ram_peak_mib = ru_maxrss_to_mib(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)

    run = {
        "schema": RUN_SCHEMA,
        "series": FP32_CONTROL_SERIES_ID if quantize is None else "EXP-20261004-01",
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
        "vram_samples": len(sampler.samples),
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
