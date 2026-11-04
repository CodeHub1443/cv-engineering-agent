"""
cv_agent.execution.runtimes.deepstream_validate_pipeline — verified binding
for the deepstream-generate-pipeline skill's `scripts/validate_pipeline.py`.

ADR-0009 §8 verification evidence (personal inspection, not assumed):

- **Implementation inspected.** Read all 777 lines of
  `~/.claude/skills/deepstream-generate-pipeline/scripts/validate_pipeline.py`.
  The script validates a GStreamer/DeepStream pipeline string WITHOUT running
  it, through up to six deterministic check stages:
    1. Syntax — quotes, empty segments, leading/trailing pipes.
    2. Elements — calls `gst-inspect-1.0 <element>` for each token; skipped
       with a warning if `gst-inspect-1.0` is not on PATH.
    3. Properties — compares known DeepStream element property sets.
    4. Structure — source/sink presence, named-pad refs.
    5. Platform/ordering — sink type, element ordering.
    6. Live parse — optional `gst-launch-1.0` dry-run with real sources/sinks
       replaced by `fakesrc`/`fakesink`; times out after 5 s; `FileNotFoundError`
       for missing `gst-launch-1.0` is caught and reported as a warning, never a
       crash.
  No GPU, no network, no file writes. Python stdlib only: `argparse`, `json`,
  `re`, `shlex`, `subprocess`, `shutil`. No third-party packages.

- **Invocation/CLI contract verified.** Empirically confirmed on this machine:
    `python3 validate_pipeline.py "<gst-launch-1.0 ...>"` OR
    `python3 validate_pipeline.py --pipeline "<...>" [--format {json,summary}]`
  Default output format is `json` (used here; never `summary`).

- **Exit-code behavior verified empirically** (not assumed from reading alone):
    - Exit 0: pipeline passes all checks → `{"valid": true, ...}` on stdout.
    - Exit 1: pipeline fails one or more checks → `{"valid": false, "errors":
      [...], ...}` on stdout.
    - Exit 1: no pipeline provided → `ERROR: No pipeline provided` on stderr
      (not JSON — this adapter guards against it before spawning).

- **Output/artifact contract verified.** Always a JSON object on stdout when
  the pipeline argument is present. Schema:
    `{"valid": bool, "elements_found": list[str], "num_elements": int,
     "pad_refs": list, "errors": list[str], "warnings": list[str]}`
  Never writes files. `--output` is not part of this script's contract;
  all output is always on stdout.

- **Side effects understood and acceptable.** Calls `gst-inspect-1.0` (
  read-only, no state change) and may launch a short `gst-launch-1.0` dry-run
  with `fakesrc`/`fakesink` substitutions, capped at 5 s, producing no
  artifacts. Both are read-only CV infrastructure probes; this binding is in
  the "Read-only research, retrieval, analysis" category of `docs/APPROVALS.md`
  → `approval_policy="allowed"`.

What this module does NOT claim:
- It does not make any other skill executable — `verified=True` is set for
  exactly this one binding (ADR-0009 §8).
- The `LinuxNvidiaJobRuntime` executing this is generic (it just runs a
  subprocess); the *binding* here is what names the specific skill as verified.
- No host GPU is required by `validate_pipeline.py` itself; the
  `LinuxNvidiaJobRuntime` host check (OS=linux, gpu_vendor=nvidia) is a
  property of the runtime, not the script. The script runs on any Linux host.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cv_agent.execution.binding import (
    ExecutionBinding,
    ExecutionBindingRegistry,
    InputField,
)
from cv_agent.execution.jobs.runtimes.linux_nvidia import (
    RUNTIME_ID as _LINUX_NVIDIA_RUNTIME_ID,
)
from cv_agent.execution.models import ApprovalPolicy
from cv_agent.skills.models import Skill

SKILL_ID = "deepstream-generate-pipeline"
BINDING_ID = "deepstream-validate-pipeline-linux-nvidia-v1"
_SCRIPT_RELATIVE = Path("scripts") / "validate_pipeline.py"


def resolve_command(skill: Skill, pipeline: str) -> list[str]:
    """
    Build the subprocess command for `validate_pipeline.py`.

    Derives the script path from `skill.location` (the real, discovered
    SKILL.md path) — never a hard-coded absolute path, so this adapter follows
    wherever the real environment installed the skill.

    Uses `sys.executable` as the Python interpreter, the same discipline as
    `TrtPerfAnalysisRuntime` — this process already knows its interpreter, so
    the skill's own `run.sh`/`run.cmd` PATH discovery is unnecessary.

    Raises ValueError if `scripts/validate_pipeline.py` does not exist next
    to the skill's SKILL.md — the caller should treat this as a not-installed
    condition, not proceed with a missing script.
    """
    skill_root = Path(skill.location).parent
    script_path = skill_root / _SCRIPT_RELATIVE
    if not script_path.is_file():
        raise ValueError(
            f"scripts/validate_pipeline.py not found at {script_path} "
            f"— the installed skill does not match the expected layout."
        )
    python = sys.executable
    return [python, str(script_path), "--pipeline", pipeline]


def build_binding(
    skill_id: str = SKILL_ID,
    *,
    approval_policy: ApprovalPolicy = "allowed",
) -> ExecutionBinding:
    """
    The one real ExecutionBinding this module ships (ADR-0009 §8).

    `approval_policy` defaults to "allowed" because `validate_pipeline.py` is
    a read-only validation analysis tool — "Read-only research, retrieval,
    analysis → ✅ free" per `docs/APPROVALS.md`. A caller that wants to exercise
    the approval-gate path against this runtime may pass
    `approval_policy="approval_required"` explicitly without changing this
    module's recommended default.

    `verified=True` is set because this binding's author has personally
    inspected the script's implementation, confirmed the CLI contract
    empirically, and documented the inspection in this module's docstring
    (per ADR-0009 §8 and the trt-perf-analysis precedent).
    """
    return ExecutionBinding(
        skill_id=skill_id,
        binding_id=BINDING_ID,
        runtime_id=_LINUX_NVIDIA_RUNTIME_ID,
        approval_policy=approval_policy,
        verified=True,
        description=(
            "Subprocess invocation of the installed deepstream-generate-pipeline "
            "skill's scripts/validate_pipeline.py — validates a GStreamer/DeepStream "
            "pipeline string (syntax, element, property, structure checks), "
            "stdlib only, read-only, no GPU required. "
            "command built by resolve_command(). "
            "See ADR-0009 §8."
        ),
        input_schema=(
            InputField(
                name="command",
                required=True,
                description=(
                    "list[str] passed to LinuxNvidiaJobRuntime. "
                    "Build with resolve_command(skill, pipeline_string)."
                ),
            ),
        ),
    )


def register(
    registry: ExecutionBindingRegistry,
    *,
    skill_id: str = SKILL_ID,
    approval_policy: ApprovalPolicy = "allowed",
) -> None:
    """
    Explicit, opt-in wiring — never called automatically by CVAgent.__init__.

    Registers a verified binding for `skill_id`. The caller must also supply a
    `LinuxNvidiaJobRuntime` instance in the `job_runtimes` dict when
    constructing `JobExecutor`:

        from cv_agent.execution.runtimes.deepstream_validate_pipeline import register
        from cv_agent.execution.jobs.runtimes.linux_nvidia import LinuxNvidiaJobRuntime
        register(agent.execution_bindings)
        executor = JobExecutor(
            registry=agent.execution_bindings,
            job_runtimes={LinuxNvidiaJobRuntime.RUNTIME_ID: LinuxNvidiaJobRuntime()},
            host_verifier=LinuxNvidiaHostVerifier(),
        )
    """
    registry.register_binding(build_binding(skill_id, approval_policy=approval_policy))
