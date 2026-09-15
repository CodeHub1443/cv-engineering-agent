"""
cv_agent.runtime.agent — Top-level CVAgent orchestrator.

CVAgent wires together:
    - Configuration (AgentConfig)
    - LLM provider (via provider registry)
    - Capability registry
    - LangGraph compiled graph

It is the primary interface for:
    - Running agent tasks (run())
    - Health checks (health_check())

Graph logic, LLM prompting, and capability invocation are intentionally
kept out of this class and belong in their respective modules.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from cv_agent.capabilities.registry import CapabilityRegistry
from cv_agent.config.settings import AgentConfig, load_config
from cv_agent.execution.binding import ExecutionBindingRegistry
from cv_agent.execution.executor import SkillExecutor
from cv_agent.execution.models import SkillExecutionRequest, SkillExecutionResult
from cv_agent.graph.builder import build_graph
from cv_agent.graph.state import AgentState
from cv_agent.graph.workflow import build_requirements_workflow_graph
from cv_agent.llm.base import LLMProvider
from cv_agent.llm.registry import get_provider
from cv_agent.requirements.analyzer import RequirementsAnalyzer
from cv_agent.requirements.models import RequirementsAnalysis
from cv_agent.skills.inventory import SkillInventory
from cv_agent.skills.local import LocalSkillSource, default_skill_roots
from cv_agent.skills.models import Skill
from cv_agent.skills.resolver import ResolutionResult, TaskResolver


class CVAgent:
    """
    CV Engineering Agent — top-level orchestrator.

    Instantiate with an optional AgentConfig; if omitted, config is loaded
    from the default TOML file (config/default.toml).
    """

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        self._config: AgentConfig = config or load_config()
        self._llm: LLMProvider = get_provider(
            self._config.llm.provider,
            self._config.llm.model,
        )
        self._registry: CapabilityRegistry = CapabilityRegistry(
            self._config.registry_path
        )
        skill_roots = self._config.skill_paths or default_skill_roots()
        self._skill_inventory: SkillInventory = SkillInventory(
            sources=(LocalSkillSource(roots=skill_roots),)
        )
        self._resolver: TaskResolver = TaskResolver(
            capability_registry=self._registry,
            skill_inventory=self._skill_inventory,
        )
        self._requirements_analyzer: RequirementsAnalyzer = RequirementsAnalyzer(
            task_resolver=self._resolver,
            llm=self._llm,
        )
        # No binding is registered by default — see ADR-0009 §5. Tests and any
        # future genuinely-verified adapter register into this registry
        # explicitly; CVAgent never pre-populates it.
        self._execution_registry: ExecutionBindingRegistry = ExecutionBindingRegistry()
        self._executor: SkillExecutor = SkillExecutor(self._execution_registry)
        self._graph: Any = build_graph()
        self._workflow_graph: Any = build_requirements_workflow_graph(
            requirements_analyzer=self._requirements_analyzer,
            executor=self._executor,
            skill_inventory=self._skill_inventory,
        )

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def config(self) -> AgentConfig:
        return self._config

    @property
    def llm(self) -> LLMProvider:
        return self._llm

    @property
    def registry(self) -> CapabilityRegistry:
        return self._registry

    @property
    def skills(self) -> SkillInventory:
        return self._skill_inventory

    @property
    def execution_bindings(self) -> ExecutionBindingRegistry:
        """Inspection-only: list what execution bindings/runtimes exist,
        without running anything. Empty by default — see ADR-0009 §5."""
        return self._execution_registry

    def resolve(self, task: str) -> ResolutionResult:
        """Deterministic task -> capability -> skill resolution. No LLM."""
        return self._resolver.resolve(task)

    def analyze_requirements(
        self,
        user_request: str,
        *,
        assumptions: Optional[dict[str, str]] = None,
    ) -> RequirementsAnalysis:
        """
        Structured requirements understanding + CV task decomposition.

        Deterministic rule-based extraction (known/unknown/assumed fields,
        candidate task hypotheses, capability links via the existing
        resolver, clarification questions); the configured LLM provider is
        used only for an optional narrative summary, never as a source of
        fact. Does not execute any skill or tool.
        """
        return self._requirements_analyzer.analyze(user_request, assumptions=assumptions)

    def execute(self, skill: Skill, request: SkillExecutionRequest) -> SkillExecutionResult:
        """
        Attempt to execute a resolved skill through the execution boundary.

        Fails safely with a structured, non-raising result (status
        "not_executable" or "rejected") when no verified binding exists or
        approval was not granted — see cv_agent.execution.executor. Normal
        user requests (resolve(), analyze_requirements()) never call this;
        it must be invoked explicitly.
        """
        return self._executor.execute(skill, request)

    def can_execute(self, skill_id: str) -> bool:
        """Inspect only — true iff a verified binding + registered runtime
        exists for skill_id. Never runs anything."""
        return self._executor.can_execute(skill_id)

    # ── Core operations ───────────────────────────────────────────────────

    def run(
        self,
        task: Optional[str] = None,
        *,
        session_id: Optional[str] = None,
        task_type: Optional[str] = None,
    ) -> AgentState:
        """
        Execute a single agent session through the graph.

        Args:
            task:       Natural-language task description.
            session_id: Reuse an existing session ID to resume a paused run.
                        A new UUID is generated if omitted.
            task_type:  Structured task type tag for capability selection.

        Returns:
            Final AgentState after graph execution completes.
        """
        sid = session_id or str(uuid.uuid4())
        initial_state: AgentState = {
            "session_id": sid,
            "status": "initializing",
            "task": task,
            "task_type": task_type,
            "provider": self._llm.provider_name,
            "model": self._llm.model_name,
            "steps": [],
            "selected_capabilities": [],
            "error": None,
            "pending_human_input": None,
            "human_feedback": None,
        }
        graph_config = {"configurable": {"thread_id": sid}}
        result: AgentState = self._graph.invoke(initial_state, config=graph_config)
        return result

    # ── Requirements-clarification + approval-gated execution workflow ─────
    # (ADR-0003) — a distinct graph from run()/build_graph(); see its
    # module docstring (cv_agent.graph.workflow) for why.

    def start_workflow(
        self,
        task: str,
        *,
        session_id: Optional[str] = None,
        pending_execution: Optional[dict[str, Any]] = None,
    ) -> AgentState:
        """
        Start (or restart) a requirements-clarification / approval-gated
        execution run. Returns the state at whatever point the graph
        stopped — either paused at an interrupt (state contains
        "__interrupt__") or finished ("status" == "done").

        pending_execution, if given, is {"skill_id": str, "inputs": dict,
        "task": str | None} — a skill this run should also attempt to
        execute, gated by its binding's approval policy. None means this
        run only does requirements analysis/clarification.
        """
        sid = session_id or str(uuid.uuid4())
        initial_state: AgentState = {
            "session_id": sid,
            "status": "initializing",
            "task": task,
            "steps": [],
            "error": None,
            "pending_human_input": None,
            "human_feedback": None,
            "requirements_analysis": None,
            "clarification_answers": {},
            "pending_execution": pending_execution,
            "approval_decision": None,
            "execution_result": None,
        }
        graph_config = {"configurable": {"thread_id": sid}}
        result: AgentState = self._workflow_graph.invoke(initial_state, config=graph_config)
        return result

    def resume_workflow(self, session_id: str, resume_value: Any) -> AgentState:
        """
        Resume a paused workflow run with a human-supplied value — the
        clarification answers dict for a clarify interrupt, or the literal
        string "approved"/"rejected" for an approval interrupt. Raises no
        special exception for an unpaused/unknown session_id; LangGraph
        itself will error if there is nothing to resume.
        """
        from langgraph.types import Command  # noqa: PLC0415

        graph_config = {"configurable": {"thread_id": session_id}}
        result: AgentState = self._workflow_graph.invoke(
            Command(resume=resume_value), config=graph_config
        )
        return result

    def get_workflow_state(self, session_id: str) -> AgentState:
        """Inspect a workflow run's current checkpointed state without
        resuming it."""
        graph_config = {"configurable": {"thread_id": session_id}}
        snapshot = self._workflow_graph.get_state(graph_config)
        return snapshot.values  # type: ignore[return-value]

    def health_check(self) -> dict[str, Any]:
        """
        Return a structured health summary.

        Checks:
            - LangGraph availability and version
            - Capability registry loadability and count
            - Configured provider and model

        Returns:
            dict with keys: status, provider, model, capability_count,
            langgraph_available, langgraph_version, registry_ok.
        """
        # LangGraph check
        try:
            from importlib.metadata import version
            
            lg_version: str = version("langgraph")
            import langgraph  # noqa: PLC0415
            lg_ok = True
        except Exception as exc:  # noqa: BLE001
            lg_version = str(exc)
            lg_ok = False

        # Registry check
        try:
            self._registry.load()
            cap_count = self._registry.capability_count
            registry_ok = True
        except Exception:  # noqa: BLE001
            cap_count = 0
            registry_ok = False

        overall = "ok" if (lg_ok and registry_ok) else "degraded"

        return {
            "status": overall,
            "provider": self._llm.provider_name,
            "model": self._llm.model_name,
            "capability_count": cap_count,
            "langgraph_available": lg_ok,
            "langgraph_version": lg_version,
            "registry_ok": registry_ok,
        }
