"""Focused behavioral tests for the top-level CVAgent."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


def _write_skill(root: Path, skill_id: str) -> None:
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill_id}\ndescription: fixture skill.\n---\nbody\n",
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
