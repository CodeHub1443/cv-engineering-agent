"""Focused behavioral tests for the top-level CVAgent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from cv_agent.config.settings import AgentConfig
from cv_agent.execution.binding import ExecutionBinding
from cv_agent.execution.models import RuntimeOutcome, SkillExecutionRequest
from cv_agent.runtime.agent import CVAgent
from cv_agent.skills.models import Skill


def test_cvagent_run_completes_with_mock_provider() -> None:
    agent = CVAgent()
    result = agent.run("smoke test", task_type="planning")

    assert result["session_id"]
    assert result["status"] == "ready"
    assert result["provider"] == "mock"
    assert result["model"] == "fake-1"
    assert result["error"] is None


def test_cvagent_run_preserves_explicit_session_id() -> None:
    agent = CVAgent()
    result = agent.run("smoke test", session_id="session-123")

    assert result["session_id"] == "session-123"


@dataclass
class _FakeRuntime:
    """Minimal fake ExecutionRuntime for CVAgent-level executable-status
    wiring tests — never touches a real skill or subprocess."""

    runtime_id: str = "fake-runtime"

    def invoke(self, skill: Skill, request: SkillExecutionRequest) -> RuntimeOutcome:
        return RuntimeOutcome(success=True, output={"ok": True})


def _write_skill(root: Path, skill_id: str, description: str = "fixture skill.") -> None:
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill_id}\ndescription: {description}\n---\nbody\n",
        encoding="utf-8",
    )


class TestExecutableStatusWiring:
    """ADR-0007 §9 / ADR-0009 §10: CVAgent is the application-layer point
    that connects skill discovery to the real execution registry — proves
    the wiring end to end, not just at the SkillInventory/TaskResolver
    unit level already covered in tests/test_skills.py."""

    def test_fresh_agent_reports_discovered_skill_as_not_executable(
        self, tmp_path: Path
    ) -> None:
        _write_skill(tmp_path, "fixture-skill")
        agent = CVAgent(AgentConfig(skill_paths=(tmp_path,)))

        assert agent.execution_bindings.list_bindings() == []
        skill = agent.skills.get("fixture-skill")
        assert skill is not None
        assert skill.executable is False

    def test_verified_registered_binding_makes_the_skill_executable(
        self, tmp_path: Path
    ) -> None:
        _write_skill(tmp_path, "fixture-skill")
        agent = CVAgent(AgentConfig(skill_paths=(tmp_path,)))

        agent.execution_bindings.register_runtime(_FakeRuntime())
        agent.execution_bindings.register_binding(
            ExecutionBinding(
                skill_id="fixture-skill",
                binding_id="fixture-skill-fake-v1",
                runtime_id="fake-runtime",
                approval_policy="allowed",
                verified=True,
            )
        )

        skill = agent.skills.get("fixture-skill")
        assert skill is not None
        assert skill.executable is True

    def test_unverified_binding_does_not_make_the_skill_executable(
        self, tmp_path: Path
    ) -> None:
        """A declared-but-unverified binding must never be treated as
        evidence the skill actually works (ADR-0009 §3: SkillExecutor
        treats verified=False the same as no binding at all)."""
        _write_skill(tmp_path, "fixture-skill")
        agent = CVAgent(AgentConfig(skill_paths=(tmp_path,)))

        agent.execution_bindings.register_runtime(_FakeRuntime())
        agent.execution_bindings.register_binding(
            ExecutionBinding(
                skill_id="fixture-skill",
                binding_id="fixture-skill-fake-v1",
                runtime_id="fake-runtime",
                approval_policy="allowed",
                verified=False,
            )
        )

        skill = agent.skills.get("fixture-skill")
        assert skill is not None
        assert skill.executable is False

    def test_resolve_reflects_the_same_live_executable_status(
        self, tmp_path: Path
    ) -> None:
        """The same wiring must be visible through resolve(), not only
        through skills.get() — both read the same SkillInventory. Uses a
        skill_id/description/query combination already proven (in
        tests/test_skills.py) to survive TaskResolver's capability-match
        gate, since resolve() only matches skills after matching at least
        one real capability first."""
        skill_dir = tmp_path / "cuda-agent"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: cuda-agent\ndescription: CUDA kernel optimization expert.\n---\n",
            encoding="utf-8",
        )
        agent = CVAgent(AgentConfig(skill_paths=(tmp_path,)))
        agent.execution_bindings.register_runtime(_FakeRuntime())
        agent.execution_bindings.register_binding(
            ExecutionBinding(
                skill_id="cuda-agent",
                binding_id="cuda-agent-fake-v1",
                runtime_id="fake-runtime",
                approval_policy="allowed",
                verified=True,
            )
        )

        result = agent.resolve("optimize deployment for jetson using cuda kernels")
        match = next((m for m in result.matched_skills if m.skill_id == "cuda-agent"), None)
        assert match is not None
        assert match.executable is True


_TRT_PERF_REQUEST = (
    "Detect people and evaluate deployment optimization performance benchmarking "
    "of the model."
)
_TRT_PERF_DESCRIPTION = "TensorRT performance benchmarking and layer analysis tool."


class TestRequirementsAnalysisSkillLinks:
    """
    ADR-0008 §9: CVAgent.analyze_requirements() surfaces skill_links with
    live executable status end to end — the exact acceptance scenario the
    task specified: fresh agent -> register a verified binding -> analyze
    -> the matched skill's executable flag reflects that registration,
    and reverts to False without it. Uses a fixture 'trt-perf-analysis'
    skill (portable, no machine dependency) plus _FakeRuntime, mirroring
    TestExecutableStatusWiring above; a genuine end-to-end test against
    the real installed skill follows in TestRealTrtPerfAnalysisSkillLink.
    """

    def test_matched_skill_is_executable_after_registering_a_verified_binding(
        self, tmp_path: Path
    ) -> None:
        _write_skill(tmp_path, "trt-perf-analysis", _TRT_PERF_DESCRIPTION)
        agent = CVAgent(AgentConfig(skill_paths=(tmp_path,)))

        agent.execution_bindings.register_runtime(_FakeRuntime())
        agent.execution_bindings.register_binding(
            ExecutionBinding(
                skill_id="trt-perf-analysis",
                binding_id="trt-perf-analysis-fake-v1",
                runtime_id="fake-runtime",
                approval_policy="allowed",
                verified=True,
            )
        )

        analysis = agent.analyze_requirements(_TRT_PERF_REQUEST)

        trt_links = [link for link in analysis.skill_links if link.skill_id == "trt-perf-analysis"]
        assert len(trt_links) == 1
        assert trt_links[0].executable is True

    def test_same_matched_skill_is_not_executable_without_registration(
        self, tmp_path: Path
    ) -> None:
        """Same discovered skill, same request, fresh CVAgent with no
        binding registered — the matched skill must still be present
        (discovery is unaffected) but reported as not executable."""
        _write_skill(tmp_path, "trt-perf-analysis", _TRT_PERF_DESCRIPTION)
        agent = CVAgent(AgentConfig(skill_paths=(tmp_path,)))

        analysis = agent.analyze_requirements(_TRT_PERF_REQUEST)

        trt_links = [link for link in analysis.skill_links if link.skill_id == "trt-perf-analysis"]
        assert len(trt_links) == 1
        assert trt_links[0].executable is False

    def test_unverified_binding_does_not_make_the_matched_skill_executable(
        self, tmp_path: Path
    ) -> None:
        _write_skill(tmp_path, "trt-perf-analysis", _TRT_PERF_DESCRIPTION)
        agent = CVAgent(AgentConfig(skill_paths=(tmp_path,)))

        agent.execution_bindings.register_runtime(_FakeRuntime())
        agent.execution_bindings.register_binding(
            ExecutionBinding(
                skill_id="trt-perf-analysis",
                binding_id="trt-perf-analysis-fake-v1",
                runtime_id="fake-runtime",
                approval_policy="allowed",
                verified=False,
            )
        )

        analysis = agent.analyze_requirements(_TRT_PERF_REQUEST)

        trt_links = [link for link in analysis.skill_links if link.skill_id == "trt-perf-analysis"]
        assert len(trt_links) == 1
        assert trt_links[0].executable is False


def _real_trt_perf_analysis_discovered() -> bool:
    from cv_agent.skills.local import LocalSkillSource

    return any(s.skill_id == "trt-perf-analysis" for s in LocalSkillSource().discover())


_requires_real_trt_perf_analysis = pytest.mark.skipif(
    not _real_trt_perf_analysis_discovered(),
    reason="trt-perf-analysis is not installed under ~/.claude/skills or "
    "~/.agents/skills on this machine — real skill_links integration test "
    "is skipped, not faked.",
)


class TestRealTrtPerfAnalysisSkillLink:
    """
    Genuine end-to-end version of the same acceptance scenario against the
    real, installed trt-perf-analysis skill and its real, shipped
    ExecutionBinding (cv_agent.execution.runtimes.trt_perf_analysis) —
    not faked. Skipped (not faked) when the skill isn't discoverable in
    this environment, mirroring tests/test_cli_execute.py's convention.
    """

    @_requires_real_trt_perf_analysis
    def test_real_skill_becomes_executable_after_real_registration(self) -> None:
        from cv_agent.execution.runtimes.trt_perf_analysis import register

        agent = CVAgent()
        before = agent.analyze_requirements(_TRT_PERF_REQUEST)
        before_links = [link for link in before.skill_links if link.skill_id == "trt-perf-analysis"]
        assert len(before_links) == 1
        assert before_links[0].executable is False

        register(agent.execution_bindings)
        after = agent.analyze_requirements(_TRT_PERF_REQUEST)
        after_links = [link for link in after.skill_links if link.skill_id == "trt-perf-analysis"]
        assert len(after_links) == 1
        assert after_links[0].executable is True
