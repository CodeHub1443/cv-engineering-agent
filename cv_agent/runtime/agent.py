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

import json
import uuid
from datetime import datetime, timezone
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
from cv_agent.memory.models import ProjectUnderstandingRevision, SessionRecord
from cv_agent.memory.store import ProjectMemoryStore, open_store
from cv_agent.requirements.analyzer import RequirementsAnalyzer
from cv_agent.requirements.models import RequirementsAnalysis
from cv_agent.skills.inventory import SkillInventory
from cv_agent.skills.local import LocalSkillSource, default_skill_roots
from cv_agent.skills.models import Skill
from cv_agent.skills.resolver import ResolutionResult, TaskResolver


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_REVISION_COMPARISON_EXCLUDED_KEYS = ("narrative_summary", "llm_provider")
"""Keys excluded when deciding whether a new ProjectUnderstandingRevision is
needed (see CVAgent._sync_memory_after_run()) — not from what gets stored.
Per ADR-0008 §2/§3, narrative_summary is LLM-generated prose that is
"never a source of any structured fact"; two analyses with identical facts
but re-worded prose (which even the mock provider already produces, via a
per-call response counter — confirmed empirically) are the same
understanding, not a new one. This is a fixed exclusion list grounded in an
existing ADR's own field classification, not semantic/fuzzy diffing."""


