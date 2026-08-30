# CV Engineering Agent — Tooling and MCP

**Version:** V1.0  
**Status:** Foundational specification

## Purpose

Define the boundary between agent reasoning and executable operations.

```text
Agent
  ├── LLM
  ├── Knowledge
  ├── Capability Resolver
  └── Tools / Workers
          ↓
      controlled interfaces
```

## Execution Principle

Agents determine **what** should happen. Tools/workers determine **how** it happens.

The agent should prefer typed interfaces over arbitrary shell execution.

## Capability / Skill / Tool / Worker Model

These concepts are intentionally separate:

| Concept | Responsibility | Example |
|---|---|---|
| Capability | Goal-oriented engineering outcome | model optimization |
| Skill | Specialized procedural knowledge/workflow | NVIDIA Model Optimizer PTQ |
| Tool | Executable interface for an operation | TensorRT profiling |
| Agent / Worker | Reasoning or delegated execution worker | CUDA Agent, Claude Code |
| Knowledge Source | Evidence used for grounded reasoning | NVIDIA documentation |

Resolution should follow the requirement rather than the implementation technology:

```text
User Task
 ↓
Required Capability
 ↓
Applicable Skill(s)
 ↓
Required Tool(s) / Worker(s)
 ↓
Platform Profile
 ↓
Policy
 ↓
Execution
```

## Capability Resolution

```text
Task
 ↓
Capability
 ↓
Skill
 ↓
Tool / Worker
 ↓
Platform Profile
 ↓
Policy
 ↓
Execution
 ↓
Structured Result
```

The capability registry describes relationships. The runtime performs resolution, platform checks, and policy checks.

## Tool Families

Initial conceptual interfaces include:

```text
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

platform.detect
platform.verify
platform.profile
platform.optimize

onnx.export
tensorrt.build
deepstream.test

docker.build
deployment.validate
```

Names are stable conceptual boundaries, not mandatory final function names.

## Platform-Aware Tooling

Platform detection must occur before platform-dependent installation or optimization.

Every platform-sensitive tool should receive or resolve a verified `PlatformProfile` rather than assuming Linux, Windows, macOS, or Jetson semantics.

Installation tools must distinguish inspection from mutation. System changes should expose the intended change set and pass policy before execution.

## MCP

MCP is an integration protocol, not the definition of CV engineering semantics.

Project-owned tool contracts remain independent of MCP so the application can evolve protocol and SDK versions without rewriting domain logic.

MCP-specific transport, authorization, SDK, and version details belong in the adapter layer. Do not hard-code those details into CV domain contracts.

Where relevant, distinguish:

```text
Tools
Resources
Prompts
Long-running Tasks / extensions
```

according to the selected MCP specification and SDK version.

## Tool Result Contract

A material tool should return structured data containing, where relevant:

```text
status
result
artifacts
metrics
logs
errors
provenance
execution_metadata
```

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

Capability resolution determines when these are applicable and the platform detector determines whether the local target can support them.

The agent should use existing specialized NVIDIA/CUDA capabilities rather than duplicating their implementation inside the CV domain layer.

## Safety

Every external or materially consequential operation must be policy-checked before execution where required.

The tool layer must not infer approval from the existence of a planning request.
