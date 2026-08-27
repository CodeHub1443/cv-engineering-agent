# CV Engineering Agent V1.0 — GitHub Development & Delivery Flow

**Status:** Approved Working Process  
**Version:** V1.0  
**Repository:** `CodeHub1443/cv-engineering-agent`

---

## 1. Purpose

This document defines how CV Engineering Agent V1.0 is developed, reviewed, tested, approved, merged, and released through GitHub.

The project follows:

- Trunk-based development
- Short-lived branches
- Pull Requests
- Mandatory CI/CD validation
- Project Manager approval
- Protected integration branches
- Small, isolated feature increments
- One feature at a time

---

## 2. Core Branching Model

The repository has two important branch roles:

```text
actual main
    = official project trunk / release integration branch

 dev-munna
    = development trunk / working integration branch
```

### Absolute rules

`main` must never be used for day-to-day development.

For this project, `dev-munna` is the development branch on which AJ acts as the Project Manager for the working development stream.

The intended promotion flow is:

```text
feature branch
      |
      v
 dev-munna
      |
      |  development PM approval
      v
actual main
      |
      v
 official project state / release
```

No feature is developed directly on `dev-munna` either. All feature work uses short-lived branches.

The actual `main` branch remains the final project integration/release authority and should be protected separately.

---

## 3. One Feature at a Time

The default workflow is sequential:

```text
Feature A
   |
   v
short-lived branch
   |
   v
implementation
   |
   v
local tests
   |
   v
PR -> dev-munna
   |
   v
CI/CD
   |
   v
AJ / development PM approval
   |
   v
merge to dev-munna
   |
   v
Feature B
```

We do not start unrelated feature branches unless there is a clear dependency or project-management reason.

If a feature becomes too large, split it into smaller features.

---

## 4. Branch Naming

Feature branches:

```text
feature/<short-name>
```

Examples:

```text
feature/architecture-doc
feature/runtime-orchestrator
feature/llm-gateway
feature/research-engine
feature/rag-pipeline
feature/mcp-tool-layer
feature/requirement-agent
feature/dataset-agent
feature/model-agent
feature/training-engine
feature/evaluation-engine
feature/benchmark-engine
feature/optimization-engine
feature/nvidia-tooling
feature/tensorrt-integration
feature/deepstream-integration
feature/deployment-engine
```

Bug fixes:

```text
fix/<short-name>
```

CI/CD changes:

```text
ci/<short-name>
```

Documentation-only changes:

```text
docs/<short-name>
```

Urgent fixes:

```text
hotfix/<short-name>
```

Branches must remain short-lived.

Target lifetime:

```text
Ideal:       < 1 day
Acceptable:  1–3 days
Exceptional: > 3 days
```

---

## 5. Development Trunk: `dev-munna`

`dev-munna` is the project's **working integration trunk**.

It exists so that development can be performed and validated independently of the official `main` branch.

AJ is the development Project Manager for `dev-munna`.

Responsibilities of the `dev-munna` PM gate:

- verify feature scope
- verify acceptance criteria
- verify tests
- verify architecture compatibility
- verify documentation
- verify risk
- decide whether the feature is ready to become part of the development trunk

The branch is not a substitute for feature branches.

```text
feature/*
   |
   +--> dev-munna
```

not:

```text
developer --> dev-munna directly
```

---

## 6. Official `main`

`main` is the official project trunk.

It represents the approved project state that the actual project manager can accept for official integration and release.

Rules:

```text
DO NOT develop directly on main.
DO NOT push directly to main.
DO NOT experiment directly on main.
DO NOT merge to main without the official project-manager gate.
```

Promotion is:

```text
dev-munna
    |
    v
official PR
    |
    v
CI/CD
    |
    v
official PM review
    |
    v
main
```

The official project manager may reject or request changes to a `dev-munna` promotion without affecting the development trunk.

---

## 7. Pull Request Model

### Feature PR

