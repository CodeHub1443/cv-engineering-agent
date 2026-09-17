"""
Integration tests for Project Memory (ADR-0004) wired into CVAgent/the
workflow graph (ADR-0003) — the controlled integration step that makes
durable memory actually participate in the application lifecycle without
collapsing it into LangGraph checkpoint state.

Uses the real CVAgent (not fakes) — same convention as
tests/test_workflow.py's `TestCVAgentWorkflowWiring`: `CV_AGENT_SKILL_PATHS`
pinned to an isolated empty `tmp_path`, and an explicit
`AgentConfig(workspace_root=tmp_path)` so no test ever touches the real
repository's own `.cv_agent/` directory or a real skill installation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_VAGUE_TASK = "I have a prison project. Escape-attempt detection."

_WELL_DEFINED_TASK = (
    "Detect intruders using our 8 outdoor CCTV cameras at 1080p/15fps, "
    "deploy on a Jetson Orin, need real-time response with recall above 95%, "
    "and we have 2000 labeled clips already."
)

_PLANNING_TASK = _WELL_DEFINED_TASK + (
    " Also evaluate deployment optimization performance benchmarking of the model."
)
"""Same fully-specified request as _WELL_DEFINED_TASK (zero clarification
questions) plus benchmarking vocabulary, so it matches a fixture skill
described as a benchmarking tool — same convention as
tests/test_workflow.py's own _PLANNING_TASK."""


def _agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, skill_root: Path | None = None):
    monkeypatch.setenv("CV_AGENT_SKILL_PATHS", str(skill_root or tmp_path))
    from cv_agent.config.settings import AgentConfig
    from cv_agent.runtime.agent import CVAgent

    return CVAgent(AgentConfig(workspace_root=tmp_path))


