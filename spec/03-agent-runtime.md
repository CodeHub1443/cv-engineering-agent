# CV Engineering Agent — Agent Runtime

**Version:** V1.1
**Status:** Technical elaboration of `docs/PROJECT.md` (frozen canon, cited as
`[P§n]`) and `docs/architecture/OVERVIEW.md`'s Orchestration layer (ADR-0003, not
yet written). This file does not restate the canon's vision, philosophy, or lifecycle
diagram — see `docs/PROJECT.md` §6 for those. It elaborates the *runtime execution
contract* that a future ADR-0003 must formalize.

> **Implementation status:** none of this is built yet. The actual runtime today is
> `cv_agent/graph/builder.py` — a two-node `START → initialize → END` LangGraph stub.
> See `docs/state/STATUS.md`. Do not read this file as a description of current
> behavior.

## Purpose

Define the execution contract for stateful CV engineering workflows, for a future
ADR-0003 (orchestration state + approval interrupts, per `docs/roadmap/ROADMAP.md`
Phase 1) to formalize.

## Runtime Model

~~~text
Request
  ↓
Load / Create Project State
  ↓
Discover required lifecycle stages   [P§6]
  ↓
LangGraph Workflow
  ↓
Agent Node
  ├── LLM reasoning
  ├── Knowledge retrieval
  ├── Research when required
  ├── Capability / skill resolution
  ├── Platform verification
  ├── Tool execution
  └── Human approval / interrupt
  ↓
State + Artifacts + Decision Trace
~~~

The lifecycle stages referenced above are `docs/PROJECT.md` §6's canonical sequence
(elaborated per-stage in `docs/GLOSSARY.md`'s stage table) — not redefined here.

## State Domains

The runtime state should explicitly represent, as applicable:

- session identity and lifecycle status
- project/task context
- requirements and unknowns
- active provider/model
- selected capabilities
- selected skills/tools/workers
- platform profile
- pending actions and approvals
- execution steps
- research/evidence references
- artifacts
- datasets and versions
- experiments and results
- decisions
- resource usage/cost metadata
- errors and recovery metadata

The current AgentState is the foundation. Future state additions must be explicit, typed, versioned when necessary, and backward-compatible where practical.

## Lifecycle

~~~text
initializing → ready → running → paused → running → done
                         └──────────────→ error
~~~

paused represents an intentional wait, typically for human approval or required user input.

## Node Contract

Each node should:

- have one primary responsibility;
- receive typed state/context;
- return structured partial state updates;
- emit traceable events where execution matters;
- avoid owning global workflow routing.

LangGraph owns topology and transitions. Domain logic stays in project-owned components.

## LLM Contract

Agent nodes receive an abstract LLM interface. They must not instantiate vendor SDKs directly.

Provider/model selection belongs to configuration and routing. The architecture must permit replaceable providers and models, including Claude, OpenAI/Codex-compatible models, Qwen, DeepSeek, local models, and future providers where supported.

## Tool Contract

A node requests a capability/tool operation through a controlled interface. It must receive structured results rather than parsing arbitrary shell output whenever a typed tool is available.

## Expensive / Consequential Execution

The runtime should estimate material resource cost and risk before expensive or consequential operations. Examples include large training runs, NAS, broad hyperparameter searches, cloud GPU consumption, system-level installation changes, destructive data operations, and production deployment.

Where policy requires it, the runtime pauses for explicit approval before execution. Planning approval must not be interpreted as execution approval.

## Failure Handling

The runtime must classify failures as:

- validation failures;
- transient provider/tool failures;
- permanent execution failures;
- policy/approval failures;
- cancellation/timeouts;
- unrecoverable failures.

Retries are bounded and only allowed for operations known to be safe to retry. Non-idempotent actions must not be blindly replayed.

## Human Interrupts

Approval is a runtime state transition.

~~~text
proposed action
   ↓
policy evaluation
   ↓
pause
   ↓
human decision
   ↓
resume / reject
~~~

A planning approval is not execution approval.

## Checkpointing / Resumption

A resumable run must retain sufficient state and a stable run/thread identifier to continue after interruption or process restart.

The long-term production implementation may replace the current in-memory checkpointer with a durable backend without changing agent contracts.

## Artifacts and Trace

Material actions must preserve:

- what was proposed;
- which lifecycle stage was active;
- which capability/skill/tool/worker was selected;
- who/what executed it;
- execution status;
- outputs;
- artifacts;
- relevant metrics;
- resource usage;
- errors;
- decision/result.

## Coding Workers

Codex CLI and Claude Code are delegated coding-worker runtimes. They operate behind controlled execution and repository policies.

They are not the source of truth for project state or architecture.