```text
feature/<name>
      |
      v
PR -> dev-munna
```

### Official promotion PR

```text
dev-munna
      |
      v
PR -> main
```

This gives the project two explicit approval boundaries:

1. **Development PM gate:** feature -> `dev-munna`
2. **Official PM gate:** `dev-munna` -> `main`

---

## 8. Pull Request Requirements

Every PR must contain:

- problem statement
- scope
- implementation summary
- architecture impact
- tests performed
- acceptance criteria
- risks
- dependencies
- documentation impact
- screenshots/logs where useful

Recommended PR structure:

```markdown
## Problem

## Scope

## Changes

## Architecture Impact

## Tests

## Risks

## Dependencies

## Acceptance Criteria
```

---

## 9. CI/CD Gate

Every PR must pass automated validation before approval.

Minimum pipeline:

```text
Pull Request
     |
     v
Formatting
     |
     v
Linting
     |
     v
Type Checking
     |
     v
Unit Tests
     |
     v
Integration Tests
     |
     v
Security Checks
     |
     v
Package Build
     |
     v
Architecture / Spec Checks
```

GPU-specific CI should be added when GPU infrastructure is available:

```text
CUDA
TensorRT
DeepStream
GPU integration
```

CPU CI must remain capable of validating the core software architecture.

---

## 10. Local Validation Before Push

Before opening a PR, the developer should run the equivalent local checks.

Example:

```bash
pytest tests/ -v
```

and the project's configured formatting, linting, typing, and build commands.

A PR should not be used as the first place where obvious failures are discovered.

---

## 11. Review Gates

### Gate A — Technical Review

Review:

- correctness
- maintainability
- architecture
- tests
- security
- performance implications
- API compatibility

### Gate B — Development PM Approval

AJ, acting as development PM for `dev-munna`, verifies:

- feature is complete
- acceptance criteria are satisfied
- CI is green
- documentation is updated
- architecture remains consistent
- feature is appropriate for the current milestone

Only then may the feature merge into `dev-munna`.

### Gate C — Official Project Manager Approval

Promotion from `dev-munna` to `main` requires the actual project manager's approval.

```text
dev-munna
   |
   v
Official PR
   |
   v
Official PM approval
   |
   v
main
```

---

## 12. Merge Strategy

Use squash merging for normal feature branches.

Example:

```text
feature/llm-gateway
      |
      | development commits
      v
PR
      |
      v
CI + review + PM approval
      |
      v
squash merge
      |
      v
dev-munna
```

The development trunk should contain meaningful milestone commits rather than noisy fix-up history.

---

## 13. Keeping Branches Current

Before opening or merging a PR:

```bash
git fetch origin
git rebase origin/dev-munna
```

For a branch intended for official promotion, update it against the latest `dev-munna` first.

If a short-lived branch needs a force push after rebasing:

```bash
git push --force-with-lease
```

Never force-push `main`.

---

## 14. Feature Completion Definition

A feature is complete only when:

```text
[ ] Implementation complete
[ ] Unit tests complete
[ ] Integration tests complete where required
[ ] Documentation updated
[ ] Configuration updated where required
[ ] Security considerations reviewed
[ ] Local validation passes
[ ] CI passes
[ ] Technical review complete
[ ] Development PM approval received
[ ] PR merged to dev-munna
[ ] Post-merge dev-munna CI passes
[ ] Branch deleted
```

A feature is therefore not considered complete merely because its code works locally.

---

## 15. Official Promotion Completion

A development increment is officially promoted only when:

```text
[ ] dev-munna is green
[ ] Official promotion PR created
[ ] CI passes
[ ] Official project manager review complete
[ ] Official PM approval received
[ ] PR merged to main
[ ] main post-merge CI passes
```

---

## 16. Workstream Distribution

The V1.0 project is divided into engineering workstreams, but workstreams are not long-lived branches.

### Architecture & Documentation

```text
docs/architecture-*
docs/lifecycle-*
docs/artifact-*
```

