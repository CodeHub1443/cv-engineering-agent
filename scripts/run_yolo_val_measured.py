"""One controlled `yolo val` run: the EXP-20261004-01 series or one owner-fixed candidate.

Runs YOLO11n on the dataset named by --dataset-spec (the eval_dataset_ref.json at the dataset root,
ADR-0025) at conf=0.001 (Q28), batch=1, device 0, quantize=16, with only --imgsz varying. The spec
gives the layout, expected counts and target class; --data-yaml is the ultralytics yaml, which must
agree with it. It writes the artifacts that scripts/record_evaluation_runs.py verifies:

    <project>/<name>/predictions.json   written by ultralytics
    <project>/<name>.val.log            full stdout+stderr of the run
    <project>/<name>.run.json           how the run was executed (exit code, timing, hashes,
                                        approval reference, GPU identity, peak VRAM, peak RAM,
                                        dataset id, spec sha256, label digest)

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

from cv_agent.datasets.eval_ref import (  # noqa: E402
    EvalDatasetRef,
    EvalDatasetRefError,
    compute_label_digest,
    load_eval_dataset_ref,
)
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
    coresident_names,
    foreign_process_seen,
    is_exempt_process,
    precision_label,
    scoring_problems,
    series_run_name,
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
MODEL_NAME = "yolo11n.pt"
VRAM_POLL_SECONDS = 1.0
# Ultralytics' auto-install gate: `AUTOINSTALL = str(os.getenv("YOLO_AUTOINSTALL", True)).lower() == "true"`
# (ultralytics/utils/__init__.py:45, read at utils/checks.py:472; ultralytics 8.4.6 (Windows); 8.4.138 to be checked on Linux),
# so any value but "true" disables it (Q70).
AUTOINSTALL_ENV = "YOLO_AUTOINSTALL"
ENVIRONMENT_KEYS = ("python_version", "torch_version", "torch_cuda_version", "ultralytics_version", "pip_freeze_sha256")


FP32_CONTROL_IMGSZ = 640
PRECISIONS = {"fp16": QUANTIZE, "fp32": None}


def run_name(imgsz: int, dataset_id: str, quantize: int | None = QUANTIZE, exp_id: str | None = None) -> str:
    """The run directory name; the dataset fragment is the reference's id (COCO: coco-val2017)."""
    if exp_id is not None:
        return candidate_run_name(exp_id, imgsz, dataset_id)
    return series_run_name(imgsz, dataset_id, fp32=quantize is None)


