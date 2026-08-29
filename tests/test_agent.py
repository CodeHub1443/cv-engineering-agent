"""Focused behavioral tests for the top-level CVAgent."""

from __future__ import annotations

from cv_agent.runtime.agent import CVAgent


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
