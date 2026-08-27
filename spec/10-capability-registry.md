# CV Engineering Agent — Capability Registry

**Version:** V1.0  
**Machine-readable source:** spec/capability_registry.json  
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

## Resolution Model

~~~text
Task
 ↓
Capability
 ↓
Skill / Tool / Worker / Knowledge resolution
 ↓
Policy check
 ↓
Execution
 ↓
Structured result + artifacts
~~~

Capability selection and execution are separate concerns.

## Capability Metadata

Each capability should define:

- id
- name
- category
- description
- required inputs
- outputs
- relevant skills
- relevant tools
- relevant agents
- knowledge sources
- applicable task types
- prerequisites
- status
- risk level

## Capability Families

### Planning
- cv.requirements.analysis
- cv.problem.formulation

### Data / Modeling
- cv.dataset.audit
- cv.model.selection
- cv.model.inspection

### Training / Experimentation
- cv.training.design
- cv.experiment.management

### Evaluation
- cv.evaluation
- cv.baseline.establishment
- cv.failure.analysis
- cv.benchmarking

### Research / Knowledge
- cv.research
- cv.knowledge.retrieval
- cv.research.verify

### Deployment / Optimization
- cv.deployment.optimization
- cv.deployment.validation

### Orchestration
- cv.skill.resolution

## Architectural Rules

1. Domain capability ownership is separate from coding-worker ownership.
2. A capability may use multiple skills, tools and workers.
3. Availability does not imply automatic execution.
4. Policy determines whether execution is permitted.
5. Material results must produce traceable artifacts.
6. Human and machine registry representations must remain consistent.
7. Provider/model names are not architectural requirements.
8. The resolver must verify that referenced skills and tools are actually available before execution.
