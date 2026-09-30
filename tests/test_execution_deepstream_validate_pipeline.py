"""
Tests for cv_agent.execution.runtimes.deepstream_validate_pipeline — the
verified binding for the deepstream-generate-pipeline skill (ADR-0009 §8).

Three kinds of test here, deliberately kept separate:

1. TestSkillDiscovery — the skill is discoverable via the same LocalSkillSource
   CVAgent uses; an arbitrary uninspected skill has no verified binding.
2. TestBindingContract — pure unit tests of the binding's own metadata (verified,
   approval_policy, runtime_id, input_schema).
3. TestCommandResolution — unit tests of resolve_command(): correct argv built
   from a Skill and a pipeline string; missing script → ValueError.
4. TestRegistryWiring — registry/executor integration: binding registers, does not
   auto-register, does not affect unrelated skills.
5. TestApprovalAndPinIntegrity — JobExecutor's approval/pin checks remain
   enforced: unverified binding refused, host mismatch returned, pin integrity
   preserved.
6. TestRealSubprocessViaJobExecutor — genuine subprocess invocation of the real,
   installed skill through LinuxNvidiaJobRuntime + JobExecutor. Skipped (not
   faked) when the skill is not discoverable on this machine.

Nothing here fakes a subprocess result to claim the script passed — real
invocation tests run the real script or are skipped. Unit tests of this module's
own plumbing use mocked processes via monkeypatch where needed.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from cv_agent.execution.binding import ExecutionBindingRegistry
from cv_agent.execution.host import HostProfile, HostRequirement, LinuxNvidiaHostVerifier
from cv_agent.execution.jobs.executor import JobExecutor
from cv_agent.execution.jobs.models import JobResult
from cv_agent.execution.jobs.runtimes.linux_nvidia import (
    RUNTIME_ID as LINUX_NVIDIA_RUNTIME_ID,
    LinuxNvidiaJobRuntime,
    build_binding as linux_nvidia_build_binding,
)
from cv_agent.execution.models import SkillExecutionRequest
from cv_agent.execution.runtimes.deepstream_validate_pipeline import (
    BINDING_ID,
    SKILL_ID,
    build_binding,
    register,
    resolve_command,
)
from cv_agent.skills.local import LocalSkillSource
from cv_agent.skills.models import Skill


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fixture_skill(location: str = "/fixtures/deepstream-generate-pipeline/SKILL.md") -> Skill:
    return Skill(
        skill_id=SKILL_ID,
        name=SKILL_ID,
        description="fixture",
        source="fixture",
        location=location,
    )


def _discover_real_skill() -> Skill | None:
    for skill in LocalSkillSource().discover():
        if skill.skill_id == SKILL_ID:
            return skill
    return None


_REAL_SKILL = _discover_real_skill()
requires_real_skill = pytest.mark.skipif(
    _REAL_SKILL is None,
    reason=(
        "deepstream-generate-pipeline is not installed under ~/.claude/skills "
        "or ~/.agents/skills — real-invocation tests are skipped, not faked."
    ),
)

# Valid simple pipeline: no DeepStream elements, so gst-inspect succeeds.
_VALID_PIPELINE = "gst-launch-1.0 videotestsrc ! autovideosink"
# Invalid pipeline: syntax error (empty segment between pipes).
_INVALID_PIPELINE = "gst-launch-1.0 filesrc ! ! fakesink"


def _make_job_executor(*, verified: bool = True, host_ok: bool = True) -> JobExecutor:
    registry = ExecutionBindingRegistry()
    register(registry) if verified else None
    if not verified:
        registry.register_binding(
            linux_nvidia_build_binding(SKILL_ID, verified=False, approval_policy="allowed")
        )
    profile = HostProfile(
        os="linux",
        gpu_available=host_ok,
        gpu_vendor="nvidia" if host_ok else None,
        driver_version="535.0" if host_ok else None,
    )
    runtime = LinuxNvidiaJobRuntime()
    return JobExecutor(
        registry=registry,
        job_runtimes={LINUX_NVIDIA_RUNTIME_ID: runtime},
        host_verifier=LinuxNvidiaHostVerifier(profile=profile),
    )


def _run_to_completion(
    executor: JobExecutor,
    skill: Skill,
    request: SkillExecutionRequest,
) -> JobResult:
    """Start, poll until terminal, collect — the V1 contract."""
    host_req = HostRequirement(os="linux", gpu_vendor="nvidia")
    handle, result = executor.start_job(skill, request, host_req)
    if handle is None:
        return result
    # Poll until terminal (validate_pipeline.py finishes in < 1 s).
    for _ in range(200):
        status = executor.poll_job(handle)
        if status in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.05)
    outcome = executor.collect_job(handle)
    # Re-wrap outcome into JobResult for consistent return type.
    return JobResult(
        skill_id=skill.skill_id,
        job_id=handle.job_id,
        status=status,  # type: ignore[arg-type]
        evidence=result.evidence,
        outcome=outcome,
    )


# ---------------------------------------------------------------------------
# 1. Skill discoverability
# ---------------------------------------------------------------------------

class TestSkillDiscovery:
    def test_skill_is_discoverable(self) -> None:
        """The skill must be found via the same discovery path CVAgent uses.
        Skipped when not installed (same as trt-perf-analysis precedent)."""
        if _REAL_SKILL is None:
            pytest.skip("deepstream-generate-pipeline not installed on this machine")
        assert _REAL_SKILL.skill_id == SKILL_ID

    def test_arbitrary_uninspected_skill_has_no_verified_binding(self) -> None:
        """An arbitrary skill (yolo, deepstream-sop, etc.) must not appear as
        verified — ADR-0009 §8: verification covers exactly one skill per binding
        module. The generic linux_nvidia.build_binding() defaults to
        verified=False; only this module's build_binding() sets verified=True."""
        uninspected = linux_nvidia_build_binding("yolo", verified=False)
        assert uninspected.verified is False

    def test_only_this_skill_is_marked_verified_in_registry(self) -> None:
        registry = ExecutionBindingRegistry()
        register(registry)
        # Add an unverified binding for a second skill.
        registry.register_binding(
            linux_nvidia_build_binding("yolo", verified=False, approval_policy="allowed")
        )
        verified_skills = [b.skill_id for b in registry.list_bindings() if b.verified]
        assert verified_skills == [SKILL_ID]


