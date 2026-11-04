"""
Tests for cv_agent.execution.jobs.runtimes.yolo_inference.

ADR-0009 §8 — test that the binding module upholds the discipline:
  - constants are correct identifiers
  - command builder produces the expected CLI invocation
  - required inputs are enforced; optional inputs get correct defaults
  - artifact paths follow the CLI's known output convention
  - build_binding() produces a verified, approval-gated ExecutionBinding
  - register_binding() registers in the registry
  - no direct runtime bypass (module does not import JobExecutor or JobRuntime)

Real inference integration test is skipped when no committed video fixture
exists in the repository and/or no GPU is available (CI-safe by default).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Literal

import pytest

import cv_agent.execution.jobs.runtimes.yolo_inference as yolo_mod
from cv_agent.execution.binding import ExecutionBinding, ExecutionBindingRegistry, pin_is_well_formed
from cv_agent.execution.host import HostProfile, HostRequirement, LinuxNvidiaHostVerifier
from cv_agent.execution.jobs.executor import JobExecutor
from cv_agent.execution.jobs.models import JobHandle, JobOutcome, JobResourceMetadata
from cv_agent.execution.models import SkillExecutionRequest
from cv_agent.execution.jobs.runtimes.linux_nvidia import RUNTIME_ID as LINUX_NVIDIA_RUNTIME_ID
from cv_agent.skills.models import Skill
from cv_agent.execution.jobs.runtimes.yolo_inference import (
    BINDING_ID,
    DEFAULT_CLASSES,
    DEFAULT_CONF,
    DEFAULT_IMGSZ,
    DEFAULT_MODEL,
    DEFAULT_TRACKER,
    DEFAULT_YOLO_EXECUTABLE,
    RUNTIME_ID,
    SKILL_ID,
    build_binding,
    build_command,
    expected_artifact_paths,
    register_binding,
)

# ── Fixtures ──────────────────────────────────────────────────────────────

_VALID_INPUTS: dict = {
    "source": "/data/video.mp4",
    "output_dir": "/tmp/runs",
    "run_name": "baseline",
}

_VALID_INPUTS_ALL: dict = {
    "source": "/data/video.mp4",
    "output_dir": "/tmp/runs",
    "run_name": "baseline",
    "model": "yolo11n.pt",
    "tracker": "bytetrack.yaml",
    "conf": 0.25,
    "imgsz": 640,
    "classes": [0],
    "device": "0",
    "yolo_executable": "yolo",
}

# ── Binding identity ──────────────────────────────────────────────────────


class TestBindingIdentity:
    def test_skill_id(self):
        assert SKILL_ID == "yolo-inference"

    def test_binding_id(self):
        assert BINDING_ID == "yolo11n-person-track-linux-job-v1"

    def test_runtime_id_matches_linux_nvidia(self):
        assert RUNTIME_ID == LINUX_NVIDIA_RUNTIME_ID

    def test_default_model(self):
        assert DEFAULT_MODEL == "yolo11n.pt"

    def test_default_tracker(self):
        assert DEFAULT_TRACKER == "bytetrack.yaml"

    def test_default_classes_person_only(self):
        assert DEFAULT_CLASSES == [0]

    def test_default_conf(self):
        assert DEFAULT_CONF == 0.25

    def test_default_imgsz(self):
        assert DEFAULT_IMGSZ == 640

    def test_default_yolo_executable(self):
        assert DEFAULT_YOLO_EXECUTABLE == "yolo"


# ── Command builder ────────────────────────────────────────────────────────


class TestBuildCommand:
    def test_returns_list_of_strings(self):
        cmd = build_command(_VALID_INPUTS)
        assert isinstance(cmd, list)
        assert all(isinstance(a, str) for a in cmd)

    def test_first_element_is_executable(self):
        cmd = build_command(_VALID_INPUTS)
        assert cmd[0] == "yolo"

    def test_second_element_is_track(self):
        cmd = build_command(_VALID_INPUTS)
        assert cmd[1] == "track"

    def test_default_model_arg(self):
        cmd = build_command(_VALID_INPUTS)
        assert "model=yolo11n.pt" in cmd

    def test_source_arg(self):
        cmd = build_command(_VALID_INPUTS)
        assert "source=/data/video.mp4" in cmd

    def test_classes_arg_default_person(self):
        cmd = build_command(_VALID_INPUTS)
        assert "classes=[0]" in cmd

    def test_tracker_arg_default(self):
        cmd = build_command(_VALID_INPUTS)
        assert "tracker=bytetrack.yaml" in cmd

    def test_conf_arg_default(self):
        cmd = build_command(_VALID_INPUTS)
        assert "conf=0.25" in cmd

    def test_imgsz_arg_default(self):
        cmd = build_command(_VALID_INPUTS)
        assert "imgsz=640" in cmd

    def test_save_true(self):
        cmd = build_command(_VALID_INPUTS)
        assert "save=True" in cmd

    def test_save_txt_true(self):
        cmd = build_command(_VALID_INPUTS)
        assert "save_txt=True" in cmd

    def test_project_arg(self):
        cmd = build_command(_VALID_INPUTS)
        assert "project=/tmp/runs" in cmd

    def test_name_arg(self):
        cmd = build_command(_VALID_INPUTS)
        assert "name=baseline" in cmd

    def test_device_default(self):
        cmd = build_command(_VALID_INPUTS)
        assert "device=0" in cmd

    def test_no_leading_dashes(self):
        cmd = build_command(_VALID_INPUTS)
        for arg in cmd[2:]:
            assert not arg.startswith("--"), (
                f"Arg {arg!r} must not use --flag syntax; yolo CLI uses key=value."
            )

    def test_custom_model(self):
        inputs = {**_VALID_INPUTS, "model": "/models/yolo11n.pt"}
        cmd = build_command(inputs)
        assert "model=/models/yolo11n.pt" in cmd

    def test_custom_executable(self):
        inputs = {**_VALID_INPUTS, "yolo_executable": "/usr/local/bin/yolo"}
        cmd = build_command(inputs)
        assert cmd[0] == "/usr/local/bin/yolo"

    def test_custom_device_cpu(self):
        inputs = {**_VALID_INPUTS, "device": "cpu"}
        cmd = build_command(inputs)
        assert "device=cpu" in cmd

    def test_custom_classes_multi(self):
        inputs = {**_VALID_INPUTS, "classes": [0, 1, 2]}
        cmd = build_command(inputs)
        assert "classes=[0,1,2]" in cmd

    def test_all_optional_args(self):
        cmd = build_command(_VALID_INPUTS_ALL)
        assert len(cmd) >= 13  # at minimum, all required args

    def test_source_missing_raises(self):
        with pytest.raises(ValueError, match="source"):
            build_command({"output_dir": "/tmp/runs", "run_name": "x"})

    def test_output_dir_missing_raises(self):
        with pytest.raises(ValueError, match="output_dir"):
            build_command({"source": "/data/v.mp4", "run_name": "x"})

    def test_run_name_missing_raises(self):
        with pytest.raises(ValueError, match="run_name"):
            build_command({"source": "/data/v.mp4", "output_dir": "/tmp"})

    def test_empty_source_raises(self):
        with pytest.raises(ValueError, match="source"):
            build_command({"source": "", "output_dir": "/tmp", "run_name": "x"})

    def test_empty_output_dir_raises(self):
        with pytest.raises(ValueError, match="output_dir"):
            build_command({"source": "/data/v.mp4", "output_dir": "", "run_name": "x"})

    def test_empty_run_name_raises(self):
        with pytest.raises(ValueError, match="run_name"):
            build_command({"source": "/data/v.mp4", "output_dir": "/tmp", "run_name": ""})

    def test_command_length_at_least_13(self):
        cmd = build_command(_VALID_INPUTS)
        assert len(cmd) >= 13


# ── Artifact paths ─────────────────────────────────────────────────────────


class TestExpectedArtifactPaths:
    def test_returns_dict(self):
        paths = expected_artifact_paths(_VALID_INPUTS)
        assert isinstance(paths, dict)

    def test_annotated_video_dir_key(self):
        paths = expected_artifact_paths(_VALID_INPUTS)
        assert "annotated_video_dir" in paths

    def test_tracking_labels_dir_key(self):
        paths = expected_artifact_paths(_VALID_INPUTS)
        assert "tracking_labels_dir" in paths

    def test_annotated_video_dir_is_run_dir(self):
        paths = expected_artifact_paths(_VALID_INPUTS)
        expected = str(Path("/tmp/runs") / "baseline")
        assert paths["annotated_video_dir"] == expected

    def test_tracking_labels_dir_under_run_dir(self):
        paths = expected_artifact_paths(_VALID_INPUTS)
        expected = str(Path("/tmp/runs") / "baseline" / "labels")
        assert paths["tracking_labels_dir"] == expected

    def test_absolute_paths(self):
        paths = expected_artifact_paths(_VALID_INPUTS)
        assert paths["annotated_video_dir"].startswith("/")
        assert paths["tracking_labels_dir"].startswith("/")

    def test_custom_output_dir(self):
        inputs = {**_VALID_INPUTS, "output_dir": "/mnt/data/output"}
        paths = expected_artifact_paths(inputs)
        assert paths["annotated_video_dir"].startswith("/mnt/data/output")

    def test_labels_dir_ends_with_labels(self):
        paths = expected_artifact_paths(_VALID_INPUTS)
        assert paths["tracking_labels_dir"].endswith("labels")

    def test_empty_inputs_fallback(self):
        """Returns string paths even with no inputs (fallback defaults)."""
        paths = expected_artifact_paths({})
        assert "annotated_video_dir" in paths
        assert "tracking_labels_dir" in paths


# ── build_binding() ────────────────────────────────────────────────────────


class TestBuildBinding:
    def test_returns_execution_binding(self):
        b = build_binding()
        assert isinstance(b, ExecutionBinding)

    def test_skill_id(self):
        b = build_binding()
        assert b.skill_id == SKILL_ID

    def test_binding_id(self):
        b = build_binding()
        assert b.binding_id == BINDING_ID

    def test_runtime_id(self):
        b = build_binding()
        assert b.runtime_id == RUNTIME_ID

    def test_verified_true_by_default(self):
        b = build_binding()
        assert b.verified is True

    def test_verified_false_when_requested(self):
        b = build_binding(verified=False)
        assert b.verified is False

    def test_approval_policy_default(self):
        b = build_binding()
        assert b.approval_policy == "approval_required"

    def test_approval_policy_custom(self):
        b = build_binding(approval_policy="allowed")
        assert b.approval_policy == "allowed"

    def test_description_nonempty(self):
        b = build_binding()
        assert b.description.strip()

    def test_input_schema_nonempty(self):
        b = build_binding()
        assert len(b.input_schema) > 0

    def test_input_schema_has_source(self):
        b = build_binding()
        names = {f.name for f in b.input_schema}
        assert "source" in names

    def test_input_schema_has_output_dir(self):
        b = build_binding()
        names = {f.name for f in b.input_schema}
        assert "output_dir" in names

    def test_input_schema_has_run_name(self):
        b = build_binding()
        names = {f.name for f in b.input_schema}
        assert "run_name" in names

    def test_input_schema_has_command(self):
        b = build_binding()
        names = {f.name for f in b.input_schema}
        assert "command" in names

    def test_input_schema_command_required(self):
        b = build_binding()
        cmd_field = next(f for f in b.input_schema if f.name == "command")
        assert cmd_field.required is True

    def test_input_schema_source_required(self):
        b = build_binding()
        f = next(field for field in b.input_schema if field.name == "source")
        assert f.required is True

    def test_input_schema_model_not_required(self):
        b = build_binding()
        f = next(field for field in b.input_schema if field.name == "model")
        assert f.required is False

    def test_custom_skill_id(self):
        b = build_binding("my-skill")
        assert b.skill_id == "my-skill"

    def test_custom_binding_id(self):
        b = build_binding(binding_id="custom-binding-v1")
        assert b.binding_id == "custom-binding-v1"


# ── register_binding() ─────────────────────────────────────────────────────


class TestRegisterBinding:
    def test_registers_in_registry(self):
        registry = ExecutionBindingRegistry()
        register_binding(registry)
        found = registry.get_binding(SKILL_ID)
        assert found is not None
        assert found.skill_id == SKILL_ID

    def test_registered_binding_is_verified(self):
        registry = ExecutionBindingRegistry()
        register_binding(registry)
        found = registry.get_binding(SKILL_ID)
        assert found.verified is True

    def test_registered_binding_approval_required(self):
        registry = ExecutionBindingRegistry()
        register_binding(registry)
        found = registry.get_binding(SKILL_ID)
        assert found.approval_policy == "approval_required"

    def test_register_unverified(self):
        registry = ExecutionBindingRegistry()
        register_binding(registry, verified=False)
        found = registry.get_binding(SKILL_ID)
        assert found.verified is False

    def test_register_custom_skill_id(self):
        registry = ExecutionBindingRegistry()
        register_binding(registry, skill_id="yolo-v2")
        found = registry.get_binding("yolo-v2")
        assert found is not None

    def test_register_does_not_affect_other_skills(self):
        registry = ExecutionBindingRegistry()
        register_binding(registry)
        assert registry.get_binding("other-skill") is None


# ── Architecture boundary ──────────────────────────────────────────────────


class TestArchitectureBoundary:
    """
    The binding module MUST NOT import JobExecutor or any JobRuntime subclass
    directly (ADR-0013 §3: only JobExecutor calls runtimes). It also MUST NOT
    import LinuxNvidiaJobRuntime — it is allowed to import only the RUNTIME_ID
    string constant, never the class.
    """

    def test_no_import_job_executor(self):
        """JobExecutor must not be imported — only JobExecutor calls runtimes."""
        import_lines = [
            line for line in
            Path("cv_agent/execution/jobs/runtimes/yolo_inference.py")
            .read_text().splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]
        assert not any("JobExecutor" in line for line in import_lines), (
            "yolo_inference.py must not import JobExecutor — "
            "only JobExecutor calls runtimes (ADR-0013 §3)."
        )

    def test_no_import_linux_nvidia_job_runtime_class(self):
        """Only the RUNTIME_ID constant may be imported, not the class."""
        import_lines = [
            line for line in
            Path("cv_agent/execution/jobs/runtimes/yolo_inference.py")
            .read_text().splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]
        assert not any("LinuxNvidiaJobRuntime" in line for line in import_lines), (
            "yolo_inference.py must not import LinuxNvidiaJobRuntime class — "
            "only the RUNTIME_ID string constant is allowed (ADR-0009 §8)."
        )

    def test_no_import_host_verifier(self):
        """HostVerifier is for JobExecutor pre-flight, not binding modules."""
        import_lines = [
            line for line in
            Path("cv_agent/execution/jobs/runtimes/yolo_inference.py")
            .read_text().splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]
        assert not any("HostVerifier" in line for line in import_lines), (
            "yolo_inference.py must not import any HostVerifier — "
            "host checks are JobExecutor's responsibility (ADR-0013 §3.2)."
        )

    def test_module_has_skill_id(self):
        assert hasattr(yolo_mod, "SKILL_ID")

    def test_module_has_binding_id(self):
        assert hasattr(yolo_mod, "BINDING_ID")

    def test_module_has_runtime_id(self):
        assert hasattr(yolo_mod, "RUNTIME_ID")

    def test_module_has_build_command(self):
        assert callable(yolo_mod.build_command)

    def test_module_has_expected_artifact_paths(self):
        assert callable(yolo_mod.expected_artifact_paths)

    def test_module_has_build_binding(self):
        assert callable(yolo_mod.build_binding)

    def test_module_has_register_binding(self):
        assert callable(yolo_mod.register_binding)


# ── Approval / pin integrity (regression for D-056 malformed-pin bug) ─────────
#
# Root cause (D-056): scripts/run_baseline.py called binding.pin() which returns
# only the binding-level snapshot {"skill_id": ..., "binding_id": ..., ...}.
# pin_is_well_formed() / pin_mismatch() require the FULL execution pin produced
# by registry.pin(skill_id): {"binding": {...}, "runtime_generation": int|None}.
# Using binding.pin() directly caused pin_mismatch() to return
# ("execution_pin_malformed",) and JobExecutor.start_job() to reject with
# status="rejected", category="binding_mismatch".
# Fix: call registry.pin(skill_id), not binding.pin().


@dataclass
class _FakeJobRuntime:
    """Minimal fake runtime — never actually launches a subprocess."""
    runtime_id: str = RUNTIME_ID
    _calls: list = dc_field(default_factory=list, repr=False)

    def start(self, skill: Skill, _request: SkillExecutionRequest) -> JobHandle:
        self._calls.append(skill.skill_id)
        return JobHandle(
            job_id="fake-job-001",
            runtime_id=self.runtime_id,
            started_at="2026-09-29T00:00:00+00:00",
        )

    def poll(self, _handle: JobHandle) -> Literal["running", "completed", "failed", "cancelled"]:
        return "completed"

    def cancel(self, _handle: JobHandle) -> None:
        pass

    def collect(self, _handle: JobHandle) -> JobOutcome:
        return JobOutcome(
            success=True,
            exit_code=0,
            stdout="Speed: 5.2ms preprocess, 12.1ms inference",
            stderr="",
            artifacts={"run_dir": "/tmp/runs/baseline"},
            resources=JobResourceMetadata(wall_time_seconds=3.0),
        )


def _nvidia_profile() -> HostProfile:
    return HostProfile(
        os="linux", gpu_available=True, gpu_vendor="nvidia",
        driver_version="535.309.01", vram_mb=12288,
    )


def _make_executor() -> tuple[JobExecutor, ExecutionBindingRegistry, _FakeJobRuntime]:
    reg = ExecutionBindingRegistry()
    register_binding(reg, skill_id=SKILL_ID, verified=True,
                     approval_policy="approval_required")
    rt = _FakeJobRuntime()
    exec_ = JobExecutor(
        registry=reg,
        job_runtimes={RUNTIME_ID: rt},
        host_verifier=LinuxNvidiaHostVerifier(profile=_nvidia_profile()),
    )
    return exec_, reg, rt


def _approved_skill() -> Skill:
    return Skill(
        skill_id=SKILL_ID,
        name="yolo-inference",
        description="test",
        source="fixture",
        location="/fixture/SKILL.md",
        executable=True,
    )


def _host_req() -> HostRequirement:
    return HostRequirement(os="linux", gpu_vendor="nvidia", min_vram_mb=2048)


class TestApprovalPinIntegrity:
    """
    Regression suite for D-056: binding.pin() vs registry.pin() contract.

    The correct execution pin MUST come from registry.pin(skill_id), NOT from
    binding.pin(). These tests reproduce the observed failure mode and prove the
    corrected path works end-to-end through JobExecutor.start_job().
    """

    # ── Reproduce the bug ──────────────────────────────────────────────────

    def test_binding_pin_alone_is_malformed(self):
        """
        Regression: calling binding.pin() directly returns a binding-only
        snapshot that fails pin_is_well_formed() — it lacks the outer
        {"binding": ..., "runtime_generation": ...} wrapper.
        """
        reg = ExecutionBindingRegistry()
        register_binding(reg)
        binding = reg.get_binding(SKILL_ID)
        assert binding is not None

        raw_binding_pin = binding.pin()
        assert not pin_is_well_formed(raw_binding_pin, skill_id=SKILL_ID), (
            "binding.pin() returned a value that passes pin_is_well_formed() — "
            "that means the wrapper is now part of binding.pin(), and this test "
            "must be updated to reflect the new contract."
        )

    def test_binding_pin_as_request_pin_is_rejected(self):
        """
        Regression: passing binding.pin() as expected_binding_pin to
        start_job() must be rejected with binding_mismatch / execution_pin_malformed.
        This is the exact failure observed in D-056.
        """
        exec_, reg, rt = _make_executor()
        binding = reg.get_binding(SKILL_ID)
        assert binding is not None

        wrong_pin = binding.pin()   # binding-only snapshot, NOT the full pin
        inputs = {**_VALID_INPUTS, "command": build_command(_VALID_INPUTS)}
        handle, result = exec_.start_job(
            _approved_skill(),
            SkillExecutionRequest(
                inputs=inputs,
                approved=True,
                expected_binding_pin=wrong_pin,
            ),
            _host_req(),
        )
        assert handle is None
        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "binding_mismatch"
        assert "execution_pin_malformed" in result.error.message

    # ── Prove the fix ──────────────────────────────────────────────────────

    def test_registry_pin_is_well_formed(self):
        """registry.pin(skill_id) produces a pin that passes pin_is_well_formed()."""
        reg = ExecutionBindingRegistry()
        register_binding(reg)
        pin = reg.pin(SKILL_ID)
        assert pin is not None
        assert pin_is_well_formed(pin, skill_id=SKILL_ID)

    def test_registry_pin_has_correct_outer_keys(self):
        """The execution pin has exactly {"binding", "runtime_generation"} at the top."""
        reg = ExecutionBindingRegistry()
        register_binding(reg)
        pin = reg.pin(SKILL_ID)
        assert pin is not None
        assert set(pin.keys()) == {"binding", "runtime_generation"}

    def test_registry_pin_binding_contains_skill_id(self):
        reg = ExecutionBindingRegistry()
        register_binding(reg)
        pin = reg.pin(SKILL_ID)
        assert pin is not None
        assert pin["binding"]["skill_id"] == SKILL_ID

    def test_registry_pin_runtime_generation_none_for_job_runtime(self):
        """
        LinuxNvidiaJobRuntime is a JobRuntime, not registered in ExecutionBindingRegistry
        _runtimes (which holds ExecutionRuntime objects). So runtime_generation is None.
        The executor reads None from the same registry call → no mismatch.
        """
        reg = ExecutionBindingRegistry()
        register_binding(reg)
        pin = reg.pin(SKILL_ID)
        assert pin is not None
        assert pin["runtime_generation"] is None

    def test_full_approval_path_with_registry_pin_starts_job(self):
        """
        End-to-end: registry.pin() + approved=True must pass all 10 pre-flight
        checks and return status="started".
        """
        exec_, reg, rt = _make_executor()
        pin = reg.pin(SKILL_ID)
        assert pin is not None
        inputs = {**_VALID_INPUTS, "command": build_command(_VALID_INPUTS)}
        handle, result = exec_.start_job(
            _approved_skill(),
            SkillExecutionRequest(
                inputs=inputs,
                approved=True,
                expected_binding_pin=pin,
            ),
            _host_req(),
        )
        assert handle is not None, (
            f"start_job() rejected with: [{result.error and result.error.category}] "
            f"{result.error and result.error.message}"
        )
        assert result.status == "started"
        assert len(rt._calls) == 1
        assert rt._calls[0] == SKILL_ID

    def test_registry_pin_not_approved_is_rejected(self):
        """Correct pin + approved=False → still rejected at step 6."""
        exec_, reg, _ = _make_executor()
        pin = reg.pin(SKILL_ID)
        assert pin is not None
        inputs = {**_VALID_INPUTS, "command": build_command(_VALID_INPUTS)}
        handle, result = exec_.start_job(
            _approved_skill(),
            SkillExecutionRequest(
                inputs=inputs,
                approved=False,
                expected_binding_pin=pin,
            ),
            _host_req(),
        )
        assert handle is None
        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "approval_denied"

    def test_stale_registry_pin_is_rejected(self):
        """
        After re-registering the binding (simulating a change), a pin captured
        before the change is stale and must be rejected.
        """
        exec_, reg, _ = _make_executor()
        stale_pin = reg.pin(SKILL_ID)
        assert stale_pin is not None

        # Simulate binding change: re-register with a different approval_policy.
        from cv_agent.execution.jobs.runtimes.yolo_inference import build_binding
        new_binding = build_binding(approval_policy="allowed")
        reg.register_binding(new_binding)

        inputs = {**_VALID_INPUTS, "command": build_command(_VALID_INPUTS)}
        handle, result = exec_.start_job(
            _approved_skill(),
            SkillExecutionRequest(
                inputs=inputs,
                approved=True,
                expected_binding_pin=stale_pin,
            ),
            _host_req(),
        )
        assert handle is None
        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "binding_mismatch"
        assert "binding.approval_policy" in result.error.message

    def test_e1_rule_no_pin_approval_required_rejected(self):
        """approved=True without any pin is refused by E1 rule."""
        exec_, reg, _ = _make_executor()
        inputs = {**_VALID_INPUTS, "command": build_command(_VALID_INPUTS)}
        handle, result = exec_.start_job(
            _approved_skill(),
            SkillExecutionRequest(
                inputs=inputs,
                approved=True,
                expected_binding_pin=None,
            ),
            _host_req(),
        )
        assert handle is None
        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "approval_denied"


# ── Real inference integration test ────────────────────────────────────────
# Skipped in CI: requires a committed video fixture AND GPU capability.
# To run manually: pytest tests/test_yolo_inference_binding.py::TestRealInference
# with a real video fixture path in VIDEO_FIXTURE_PATH.

_VIDEO_FIXTURE = Path("tests/fixtures/person_detection_sample.mp4")
_YOLO_BIN = Path("/home/dev/.local/bin/yolo")

_skip_no_fixture = pytest.mark.skipif(
    not _VIDEO_FIXTURE.exists(),
    reason=(
        "STOP: No committed video fixture in repository. "
        f"Expected: {_VIDEO_FIXTURE}. "
        "Required before the real inference integration test can execute. "
        "External videos at /home/dev/Videos/ and /home/dev/Downloads/ are "
        "NOT repository assets and MUST NOT be used as test inputs (Task 3 requirement). "
        "Add a short (~5s), royalty-free, committed video fixture to tests/fixtures/ first."
    ),
)

_skip_no_yolo = pytest.mark.skipif(
    not _YOLO_BIN.exists(),
    reason=f"yolo CLI not found at {_YOLO_BIN}",
)


@_skip_no_fixture
@_skip_no_yolo
class TestRealInference:
    """
    Real subprocess integration test. Only runs when BOTH conditions are met:
      1. tests/fixtures/person_detection_sample.mp4 is committed in the repo.
      2. The yolo CLI is installed at /home/dev/.local/bin/yolo.

    GPU inference is NOT required — yolo falls back to CPU automatically.
    Expected runtime: <60s for a 5s fixture on CPU (yolo11n is fast on CPU).

    Known blocker: RTX 3060 present but driver 12.2 < torch requirement
    of CUDA 13.0+ → torch.cuda.is_available() returns False → CPU fallback.
    GPU inference (1.5 ms/frame from D-053 evidence) is not achievable until
    the CUDA compatibility gap is resolved.
    """

    def test_real_inference_cpu(self, tmp_path):
        """Build command with device=cpu, run as subprocess, check exit code."""
        inputs = {
            "source": str(_VIDEO_FIXTURE.absolute()),
            "output_dir": str(tmp_path),
            "run_name": "integration_test",
            "model": str(Path(".cv_agent/models/yolo11n.pt").absolute()),
            "device": "cpu",
            "yolo_executable": str(_YOLO_BIN),
        }
        cmd = build_command(inputs)
        # inject command into inputs for reference (not passed to subprocess directly)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"yolo track exited {result.returncode}.\n"
            f"stdout: {result.stdout[:500]}\n"
            f"stderr: {result.stderr[:500]}"
        )
        paths = expected_artifact_paths(inputs)
        run_dir = Path(paths["annotated_video_dir"])
        assert run_dir.exists(), f"Output dir {run_dir} was not created."
        labels_dir = Path(paths["tracking_labels_dir"])
        assert labels_dir.exists(), f"Labels dir {labels_dir} was not created."

    def test_invalid_source_nonzero_exit(self, tmp_path):
        """Confirm CLI returns non-zero exit code when source does not exist."""
        inputs = {
            "source": str(tmp_path / "does_not_exist.mp4"),
            "output_dir": str(tmp_path),
            "run_name": "invalid_test",
            "device": "cpu",
            "yolo_executable": str(_YOLO_BIN),
        }
        cmd = build_command(inputs)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0, (
            "Expected non-zero exit code for invalid source; got 0."
        )
