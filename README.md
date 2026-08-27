# CV Engineering Agent

Independent, production-oriented Computer Vision engineering agent built around LangGraph and a project-owned CV engineering architecture.

## Purpose

Turn ambiguous real-world CV requests into evidence-backed, reproducible engineering work:

~~~text
Requirement
→ Research / Problem Framing
↔ Problem Formulation
→ Architecture
→ Data
→ Model
→ Experiment
→ Training
→ Evaluation
→ Benchmark
→ Failure Analysis
→ Optimization / NAS when justified
→ Deployment
→ Production Validation
→ Monitoring
~~~

The lifecycle is iterative. The agent may revisit earlier stages when new evidence changes a decision.

## Current Foundation

The repository currently provides:

- LangGraph runtime foundation
- shared agent state
- LLM provider abstraction and mock provider
- configuration
- capability registry
- foundational V1.0 architecture specifications
- artifact and experiment contracts
- automated tests for the existing runtime

## Architecture

~~~text
CV Engineering Agent
├── LangGraph Orchestrator
├── Agent Runtime / Project State
├── LLM Gateway
├── Policy / Approval Engine
├── Capability Registry
├── Capability / Skill Resolver
├── Knowledge + RAG
├── Research Engine
├── MCP / Tool Layer
├── Experiment Manager
├── Artifact Manager
├── Model Inspector
└── CV Engineering Agents
~~~

Important architectural boundary:

~~~text
LLM Provider / Model
        ≠
Coding Worker Runtime
        ≠
MCP Tool / Resource
        ≠
CV Engineering Agent
        ≠
Skill
        ≠
Knowledge Source
~~~

Codex CLI and Claude Code are coding-worker runtimes. They are not the domain agents or provider abstraction.

## Technology Baseline

| Layer | Baseline |
|---|---|
| Orchestration | LangGraph |
| LLM abstraction | Project-owned interface + provider adapters |
| Knowledge/RAG | Project-owned abstraction initially |
| Research | Project-owned evidence/research layer |
| Tool protocol | MCP through an adapter boundary |
| Coding workers | Codex CLI, Claude Code |
| CV execution | Python / C++ / CUDA / DeepStream as applicable |
| Training | PyTorch + task/framework trainers |
| Benchmarking | Project-owned benchmark layer |
| Vector store | TBD |
| Model inspection | Project-owned inspector + Netron visualization |

## NVIDIA / Edge Capabilities

The architecture is designed to use applicable installed NVIDIA and CUDA capabilities, including:

- NVIDIA TAO
- DALI
- DeepStream
- TensorRT
- NVIDIA Model Optimizer
- CUDA-Agent
- Jetson tooling
- GPU profiling
- kernel optimization

The capability resolver should select only the capabilities relevant to the current engineering task.

## Knowledge and Research

The knowledge system combines:

~~~text
Stable / Canonical Knowledge
        +
Current Technology Knowledge
        +
Live Research
~~~

Important research sources include:

- NVIDIA
- Ultralytics / YOLO
- Roboflow
- Hugging Face
- GitHub
- research papers
- official documentation
- engineering blogs
- practitioner sources including LinkedIn

Community content is a discovery signal and should be verified before supporting important engineering decisions.

## Repository Structure

~~~text
cv_agent/
├── capabilities/   # Capability registry interface
├── config/         # Configuration
├── graph/          # LangGraph state and graph
├── llm/            # LLM abstraction
└── runtime/        # Top-level CVAgent runtime

spec/
├── 00-vision.md
├── 01-principles.md
├── 02-architecture.md
├── 03-agent-runtime.md
├── 04-knowledge-and-research.md
├── 05-cv-engineering-lifecycle.md
├── 06-tooling-and-mcp.md
├── 07-human-approval-and-safety.md
├── 08-training-and-optimization.md
├── 09-artifact-and-experiment-contracts.md
├── 10-capability-registry.md
└── capability_registry.json

docs/
└── development/
    └── GITHUB_FLOW_V1.md
~~~

## Development Model

Development is performed through:

~~~text
Short-lived feature branch
        ↓
PR → dev-munna
        ↓
CI/CD
        ↓
Technical Review
        ↓
AJ / Development PM Approval
        ↓
dev-munna
~~~

The official main branch is outside the normal agent development workflow.

## Installation

~~~bash
pip install -e ".[dev]"
~~~

## Tests

~~~bash
pytest tests/ -v
~~~

## Status

The project is currently establishing its V1.0 architecture and contracts. Runtime execution, live research, RAG, MCP tools, training, benchmarking, optimization, and deployment capabilities are being added incrementally behind these contracts.
