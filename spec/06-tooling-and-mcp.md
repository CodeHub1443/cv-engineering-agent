# CV Engineering Agent — Tooling and MCP

**Version:** V1.0  
**Status:** Foundational specification

## Purpose

Define the boundary between agent reasoning and executable operations.

~~~text
Agent
  ├── LLM
  ├── Knowledge
  ├── Capability Resolver
  └── Tools / Workers
          ↓
      controlled interfaces
~~~

## Execution Principle

Agents determine **what** should happen. Tools/workers determine **how** it happens.

The agent should prefer typed interfaces over arbitrary shell execution.

## Capability Resolution

~~~text
Task
 ↓
Capability
 ↓
Skill
 ↓
Tool / Worker
 ↓
Policy
 ↓
Execution
 ↓
Structured Result
~~~

The capability registry describes relationships. The runtime performs resolution and policy checks.

## Tool Families

Initial conceptual interfaces include:

~~~text
research.search
research.fetch
github.search

dataset.inspect
dataset.validate
dataset.prepare

model.inspect
model.export

experiment.create
experiment.compare

training.plan
training.start
training.status
training.stop

evaluation.run
benchmark.run
gpu.profile

onnx.export
tensorrt.build
deepstream.test

docker.build
deployment.validate
~~~

Names are stable conceptual boundaries, not mandatory final function names.

## MCP

MCP is an integration protocol, not the definition of CV engineering semantics.

Project-owned tool contracts remain independent of MCP so the application can evolve protocol and SDK versions without rewriting domain logic.

For current implementations, target MCP through an adapter layer rather than binding the core runtime to a specific MCP transport or SDK version. The 2026-07-28 specification introduced a stateless protocol core and changed the surrounding extension and authorization model, so protocol/version details belong in the adapter layer. citeturn832299search0turn832299search4

Where relevant, distinguish:

~~~text
Tools
Resources
Prompts
Long-running Tasks / extensions
~~~

according to the selected MCP specification and SDK version.

## Tool Result Contract

A material tool should return structured data containing, where relevant:

~~~text
status
result
artifacts
metrics
logs
errors
provenance
execution_metadata
~~~

Long-running operations should expose a stable operation or experiment identifier and status retrieval.

## Coding Workers

Codex CLI and Claude Code are coding-worker runtimes.

They are:

- not CV domain agents;
- not MCP tools;
- not the LLM provider abstraction.

They may be invoked through controlled execution interfaces for authorized repository work.

## NVIDIA / CUDA Tooling

Relevant integrations include:

- NVIDIA skills;
- CUDA-Agent;
- TensorRT;
- DeepStream;
- Jetson tooling;
- GPU profiling;
- Model Optimizer;
- kernel optimization.

Capability resolution determines when these are applicable.

## Safety

Every external or materially consequential operation must be policy-checked before execution where required.

The tool layer must not infer approval from the existence of a planning request.
