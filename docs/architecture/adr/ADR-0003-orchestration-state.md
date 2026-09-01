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

Furthermore, Q8 / D-018 established a dual-layer persistence model (Git-tracked structured
project memory plus local SQLite at `.cv_agent/state/experiments.sqlite` for high-volume
experiment rows). ADR-0003 introduces `.cv_agent/state/checkpoints.sqlite` for orchestration
state; this document explicitly reconciles these two SQLite persistence roles to prevent
state leakage or architectural blurring.

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
  - Long-term experiment ledger and persistent project domain memory → Project Memory & Ledger (ADR-0004) `[P§25]`, `[P§33]`, Q8 / D-018;
  - External job submission and training execution on GPU targets → Training Subsystem (ADR-0010) `[P§10]`, `[P§24]`, Q2 / D-014.
- **Why this responsibility does not belong to an existing component:**
  Reasoning decides *what* should be done; tools determine *how* to invoke capabilities;
  orchestration alone coordinates *when* steps occur, tracks lifecycle progress, guarantees
  safe interruption before expensive actions, and ensures recovery upon failure.

## 3. Decision

We define the orchestration layer around a LangGraph `StateGraph(AgentState)` with local
SQLite-backed checkpoint persistence (`SqliteSaver`) stored at `.cv_agent/state/checkpoints.sqlite`
scoped to the project repository (Q1 / D-013), with in-memory `MemorySaver` retained solely
for ephemeral unit tests.

### 3.1. Dual-SQLite Separation and Persistence Reconciliation (Q8 / D-018, `[P§34]`)

To maintain strict architectural boundaries, the repository maintains two distinct SQLite
databases under `.cv_agent/state/` with non-overlapping lifecycles and responsibilities:

```
.cv_agent/state/
├── checkpoints.sqlite    ← ADR-0003: Orchestration runtime state (ephemeral / medium-term)
│                           Owns: super-step snapshots, channel values, pending approval tickets.
│                           Lifecycle: pruneable after session completion / retention expiry.
└── experiments.sqlite    ← ADR-0004 / D-018: Experiment ledger (permanent / long-term)
                            Owns: immutable hyperparameters, metrics, dataset refs, artifact paths.
                            Lifecycle: permanent, reproducible historical record [P§25].
```

**Non-Negotiable Boundary Rules:**
1. **No Silent Ledger Creep:** Orchestration checkpoints must **never** silently become the
   experiment ledger. Node execution snapshots in `checkpoints.sqlite` capture only the
   in-flight runtime state necessary to resume graph execution.
2. **Domain Memory Handoff:** When a workflow node finishes an experiment or reaches a
   milestone, it commits the structured result to the Experiment Ledger (`experiments.sqlite`
   via ADR-0004) and writes persistent domain insights to Git-tracked project memory.
   The orchestration state only retains a string reference (`memory_ref` / `experiment_id`).
3. **Retention & Pruning Independence:** `checkpoints.sqlite` is subject to a configurable
   retention policy (default 30 days post-completion) and can be vacuumed or pruned without
   impacting the permanent experiment history in `experiments.sqlite`.

### 3.2. Core Orchestration Mechanisms

1. **Typed State Schema (`AgentState`):** An explicit, typed dictionary containing
   immutable records for lifecycle status, active lifecycle stage, task definition,
   selected capabilities, execution step log, pending approval tickets, external job
   handles, and runtime error diagnostics.
2. **Persistent Approval Interrupts (Q3 / D-015, `[P§24]`):** Gated operations (GPU training,
   cloud provisioning, destructive data mutations, production deployments per `docs/APPROVALS.md`)
   transition state to `AWAITING_APPROVAL`, emit a structured `ApprovalRequest` with cost/risk
   metadata, trigger a LangGraph interrupt/breakpoint, and commit a persistent checkpoint.
   Resumption is asynchronous via CLI/API by passing an `ApprovalResponse` matching the `request_id`.
3. **Asynchronous External Job Handles (Q2 / D-014):** Nodes submitting long-running GPU
   training or remote evaluations record an `ActiveJobRef` in state. The graph polls or awaits
   job completion tokens without blocking the main orchestrator in-process.
