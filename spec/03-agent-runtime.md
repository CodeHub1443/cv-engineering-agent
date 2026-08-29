# CV Engineering Agent — Agent Runtime

**Version:** V1.0  
**Status:** Foundational specification

## Purpose

Define the execution contract for stateful CV engineering workflows.

## Runtime Model

~~~text
Request
  ↓
Load / Create Project State
  ↓
LangGraph Workflow
  ↓
Agent Node
  ├── LLM reasoning
  ├── Knowledge retrieval
  ├── Capability / skill resolution
  ├── Tool execution
  └── Human approval / interrupt
  ↓
State + Artifacts + Decision Trace
~~~

## State Domains

The runtime state should explicitly represent, as applicable:

- session identity and lifecycle status
- project/task context
- requirements and unknowns
- active provider/model
- selected capabilities
- pending actions and approvals
- execution steps
- research/evidence references
- artifacts
- experiments and results
- decisions
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

Provider/model selection belongs to configuration and routing.

## Tool Contract

A node requests a capability/tool operation through a controlled interface. It must receive structured results rather than parsing arbitrary shell output whenever a typed tool is available.

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
- which capability/tool/worker was selected;
- who/what executed it;
- execution status;
- outputs;
- artifacts;
- relevant metrics;
- errors;
- decision/result.

## Coding Workers

Codex CLI and Claude Code are delegated coding-worker runtimes. They operate behind controlled execution and repository policies.

They are not the source of truth for project state or architecture.
