"""
scripts/run_baseline.py — First real baseline execution for the reference task.

Person Detection + Tracking · D-043 · baseline_id="SELF" · exp_id=EXP-20260929-01

Runs the selected YOLO11n model through the full Agent architecture:
  SelectionRecommendation → JobExecutor (approval gate) → LinuxNvidiaJobRuntime
  → JobResult → job_result_to_experiment_record() → ExperimentLedger

Usage (from repo root):
    python3 scripts/run_baseline.py

Owner approval: Tanvir's explicit instruction 2026-09-29 ("execute the FIRST
REAL baseline") authorises request.approved=True in this script.

Governance:
  - Does NOT bypass JobExecutor or its pre-flight checks.
  - Does NOT call LinuxNvidiaJobRuntime.start() directly.
  - Does NOT fabricate any metric.
  - Approval pin is generated from the live binding snapshot at runtime.
  - Does not start evaluation, optimization, or training.
"""
# ruff: noqa: E402, F541  — sequential imports are intentional in this runner script

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

# ── 1. Model Selection — read from existing research, do not assume YOLO ──────

print("=== 1. Model Selection (D-053) ===")
from cv_agent.llm.mock import FakeLLMProvider
from cv_agent.model_selection.reference_task_research import run_reference_selection

rec = run_reference_selection(FakeLLMProvider())
assert rec.is_proposal is True, "SelectionRecommendation.is_proposal invariant violated"
candidate_id: str = rec.recommended_candidate_id
print(f"  recommended_candidate_id : {candidate_id}")
print(f"  confidence               : {rec.confidence}")
print(f"  is_proposal              : {rec.is_proposal}")

# ── 2. Resolve paths ───────────────────────────────────────────────────────────

MODEL_PATH   = REPO_ROOT / ".cv_agent" / "models" / "yolo11n.pt"
VIDEO_PATH   = REPO_ROOT / "tests" / "fixtures" / "person_detection_sample.mp4"
OUTPUT_ROOT  = REPO_ROOT / ".cv_agent" / "baselines"
RUN_NAME     = "baseline-yolo11n-person-track-20260929"
DB_PATH      = REPO_ROOT / ".cv_agent" / "experiments.sqlite"

OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

print(f"\n=== 2. Environment ===")
print(f"  candidate    : {candidate_id}")
print(f"  model        : {MODEL_PATH}  exists={MODEL_PATH.exists()}")
print(f"  video        : {VIDEO_PATH}  exists={VIDEO_PATH.exists()}")
print(f"  output_root  : {OUTPUT_ROOT}")
print(f"  db_path      : {DB_PATH}")

if not MODEL_PATH.exists():
    sys.exit(f"BLOCKED: model not found at {MODEL_PATH}")
if not VIDEO_PATH.exists():
    sys.exit(f"BLOCKED: video fixture not found at {VIDEO_PATH}")

# ── 3. Wire up the execution architecture ──────────────────────────────────────

print(f"\n=== 3. Architecture setup ===")
from cv_agent.execution.binding import ExecutionBindingRegistry
from cv_agent.execution.host import HostRequirement, LinuxNvidiaHostVerifier
from cv_agent.execution.jobs.executor import JobExecutor
from cv_agent.execution.jobs.runtimes.linux_nvidia import LinuxNvidiaJobRuntime
from cv_agent.execution.jobs.runtimes.yolo_inference import (
    SKILL_ID,
    build_command,
    register_binding,
)
from cv_agent.execution.models import SkillExecutionRequest
from cv_agent.skills.models import Skill

registry = ExecutionBindingRegistry()
register_binding(registry, skill_id=SKILL_ID, verified=True,
                 approval_policy="approval_required")

runtime  = LinuxNvidiaJobRuntime()
executor = JobExecutor(
    registry=registry,
    job_runtimes={LinuxNvidiaJobRuntime.RUNTIME_ID: runtime},
    host_verifier=LinuxNvidiaHostVerifier(),
)
print(f"  binding registered : {SKILL_ID}")
print(f"  can_start          : {executor.can_start(SKILL_ID)}")

