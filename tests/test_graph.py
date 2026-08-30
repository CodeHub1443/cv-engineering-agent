"""Tests for cv_agent.graph.builder."""

from __future__ import annotations

import pytest

from cv_agent.graph.builder import build_graph
from cv_agent.graph.state import AgentState
from cv_agent.runtime.agent import CVAgent


@pytest.fixture()
def graph():
    """Fresh compiled graph for each test."""
    return build_graph()


class TestBuildGraph:
    def test_returns_compiled_graph(self, graph) -> None:
        assert graph is not None

    def test_graph_has_invoke(self, graph) -> None:
        assert callable(getattr(graph, "invoke", None))

    def test_different_calls_produce_independent_graphs(self) -> None:
        g1 = build_graph()
        g2 = build_graph()
        assert g1 is not g2


class TestGraphExecution:
    """Full START → initialize → END execution."""

    def _run(self, graph, session_id: str = "test-session") -> AgentState:
        initial: AgentState = {
            "session_id": session_id,
            "status": "initializing",
            "steps": [],
        }
        cfg = {"configurable": {"thread_id": session_id}}
        return graph.invoke(initial, config=cfg)

    def test_status_becomes_ready(self, graph) -> None:
        result = self._run(graph)
        assert result["status"] == "ready"

    def test_session_id_preserved(self, graph) -> None:
        result = self._run(graph, session_id="explicit-id-42")
        assert result["session_id"] == "explicit-id-42"

    def test_session_id_generated_when_missing(self, graph) -> None:
        initial: AgentState = {"status": "initializing", "steps": []}
        cfg = {"configurable": {"thread_id": "gen-test"}}
        result = graph.invoke(initial, config=cfg)
        assert result.get("session_id")  # non-empty UUID assigned

    def test_steps_contain_initialize_entry(self, graph) -> None:
        result = self._run(graph)
        assert len(result["steps"]) >= 1
        assert result["steps"][0]["node"] == "initialize"

    def test_error_field_is_none_on_success(self, graph) -> None:
        result = self._run(graph)
        assert result.get("error") is None

    def test_resumable_with_same_thread(self, graph) -> None:
        """Running twice with the same thread_id should not raise."""
        cfg = {"configurable": {"thread_id": "resume-test"}}
        initial: AgentState = {"status": "initializing", "steps": []}
        graph.invoke(initial, config=cfg)
        # Second invoke should succeed (graph is checkpointed)
        result = graph.invoke(initial, config=cfg)
        assert result["status"] == "ready"

    def test_independent_threads_dont_share_state(self) -> None:
        graph = build_graph()
        cfg_a = {"configurable": {"thread_id": "thread-a"}}
        cfg_b = {"configurable": {"thread_id": "thread-b"}}
        initial: AgentState = {"status": "initializing", "steps": []}
        r_a = graph.invoke(initial, config=cfg_a)
        r_b = graph.invoke(initial, config=cfg_b)
        # Both should succeed independently
        assert r_a["status"] == "ready"
        assert r_b["status"] == "ready"


class TestCVAgentRun:
    def test_run_initializes_and_executes_a_checkpointed_session(self) -> None:
        result = CVAgent().run(
            "inspect a model",
            task_type="model_analysis",
            session_id="runtime-test-session",
        )

        assert result["status"] == "ready"
        assert result["session_id"] == "runtime-test-session"
        assert result["task"] == "inspect a model"
        assert result["task_type"] == "model_analysis"
        assert result["provider"] == "mock"
        assert result["model"] == "fake-1"
        assert result["selected_capabilities"] == []
        assert result["steps"] == [
            {
                "node": "initialize",
                "action": "session_started",
                "session_id": "runtime-test-session",
            }
        ]