4. **Deterministic Replay and Idempotency:** Every node update appends an indexed `StepRecord` and
   mutates a monotonic step counter. Nodes performing external operations check existing job
   tokens in state before dispatching to prevent duplicate external actions during checkpoint
   restoration or node retries.
5. **Session and Thread Scoping (Q1 / D-013):** Each agent invocation runs under a unique
   `session_id` mapped directly to LangGraph's `thread_id`. File-level SQLite locking ensures
   only one active execution thread modifies a session's state at a time.
6. **Checkpoint Atomicity & Crash Recovery:** SQLite Write-Ahead Logging (WAL) mode guarantees
   atomic super-step commits. Uncommitted partial writes during an abrupt crash rollback
   cleanly, allowing resumption from the last verified super-step snapshot.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| **1. Ephemeral In-Memory Checkpointer (`MemorySaver` only)** | Zero dependencies; trivial setup; already present in Phase 0 prototype. | Fails Q3 / D-015 completely: process termination destroys pending approval state and midway execution traces. Requires re-running entire workflows if interrupted. | Violates persistent approval contract (Q3 / D-015) and reproducibility requirements `[P§25]`. |
| **2. Single Consolidated SQLite Database for Checkpoints & Experiments** | Single file to manage under `.cv_agent/state/`. | Violates `[P§34]` separation of concerns; tightly couples ephemeral orchestration runtime serialization (LangGraph pickle/msgpack channels) with permanent, queryable experiment schema (ADR-0004); makes pruning runtime checkpoints risky for permanent experiment retention. | Violates layer separation and makes retention governance fragile. |
| **3. Custom Finite State Machine (plain Python FSM or Celery/Airflow)** | Full custom control without LangGraph framework constraints; robust DAG scheduling in Airflow. | High implementation overhead; reinvents state graph branching, streaming, and breakpoint interrupts; Airflow/Celery introduces heavy infrastructure dependencies (broker, worker daemons) unsuited for local workstation CLI operation (Q2 / D-014). | `[P§21]` explicitly mandates LangGraph; custom FSMs add unnecessary boilerplate and maintenance burden `[P§34]`. |
| **4. Client-Server Distributed Checkpointer (PostgreSQL / Redis)** | Concurrent multi-user access; enterprise clustering; horizontal scaling. | Violates Q1 / D-013 (single-project local repository isolation) and Q2 / D-014 (local workstation execution); requires running external services/containers for basic local agent usage. | Over-engineering for a local workstation engineering assistant. Local embedded SQLite provides zero-config persistence with ACID reliability. |

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

    # ── Capabilities & Routing (ADR-0001) ─────────────────────────────────
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

    # ── Execution History & Memory Pointer (ADR-0004) ──────────────────────
    steps: list[StepRecord]
    memory_ref: str | None
    experiment_ref: str | None
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
    wal_mode: bool = True