Owns:

- architecture
- lifecycle
- contracts
- safety
- approval policy
- development standards

### Core Runtime

```text
feature/runtime-*
```

Owns:

- LangGraph
- state
- sessions
- checkpointing
- interrupts
- resume
- retries

### LLM Gateway

```text
feature/llm-*
feature/provider-*
```

Owns:

- provider abstraction
- model routing
- structured output
- streaming
- tool calling
- retries
- fallbacks

### Knowledge / RAG

```text
feature/source-registry
feature/knowledge-*
feature/rag-*
```

Owns:

- canonical knowledge
- technology knowledge
- live research knowledge
- retrieval
- embeddings
- reranking
- provenance
- freshness

### Research Engine

```text
feature/research-*
```

Owns:

- web research
- GitHub research
- papers
- NVIDIA
- YOLO / Ultralytics
- Roboflow
- Hugging Face
- LinkedIn discovery signals
- evidence verification

### MCP / Tools

```text
feature/mcp-*
feature/tool-*
```

Owns typed execution boundaries for:

- research
- GitHub
- datasets
- training
- evaluation
- benchmarking
- GPU profiling
- model conversion
- TensorRT
- DeepStream
- Docker

### CV Intelligence

```text
feature/requirement-*
feature/research-agent-*
feature/architecture-agent-*
feature/dataset-agent-*
feature/model-agent-*
```

Owns the CV reasoning layer.

### Training / Experimentation

```text
feature/experiment-*
feature/training-*
```

Owns:

- experiment registry
- dataset lineage
- training launcher
- checkpoints
- metrics
- artifact tracking
- experiment comparison

### Evaluation / Benchmarking

```text
feature/evaluation-*
feature/benchmark-*
feature/failure-analysis-*
```

Owns:

- accuracy evaluation
- runtime benchmarking
- failure analysis
- model comparison

### NVIDIA / Edge

```text
feature/nvidia-*
feature/tensorrt-*
feature/deepstream-*
feature/cuda-*
feature/jetson-*
```

Owns:

- CUDA
- TensorRT
- DeepStream
- GStreamer
- Jetson
- FP16
- INT8
- PTQ/QAT
- GPU profiling
- kernel optimization

### Deployment

```text
feature/deployment-*
feature/monitoring-*
```

Owns:

- packaging
- Docker
- production deployment
- validation
- rollback
- monitoring

---

## 17. V1.0 Development Order

Development proceeds in dependency order:

```text
01 Architecture & Specification
        |
        v
02 Runtime Foundation
        |
        v
03 LLM Gateway
        |
        v
04 Knowledge / RAG Foundation
        |
        v
05 Research Engine
        |
        v
06 MCP / Tool Layer
        |
        v
07 Requirement Agent
        |
        v
08 Research Agent
        |
        v
09 CV Architecture Agent
        |
        v
10 Dataset Agent
        |
        v
11 Model Agent
        |
        v
12 Experiment Manager
        |
        v
13 Training Engine
        |
        v
14 Evaluation Engine
        |
        v
15 Benchmark Engine
        |
        v
16 Failure Analysis
        |
        v
17 Optimization Engine
        |
        v
18 NVIDIA / TensorRT / CUDA / DeepStream
        |
        v
19 Deployment Engine
        |
        v
20 Monitoring
        |
        v
21 Full Engineering Loop
```

The implementation should remain incremental. Do not build the entire stack before integrating anything.

---

## 18. First Vertical Slice

The first useful end-to-end slice is:

```text
USER
  |
  v
Requirement Agent
  |
  v
Research Agent
  |
  v
CV Architecture Agent
  |
  v
Project Specification
```

Expected artifacts:

```text
requirements.md
research.md
problem_formulation.md
architecture.md
dataset_spec.md
experiment_plan.md
```

This validates the foundational combination of:

- LangGraph
- LLM Gateway
- project state
- research
- knowledge/RAG
- artifact generation

before expensive model-training infrastructure is introduced.

