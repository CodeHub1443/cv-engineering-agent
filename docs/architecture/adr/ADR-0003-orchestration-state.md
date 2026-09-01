# ADR-0003: Orchestration State Machine, Checkpointing, and Persistent Approvals

- **Status:** Proposed
- **Date:** 2026-09-01
- **Layer:** orchestration
- **Canon:** `[P§6]`, `[P§21]`, `[P§24]`, `[P§25]`, `[P§29.8]`, `[P§33]`, `[P§34]`
- **Supersedes / Superseded by:** —
- **Issue:** #TBD

## 1. Context

The CV Engineering Agent operates across complex multi-step engineering stages
(DISCOVER → DEFINE → DEVELOP → BENCHMARK → DEPLOY → MONITOR per `[P§6]`, `[P§35]`).
`[P§21]` designates LangGraph as the authoritative orchestration layer responsible for
state, workflow, branching, iteration, human approval, tool execution, retries,
checkpoints, and multi-step reasoning.

The existing repository contains a minimal prototype (`cv_agent/graph/state.py` and
`cv_agent/graph/builder.py`) providing an ephemeral `START → initialize → END` graph
backed by an in-memory `MemorySaver`. While sufficient for early packaging tests, it
lacks:
1. Persistence across process restarts, violating the requirement that human approval
   requests survive workstation reboots and asynchronous review (Q3 / D-015);
2. Workspace-scoped state isolation for single-project repositories (Q1 / D-013);
3. External job references for asynchronous training workloads executed out-of-process
   on local, remote, or cloud GPU targets (Q2 / D-014);
4. Deterministic replay and idempotency boundaries when recovering from failures;
5. Strict typing for stage lifecycles, approval tickets, step histories, and execution
   metadata without leaking reasoning, domain knowledge, or provider specifics into the
   graph `[P§19]`, `[P§20]`, `[P§34]`.

Phase 1 requires formalizing the orchestration state schema, checkpointing backend,
approval interrupt lifecycle, and recovery contracts before downstream stage nodes,
tool integrations, and memory subsystems are constructed.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** the execution state machine, workflow graph topology, node-to-node state
  propagation, checkpoint storage and restoration across process restarts, interrupt/resume
  mechanics for human approval gates, and execution step logging.
- **This does NOT own:**
  - LLM provider management, selection, or API calls → LLM Gateway (ADR-0002) `[P§20]`;
  - Domain reasoning, hypothesis generation, problem formulation, or diagnosis → Reasoning Layer (ADR-0008) `[P§4]`, `[P§19]`;
  - Capability catalogs, type inventories, or skill/tool resolution → Capability Registry (ADR-0001) `[P§23]`;
  - Procedural skill implementations and domain instructions → Skills (ADR-0007) `[P§15]`;
  - Tool execution transport and executable interfaces → Tools/MCP (ADR-0005) `[P§22]`;
  - Long-term experiment ledger and persistent project domain memory → Project Memory & Ledger (ADR-0004) `[P§25]`, `[P§33]`;
  - External job submission and training execution on GPU targets → Training Subsystem (ADR-0010) `[P§10]`, `[P§24]`, Q2 / D-014.
- **Why this responsibility does not belong to an existing component:**
  Reasoning decides *what* should be done; tools determine *how* to invoke capabilities;
  orchestration alone coordinates *when* steps occur, tracks lifecycle progress, guarantees
  safe interruption before expensive actions, and ensures recovery upon failure.

## 3. Decision

We define the orchestration layer around a LangGraph `StateGraph(AgentState)` with local
SQLite-backed checkpoint persistence (`SqliteSaver`) stored at `.cv_agent/state/checkpoints.sqlite`
scoped to the project repository (Q1 / D-013, Q8 / D-018), with in-memory `MemorySaver`
retained solely for ephemeral unit tests.

The core architecture establishes:
1. **Typed State Schema (`AgentState`):** An explicit, typed dictionary containing
   immutable records for lifecycle status, active lifecycle stage, task definition,
   selected capabilities, execution step log, pending approval tickets, external job
   handles, and runtime error diagnostics.
2. **Persistent Approval Interrupts (Q3 / D-015, `[P§24]`):** Gated operations (GPU training,
   cloud provisioning, destructive data mutations, production deployments per `docs/APPROVALS.md`)
   transition state to `AWAITING_APPROVAL`, emit a structured `ApprovalRequest` with cost/risk
   metadata, trigger a LangGraph interrupt/breakpoint, and commit a persistent checkpoint.
   Resumption is asynchronous via CLI/API by passing an `ApprovalResponse` into the session thread.
