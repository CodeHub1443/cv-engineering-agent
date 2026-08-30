# CV Engineering Agent — GitHub Development Model

**Audience:** Official Project Manager, Development PM, Developers, AI/CV agents  
**Status:** Proposed operating model for V1.0  
**Repository:** `CodeHub1443/cv-engineering-agent`

## 1. Executive Summary

CV Engineering Agent V1.0 uses a trunk-based development model with short-lived feature branches and two controlled integration levels.

- **`main`** is the official project trunk and release authority.
- **`dev-munna`** is the working development trunk.
- **AJ** acts as the Development Project Manager for `dev-munna`.
- The **Official Project Manager** owns the final promotion decision into `main`.
- Developers and coding agents never develop directly on either trunk.
- Every feature is implemented on a short-lived branch, validated by CI/CD, reviewed, approved, and merged into `dev-munna`.
- `dev-munna` is periodically promoted to `main` through a separate Pull Request and official PM approval.

This model gives the development team a safe integration area while keeping `main` clean, stable, auditable, and suitable for official releases.

---

## 2. Branch Roles

```text
                         OFFICIAL PROJECT
                              TRUNK
                             `main`
                                ▲
                                │
                     Official PM approval
                                │
                                │
                         Promotion PR
                                │
                                │
                         `dev-munna`
                    DEVELOPMENT INTEGRATION
                              TRUNK
                                ▲
                                │
                    Development PM approval
                                │
                                │
                         Feature PR
                                │
                                │
                     short-lived branch
                                ▲
                                │
                           developer
```

### `main`

`main` is the official project trunk.

It represents code that has passed the development process and has been explicitly accepted by the Official Project Manager.

`main` is never used as a normal development workspace.

### `dev-munna`

`dev-munna` is the controlled development integration trunk.

It allows the development team to integrate completed features, run integrated CI/CD, and validate the next project state without modifying the official `main` branch.

AJ is the Development PM for this branch.

---

## 3. Non-Negotiable Rules

1. **Never develop directly on `main`.**
2. **Never push directly to `main`.**
3. **Never develop directly on `dev-munna`.**
4. All feature work uses a short-lived branch.
5. One coherent feature per branch/PR is the default.
6. CI/CD must pass before a feature is approved.
7. Technical review is required.
8. Development PM approval is required before merging into `dev-munna`.
9. Official PM approval is required before merging `dev-munna` into `main`.
10. Important milestones must be committed and pushed to GitHub.
11. Destructive or high-risk agent operations remain governed by the project's safety/approval policy.
12. A feature is not complete merely because it works locally; it is complete only after the required PR and integration gates pass.

---

## 4. Feature Development Flow

Every feature follows this sequence:

```text
GitHub Issue
     ↓
Short-lived feature branch
     ↓
Implementation
     ↓
Local validation
     ↓
Pull Request → dev-munna
     ↓
Automated CI/CD
     ↓
Technical Review
     ↓
Development PM Approval
     ↓
Squash Merge → dev-munna
     ↓
Post-merge CI
     ↓
Feature complete
```

The next feature starts only after the current feature reaches its defined completion state, unless the PM explicitly authorizes parallel work because of a dependency or risk-management reason.

---

## 5. Official Promotion Flow

When a set of development work is ready for official integration:

```text
dev-munna
     ↓
Promotion Pull Request → main
     ↓
Full CI/CD
     ↓
Technical Review
     ↓
Official Project Manager Review
     ↓
Official PM Approval
     ↓
Merge → main
     ↓
Post-merge CI
     ↓
Official project state
```

The Official Project Manager can:

- approve the promotion;
- request changes;
- reject the promotion;
- request additional testing;
- require a specific milestone or documentation update before promotion.

A rejection of a promotion PR does not invalidate `dev-munna`. It means the development trunk requires additional work before official integration.

---

## 6. Why Two Trunks?

The two-trunk arrangement gives the project two explicit control levels.

### Development level

`dev-munna` allows us to:

- integrate features frequently;
- test the evolving architecture;
- allow AJ to act as Development PM;
- validate agent-generated code;
- experiment within controlled boundaries;
- identify integration problems before official promotion.

### Official level

`main` provides:

- official project history;
- release authority;
- final PM control;
- stable integration state;
- production/release traceability.

The two levels are therefore not two competing development branches. `dev-munna` is a controlled development trunk; `main` is the official trunk.

---

## 7. Short-Lived Branches

Branch naming:

```text
feature/<name>
fix/<name>
ci/<name>
docs/<name>
hotfix/<name>
```

Examples:

```text
feature/runtime-orchestrator
feature/llm-gateway
feature/rag-foundation
feature/research-engine
feature/requirement-agent
feature/dataset-agent
feature/training-engine
feature/benchmark-engine
feature/tensorrt-integration
docs/architecture-v1
ci/github-actions
fix/graph-state-persistence
```