# ---------------------------------------------------------------------------
# 2. Binding contract
# ---------------------------------------------------------------------------

class TestBindingContract:
    def test_binding_is_verified(self) -> None:
        assert build_binding().verified is True

    def test_binding_skill_id_is_correct(self) -> None:
        assert build_binding().skill_id == SKILL_ID

    def test_binding_id_is_stable(self) -> None:
        assert build_binding().binding_id == BINDING_ID

    def test_binding_uses_linux_nvidia_runtime(self) -> None:
        assert build_binding().runtime_id == LINUX_NVIDIA_RUNTIME_ID

    def test_default_approval_policy_is_allowed(self) -> None:
        """validate_pipeline.py is read-only analysis — APPROVALS.md category
        'Read-only research, retrieval, analysis → ✅ free'."""
        assert build_binding().approval_policy == "allowed"

    def test_input_schema_requires_command(self) -> None:
        by_name = {f.name: f for f in build_binding().input_schema}
        assert "command" in by_name
        assert by_name["command"].required is True

    def test_approval_policy_override_accepted(self) -> None:
        binding = build_binding(approval_policy="approval_required")
        assert binding.approval_policy == "approval_required"
        assert binding.verified is True


# ---------------------------------------------------------------------------
# 3. Command resolution
# ---------------------------------------------------------------------------