# ── 4. Build command and pin ───────────────────────────────────────────────────

print(f"\n=== 4. Command + pin ===")
inputs: dict = {
    "source"          : str(VIDEO_PATH.absolute()),
    "output_dir"      : str(OUTPUT_ROOT.absolute()),
    "run_name"        : RUN_NAME,
    "model"           : str(MODEL_PATH.absolute()),
    "tracker"         : "bytetrack.yaml",
    "conf"            : 0.25,
    "imgsz"           : 640,
    "classes"         : [0],
    "device"          : "0",
    "yolo_executable" : "/home/dev/.local/bin/yolo",
}
command = build_command(inputs)
inputs["command"] = command

print("  command: " + " ".join(command))

# registry.pin(skill_id) is the full execution pin:
#   {"binding": binding.pin(), "runtime_generation": int | None}
# binding.pin() alone is only the binding-level snapshot — it is NOT a valid
# execution pin and pin_is_well_formed() will reject it with
# "execution_pin_malformed" (ADR-0003 §10.4, confirmed in D-056).
pin = registry.pin(SKILL_ID)
assert pin is not None, f"registry.pin() returned None — is '{SKILL_ID}' registered?"
print(f"  pin keys: {list(pin.keys())}  runtime_generation={pin['runtime_generation']}")

# ── 5. Construct SkillExecutionRequest with approval ──────────────────────────

skill = Skill(
    skill_id=SKILL_ID,
    name="yolo-inference",
    description="Ultralytics YOLO inference — person detection + ByteTrack tracking",
    source="local",
    location="/home/dev/.local/lib/python3.10/site-packages/ultralytics",
    tags=("person-detection", "tracking", "yolo"),
    executable=True,
)

request = SkillExecutionRequest(
    inputs=inputs,
    task="First real baseline: Person Detection + Tracking, yolo11n, D-043",
    requested_by="agent",
    approved=True,              # Owner (Tanvir) authorised 2026-09-29
    expected_binding_pin=pin,   # Captured from live binding snapshot above
)

host_req = HostRequirement(os="linux", gpu_vendor="nvidia", min_vram_mb=2048)

# ── 6. Start through JobExecutor (approval gate) ──────────────────────────────

print(f"\n=== 5. JobExecutor.start_job() ===")
t_start = time.monotonic()
handle, start_result = executor.start_job(skill, request, host_req)

print(f"  start status : {start_result.status}")
if start_result.error:
    print(f"  error        : [{start_result.error.category}] {start_result.error.message}")

if start_result.status != "started":
    sys.exit("BLOCKED: job did not start through approval gate — see error above")

print(f"  job_id       : {handle.job_id}")
print(f"  binding_id   : {start_result.evidence.binding_id}")
print(f"  runtime_id   : {start_result.evidence.runtime_id}")

# ── 7. Poll until terminal ────────────────────────────────────────────────────

print(f"\n=== 6. Polling (2–5 min, GPU device 0) ===")
poll_n = 0
while True:
    status = executor.poll_job(handle)
    poll_n += 1
    if poll_n % 15 == 0:
        elapsed = time.monotonic() - t_start
        print(f"  ...{elapsed:.0f}s elapsed  status={status}")
    if status in ("completed", "failed", "cancelled"):
        break
    time.sleep(2)

wall_time_s = time.monotonic() - t_start
print(f"  final status : {status}  wall_time={wall_time_s:.1f}s")

# ── 8. Collect outcome ────────────────────────────────────────────────────────

from cv_agent.execution.jobs.models import JobResult

print(f"\n=== 7. collect_job() ===")
outcome = executor.collect_job(handle)
print(f"  success      : {outcome.success}")
print(f"  exit_code    : {outcome.exit_code}")
print(f"  wall_time_s  : {outcome.resources.wall_time_seconds}")
print(f"  artifacts    : {outcome.artifacts}")
if outcome.error_message:
    print(f"  error_msg    : {outcome.error_message[:400]}")