Branches should normally live less than three days. If work becomes too large, split it into smaller features.

Bad:

```text
feature/build-the-entire-agent
```

Good:

```text
feature/llm-gateway
feature/provider-anthropic
feature/provider-qwen
```

---

## 8. One Feature at a Time

The development process is intentionally incremental.

```text
Feature A
  ↓
validate
  ↓
merge to dev-munna
  ↓
Feature B
  ↓
validate
  ↓
merge to dev-munna
  ↓
Feature C
```

This prevents:

- large merge conflicts;
- architectural drift;
- difficult reviews;
- hidden dependencies;
- unclear ownership;
- difficult rollback;
- large batches of unverified AI-generated code.

If multiple features are technically independent and parallel work is necessary, each still follows the same short-lived branch and PR rules.

---

## 9. Workstream Model

The project is divided into engineering workstreams. These are areas of responsibility, **not permanent Git branches**.

### Architecture & Documentation

Owns:

- architecture
- lifecycle
- contracts
- safety
- development process
- API contracts
- artifact contracts

### Core Runtime

Owns:

- LangGraph
- state
- sessions
- checkpointing
- interrupts
- resume
- retries
- runtime errors

### LLM / AI Integration

Owns:

- LLM Gateway
- provider adapters
- model routing
- structured output
- streaming
- tool calling
- provider fallback

Target providers may include Claude, OpenAI, Qwen, DeepSeek, local models, and future providers.

### Knowledge / RAG

Owns:

- canonical knowledge
- technology knowledge
- live research knowledge
- ingestion
- retrieval
- embeddings
- reranking
- provenance
- freshness

### Research

Owns current technical research across:

- NVIDIA
- CUDA
- TensorRT
- DeepStream
- Jetson
- Ultralytics / YOLO
- Roboflow
- Hugging Face
- GitHub
- papers and official documentation
- practitioner/community signals including LinkedIn

LinkedIn/community content is treated as a discovery signal and should be verified when it is used to support important engineering decisions.

### MCP / Tooling

Owns typed execution interfaces for:

- research
- GitHub
- datasets
- training
- evaluation
- benchmarking
- GPU profiling
- ONNX
- TensorRT
- DeepStream
- Docker

### CV Intelligence

Owns the engineering reasoning agents:

```text
Requirement
Problem Formulation
Research
Architecture
Dataset
Model
Experiment
Training
Evaluation
Failure Analysis
Benchmark
Optimization
Deployment
Monitoring
Review
```

These agents are introduced incrementally rather than all at once.

### Training / Experimentation

Owns:

- experiment registry
- dataset lineage
- training launcher
- checkpoints
- metrics
- artifact tracking
- experiment comparison

### Evaluation / Benchmarking

Owns:

- accuracy evaluation
- runtime benchmarking
- failure analysis
- model comparison
- end-to-end pipeline profiling

### NVIDIA / Edge

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
- NVIDIA skills integration
- CUDA-Agent integration

### Deployment

Owns:

- packaging
- Docker
- runtime deployment
- production validation
- rollback
- monitoring

---

## 10. Feature-to-Branch Examples

The following are examples, not permanent branches:

```text
Architecture documentation
    → docs/architecture-v1

Runtime orchestration
    → feature/runtime-orchestrator

LLM abstraction
    → feature/llm-gateway

Claude provider
    → feature/provider-anthropic

RAG foundation
    → feature/rag-foundation

Research source registry
    → feature/source-registry

MCP tool layer
    → feature/mcp-tool-layer

Requirement Agent
    → feature/requirement-agent

Dataset Agent
    → feature/dataset-agent

Training Engine
    → feature/training-engine

TensorRT integration
    → feature/tensorrt-integration
```

After merge, the short-lived branch is deleted.

---

## 11. Pull Request Requirements

Every PR should state:

```text
Problem
Scope
Implementation
Architecture impact
Tests
Risks
Dependencies
Acceptance criteria
Documentation impact
```

Recommended template:

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

## 12. CI/CD Requirements

The CI/CD pipeline is a mandatory gate.

Minimum validation:

```text
Formatting
   ↓
Linting
   ↓
Type Checking
   ↓
Unit Tests
   ↓
Integration Tests
   ↓
Security Checks
   ↓
Package Build
   ↓
Architecture / Specification Checks
```

When GPU infrastructure is available, additional validation should cover:

```text
CUDA
TensorRT
DeepStream
GPU integration
```

The core project must still be testable without a GPU.

---

## 13. PM Approval Model

There are two PM gates.

### Development PM — AJ

Controls feature integration into `dev-munna`.

Checks:

- scope
- acceptance criteria
- CI status
- tests
- architecture consistency
- documentation
- risk
- milestone relevance

### Official Project Manager

Controls official integration into `main`.

Checks:

- development milestone completeness
- integrated CI/CD
- architecture integrity
- project-level risk
- documentation
- release readiness
- deployment/release implications

---