class TestWorkspaceRootPropagation:
    def test_default_agent_config_workspace_root_is_none(self) -> None:
        from cv_agent.config.settings import AgentConfig

        assert AgentConfig().workspace_root is None

    def test_explicit_workspace_root_determines_memory_location(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _agent(tmp_path, monkeypatch)
        agent.memory  # noqa: B018 — property access is what triggers construction
        assert (tmp_path / ".cv_agent" / "memory.sqlite").is_file()

    def test_no_config_never_touches_memory_for_non_memory_methods(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CVAgent() with default config (workspace_root=None) must not
        create anything anywhere just from health_check()/resolve()/
        analyze_requirements() — memory stays lazy. Proven here by pinning
        cwd to tmp_path and confirming nothing was written to it."""
        monkeypatch.setenv("CV_AGENT_SKILL_PATHS", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        from cv_agent.runtime.agent import CVAgent

        agent = CVAgent()
        agent.health_check()
        agent.resolve("detect defects")
        agent.analyze_requirements("detect defects on a line")

        assert not (tmp_path / ".cv_agent").exists()


class TestSessionLifecycle:
    def test_start_workflow_creates_session_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _agent(tmp_path, monkeypatch)
        result = agent.start_workflow(_VAGUE_TASK, session_id="sess-1")

        assert "__interrupt__" in result
        session = agent.memory.get_session("sess-1")
        assert session is not None
        assert session.session_id == "sess-1"
        assert session.ended_at is None  # still paused, not done

    def test_session_identity_matches_agent_state_session_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _agent(tmp_path, monkeypatch)
        result = agent.start_workflow(_WELL_DEFINED_TASK, session_id="exact-id-123")

        assert result["session_id"] == "exact-id-123"
        session = agent.memory.get_session("exact-id-123")
        assert session is not None
        assert session.session_id == result["session_id"]

    def test_resume_updates_session_to_done_with_ended_at(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _agent(tmp_path, monkeypatch)
        started = agent.start_workflow(_VAGUE_TASK, session_id="sess-2")
        questions = started["__interrupt__"][0].value["questions"]
        answers = {q["relates_to_field"]: "provided" for q in questions}

        resumed = agent.resume_workflow("sess-2", answers)

        assert resumed["status"] == "done"
        session = agent.memory.get_session("sess-2")
        assert session is not None
        assert session.status == "done"
        assert session.ended_at is not None

    def test_resume_does_not_create_a_second_session_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _agent(tmp_path, monkeypatch)
        started = agent.start_workflow(_VAGUE_TASK, session_id="sess-3")
        questions = started["__interrupt__"][0].value["questions"]
        answers = {q["relates_to_field"]: "provided" for q in questions}
        agent.resume_workflow("sess-3", answers)

        assert len(agent.memory.list_sessions()) == 1

    def test_restarting_start_workflow_preserves_original_started_at(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _agent(tmp_path, monkeypatch)
        agent.start_workflow(_WELL_DEFINED_TASK, session_id="sess-4")
        first_started_at = agent.memory.get_session("sess-4").started_at

        agent.start_workflow(_WELL_DEFINED_TASK, session_id="sess-4")
        second_started_at = agent.memory.get_session("sess-4").started_at

        assert first_started_at == second_started_at


class TestProjectUnderstandingPersistenceTrigger:
    def test_first_analysis_persists_exactly_one_revision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _agent(tmp_path, monkeypatch)
        agent.start_workflow(_VAGUE_TASK, session_id="pu-1")

        revisions = agent.memory.list_understanding_revisions()
        assert len(revisions) == 1
        assert revisions[0].session_id == "pu-1"

    def test_current_understanding_matches_state_requirements_analysis(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Compared JSON-normalized: a fresh, never-yet-checkpointed
        AgentState still has the tuples dataclasses.asdict() produced,
        while anything read back from the store has gone through JSON and
        come back with lists — same data, different container type. See
        CVAgent._sync_memory_after_run()'s own docstring for why the
        product code itself normalizes before comparing."""
        import json

        agent = _agent(tmp_path, monkeypatch)
        result = agent.start_workflow(_VAGUE_TASK, session_id="pu-2")

        current = agent.memory.get_current_understanding()
        assert current is not None
        normalized_result = json.loads(json.dumps(result["requirements_analysis"]))
        assert current.requirements_analysis == normalized_result

    def test_clarification_resume_persists_a_second_superseding_revision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _agent(tmp_path, monkeypatch)
        started = agent.start_workflow(_VAGUE_TASK, session_id="pu-3")
        first_revision = agent.memory.get_current_understanding()
        questions = started["__interrupt__"][0].value["questions"]
        answers = {q["relates_to_field"]: "provided" for q in questions}

        agent.resume_workflow("pu-3", answers)

        revisions = agent.memory.list_understanding_revisions()
        assert len(revisions) == 2
        assert revisions[0].revision_id == first_revision.revision_id
        assert revisions[1].supersedes == first_revision.revision_id
        current = agent.memory.get_current_understanding()
        assert current.revision_id == revisions[1].revision_id

    def test_restarting_with_identical_task_does_not_duplicate_revision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression test for the tuple-vs-list container-type mismatch:
        a fresh, never-yet-checkpointed AgentState.requirements_analysis
        still has tuples (dataclasses.asdict()'s own output), while
        anything read back from the SQLite store has gone through JSON and
        come back with lists. A naive `!=` comparison between those two
        would treat identical content as "different" every time and never
        dedup. Restarting start_workflow() with the exact same task
        produces the exact same analysis content — this must NOT create a
        second revision."""
        agent = _agent(tmp_path, monkeypatch)
        agent.start_workflow(_WELL_DEFINED_TASK, session_id="pu-restart")
        assert len(agent.memory.list_understanding_revisions()) == 1

        agent.start_workflow(_WELL_DEFINED_TASK, session_id="pu-restart")
        assert len(agent.memory.list_understanding_revisions()) == 1

    def test_well_defined_request_persists_exactly_one_revision_no_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _agent(tmp_path, monkeypatch)
        result = agent.start_workflow(_WELL_DEFINED_TASK, session_id="pu-4")

        assert "__interrupt__" not in result
        assert result["status"] == "done"
        assert len(agent.memory.list_understanding_revisions()) == 1

    def test_approval_only_resume_does_not_duplicate_understanding_revision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An approval-gate interrupt/resume never touches
        requirements_analysis — the equality-based revision-trigger policy
        (ADR-0004 §9) must not write a redundant, identical revision for
        it."""
        from cv_agent.execution.binding import ExecutionBinding
        from cv_agent.execution.models import RuntimeOutcome

        class _FakeRuntime:
            runtime_id = "fake-runtime"

            def invoke(self, skill, request):
                return RuntimeOutcome(success=True, output={})

        agent = _agent(tmp_path, monkeypatch)
        agent.execution_bindings.register_runtime(_FakeRuntime())
        agent.execution_bindings.register_binding(
            ExecutionBinding(
                skill_id="fixture-skill",
                binding_id="b1",
                runtime_id="fake-runtime",
                approval_policy="approval_required",
                verified=True,
            )
        )

        started = agent.start_workflow(
            _WELL_DEFINED_TASK,
            session_id="pu-5",
            pending_execution={"skill_id": "fixture-skill", "inputs": {}, "task": None},
        )
        assert "__interrupt__" in started  # paused at approval_gate, not clarify
        assert len(agent.memory.list_understanding_revisions()) == 1

        resumed = agent.resume_workflow("pu-5", "approved")

        assert resumed["status"] == "done"
        assert len(agent.memory.list_understanding_revisions()) == 1  # unchanged


class TestExecutionInputsChannel:
    """ADR-0010 §12: CVAgent.start_workflow(execution_inputs=...) is the
    real, top-level API surface for the explicit execution-input channel —
    proven here through the actual CVAgent/workflow-graph/skill-discovery
    wiring end to end, not only at the graph-node level already covered by
    tests/test_workflow.py::TestPlanExecutionIntegration."""

    @staticmethod
    def _write_fixture_skill(skill_root: Path) -> None:
        skill_dir = skill_root / "trt-perf-analysis"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: trt-perf-analysis\n"
            "description: TensorRT performance benchmarking and layer analysis tool.\n"
            "---\nbody\n",
            encoding="utf-8",
        )

    @staticmethod
    def _register_binding(agent, *, input_schema=()) -> None:
        from cv_agent.execution.binding import ExecutionBinding
        from cv_agent.execution.models import RuntimeOutcome

        class _FakeRuntime:
            runtime_id = "fake-runtime"

            def invoke(self, skill, request):
                return RuntimeOutcome(success=True, output={})

        agent.execution_bindings.register_runtime(_FakeRuntime())
        agent.execution_bindings.register_binding(
            ExecutionBinding(
                skill_id="trt-perf-analysis",
                binding_id="trt-perf-analysis-fake-v1",
                runtime_id="fake-runtime",
                approval_policy="allowed",
                verified=True,
                input_schema=input_schema,
            )
        )

    def test_execution_inputs_flow_through_start_workflow_to_a_real_plan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cv_agent.execution.binding import InputField

        skill_root = tmp_path / "skills"
        self._write_fixture_skill(skill_root)
        agent = _agent(tmp_path, monkeypatch, skill_root=skill_root)
        self._register_binding(
            agent,
            input_schema=(InputField(name="path", required=True, description="folder path"),),
        )

        result = agent.start_workflow(
            _PLANNING_TASK,
            session_id="exec-inputs-1",
            execution_inputs={"path": "/data/clips"},
        )

        assert "__interrupt__" not in result
        assert result["planning_result"]["status"] == "planned"
        assert result["pending_execution"] == {
            "skill_id": "trt-perf-analysis",
            "inputs": {"path": "/data/clips"},
            "task": _PLANNING_TASK,
        }
        assert result["status"] == "done"
        assert result["execution_result"]["status"] == "completed"

    def test_omitted_execution_inputs_default_to_empty_and_still_block_a_missing_required_input(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backward compatibility: a caller who does not pass
        execution_inputs at all sees the exact same 'no plan' outcome as
        before this parameter existed — the default is {}, never inferred
        from clarification_answers or anything else in the request text."""
        from cv_agent.execution.binding import InputField

        skill_root = tmp_path / "skills"
        self._write_fixture_skill(skill_root)
        agent = _agent(tmp_path, monkeypatch, skill_root=skill_root)
        self._register_binding(
            agent,
            input_schema=(InputField(name="path", required=True, description="folder path"),),
        )

        result = agent.start_workflow(_PLANNING_TASK, session_id="exec-inputs-2")

        assert result["pending_execution"] is None
        assert result["planning_result"]["status"] == "missing_required_inputs"
        assert list(result["planning_result"]["missing_inputs"]) == ["path"]


class TestPersistenceVisibleToNewCVAgent:
    def test_new_cvagent_instance_sees_prior_persisted_understanding(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_1 = _agent(tmp_path, monkeypatch)
        agent_1.start_workflow(_WELL_DEFINED_TASK, session_id="cross-1")

        agent_2 = _agent(tmp_path, monkeypatch)
        current = agent_2.memory.get_current_understanding()
        assert current is not None
        assert current.session_id == "cross-1"

    def test_new_cvagent_instance_sees_prior_session_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent_1 = _agent(tmp_path, monkeypatch)
        agent_1.start_workflow(_WELL_DEFINED_TASK, session_id="cross-2")

        agent_2 = _agent(tmp_path, monkeypatch)
        session = agent_2.memory.get_session("cross-2")
        assert session is not None
        assert session.status == "done"


class TestSeparateWorkspacesSeparateDatabases:
    def test_two_workspace_roots_produce_isolated_memory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root_a = tmp_path / "workspace-a"
        root_b = tmp_path / "workspace-b"
        root_a.mkdir()
        root_b.mkdir()

        monkeypatch.setenv("CV_AGENT_SKILL_PATHS", str(tmp_path))
        from cv_agent.config.settings import AgentConfig
        from cv_agent.runtime.agent import CVAgent

        agent_a = CVAgent(AgentConfig(workspace_root=root_a))
        agent_b = CVAgent(AgentConfig(workspace_root=root_b))

        agent_a.start_workflow(_WELL_DEFINED_TASK, session_id="only-in-a")
        agent_b.start_workflow(_WELL_DEFINED_TASK, session_id="only-in-b")

        assert agent_a.memory.get_session("only-in-a") is not None
        assert agent_a.memory.get_session("only-in-b") is None
        assert agent_b.memory.get_session("only-in-b") is not None
        assert agent_b.memory.get_session("only-in-a") is None

        db_a = root_a / ".cv_agent" / "memory.sqlite"
        db_b = root_b / ".cv_agent" / "memory.sqlite"
        assert db_a.is_file()
        assert db_b.is_file()
        assert db_a != db_b


class TestMemoryFailureSurfacing:
    def test_start_workflow_raises_project_memory_error_not_silent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cv_agent.memory.store import ProjectMemoryError

        blocker = tmp_path / ".cv_agent"
        blocker.write_text("not a directory — blocks memory dir creation")

        agent = _agent(tmp_path, monkeypatch)

        with pytest.raises(ProjectMemoryError):
            agent.start_workflow(_WELL_DEFINED_TASK, session_id="will-fail")

    def test_memory_property_access_raises_project_memory_error_not_silent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cv_agent.memory.store import ProjectMemoryError

        blocker = tmp_path / ".cv_agent"
        blocker.write_text("not a directory")

        agent = _agent(tmp_path, monkeypatch)

        with pytest.raises(ProjectMemoryError):
            agent.memory.get_current_understanding()


class TestGraphExceptionMarksSessionError:
    """Code-review finding: an exception escaping the graph invocation must
    not leave a SessionRecord silently stuck at status="running" forever.
    Forces the failure by monkeypatching the real, already-compiled
    `_workflow_graph.invoke` on a real CVAgent — the memory store itself is
    never mocked; every assertion reads back through the real
    SqliteProjectMemoryStore via agent.memory."""

    class _Boom(Exception):
        pass

    def _break_graph_invoke(self, agent, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*args: object, **kwargs: object):
            raise self._Boom("simulated graph invocation failure")

        monkeypatch.setattr(agent._workflow_graph, "invoke", _raise)

    def test_start_workflow_exception_on_fresh_session_marks_error_and_reraises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _agent(tmp_path, monkeypatch)
        self._break_graph_invoke(agent, monkeypatch)

        with pytest.raises(self._Boom, match="simulated graph invocation failure"):
            agent.start_workflow(_WELL_DEFINED_TASK, session_id="crash-fresh")

        session = agent.memory.get_session("crash-fresh")
        assert session is not None
        assert session.status == "error"
        assert session.ended_at is not None
        assert session.started_at is not None
        assert session.produced_revision_id is None  # nothing was ever produced

    def test_start_workflow_exception_on_restart_preserves_started_at_and_revision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The meaningful version of the test: something must actually
        exist to be preserved. A real successful run first creates a
        session with a produced_revision_id and a started_at timestamp;
        the crashed restart must keep both exactly, not reset them."""
        agent = _agent(tmp_path, monkeypatch)
        agent.start_workflow(_WELL_DEFINED_TASK, session_id="crash-restart")
        first_session = agent.memory.get_session("crash-restart")
        assert first_session is not None
        assert first_session.produced_revision_id is not None
        original_started_at = first_session.started_at
        original_revision_id = first_session.produced_revision_id

        self._break_graph_invoke(agent, monkeypatch)

        with pytest.raises(self._Boom):
            agent.start_workflow(_WELL_DEFINED_TASK, session_id="crash-restart")

        session = agent.memory.get_session("crash-restart")
        assert session is not None
        assert session.status == "error"
        assert session.ended_at is not None
        assert session.started_at == original_started_at
        assert session.produced_revision_id == original_revision_id
        # The crash must not have touched Project Understanding at all.
        assert len(agent.memory.list_understanding_revisions()) == 1

    def test_resume_workflow_exception_marks_session_error_and_reraises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _agent(tmp_path, monkeypatch)
        started = agent.start_workflow(_VAGUE_TASK, session_id="crash-resume")
        assert "__interrupt__" in started
        paused_session = agent.memory.get_session("crash-resume")
        assert paused_session is not None
        original_started_at = paused_session.started_at

        self._break_graph_invoke(agent, monkeypatch)
        questions = started["__interrupt__"][0].value["questions"]
        answers = {q["relates_to_field"]: "provided" for q in questions}

        with pytest.raises(self._Boom, match="simulated graph invocation failure"):
            agent.resume_workflow("crash-resume", answers)

        session = agent.memory.get_session("crash-resume")
        assert session is not None
        assert session.status == "error"
        assert session.ended_at is not None
        assert session.started_at == original_started_at

    def test_combined_failure_preserves_graph_exception_with_memory_error_as_cause(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PR review finding: if the graph invocation raises AND the
        subsequent attempt to persist that as a SessionRecord error also
        fails (e.g. the store becomes unusable), the ORIGINAL graph
        exception must still be what propagates to the caller — a
        memory-layer failure must never silently replace it. The memory
        failure must also not be silently swallowed: it must be visible,
        attached as the propagated exception's __cause__.

        The store failure is genuine, not mocked: this closes the real
        SqliteProjectMemoryStore's connection (the same trick
        TestMemoryFailureSurfacing/test_memory.py's
        TestErrorHandlingDoesNotSwallow already use) so the real
        _mark_session_error() call hits a real sqlite3-backed
        ProjectMemoryError, not a simulated one."""
        from cv_agent.memory.store import ProjectMemoryError

        agent = _agent(tmp_path, monkeypatch)
        store = agent.memory  # trigger lazy construction while the store is healthy

        def _raise_after_breaking_store(*args: object, **kwargs: object):
            # The pre-invoke SessionRecord write (status="running") already
            # succeeded by this point — only now does the store become
            # unusable, simulating a failure that hits exactly when
            # _mark_session_error() tries to read/write it afterward.
            store.close()
            raise self._Boom("simulated graph invocation failure")

        monkeypatch.setattr(agent._workflow_graph, "invoke", _raise_after_breaking_store)

        with pytest.raises(self._Boom) as exc_info:
            agent.start_workflow(_WELL_DEFINED_TASK, session_id="double-fail")

        # The graph exception is the one that propagated, unchanged...
        assert str(exc_info.value) == "simulated graph invocation failure"
        # ...and the memory failure was not silently swallowed — it is
        # attached as context, not hidden and not the primary exception.
        assert isinstance(exc_info.value.__cause__, ProjectMemoryError)


class TestOrchestrationUnaffected:
    """Regression guard specific to this integration step: adding
    workspace_root to AgentConfig and memory calls to start_workflow()/
    resume_workflow() must not change run()/health_check(), and must not
    touch disk for calls that never reach the workflow graph."""

    def test_run_and_health_check_unaffected_by_workspace_root_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _agent(tmp_path, monkeypatch)

        result = agent.run("inspect a model", task_type="model_analysis")

        assert result["status"] == "ready"
        assert result["steps"] == [
            {
                "node": "initialize",
                "action": "session_started",
                "session_id": result["session_id"],
            }
        ]
        assert agent.health_check()["status"] in ("ok", "degraded")
        # run()/health_check() never touch memory even though workspace_root
        # is configured — laziness is preserved end to end.
        assert not (tmp_path / ".cv_agent").exists()

    def test_start_workflow_interrupt_payload_shape_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = _agent(tmp_path, monkeypatch)
        result = agent.start_workflow(_VAGUE_TASK, session_id="shape-check")

        payload = result["__interrupt__"][0].value
        assert payload["type"] == "clarification"
        assert "questions" in payload
