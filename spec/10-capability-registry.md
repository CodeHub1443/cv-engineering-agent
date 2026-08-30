# CV Engineering Agent — Capability Registry

**Version:** V1.0  
**Machine-readable source:** `spec/capability_registry.json`  
**Status:** Human and machine representations must remain consistent.

## Purpose

The registry maps goal-oriented CV capabilities to applicable skills, tools, workers and knowledge sources. It describes availability and relationships; it does not execute work.

## Entity Types

| Type | Definition |
|---|---|
| CAPABILITY | Goal-oriented engineering outcome. |
| SKILL | Specialized procedural knowledge or workflow. |
| TOOL | Executable interface for an operation. |
| AGENT / RUNTIME | Worker/runtime that can perform delegated work. |
| KNOWLEDGE SOURCE | Reference material used for grounded reasoning. |

## Registry Identity

Registry items are uniquely identified by the pair:

```text
(item_type, id)
```

IDs are **not globally unique across entity types**. The same ID may legitimately occur for different entity types and must never overwrite another entity during registry loading or lookup.

Examples:

```text
(skill, cuda-agent)
(agent, cuda-agent)

(skill, triton-perf-analyzer)
(tool, triton-perf-analyzer)
```

Listing, description, checking, and selection operations must preserve the requested entity type. Backward-compatible ID-only operations may be retained only where the type is unambiguous; ambiguous IDs must not be guessed.

## Resolution Model

```text
Task
 ↓
Capability
 ↓
Skill / Tool / Worker / Knowledge resolution
 ↓
Platform compatibility
 ↓
Policy check
 ↓
Execution
 ↓
Structured result + artifacts
```

Capability selection and execution are separate concerns.

## Platform Rule

Platform-dependent capabilities must resolve a verified `PlatformProfile` before installation, training, profiling, inference, or deployment.

## Capability Metadata

Each capability should define:

- `id`
- `name`
- `category`
- `description`
- `required_inputs`
- `outputs`
- `relevant_skills`
- `relevant_tools`
- `relevant_agents`
- `knowledge_sources`
- `applicable_task_types`
- `prerequisites`
- `status`
- `risk_level`

## Capability Families

### Planning

- `cv.requirements.analysis`
- `cv.problem.formulation`

### Data / Modeling

- `cv.dataset.audit`
- `cv.model.selection`
- `cv.model.inspection`

### Training / Experimentation

- `cv.training.design`
- `cv.experiment.management`

### Evaluation

- `cv.evaluation`
- `cv.baseline.establishment`
- `cv.failure.analysis`
- `cv.benchmarking`

### Research / Knowledge

- `cv.research`
- `cv.knowledge.retrieval`
- `cv.research.verify`

### Deployment / Optimization

- `cv.deployment.optimization`
- `cv.deployment.validation`

### Platform

- `platform.detect`
- `platform.verify`
- `platform.optimization`

### Orchestration

- `cv.skill.resolution`

## Architectural Rules

1. Domain capability ownership is separate from coding-worker ownership.
2. A capability may use multiple skills, tools and workers.
3. Registry identity is `(item_type, id)`; cross-type IDs must never overwrite one another.
4. Availability does not imply automatic execution.
5. Policy determines whether execution is permitted.
6. Platform-sensitive capabilities must verify the detected platform before execution.
7. Material results must produce traceable artifacts.
8. Human and machine registry representations must remain consistent.
9. Provider/model names are not architectural requirements.
10. The resolver must verify that referenced skills and tools are actually available before execution.
