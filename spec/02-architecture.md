# CV Engineering Agent — System Architecture

**Version:** V1.0  
**Status:** Foundational specification

## System Boundary

~~~text
User / Client
      ↓
CV Engineering Agent
      │
      ├── LangGraph Orchestrator
      ├── Agent Runtime / Project State
      ├── LLM Gateway
      ├── Policy / Approval Engine
      ├── Capability Registry
      ├── Capability + Skill Resolver
      ├── Knowledge + RAG
      ├── Research Engine
      ├── MCP / Tool Adapters
      ├── Experiment Management
      ├── Artifact Management
      ├── Model Inspector
      └── CV Engineering Agents
             ├── Requirements
             ├── Problem Formulation
             ├── Research
             ├── Architecture
             ├── Dataset
             ├── Model
             ├── Experiment
             ├── Training
             ├── Evaluation
             ├── Failure Analysis
             ├── Benchmark
             ├── Optimization
             ├── Deployment
             └── Monitoring
~~~

## Primary Product Abstraction

The system is organized around an adaptive CV engineering lifecycle, not around code generation:

~~~text
CV Problem
   ↓
Discover → Define → Research → Design → Data → Baseline
   ↓
Train → Evaluate → Diagnose → Optimize → Benchmark
   ↓
Deploy → Monitor → Iterate
~~~

Not every project requires every stage. The runtime determines the required stages from the project state, constraints, evidence, and approved scope.

## Responsibility Planes

The architecture separates three primary responsibilities:

~~~text
REASONING              KNOWLEDGE                 EXECUTION
LLM Gateway            RAG / Project Memory      MCP / Tools
LangGraph              Live Research             Skills
Project-owned agents   Evidence / Sources        Coding Workers
                                               Training / Profiling
~~~

The separation is normative:

- **LLM** provides reasoning; it does not own project state or execution semantics.
- **LangGraph** owns workflow orchestration, branching, iteration, interrupts, and recovery.
- **Knowledge/RAG** provides grounded retrieval; it does not replace reasoning.
- **Research** acquires current information and preserves provenance/freshness.
- **Capabilities** describe what the system can accomplish.
- **Skills** provide specialized procedural knowledge.
- **Tools/MCP** provide controlled executable interfaces.
- **Training/Evaluation/Benchmarking** are execution and measurement subsystems, not LLM responsibilities.
- **Project memory** preserves durable project state, decisions, datasets, experiments, and evidence.

## Component Responsibilities

| Component | Responsibility |
|---|---|
| Orchestrator | Route workflows and enforce state transitions |
| Agent Runtime | Sessions, state, persistence, interrupts, recovery |
| LLM Gateway | Provider/model abstraction, routing, retries, usage metadata |
| Policy Engine | Approval, permissions, budgets, risk controls |
| Capability Registry | Declare available capabilities and relationships |
| Capability/Skill Resolver | Map task requirements to applicable capabilities, skills, tools and workers |
| Knowledge/RAG | Retrieve grounded project and technology knowledge |
| Research Engine | Discover, fetch, verify, rank and normalize external knowledge |
| MCP/Tool Layer | Controlled execution interfaces |
| Experiment Manager | Experiment definitions, lineage, execution metadata and comparison |
| Artifact Manager | Persist and index durable outputs |
| Model Inspector | Machine-readable model/graph analysis |
| CV Agents | Domain-specific engineering reasoning |

## Critical Distinctions

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

Examples:

- Claude, OpenAI, Qwen, DeepSeek and local models are LLM/provider choices.
- Codex CLI and Claude Code are coding-worker runtimes.
- Training, GPU profiling, GitHub, research, TensorRT and DeepStream interfaces are tools.
- RequirementAgent, ModelAgent and TrainingAgent are project-owned domain agents.
- TensorRT, TAO and CUDA workflows are specialized skills.
- NVIDIA documentation, papers and verified engineering sources are knowledge sources.

## Capability Resolution

~~~text
Task
 ↓
Capability selection
 ↓
Capability Registry
 ↓
Skill / Tool / Worker resolution
 ↓
Platform Profile
 ↓
Policy check
 ↓
Execution
 ↓
Structured result + artifacts
 ↓
State / decision update
~~~

The registry describes availability and relationships; it does not execute work.

## Model Inspection

~~~text
Model
 ├──→ Model Inspector → structured analysis for agents
 └──→ Netron → human visualization/reference
~~~

Netron is not a runtime dependency of the agent.

## Technology Baseline

| Layer | Baseline |
|---|---|
| Orchestration | LangGraph |
| LLM abstraction | Project-owned thin interface + provider adapters |
| Knowledge/RAG | Project-owned abstraction initially |
| Research | Project-owned research/evidence abstraction + web/source adapters |
| Tool protocol | MCP where appropriate |
| Coding workers | Codex CLI, Claude Code |
| CV execution | Python / C++ / CUDA / DeepStream as applicable |
| Training | PyTorch + task/framework trainers |
| Experiment tracking | Project-owned experiment contract; backend TBD |
| Benchmarking | Project-owned standardized benchmark layer |
| Vector store | TBD |
| Model inspection | Project-owned inspector + Netron visualization |

LangChain may be used selectively for useful integrations, but core CV engineering contracts remain project-owned.

## Replaceability

The architecture must allow a provider, coding worker, vector store, research adapter, MCP implementation, or inference backend to be replaced without changing the CV lifecycle contracts.

## Non-Goals

V1.0 does not require a single permanent vector database, a specific LLM vendor, a specific MCP transport, or NAS for every project.

## Platform Detection and Optimization

Platform detection is a first-class component. Before platform-dependent installation, training, profiling, inference, or deployment, the agent must produce a structured platform profile covering OS, architecture, CPU, memory, GPU/accelerator, driver/runtime state, framework support, and Jetson-specific information where applicable.

Supported platform classes are macOS, Linux, Windows, and NVIDIA Jetson. Jetson is treated as a distinct platform profile because its JetPack/Jetson Linux, ARM64, CUDA, TensorRT, DeepStream, power, and thermal characteristics materially affect execution.

The platform layer must distinguish hardware presence from hardware accessibility, driver availability, runtime availability, and framework support. The agent must select installation and optimization actions from the verified profile rather than from a generic command set.

See `spec/11-platform-detection-and-optimization.md` for the platform contract.

## Product Architecture Rule

The internal implementation roadmap and the product lifecycle are separate concepts. The repository may build Runtime, LLM, Knowledge, Research, Tooling, Training, and other subsystems in an order appropriate for engineering delivery, while the user-facing system remains organized around the CV engineering lifecycle.

No subsystem may become the product abstraction merely because it is technically convenient to implement first.