3. **Asynchronous External Job Handles (Q2 / D-014):** Nodes submitting long-running GPU
   training or remote evaluations record an `ActiveJobRef` in state. The graph polls or awaits
   job completion tokens without blocking the main orchestrator in-process.
4. **Idempotency and Recovery:** Every node update appends an indexed `StepRecord` and
   mutates a monotonic step counter. Nodes performing external operations must check
   existing job tokens in state before dispatching to prevent duplicate external actions
   during checkpoint restoration or node retries.
5. **Session and Thread Scoping:** Each agent invocation runs under a unique `session_id`
   mapped directly to LangGraph's `thread_id`. Single-process file locking ensures only
   one active execution thread modifies a session's state at a time.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| **1. Ephemeral In-Memory Checkpointer (`MemorySaver` only)** | Zero dependencies; trivial setup; already present in Phase 0 prototype. | Fails Q3 / D-015 completely: process termination destroys pending approval state and midway execution traces. Requires re-running entire workflows if interrupted. | Violates persistent approval contract (Q3 / D-015) and reproducibility requirements `[P§25]`. |
| **2. Custom Finite State Machine (plain Python FSM or Celery/Airflow)** | Full custom control without LangGraph framework constraints; robust DAG scheduling in Airflow. | High implementation overhead; reinvents state graph branching, streaming, and breakpoint interrupts; Airflow/Celery introduces heavy infrastructure dependencies (broker, worker daemons) unsuited for local workstation CLI operation (Q2 / D-014). | `[P§21]` explicitly mandates LangGraph; custom FSMs add unnecessary boilerplate and maintenance burden `[P§34]`. |
| **3. Client-Server Distributed Checkpointer (PostgreSQL / Redis)** | Concurrent multi-user access; enterprise clustering; horizontal scaling. | Violates Q1 / D-013 (single-project local repository isolation) and Q2 / D-014 (local workstation execution); requires running external services/containers for basic local agent usage. | Over-engineering for a local workstation engineering assistant. Local embedded SQLite provides zero-config persistence with ACID reliability. |

## 5. Interface

```python
# module: cv_agent.graph.state

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from typing_extensions import TypedDict


class LifecycleStatus(str, Enum):
    """Lifecycle status of the agent orchestration session."""
    INITIALIZING = "initializing"
    READY = "ready"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    EVALUATING = "evaluating"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class StageName(str, Enum):
    """Canonical CV engineering lifecycle stages [P§6], [P§35]."""
    DISCOVER = "discover"
    DEFINE = "define"
    DEVELOP = "develop"
    BENCHMARK = "benchmark"
    DEPLOY = "deploy"
    MONITOR = "monitor"


class ApprovalAction(str, Enum):
    """Decision submitted by human reviewer [P§24], [P§29.8]."""
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"


class ApprovalRiskLevel(str, Enum):
    """Risk tier for human-in-the-loop approval requests."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalRequest(TypedDict, total=False):
    """Persistent human approval ticket (Q3 / D-015, [P§24])."""
    request_id: str
    action_type: str
    description: str
    risk_level: ApprovalRiskLevel
    estimated_cost_usd: float | None
    estimated_gpu_hours: float | None
    affected_paths: list[str]
    created_at: str
    status: Literal["pending", "resolved", "expired"]


class ApprovalResponse(TypedDict, total=False):
    """Resolved response from human reviewer."""
    request_id: str
    action: ApprovalAction
    feedback: str | None
    modified_parameters: dict[str, Any] | None
    resolved_at: str
    resolved_by: str


class ActiveJobRef(TypedDict, total=False):
    """Reference to an external job running out-of-process (Q2 / D-014)."""
    job_id: str
    job_type: Literal["training", "profiling", "evaluation", "export"]
    target: Literal["local_gpu", "remote_gpu", "cloud"]
    submitted_at: str
    status: Literal["submitted", "running", "completed", "failed"]
    metadata: dict[str, Any]


class StepRecord(TypedDict, total=False):
    """Immutable trace of a single node execution in the graph."""
    step_index: int
    node: str
    stage: StageName | None
    action: str
    timestamp: str
    duration_ms: float | None
    inputs_summary: dict[str, Any] | None
    outputs_summary: dict[str, Any] | None
    error: str | None


class AgentState(TypedDict, total=False):
    """Complete, typed orchestration state passed between LangGraph nodes."""

    # ── Session & Lifecycle ───────────────────────────────────────────────
    session_id: str
    current_stage: StageName | None
    status: LifecycleStatus
    error: str | None
    step_count: int

    # ── Task Context ──────────────────────────────────────────────────────
    task: str | None
    task_type: str | None
    parameters: dict[str, Any]

    # ── Capabilities & Routing ────────────────────────────────────────────
    selected_capabilities: list[str]
    active_skill: str | None

    # ── LLM Gateway Context (ADR-0002) ────────────────────────────────────
    active_provider: str | None
    active_model: str | None
    total_tokens_used: int

    # ── Human Approval Gate (Q3 / D-015, [P§24]) ─────────────────────────
    pending_approval: ApprovalRequest | None
    approval_history: list[ApprovalResponse]

    # ── External Asynchronous Jobs (Q2 / D-014) ───────────────────────────
    active_jobs: list[ActiveJobRef]

    # ── Execution History & Memory Snapshot ───────────────────────────────
    steps: list[StepRecord]
    memory_ref: str | None
```