def get_checkpointer(config: OrchestratorConfig) -> BaseCheckpointSaver:
    """
    Instantiate the appropriate LangGraph checkpointer.
    Returns a persistent SqliteSaver targeting config.checkpoint_db_path
    with WAL mode enabled when enable_persistence is True;
    otherwise returns MemorySaver.
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


def prune_checkpoints(
    config: OrchestratorConfig,
    older_than_days: int | None = None,
) -> int:
    """
    Prune completed or expired session checkpoints from checkpoints.sqlite
    older than the specified retention threshold. Does not touch experiments.sqlite.
    Returns count of pruned records.
    """
    ...
```

## 6. Consequences

- **Enables:**
  - Robust resumption of interrupted multi-hour engineering workflows across process restarts;
  - Fully compliant persistent human-in-the-loop approval gates (Q3 / D-015, `[P§24]`);
  - Asynchronous tracking of external GPU training jobs without blocking agent runtime (Q2 / D-014);
  - Complete, reproducible audit trail of node transitions and token usage `[P§25]`;
  - Clean separation between ephemeral orchestration state (`checkpoints.sqlite`) and permanent experiment records (`experiments.sqlite`) per `[P§34]`, Q8 / D-018.
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

## 7. Complete Acceptance Criteria

To achieve acceptance, implementation of ADR-0003 must satisfy the following verifiable contracts:

1. **State Transitions & Validation (`tests/test_graph_state_machine.py`):**
   - Graph enforces valid transitions between lifecycle statuses: `INITIALIZING → PLANNING → AWAITING_APPROVAL → EXECUTING → EVALUATING → COMPLETED/FAILED`.
   - Invalid direct transitions (e.g. `INITIALIZING → DEPLOYING` without `EVALUATING`) raise explicit validation errors.
2. **Checkpoint Atomicity & WAL Mode (`tests/test_checkpoint_atomicity.py`):**
   - Every node completion commits a transactional snapshot to `.cv_agent/state/checkpoints.sqlite` using SQLite WAL mode.
   - Partial writes or unhandled exceptions mid-node roll back the transaction, leaving the prior checkpoint uncorrupted.
3. **Deterministic Restart & Resume (`tests/test_checkpoint_persistence.py`):**
   - A session interrupted by process kill restores identical `AgentState`, step histories, and channel states upon instantiation with the same `session_id`.
4. **Persistent Approval Interrupts (`tests/test_approval_interrupt.py`):**
   - Nodes invoking gated operations (`docs/APPROVALS.md`) emit an `ApprovalRequest`, transition status to `AWAITING_APPROVAL`, trigger a LangGraph interrupt, and save a persistent checkpoint.
   - Graph remains paused across arbitrary process restarts until an explicit approval response is received.
5. **Approval Resolution Handling (`tests/test_approval_resolution.py`):**
   - Resuming with `ApprovalAction.APPROVED` transitions status to `EXECUTING` and proceeds with the gated action.
   - Resuming with `ApprovalAction.REJECTED` gracefully halts or diverts the workflow to alternative planning.
   - Mismatched `request_id` or malformed responses reject resumption with structured errors.
6. **External Asynchronous Job Recovery (`tests/test_job_handle_recovery.py`):**
   - Out-of-process training jobs registered in `active_jobs` retain their handles across restarts; resuming nodes query external job status without re-triggering duplicate training dispatches.
7. **Idempotency & Replay Protection (`tests/test_graph_idempotency.py`):**
   - Checkpoint restoration increments step counters monotonically and uses job submission tokens to prevent duplicate side effects during replay.
8. **Failure Recovery & Error Classification (`tests/test_graph_error_recovery.py`):**
   - Transient network/timeout errors apply retry policies up to max limits; fatal exceptions capture detailed tracebacks into `error` and mark status `FAILED` without corrupting state.
9. **Concurrency & Workspace Locking (`tests/test_graph_concurrency.py`):**
   - SQLite file locks prevent concurrent execution threads from mutating the same session state simultaneously.
10. **State Corruption Handling (`tests/test_corrupt_checkpoint_recovery.py`):**
    - Corrupted state records detect checksum/schema mismatches, log diagnostic errors, and fall back safely to the preceding valid super-step.
11. **Checkpoint Retention & Pruning (`tests/test_checkpoint_pruning.py`):**
    - Invoking `prune_checkpoints()` deletes expired checkpoint blobs older than `checkpoint_retention_days` without modifying `experiments.sqlite` or Git-tracked memory.
12. **Boundary Compliance with ADR-0001 & ADR-0002 (`tests/test_adr_layer_boundaries.py`):**
    - `AgentState` references capability IDs (`ADR-0001`) as pure strings without importing registry resolvers.
    - `AgentState` captures provider/model strings and token counts (`ADR-0002`) without importing provider SDKs into graph nodes.

## 8. Revisit trigger

This decision shall be reopened if:
1. Multi-user concurrent execution within a shared cloud workspace is required, necessitating a client-server checkpointer (e.g. PostgresSaver);
2. Graph state size exceeds SQLite practical single-row blob performance (>50MB per state update), indicating domain artifacts are erroneously leaking into orchestration state rather than Project Memory (ADR-0004);
3. Upstream LangGraph introduces breaking changes to `StateGraph` compilation or `BaseCheckpointSaver` protocols.
