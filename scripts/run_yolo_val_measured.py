"""One controlled `yolo val` run for EXP-20261004-01 (measurement-only, D-069).

Runs YOLO11n on COCO val2017 persons at conf=0.001 (Q28), batch=1, device 0, half=True, with
only --imgsz varying. It writes the artifacts that scripts/record_evaluation_runs.py verifies:

    <project>/<name>/predictions.json   written by ultralytics
    <project>/<name>.val.log            full stdout+stderr of the run
    <project>/<name>.run.json           how the run was executed (exit code, timing, hashes, GPU)

Refuses a dirty or uncommitted code tree (ADR-0016) and refuses to overwrite an existing run
directory. A non-zero exit is recorded in run.json and returned; the writer will then refuse it.
No GPU job is started unless this script is run explicitly with an approved image size.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cv_agent.execution.jobs.runtimes.yolo_eval import (  # noqa: E402
    DEFAULT_YOLO_EXECUTABLE,
    build_command,
)
from cv_agent.experiments.evaluation_records import RUN_SCHEMA  # noqa: E402
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


def run_name(imgsz: int) -> str:
    return f"e1-yolo11n-coco-val2017-imgsz{imgsz}-conf0001"


def build_argv(imgsz: int, *, state_root: Path, executable: str = DEFAULT_YOLO_EXECUTABLE) -> list[str]:
    """The `yolo val` argv: the binding's own builder, plus the two settings it does not expose.

    ``half=True`` makes FP16 explicit rather than relying on the ultralytics CUDA default.
    ``exist_ok=True`` makes ultralytics write to exactly ``name``; this script already refuses an
    existing directory, so it never overwrites a measured run.
    """
    inputs = {
        "model": str(state_root / "models" / MODEL_NAME),
        "data": str(state_root / "evaluations" / DATA_YAML_NAME),
        "output_dir": str(state_root / "evaluations"),
        "run_name": run_name(imgsz),
        "conf": CONF,
        "imgsz": imgsz,
        "classes": CLASSES,
        "device": DEVICE,
        "batch": BATCH,
        "yolo_executable": executable,
    }
    return [*build_command(inputs), "half=True", "exist_ok=True"]


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
    args = parser.parse_args(argv)

    try:
        commit = require_clean_worktree(REPO_ROOT)
    except ProvenanceError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    state = repository_state_root()
    project = state / "evaluations"
    name = run_name(args.imgsz)
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
    command = build_argv(args.imgsz, state_root=state)
    print(f"running from commit {commit}")
    print("command:", " ".join(command))

    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    with val_log.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            log.write(line)
        exit_code = proc.wait()
    wall = time.monotonic() - t0
    ended = datetime.now(timezone.utc)

    run = {
        "schema": RUN_SCHEMA,
        "series": "EXP-20261004-01",
        "imgsz": args.imgsz,
        "conf": CONF,
        "batch": BATCH,
        "device": DEVICE,
        "classes": CLASSES,
        "half": True,
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
        **gpu_identity(),
    }
    run_json.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(f"exit_code={exit_code} wall={wall:.1f}s run_dir={run_dir}")
    print(f"record metadata written to {run_json}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