```python
# module: cv_agent.graph.builder

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from cv_agent.graph.state import AgentState, ApprovalResponse


@dataclass(frozen=True)
class OrchestratorConfig:
    """Configuration for constructing the LangGraph orchestration engine."""
    workspace_root: Path
    checkpoint_db_path: Path
    enable_persistence: bool = True
    max_step_limit: int = 100
    checkpoint_retention_days: int = 30


def get_checkpointer(config: OrchestratorConfig) -> BaseCheckpointSaver:
    """
    Instantiate the appropriate LangGraph checkpointer.
    Returns a persistent SqliteSaver targeting config.checkpoint_db_path
    when enable_persistence is True; otherwise returns MemorySaver.
    """
    ...


def build_graph(
    config: OrchestratorConfig,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """
    Build and compile the CV Engineering Agent StateGraph with configured
    checkpointer and interrupt conditions for approval gates.
    """
    ...


def resume_session(
    graph: CompiledStateGraph,
    session_id: str,
    approval_response: ApprovalResponse | None = None,
) -> AgentState:
    """
    Resume an existing paused or interrupted session by its session_id
    (LangGraph thread_id), applying the human approval response if provided.
    """
    ...
```

## 6. Consequences

- **Enables:**
  - Robust resumption of interrupted multi-hour engineering workflows across process restarts;
  - Fully compliant persistent human-in-the-loop approval gates (Q3 / D-015, `[P§24]`);
  - Asynchronous tracking of external GPU training jobs without blocking agent runtime (Q2 / D-014);
  - Complete, reproducible audit trail of node transitions and token usage `[P§25]`;
  - Clean separation between workflow orchestration and domain reasoning/execution layers `[P§34]`.
- **Makes harder:**
  - Nodes cannot perform raw ad-hoc mutations outside the `AgentState` schema;
  - State serialization requires all values within `AgentState` to be JSON/msgpack-serializable;
  - Testing requires managing SQLite test fixtures or explicitly using ephemeral checkpointer mode.
- **Costs:**
  - Local disk I/O on node state transitions (negligible SQLite overhead for typical project state sizes <10MB);
  - Dependency on `langgraph-checkpoint-sqlite` (or `aiosqlite`/built-in SQLite saver).
- **Migration / blast radius if reversed:**
  - Replacing the checkpointer backend requires changing `get_checkpointer()` without modifying graph topology;
  - Replacing LangGraph would require rewriting node registration in `cv_agent/graph/builder.py`, but `AgentState` schema and approval semantics remain portable.

## 7. Acceptance test

1. **`tests/test_graph_state_schema.py`**:
   - Verify `AgentState` validates all fields, enums (`LifecycleStatus`, `StageName`, `ApprovalAction`), and sub-structures (`ApprovalRequest`, `StepRecord`, `ActiveJobRef`).
2. **`tests/test_checkpoint_persistence.py`**:
   - Execute a multi-step graph using SQLite checkpointer; kill process/destroy runtime instance; instantiate a fresh `CVAgent`/graph instance and resume by `session_id`; verify state, step history, and lifecycle status are preserved verbatim.
3. **`tests/test_approval_interrupt_resume.py`**:
   - Trigger an approval gate node; verify graph pauses and returns `status="awaiting_approval"` with `pending_approval` set; restart process; supply `ApprovalResponse(action=ApprovalAction.APPROVED)`; verify graph resumes and completes execution.
4. **`tests/test_job_handle_tracking.py`**:
   - Simulate external training job submission; verify `ActiveJobRef` is recorded and retained across checkpoints without in-process blocking.

## 8. Revisit trigger

This decision shall be reopened if:
1. Multi-user concurrent execution within a shared cloud workspace is required, necessitating a client-server checkpointer (e.g. PostgresSaver);
2. Graph state size exceeds SQLite practical single-row blob performance (>50MB per state update), indicating domain artifacts are erroneously leaking into orchestration state rather than Project Memory (ADR-0004);
3. Upstream LangGraph introduces breaking changes to `StateGraph` compilation or `BaseCheckpointSaver` protocols.