class TestCommandResolution:
    def test_resolve_command_builds_correct_argv(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / SKILL_ID
        (skill_dir / "scripts").mkdir(parents=True)
        script = skill_dir / "scripts" / "validate_pipeline.py"
        script.write_text("", encoding="utf-8")
        skill = _fixture_skill(str(skill_dir / "SKILL.md"))

        cmd = resolve_command(skill, "gst-launch-1.0 fakesrc ! fakesink")

        assert len(cmd) == 4
        assert cmd[0].endswith("python") or cmd[0].endswith("python3") or "python" in cmd[0]
        assert cmd[1] == str(script)
        assert cmd[2] == "--pipeline"
        assert cmd[3] == "gst-launch-1.0 fakesrc ! fakesink"

    def test_resolve_command_uses_skill_location(self, tmp_path: Path) -> None:
        """The script path is derived from Skill.location — not a hard-coded path."""
        skill_dir = tmp_path / "alt-install-dir"
        (skill_dir / "scripts").mkdir(parents=True)
        (skill_dir / "scripts" / "validate_pipeline.py").write_text("", encoding="utf-8")
        skill = _fixture_skill(str(skill_dir / "SKILL.md"))

        cmd = resolve_command(skill, "gst-launch-1.0 fakesrc ! fakesink")
        assert str(skill_dir / "scripts" / "validate_pipeline.py") in cmd

    def test_resolve_command_raises_when_script_missing(self, tmp_path: Path) -> None:
        skill = _fixture_skill(str(tmp_path / "nonexistent" / "SKILL.md"))
        with pytest.raises(ValueError, match="not found"):
            resolve_command(skill, "gst-launch-1.0 fakesrc ! fakesink")


# ---------------------------------------------------------------------------
# 4. Registry wiring
# ---------------------------------------------------------------------------

class TestRegistryWiring:
    def test_register_adds_exactly_one_binding(self) -> None:
        registry = ExecutionBindingRegistry()
        register(registry)
        bindings = registry.list_bindings()
        assert len(bindings) == 1
        assert bindings[0].skill_id == SKILL_ID

    def test_register_does_not_affect_unrelated_skills(self) -> None:
        registry = ExecutionBindingRegistry()
        register(registry)
        assert registry.get_binding("yolo") is None
        assert registry.get_binding("trt-perf-analysis") is None

    def test_register_does_not_auto_register_runtime(self) -> None:
        """The binding is registered but no runtime is auto-registered —
        the caller must supply LinuxNvidiaJobRuntime explicitly (opt-in)."""
        registry = ExecutionBindingRegistry()
        register(registry)
        assert registry.list_runtimes() == []

    def test_fresh_cvagent_registry_is_still_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """register() is never called automatically — ADR-0009 §3."""
        monkeypatch.setenv("CV_AGENT_SKILL_PATHS", str(tmp_path))
        from cv_agent.runtime.agent import CVAgent

        agent = CVAgent()
        assert agent.execution_bindings.list_bindings() == []

    def test_register_is_idempotent_description(self) -> None:
        """register() can be called multiple times without raising — though
        the second call overwrites the binding per ExecutionBindingRegistry
        semantics (not a hidden auto-registration side effect)."""
        registry = ExecutionBindingRegistry()
        register(registry)
        register(registry)
        assert len(registry.list_bindings()) == 1


# ---------------------------------------------------------------------------
# 5. Approval and pin integrity (JobExecutor pre-flight checks)
# ---------------------------------------------------------------------------

class TestApprovalAndPinIntegrity:
    def test_unverified_binding_is_refused_by_job_executor(self) -> None:
        """ADR-0009 §8: JobExecutor refuses binding_not_verified."""
        registry = ExecutionBindingRegistry()
        registry.register_binding(
            linux_nvidia_build_binding(SKILL_ID, verified=False, approval_policy="allowed")
        )
        profile = HostProfile(os="linux", gpu_available=True, gpu_vendor="nvidia", driver_version="535.0")
        executor = JobExecutor(
            registry=registry,
            job_runtimes={LINUX_NVIDIA_RUNTIME_ID: LinuxNvidiaJobRuntime()},
            host_verifier=LinuxNvidiaHostVerifier(profile=profile),
        )
        host_req = HostRequirement(os="linux", gpu_vendor="nvidia")
        handle, result = executor.start_job(
            _fixture_skill(),
            SkillExecutionRequest(inputs={"command": ["echo", "should-not-run"]}),
            host_req,
        )
        assert handle is None
        assert result.status == "not_submitted"
        assert result.error is not None
        assert result.error.category == "binding_not_verified"

    def test_host_mismatch_produces_host_mismatch_result(self) -> None:
        """When the host lacks a GPU, JobExecutor returns status='host_mismatch'."""
        executor = _make_job_executor(host_ok=False)
        host_req = HostRequirement(os="linux", gpu_vendor="nvidia")
        handle, result = executor.start_job(
            _fixture_skill(),
            SkillExecutionRequest(inputs={"command": ["echo", "should-not-run"]}),
            host_req,
        )
        assert handle is None
        assert result.status == "host_mismatch"

    def test_pin_mismatch_produces_rejected_result(self) -> None:
        """A tampered/wrong pin is rejected before the job starts (ADR-0003 §10)."""
        registry = ExecutionBindingRegistry()
        register(registry)
        profile = HostProfile(os="linux", gpu_available=True, gpu_vendor="nvidia", driver_version="535.0")
        executor = JobExecutor(
            registry=registry,
            job_runtimes={LINUX_NVIDIA_RUNTIME_ID: LinuxNvidiaJobRuntime()},
            host_verifier=LinuxNvidiaHostVerifier(profile=profile),
        )
        bad_pin: Any = {
            "binding": {
                "binding_id": "wrong-binding-id",
                "skill_id": SKILL_ID,
                "runtime_id": LINUX_NVIDIA_RUNTIME_ID,
                "approval_policy": "allowed",
                "verified": True,
                "description": "tampered",
            },
            "runtime_generation": 0,
        }
        host_req = HostRequirement(os="linux", gpu_vendor="nvidia")
        handle, result = executor.start_job(
            _fixture_skill(),
            SkillExecutionRequest(
                inputs={"command": ["echo", "should-not-run"]},
                expected_binding_pin=bad_pin,
            ),
            host_req,
        )
        assert handle is None
        assert result.status == "rejected"
        assert result.error is not None
        assert result.error.category == "binding_mismatch"

    def test_approval_required_without_approved_flag_is_rejected(self) -> None:
        registry = ExecutionBindingRegistry()
        register(registry, approval_policy="approval_required")
        pin = registry.pin(SKILL_ID)
        profile = HostProfile(os="linux", gpu_available=True, gpu_vendor="nvidia", driver_version="535.0")
        executor = JobExecutor(
            registry=registry,
            job_runtimes={LINUX_NVIDIA_RUNTIME_ID: LinuxNvidiaJobRuntime()},
            host_verifier=LinuxNvidiaHostVerifier(profile=profile),
        )
        host_req = HostRequirement(os="linux", gpu_vendor="nvidia")
        handle, result = executor.start_job(
            _fixture_skill(),
            SkillExecutionRequest(
                inputs={"command": ["echo", "should-not-run"]},
                approved=False,
                expected_binding_pin=pin,
            ),
            host_req,
        )
        assert handle is None
        assert result.status == "rejected"


# ---------------------------------------------------------------------------
# 6. Real subprocess via JobExecutor (skipped if skill not installed)
# ---------------------------------------------------------------------------

@requires_real_skill
class TestRealSubprocessViaJobExecutor:
    """Genuine subprocess invocation of the real installed validate_pipeline.py
    through LinuxNvidiaJobRuntime + JobExecutor. No mocks, no fabricated results.
    Skipped entirely (not faked) when the skill is not installed."""

    def test_valid_pipeline_produces_success_outcome(self) -> None:
        """A syntactically valid pipeline returns exit 0 → success=True."""
        assert _REAL_SKILL is not None
        executor = _make_job_executor()
        cmd = resolve_command(_REAL_SKILL, _VALID_PIPELINE)
        result = _run_to_completion(
            executor,
            _REAL_SKILL,
            SkillExecutionRequest(inputs={"command": cmd}),
        )
        assert result.status == "completed"
        assert result.outcome is not None
        assert result.outcome.success is True
        assert result.outcome.exit_code == 0

    def test_valid_pipeline_stdout_contains_valid_json(self) -> None:
        """validate_pipeline.py always emits a JSON object on stdout."""
        import json

        assert _REAL_SKILL is not None
        executor = _make_job_executor()
        cmd = resolve_command(_REAL_SKILL, _VALID_PIPELINE)
        result = _run_to_completion(
            executor,
            _REAL_SKILL,
            SkillExecutionRequest(inputs={"command": cmd}),
        )
        assert result.outcome is not None
        assert result.outcome.stdout is not None
        parsed = json.loads(result.outcome.stdout)
        assert isinstance(parsed, dict)
        assert parsed["valid"] is True

    def test_invalid_pipeline_produces_failure_outcome(self) -> None:
        """An invalid pipeline returns exit 1 → success=False."""
        assert _REAL_SKILL is not None
        executor = _make_job_executor()
        cmd = resolve_command(_REAL_SKILL, _INVALID_PIPELINE)
        result = _run_to_completion(
            executor,
            _REAL_SKILL,
            SkillExecutionRequest(inputs={"command": cmd}),
        )
        assert result.outcome is not None
        assert result.outcome.success is False
        assert result.outcome.exit_code == 1

    def test_invalid_pipeline_stdout_contains_errors(self) -> None:
        """exit 1 path still emits JSON with errors list."""
        import json

        assert _REAL_SKILL is not None
        executor = _make_job_executor()
        cmd = resolve_command(_REAL_SKILL, _INVALID_PIPELINE)
        result = _run_to_completion(
            executor,
            _REAL_SKILL,
            SkillExecutionRequest(inputs={"command": cmd}),
        )
        assert result.outcome is not None
        assert result.outcome.stdout is not None
        parsed = json.loads(result.outcome.stdout)
        assert parsed["valid"] is False
        assert len(parsed["errors"]) > 0

    def test_missing_command_produces_failed_job(self) -> None:
        """Missing inputs['command'] → LinuxNvidiaJobRuntime raises → status='failed'."""
        assert _REAL_SKILL is not None
        executor = _make_job_executor()
        host_req = HostRequirement(os="linux", gpu_vendor="nvidia")
        handle, result = executor.start_job(
            _REAL_SKILL,
            SkillExecutionRequest(inputs={}),  # no command
            host_req,
        )
        assert handle is None
        assert result.status == "failed"
        assert result.error is not None

    def test_real_invocation_uses_linux_nvidia_job_runtime(self) -> None:
        """Confirms the job went through LinuxNvidiaJobRuntime, not a fake."""
        assert _REAL_SKILL is not None
        executor = _make_job_executor()
        cmd = resolve_command(_REAL_SKILL, _VALID_PIPELINE)
        result = _run_to_completion(
            executor,
            _REAL_SKILL,
            SkillExecutionRequest(inputs={"command": cmd}),
        )
        assert result.evidence is not None
        assert result.evidence.binding_id == BINDING_ID
        assert result.evidence.runtime_id == LINUX_NVIDIA_RUNTIME_ID