print(f"  --- stdout (last 800 chars) ---")
print(outcome.stdout[-800:] if outcome.stdout else "(empty)")
print(f"  --- stderr (last 400 chars) ---")
print(outcome.stderr[-400:] if outcome.stderr else "(empty)")

# Build the terminal JobResult manually (start_result only has status="started")
from cv_agent.execution.models import ExecutionEvidence
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

# ── 9. ExperimentRecord ───────────────────────────────────────────────────────

print(f"\n=== 8. job_result_to_experiment_record() ===")
from cv_agent.graph.experiment_wiring import ExperimentContext, job_result_to_experiment_record

context = ExperimentContext(
    exp_id="EXP-20260929-01",
    baseline_id="SELF",
    hypothesis=(
        "YOLO11n with ByteTrack can detect and track persons in a real-time video "
        "stream on a Linux/NVIDIA GPU host, serving as the first measurable baseline "
        "for the Person Detection + Tracking reference task (D-043)."
    ),
    success_criteria=(
        "yolo track exits 0; annotated video and per-frame tracking labels are "
        "produced in output_dir/run_name/; no exception or crash is observed."
    ),
    model=candidate_id,
    approval_ref="Tanvir instruction 2026-09-29: execute the FIRST REAL baseline",
    hardware_training="NVIDIA GeForce RTX 3060 12GB, driver 535.309.01 / CUDA 12.1 (yolo subprocess: Python-3.10, torch-2.5.1+cu121)",
    hardware_target="NVIDIA GeForce RTX 3060 (same host, V1 reference baseline)",
    notes=(
        f"SelectionRecommendation: {rec.recommended_candidate_id}, "
        f"confidence={rec.confidence}, is_proposal={rec.is_proposal}. "
        f"Video: {VIDEO_PATH.name} (640x360 H.264 25fps ~114s). "
        f"Runner wall_time={wall_time_s:.1f}s."
    ),
)

record = job_result_to_experiment_record(terminal_result, context=context)
print(f"  exp_id        : {record.exp_id}")
print(f"  status        : {record.status}")
print(f"  model         : {record.model}")
print(f"  baseline_id   : {record.baseline_id}")
print(f"  created_at    : {record.created_at}")
print(f"  completed_at  : {record.completed_at}")
print(f"  train_time    : {record.train_time}")
print(f"  gpu_hours     : {record.gpu_hours}")
print(f"  hardware      : {record.hardware}")
print(f"  failure_anal  : {record.failure_analysis}")
print(f"  notes (500)   : {record.notes[:500]}")

# ── 10. Write to ExperimentLedger ─────────────────────────────────────────────

print(f"\n=== 9. ExperimentLedger ===")
from cv_agent.experiments.store import open_ledger

with open_ledger(db_path=DB_PATH) as ledger:
    ledger.record_experiment(record)
    retrieved = ledger.get_experiment("EXP-20260929-01")
    assert retrieved is not None
    assert retrieved.status == record.status
    print(f"  Written and verified: {DB_PATH}")
    print(f"  status={retrieved.status}  model={retrieved.model}")

# ── Summary ───────────────────────────────────────────────────────────────────

print(f"""
=== BASELINE COMPLETE ===
  exp_id     : EXP-20260929-01
  model      : {candidate_id}  ({MODEL_PATH.name})
  device     : GPU:0 NVIDIA GeForce RTX 3060 (yolo subprocess: torch-2.5.1+cu121 / CUDA 12.1)
  video      : {VIDEO_PATH.name}  (640x360, H.264, 25fps, ~114s)
  outcome    : {terminal_result.status}
  exit_code  : {outcome.exit_code}
  wall_time  : {wall_time_s:.1f}s
  artifacts  : {outcome.artifacts}
  ledger     : {DB_PATH}
""")