## 14. Branch Protection

### `dev-munna`

Recommended:

- PR required
- CI required
- review required
- Development PM approval required
- force pushes restricted
- deletion restricted

### `main`

Recommended:

- PR required
- all required CI checks
- Official PM approval required
- force pushes blocked
- deletion blocked
- stale approvals dismissed after significant changes
- branch must be current before merge

The exact GitHub rule configuration depends on repository permissions and available GitHub features.

---

## 15. Merge Strategy

Use squash merging for normal short-lived branches.

Example:

```text
feature/llm-gateway
      ↓
multiple local commits
      ↓
PR
      ↓
CI + Review + PM approval
      ↓
Squash merge
      ↓
dev-munna
```

This keeps trunk history focused on meaningful project milestones.

---

## 16. Keeping Branches Current

Before opening or merging a feature PR:

```bash
git fetch origin
git rebase origin/dev-munna
```

After a rebase:

```bash
git push --force-with-lease
```

Only use force-with-lease on the developer's short-lived branch. Never force-push either trunk.

---

## 17. Feature Definition of Done

A feature is complete when all applicable items are satisfied:

```text
[ ] Implementation complete
[ ] Unit tests complete
[ ] Integration tests complete where required
[ ] Documentation updated
[ ] Configuration updated where required
[ ] Security review complete
[ ] Local validation passes
[ ] CI passes
[ ] Technical review complete
[ ] Development PM approval received
[ ] PR merged into dev-munna
[ ] Post-merge dev-munna CI passes
[ ] Short-lived branch deleted
```

---

## 18. Official Promotion Definition of Done

```text
[ ] dev-munna is green
[ ] Intended milestone is complete
[ ] Promotion PR opened
[ ] Full CI passes
[ ] Technical review complete
[ ] Official PM review complete
[ ] Official PM approval received
[ ] PR merged into main
[ ] main post-merge CI passes
[ ] Release decision recorded where applicable
```

---

## 19. Development Sequence

V1.0 should be implemented in dependency order:

```text
01 Architecture & Specification
02 Runtime Foundation
03 LLM Gateway
04 Knowledge / RAG Foundation
05 Research Engine
06 MCP / Tool Layer
07 Requirement Agent
08 Research Agent
09 CV Architecture Agent
10 Dataset Agent
11 Model Agent
12 Experiment Manager
13 Training Engine
14 Evaluation Engine
15 Benchmark Engine
16 Failure Analysis
17 Optimization Engine
18 NVIDIA / TensorRT / CUDA / DeepStream
19 Deployment Engine
20 Monitoring
21 Full Engineering Loop
```

Each item becomes one or more small issues and short-lived branches.

---

## 20. First Useful Vertical Slice

The first major product slice is:

```text
User
 ↓
Requirement Agent
 ↓
Research Agent
 ↓
CV Architecture Agent
 ↓
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

This validates the agent's first useful engineering workflow before expensive training infrastructure is introduced.

---

## 21. Traceability

Every meaningful software feature should be traceable:

```text
Requirement
   ↓
GitHub Issue
   ↓
Short-lived Branch
   ↓
Commit(s)
   ↓
Pull Request
   ↓
CI/CD
   ↓
Technical Review
   ↓
Development PM Approval
   ↓
dev-munna
   ↓
Official Promotion PR
   ↓
Official PM Approval
   ↓
main
```

ML experiments additionally require:

```text
Requirement
   ↓
Experiment
   ↓
Dataset Version
   ↓
Code Commit
   ↓
Model Configuration
   ↓
Training Configuration
   ↓
Model Artifact
   ↓
Metrics
   ↓
Benchmark
   ↓
Decision
```

---

## 22. Releases

`main` is the official release source.

Releases are created only from approved `main` commits.

Example:

```text
main
 |
 +--> v0.1.0
 +--> v0.2.0
 +--> v0.3.0
 +--> v1.0.0
```

`dev-munna` may contain approved development work that is not yet an official release.

---

## 23. Hotfixes

Critical official fixes follow:

```text
main
 ↓
hotfix/<name>
 ↓
CI
 ↓
Review
 ↓
Official PM approval
 ↓
main
```

The fix must then be reconciled into `dev-munna` so the development trunk does not regress.

---

## 24. Operating Principle

The project is intentionally managed as a sequence of controlled engineering increments:

```text
ONE FEATURE
     ↓
ONE SHORT-LIVED BRANCH
     ↓
ONE PURPOSE
     ↓
IMPLEMENT
     ↓
TEST
     ↓
CI
     ↓
REVIEW
     ↓
DEVELOPMENT PM APPROVAL
     ↓
MERGE TO dev-munna
     ↓
NEXT FEATURE
     ↓
OFFICIAL PROMOTION
     ↓
OFFICIAL PM APPROVAL
     ↓
MERGE TO main
```

This is the canonical GitHub development and promotion model for CV Engineering Agent V1.0.