def _facts_only(requirements_analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v for k, v in requirements_analysis.items()
        if k not in _REVISION_COMPARISON_EXCLUDED_KEYS
    }


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
        # Durable Project Memory (ADR-0004) — lazily constructed on first
        # actual use. A CVAgent built only for health_check()/resolve()/
        # analyze_requirements()/etc. never touches disk for this; only
        # start_workflow()/resume_workflow() (and the `memory` property
        # itself) trigger construction. Never a SQLite-specific type here —
        # see cv_agent.memory.store.open_store().
        self._memory_store: Optional[ProjectMemoryStore] = None

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

    @property
    def memory(self) -> ProjectMemoryStore:
        """
        Durable Project Memory for this workspace (ADR-0004).

        Lazily constructed on first access against `self._config.
        workspace_root` (via `cv_agent.memory.store.open_store()` — never a
        SQLite-specific type here). Accessing this property is itself what
        triggers the database file to be created if it doesn't exist yet;
        `start_workflow()`/`resume_workflow()` access it internally, but
        `run()`, `resolve()`, `analyze_requirements()`, `execute()`, and
        `health_check()` never do.
        """
        return self._get_memory_store()

    def _get_memory_store(self) -> ProjectMemoryStore:
        if self._memory_store is None:
            self._memory_store = open_store(workspace_root=self._config.workspace_root)
        return self._memory_store

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

        Session lifecycle (ADR-0004): a `SessionRecord` is written to
        durable Project Memory *before* the graph runs (status "running"),
        and updated again after it stops — whether paused at an interrupt,
        finished, or the graph invocation raised — via
        `_sync_memory_after_run()` on success or `_mark_session_error()` on
        an exception (see its docstring). This is durable project context,
        not LangGraph's own run/orchestration state: the graph itself still
        checkpoints via `MemorySaver` exactly as before (ADR-0003,
        unchanged) — Project Memory does not replace or participate in
        that checkpointing, it only records that this session exists and,
        if requirements analysis produced a result, the resulting Project
        Understanding.
        """
        sid = session_id or str(uuid.uuid4())
        store = self._get_memory_store()
        existing_session = store.get_session(sid)
        started_at = existing_session.started_at if existing_session is not None else _now_iso()
        store.record_session(
            SessionRecord(
                session_id=sid,
                started_at=started_at,
                status="running",
                produced_revision_id=(
                    existing_session.produced_revision_id if existing_session is not None else None
                ),
            )
        )

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
        try:
            result: AgentState = self._workflow_graph.invoke(initial_state, config=graph_config)
        except Exception:
            self._mark_session_error(sid, started_at)
            raise
        self._sync_memory_after_run(sid, started_at, result)
        return result

    def resume_workflow(self, session_id: str, resume_value: Any) -> AgentState:
        """
        Resume a paused workflow run with a human-supplied value — the
        clarification answers dict for a clarify interrupt, or the literal
        string "approved"/"rejected" for an approval interrupt. Raises no
        special exception for an unpaused/unknown session_id; LangGraph
        itself will error if there is nothing to resume.

        Updates the same durable `SessionRecord` `start_workflow()` created
        (ADR-0004) — this call does not create a new one. See
        `start_workflow()`'s docstring for what "durable" does and does not
        mean here: LangGraph's own checkpoint (ADR-0003, `MemorySaver`,
        unchanged) is still what actually lets this call resume the paused
        graph; Project Memory only records the outcome. If the graph
        invocation itself raises, `_mark_session_error()` records that
        before the exception propagates — same handling as
        `start_workflow()`, for the same reason (a crash must not leave the
        session silently stuck at whatever status it had before).
        """
        from langgraph.types import Command  # noqa: PLC0415

        graph_config = {"configurable": {"thread_id": session_id}}
        try:
            result: AgentState = self._workflow_graph.invoke(
                Command(resume=resume_value), config=graph_config
            )
        except Exception:
            self._mark_session_error(session_id, started_at=None)
            raise
        self._sync_memory_after_run(session_id, started_at=None, result=result)
        return result

    def _mark_session_error(self, session_id: str, started_at: Optional[str]) -> None:
        """
        Called from `start_workflow()`/`resume_workflow()` when the graph
        invocation itself raises, so a crash cannot leave the persisted
        `SessionRecord` silently stuck at whatever status it had before
        (typically "running", written by `start_workflow()` just before
        invoking) — see the code-review finding this fixes.

        Preserves `started_at`/`produced_revision_id` from the existing
        session record exactly like `_sync_memory_after_run()` does, sets
        `status="error"` and `ended_at=<now>`. Does not touch Project
        Understanding — a raised call produced no reliable
        `requirements_analysis` to persist. Failures from the store itself
        propagate, same as everywhere else in this class — never swallowed.
        """
        store = self._get_memory_store()
        existing_session = store.get_session(session_id)
        effective_started_at = started_at or (
            existing_session.started_at if existing_session is not None else _now_iso()
        )
        produced_revision_id = (
            existing_session.produced_revision_id if existing_session is not None else None
        )
        store.record_session(
            SessionRecord(
                session_id=session_id,
                started_at=effective_started_at,
                ended_at=_now_iso(),
                status="error",
                produced_revision_id=produced_revision_id,
            )
        )

    def _sync_memory_after_run(
        self, session_id: str, started_at: Optional[str], result: AgentState
    ) -> None:
        """
        Write to durable Project Memory (ADR-0004) after one graph
        invocation (`start_workflow()` or `resume_workflow()`) returns —
        whether the run paused at an interrupt or finished.

        Revision-trigger policy (ADR-0004 §9, decided here): append a new
        `ProjectUnderstandingRevision` iff this run produced a
        `requirements_analysis` AND its *factual* content differs — plain
        structural equality on a fixed set of fields, not semantic diffing
        — from `get_current_understanding()`. This means: the first
        analysis in a session always persists; a second pass after a human
        answers clarification questions persists again (its facts differ,
        since assumptions were folded in); an approval-gate-only resume
        (which never touches `requirements_analysis`) or a plain restart
        with the same task writes no redundant revision, because the facts
        are unchanged from what's already current. The full dict (facts
        AND prose) is always what gets stored when a revision *is* written
        — only the *decision* of whether to write one excludes two fields.

        Two normalizations are applied before comparing, both confirmed
        empirically rather than assumed:

        1. **Container types.** `AgentState["requirements_analysis"]`'s
           tuples (from `dataclasses.asdict()`) survive untouched on a
           fresh, never-yet-checkpointed `.invoke()`, but come back as
           lists once state has been through a LangGraph checkpoint
           save/restore (as it always has by the time `resume_workflow()`
           sees it). A bare `==` against this store's own
           already-JSON-round-tripped value would report "different" for
           byte-for-byte identical data. Both sides are JSON-normalized
           (`json.loads(json.dumps(...))`) before comparing.
        2. **`narrative_summary`/`llm_provider`.** ADR-0008 §2/§3: the LLM
           narrative summary is prose, "never a source of any structured
           fact" — and even the mock provider already re-words it on every
           call (a per-call response counter), so comparing it would mean
           this policy *never* dedups in practice, including for a plain
           restart of the exact same task. Both are excluded from the
           comparison via `_facts_only()` — a fixed exclusion list grounded
           in ADR-0008's own field classification, not fuzzy diffing.

        Failures from the store (`ProjectMemoryError`) propagate — never
        caught or swallowed here.
        """
        store = self._get_memory_store()
        existing_session = store.get_session(session_id)
        effective_started_at = started_at or (
            existing_session.started_at if existing_session is not None else _now_iso()
        )
        status = result.get("status") or (
            existing_session.status if existing_session is not None else "running"
        )
        ended_at = _now_iso() if status in ("done", "error") else None
        produced_revision_id = (
            existing_session.produced_revision_id if existing_session is not None else None
        )

        requirements_analysis = result.get("requirements_analysis")
        if requirements_analysis is not None:
            current = store.get_current_understanding()
            normalized_incoming = json.loads(json.dumps(requirements_analysis, sort_keys=True))
            facts_changed = (
                current is None
                or _facts_only(current.requirements_analysis)
                != _facts_only(normalized_incoming)
            )
            if facts_changed:
                revision = ProjectUnderstandingRevision(
                    revision_id=f"PU-{uuid.uuid4().hex}",
                    created_at=_now_iso(),
                    session_id=session_id,
                    requirements_analysis=requirements_analysis,
                    supersedes=current.revision_id if current is not None else None,
                    note=(
                        f"requirements analysis produced during session "
                        f"'{session_id}' (status={status})"
                    ),
                )
                store.append_understanding_revision(revision)
                produced_revision_id = revision.revision_id

        store.record_session(
            SessionRecord(
                session_id=session_id,
                started_at=effective_started_at,
                ended_at=ended_at,
                status=status,
                produced_revision_id=produced_revision_id,
            )
        )

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