---

## 19. GitHub Issue -> Branch -> PR -> Trunk

Every meaningful feature starts with an issue.

Example:

```text
Issue #XX
Implement LLM Provider Gateway
        |
        v
feature/llm-gateway
        |
        v
PR -> dev-munna
        |
        v
CI
        |
        v
Technical Review
        |
        v
Development PM Approval
        |
        v
Merge
        |
        v
dev-munna
```

Later:

```text
dev-munna
    |
    v
Official PR -> main
    |
    v
CI
    |
    v
Official PM Approval
    |
    v
main
```

This provides complete traceability.

---

## 20. Traceability

Every important implementation should be traceable:

```text
Requirement
    |
    v
GitHub Issue
    |
    v
Short-lived Branch
    |
    v
Commit
    |
    v
Pull Request
    |
    v
CI
    |
    v
Review
    |
    v
PM Approval
    |
    v
dev-munna
    |
    v
Official PR
    |
    v
main
```

For ML experiments:

```text
Requirement
    |
    v
Experiment
    |
    v
Dataset Version
    |
    v
Code Commit
    |
    v
Model
    |
    v
Metrics
    |
    v
Benchmark
    |
    v
Decision
```

---

## 21. Protected Branch Policy

### `dev-munna`

Recommended protections:

- PR required for feature merges
- CI required
- technical review required
- development PM approval required
- force pushes restricted
- deletion restricted

### `main`

Recommended protections:

- PR required
- all CI checks required
- official project-manager approval required
- force pushes blocked
- branch deletion blocked
- stale approvals dismissed after significant changes
- branch must be current before merge

The exact GitHub protection configuration may depend on repository permissions and GitHub plan capabilities.

---

## 22. Release Model

`main` is the official release source.

Releases are created only from approved `main` commits.

Example:

```text
main
 |
 +--> v0.1.0
 |
 +--> v0.2.0
 |
 +--> v0.3.0
 |
 +--> v1.0.0
```

`dev-munna` may contain approved development work that has not yet been promoted to an official release.

---

## 23. Hotfix Flow

Critical fixes follow:

```text
main
  |
  v
hotfix/<name>
  |
  v
CI
  |
  v
Review
  |
  v
Official PM Approval
  |
  v
main
```

Afterward, the fix must be reconciled into `dev-munna` so development does not regress.

---

## 24. Golden Rule

The complete development process is:

```text
ONE FEATURE
     |
     v
ONE SHORT-LIVED BRANCH
     |
     v
ONE PURPOSE
     |
     v
IMPLEMENT
     |
     v
TEST
     |
     v
CI
     |
     v
TECHNICAL REVIEW
     |
     v
DEVELOPMENT PM APPROVAL
     |
     v
MERGE TO dev-munna
     |
     v
NEXT FEATURE
     |
     v
OFFICIAL PROMOTION PR
     |
     v
OFFICIAL PM APPROVAL
     |
     v
MERGE TO main
```

---

## 25. Non-Negotiable Rules

```text
1. main is never used for development.
2. dev-munna is the working development trunk.
3. No direct feature development on dev-munna.
4. Feature work uses short-lived branches.
5. One feature at a time is the default.
6. Every feature requires CI.
7. Every feature requires technical review.
8. Every feature requires development PM approval before dev-munna merge.
9. main requires a separate official promotion PR and official PM approval.
10. No force push to main.
11. Expensive/destructive CV-agent operations remain subject to agent safety and approval policies.
12. Important milestones are committed and pushed to GitHub.
13. Documentation and tests are part of feature completion.
14. The repository's approved trunk state must remain reproducible.
```

---

## 26. Current Operating State

At the start of this process:

```text
Official trunk:
main

Development trunk:
dev-munna

Development PM:
AJ

Current implementation milestone:
Runtime Foundation

Next planned feature:
Architecture / Development Process Documentation
```

The project should now proceed one feature at a time through the workflow defined in this document.
