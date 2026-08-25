# CV Engineering Agent — Capability Registry

**Version:** 1.0  
**Machine-readable source:** `spec/capability_registry.json`  
**Status:** This document and the JSON file must remain consistent.  
**Scope:** Computer Vision engineering — model development, evaluation, and deployment.

---

## Entity Types

The registry distinguishes four entity types:

| Type | Definition |
|------|-----------|
| **CAPABILITY** | What the CV Agent needs to accomplish. A goal-oriented unit of work. |
| **SKILL** | Specialized procedural knowledge or instructions available to the agent (e.g., a framework-specific workflow). |
| **TOOL** | An executable interface or program the agent can invoke (e.g., TensorRT CLI, profiler). |
| **AGENT / RUNTIME** | An execution worker the orchestrator can delegate to (e.g., Claude Code, Codex). |
| **KNOWLEDGE SOURCE** | Documentation, research papers, or reference material the agent can consult. |

Capabilities reference skills, tools, agents, and knowledge sources by ID. Skills and tools are **not** implemented here — this registry represents relationships and availability.

---

## Capability Metadata Schema

Each capability carries:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Dot-notation identifier (e.g., `cv.evaluation`) |
| `name` | string | Human-readable name |
| `category` | string | Functional grouping |
| `description` | string | What this capability accomplishes |
| `required_inputs` | list | Input specifications (name, type, description) |
| `outputs` | list | Output specifications |
| `relevant_skills` | list | Skill IDs applicable to this capability |
| `relevant_tools` | list | Tool IDs applicable to this capability |
| `relevant_agents` | list | Agent/runtime IDs that can execute this |
| `knowledge_sources` | list | Knowledge source IDs |
| `applicable_task_types` | list | Task type tags for capability selection |
| `prerequisites` | list | Capability IDs that should be completed first |
| `status` | enum | `available` / `partial` / `experimental` / `unavailable` |
| `risk_level` | enum | `low` / `medium` / `high` |

---

## Registered Capabilities

### `cv.requirements.analysis`
**Category:** planning  
Analyse a Computer Vision problem statement to produce structured requirements: task type (detection, segmentation, classification, etc.), performance targets (accuracy, latency, throughput), hardware constraints, dataset requirements, and deployment context.

**Skills:** problem-decomposition, constraint-analysis  
**Agents:** claude-code  
**Risk:** low

---

### `cv.dataset.audit`
**Category:** data  
Inspect and characterise a Computer Vision dataset: class distribution, image quality, annotation consistency, coverage gaps, and data-leakage risks. Produces a structured audit report and recommendations.

**Skills:** dataset-analysis, label-quality-assessment  
**Tools:** nvidia-dali-inspect  
**Agents:** claude-code  
**Risk:** low

---

### `cv.model.selection`
**Category:** modeling  
Evaluate and recommend CV model architectures for a given task, considering accuracy/latency trade-offs, hardware targets, and available training data volume.

**Skills:** architecture-survey, benchmark-comparison, transfer-learning  
**Knowledge sources:** paperswithcode-cv, nvidia-model-zoo  
**Agents:** claude-code  
**Risk:** low

---

### `cv.training.design`
**Category:** modeling  
Design a training pipeline: data augmentation strategy, loss functions, optimiser, LR schedule, mixed-precision settings, and distributed training topology.

**Skills:** pytorch-training, nvidia-dali, apex-amp, distributed-training  
**Tools:** nvidia-nsight-systems, pytorch-profiler  
**Agents:** claude-code, codex  
**Risk:** medium

---

### `cv.evaluation`
**Category:** evaluation  
Evaluate a trained CV model against a held-out test set. Compute task-appropriate metrics (mAP, mIoU, top-k accuracy, FPS) and produce per-class breakdowns, confusion analysis, and failure-case summaries.

**Skills:** metric-computation, error-analysis  
**Tools:** nvidia-nsight-systems  
**Agents:** claude-code  
**Risk:** low

---

### `cv.benchmarking`
**Category:** evaluation  
Run controlled performance benchmarks across hardware targets (GPU, Jetson, edge devices): throughput, latency percentiles, memory footprint, and power consumption.

**Skills:** trt-profiling, triton-perf-analyzer, jetson-power-measurement  
**Tools:** trt-profile, triton-perf-analyzer, nvidia-smi, tegrastats  
**Agents:** claude-code, cuda-agent  
**Risk:** medium

---

### `cv.model.inspection`
**Category:** analysis  
Inspect model internals: parameter counts, layer structure, FLOPs, activation statistics, gradient flow, and interpretability visualisations (GradCAM, feature maps, attention maps).

**Skills:** model-surgery, gradcam, flop-counting  
**Tools:** pytorch-summary, netron  
**Agents:** claude-code  
**Risk:** low

---

### `cv.deployment.optimization`
**Category:** deployment  
Optimise a trained CV model for target deployment: TensorRT engine building, quantisation (INT8/FP16), pruning, kernel fusion, and DeepStream pipeline integration.

**Skills:** tensorrt, deepstream, nvidia-model-optimizer, cuda-agent, jetson  
**Tools:** trt-build, trt-profile, deepstream-runtime, nvidia-profiling-tools, tao-toolkit  
**Agents:** claude-code, cuda-agent  
**Knowledge sources:** tensorrt-docs, deepstream-docs, jetson-developer-guide  
**Risk:** high

---

### `cv.research`
**Category:** research  
Survey the research literature for a given CV problem: identify state-of-the-art methods, summarise key papers, compare approaches, and produce a structured literature review with links to implementations.

**Skills:** arxiv-search, paperswithcode-search, citation-analysis  
**Knowledge sources:** arxiv-cv, paperswithcode-cv, semantic-scholar  
**Agents:** claude-code  
**Risk:** low

---

## Registry Extension

To add a new capability:
1. Add an entry to `spec/capability_registry.json` following the schema above.
2. Update this document to keep human and machine representations consistent.
3. Add skills/tools/agents/knowledge_sources entries if they are not already present.
4. Do **not** implement the capability as Python code in the registry module — the registry represents relationships, not implementations.