def build_argv(
    imgsz: int,
    *,
    state_root: Path,
    ref: EvalDatasetRef,
    data_yaml: Path,
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
        "data": str(data_yaml),
        "output_dir": str(state_root / "evaluations"),
        "run_name": run_name(imgsz, ref.dataset_id, quantize, exp_id),
        "conf": CONF,
        "imgsz": imgsz,
        "classes": [ref.target_class],
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


COMPUTE_APPS_ARGV = ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"]


def parse_compute_apps(text: str) -> list[dict[str, int | str]] | None:
    """Compute processes from `nvidia-smi --query-compute-apps`. [] means none; None means unreadable.

    Any row whose pid is not a number (for example ``[Insufficient Permissions]``) makes the whole
    snapshot unreadable, so it cannot be mistaken for an idle GPU (fail closed, ADR-0018). A row may
    end in a used-memory column (MiB, or ``[N/A]`` -> None); a two-column row has no ``used_mib`` key.
    """
    if "no running" in text.lower():
        return []
    processes: list[dict[str, int | str]] = []
    for line in text.strip().splitlines():
        if not line.strip():
            continue
        pid_text, _, rest = line.partition(",")
        if not pid_text.strip().isdigit():
            return None
        head, sep, tail = rest.rpartition(",")
        used = tail.strip()
        if sep and head.strip() and (used.isdigit() or used == "[N/A]"):
            processes.append({"pid": int(pid_text.strip()), "name": head.strip(), "used_mib": int(used) if used.isdigit() else None})
        else:
            processes.append({"pid": int(pid_text.strip()), "name": rest.strip()})
    return processes


def allow_path_problems(paths: list[str]) -> list[str]:
    """Why an --allow-gpu-process value cannot be matched exactly: it must be an absolute POSIX path (ADR-0018 amendment)."""
    return [f"--allow-gpu-process {p!r} must be an absolute executable path" for p in paths if not p.startswith("/")]


def split_preflight(processes: list[dict], allowed: frozenset[str]) -> tuple[list[dict], list[dict]]:
    """(blocking, gpu_coresident) for a start snapshot. A process is allowed only by an exact name match.

    ``gpu_coresident`` is what run.json records: ``{pid, process_name, used_mib}`` for each allowed process present.
    """
    blocking = [p for p in processes if not is_exempt_process(p) and p.get("name") not in allowed]
    coresident = [
        {"pid": p["pid"], "process_name": p["name"], "used_mib": p.get("used_mib")}
        for p in processes
        if p.get("name") in allowed and not is_exempt_process(p)
    ]
    return blocking, coresident


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


def _parse_names(rest: str, block: list[str]) -> dict[int, str]:
    """The ``names`` value: a block mapping (``0: person``), a flow list (``[person]``) or a block list (``- person``)."""
    if rest:
        if not (rest.startswith("[") and rest.endswith("]")):
            raise ValueError("names must be a mapping or a list of class names")
        items = [part.strip().strip("'\"") for part in rest[1:-1].split(",")]
        if not items or not all(items):
            raise ValueError("names list has an empty entry")
        return dict(enumerate(items))
    entries = [line.strip() for line in block if line.strip() and not line.strip().startswith("#")]
    if not entries:
        raise ValueError("names is empty")
    if all(entry.startswith("- ") for entry in entries):
        return dict(enumerate(entry[2:].strip().strip("'\"") for entry in entries))
    names: dict[int, str] = {}
    for entry in entries:
        index, sep, label = entry.partition(":")
        if not sep or not index.strip().isdigit() or not label.strip() or int(index) in names:
            raise ValueError(f"names entry {entry!r} is not a unique 'N: name' or '- name' line")
        names[int(index)] = label.strip()
    return names


def read_data_yaml(data_yaml: Path) -> tuple[Path, Path, dict[int, str]]:
    """(dataset root, val list path, class names) from the ultralytics yaml, with no YAML library."""
    lines = data_yaml.read_text(encoding="utf-8").splitlines()
    keys: dict[str, str] = {}
    names_at: int | None = None
    for index, line in enumerate(lines):
        if line.startswith(("path:", "val:", "names:")):
            key, _, value = line.partition(":")
            keys[key] = value.strip()
            if key == "names":
                names_at = index
    if "path" not in keys or "val" not in keys or names_at is None:
        raise ValueError(f"{data_yaml} must define 'path:', 'val:' and 'names:'")
    block: list[str] = []
    for line in lines[names_at + 1 :]:
        if line[:1] not in (" ", "\t") and line.strip():
            break
        block.append(line)
    names = _parse_names(keys["names"], block)
    root = Path(keys["path"])
    return root, root / keys["val"], names


def data_yaml_problems(
    ref: EvalDatasetRef, dataset_root: Path, yaml_root: Path, val: Path, names: dict[int, str]
) -> list[str]:
    """How the ultralytics yaml disagrees with the reference. Empty means it agrees."""
    problems: list[str] = []
    if yaml_root.resolve() != dataset_root:
        problems.append(f"data yaml path {str(yaml_root)!r} is not the dataset root {str(dataset_root)!r}")
    expected = (dataset_root / ref.list_file).resolve()
    if val.resolve() != expected:
        problems.append(f"data yaml val {str(val)!r} is not the spec's list file {str(expected)!r}")
    if ref.target_class not in names:
        problems.append(f"data yaml names {sorted(names)} do not contain target_class {ref.target_class}")
    return problems


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
    parser.add_argument(
        "--dataset-spec",
        type=Path,
        required=True,
        metavar="PATH",
        help="eval_dataset_ref.json at the dataset root (ADR-0025): layout, counts and target class",
    )
    parser.add_argument(
        "--data-yaml",
        type=Path,
        required=True,
        metavar="PATH",
        help="the ultralytics data yaml; its path, val and names must agree with the spec",
    )
    parser.add_argument(
        "--allow-gpu-process",
        action="append",
        default=[],
        metavar="EXECUTABLE_PATH",
        help=(
            "repeatable; absolute path of a co-resident GPU process allowed for this run (exact match on the "
            "nvidia-smi process name). Any other compute process still refuses. Recorded as gpu_coresident; "
            "such a run's latency/FPS/VRAM are not comparable with clean-GPU runs (ADR-0018 amendment)"
        ),
    )
    args = parser.parse_args(argv)
    bad_allow = allow_path_problems(args.allow_gpu_process)
    if bad_allow:
        print(f"REFUSED: {'; '.join(bad_allow)}", file=sys.stderr)
        return 2
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

    try:
        ref = load_eval_dataset_ref(args.dataset_spec)
        name = run_name(args.imgsz, ref.dataset_id, quantize, exp_id)
    except (EvalDatasetRefError, ValueError) as exc:
        print(f"REFUSED: dataset spec: {exc}", file=sys.stderr)
        return 2
    unscorable = scoring_problems(ref)
    if unscorable:
        print(f"REFUSED: {'; '.join(unscorable)}", file=sys.stderr)
        return 2
    dataset_root = args.dataset_spec.resolve().parent

    state = repository_state_root()
    project = state / "evaluations"
    run_dir = project / name
    run_json = project / f"{name}.run.json"
    val_log = project / f"{name}.val.log"
    for existing in (run_dir, run_json, val_log):
        if existing.exists():
            print(f"REFUSED: {existing} already exists; measured runs are never overwritten", file=sys.stderr)
            return 2

    model = state / "models" / MODEL_NAME
    data_yaml = args.data_yaml
    for path in (model, data_yaml):
        if not path.is_file():
            print(f"REFUSED: required input is missing: {path}", file=sys.stderr)
            return 2
    try:
        yaml_root, val_txt, names = read_data_yaml(data_yaml)
    except (OSError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    mismatch = data_yaml_problems(ref, dataset_root, yaml_root, val_txt, names)
    if mismatch:
        print(f"REFUSED: {'; '.join(mismatch)}", file=sys.stderr)
        return 2
    if not val_txt.is_file():
        print(f"REFUSED: val list is missing: {val_txt}", file=sys.stderr)
        return 2
    try:
        label_digest = compute_label_digest(ref, dataset_root)
    except EvalDatasetRefError as exc:
        print(f"REFUSED: cannot fingerprint the labels: {exc}", file=sys.stderr)
        return 2

    # Inputs are hashed before the run and again by the writer, so a swap in between is caught.
    hashes = {
        "model_sha256": sha256_file(model),
        "data_yaml_sha256": sha256_file(data_yaml),
        "val_txt_sha256": sha256_file(val_txt),
    }
    command = build_argv(args.imgsz, state_root=state, ref=ref, data_yaml=data_yaml, quantize=quantize, exp_id=exp_id)
    print(f"running from commit {commit}")
    print("command:", " ".join(command))

    # ADR-0018 preflight: refuse to start unless the GPU has no compute process and the list is readable.
    start_snapshot = snapshot_compute_apps(at=datetime.now(timezone.utc).isoformat())
    if start_snapshot["processes"] is None:
        print("REFUSED: cannot read the GPU process list (nvidia-smi); no run started", file=sys.stderr)
        return 2
    blocking, gpu_coresident = split_preflight(start_snapshot["processes"], frozenset(args.allow_gpu_process))
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
        "classes": [ref.target_class],
        "quantize": quantize,
        "precision_requested": precision_label(quantize),
        "approval_ref": approval_ref,
        "model": MODEL_NAME,
        "model_path": str(model),
        "data_yaml": str(data_yaml),
        "val_txt": str(val_txt),
        "dataset_spec": str(args.dataset_spec),
        "dataset_id": ref.dataset_id,
        "spec_sha256": ref.spec_sha256,
        "label_digest": label_digest,
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
        "gpu_coresident": gpu_coresident,
        "foreign_process_seen": foreign_process_seen(gpu_snapshots, proc.pid, allowed=coresident_names(gpu_coresident)),
        "gpu_exempt_process_names": sorted(EXEMPT_GPU_PROCESS_NAMES),
        "gpu_process_measurement": (
            "nvidia-smi --query-compute-apps at start (must be empty except processes named by --allow-gpu-process), every VRAM poll, and at end; "
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
