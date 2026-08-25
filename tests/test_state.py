"""Tests for cv_agent.graph.state."""

from __future__ import annotations

from cv_agent.graph.state import AgentState


class TestAgentState:
    """AgentState is a TypedDict(total=False) — all keys are optional."""

    def test_empty_state_is_valid(self) -> None:
        state: AgentState = {}
        assert state.get("status") is None
        assert state.get("session_id") is None

    def test_partial_state_with_status(self) -> None:
        state: AgentState = {"status": "ready"}
        assert state["status"] == "ready"

    def test_full_state_construction(self) -> None:
        state: AgentState = {
            "session_id": "abc-123",
            "status": "running",
            "error": None,
            "task": "train YOLOv10 on custom dataset",
            "task_type": "model_training",
            "provider": "mock",
            "model": "fake-1",
            "selected_capabilities": ["cv.training.design"],
            "steps": [{"node": "initialize", "action": "session_started"}],
            "pending_human_input": None,
            "human_feedback": None,
        }
        assert state["session_id"] == "abc-123"
        assert state["task_type"] == "model_training"
        assert len(state["selected_capabilities"]) == 1
        assert len(state["steps"]) == 1

    def test_steps_list_is_mutable(self) -> None:
        state: AgentState = {"steps": []}
        state["steps"].append({"node": "initialize"})
        assert len(state["steps"]) == 1

    def test_hitl_fields_present(self) -> None:
        """Human-in-the-loop fields must exist in the schema."""
        state: AgentState = {
            "pending_human_input": "Please review the training config.",
            "human_feedback": "Approved.",
        }
        assert state["pending_human_input"] is not None
        assert state["human_feedback"] == "Approved."
