# CV Engineering Agent — Agent Instructions

## 1. Scope

These instructions govern all AI/coding-agent work in this repository.

The agent must follow the repository's GitHub workflow and must not bypass its approval gates.

The canonical product definition is maintained in the project context supplied to this repository. Repository specifications derived from it must remain consistent with that source. `spec/00-vision.md` is the canonical in-repository vision and product-boundary specification.

## 2. Branch Safety — NON-NEGOTIABLE

### `main` is OFF LIMITS

The agent must **never modify `main`** during normal development.

Do not:

- commit to `main`
- push to `main`
- create feature branches from `main`
- edit files through a `main`-targeted write operation
- create PRs targeting `main`
- merge anything into `main`
- change or bypass `main` protections

`main` is reserved for the Official Project Manager's eventual promotion process.

### Development branch

All current development is based on:

```text
dev-munna
```

Do not commit feature work directly to `dev-munna`.

Feature work must use a short-lived branch created from the current `dev-munna`.

## 3. Required Development Flow

For every feature:

```text
Issue
  ↓
short-lived branch from dev-munna
  ↓
implement
  ↓
test locally
  ↓
PR → dev-munna
  ↓
CI/CD when coding work requires it
  ↓
technical review
  ↓
AJ / Development PM approval
  ↓
merge to dev-munna
  ↓
post-merge validation
  ↓
delete feature branch
```

Do not skip a gate merely because the change is small unless the repository's explicitly defined policy permits it.

## 4. One Feature at a Time

Default to one coherent feature at a time.

Before starting work:

1. inspect the current `dev-munna` state;
2. identify the next approved feature;
3. check dependencies and existing implementation;
4. create one appropriately scoped short-lived branch;
5. implement only that feature.

Do not start unrelated work without explicit approval.

If a feature is too large, split it into smaller independently reviewable features.

## 5. Branch Naming

Use:

```text
feature/<name>
fix/<name>
docs/<name>
ci/<name>
hotfix/<name>
```

Keep branches short-lived.

## 6. Before Changing Code

The agent must first:

- inspect the repository structure relevant to the task;
- inspect existing documentation and contracts;
- inspect the current `dev-munna` state;
- identify existing implementations before creating duplicates;
- determine the smallest viable change;
- identify tests that must be added or updated.

Do not make speculative architecture changes unrelated to the current feature.

## 7. Implementation Standards

Changes must be:

- production-oriented;
- modular;
- testable;
- typed where the language supports typing;
- observable where runtime behavior matters;
- secure by default;
- compatible with existing contracts unless the feature explicitly changes them.

Prefer small, reversible changes over broad refactors.

Do not introduce a dependency without checking whether an existing project dependency already solves the problem and whether the new dependency is justified.

## 8. AI / LLM Provider Policy

The CV Engineering Agent must support interchangeable LLM providers and models.

Provider-specific logic must not be unnecessarily coupled to agent business logic.

Use provider abstractions/interfaces where appropriate so providers such as Claude, OpenAI/Codex-compatible models, Qwen, DeepSeek, local models, and future providers can be added without redesigning the orchestration layer.

Coding-worker runtimes such as Codex CLI and Claude Code are separate from the LLM provider abstraction and must remain controlled workers rather than becoming the source of truth for project state or architecture.

## 9. Knowledge / RAG / Research

Research-driven changes must distinguish between:

- repository-defined facts;
- official documentation;
- research/papers;
- community or practitioner signals;
- agent inference.

Current information should be verified when the feature depends on rapidly changing technologies.

Relevant research channels may include Roboflow, YOLO ecosystem sources, Hugging Face, NVIDIA, TensorRT, DeepStream, TAO, CUDA, GitHub, papers, and professional engineering discussions including LinkedIn.

Community sources are discovery signals and are not automatically authoritative.

RAG is a knowledge subsystem, not the agent itself. Live research and persistent project knowledge must preserve provenance, freshness, authority, and verification state.

## 10. CV / ML Engineering

The product abstraction is the CV engineering lifecycle, not code generation. When implementing CV/ML functionality, consider the applicable lifecycle stages:

```text
DISCOVER
 → DEFINE
 → RESEARCH
 → DESIGN
 → DATA
 → BASELINE
 → TRAIN
 → EVALUATE
 → DIAGNOSE
 → OPTIMIZE
 → BENCHMARK
 → DEPLOY
 → MONITOR
 → ITERATE
```

Not every project requires every stage. The agent should determine which stages are necessary for the current problem.

Do not assume every CV problem is object detection. Consider detection, classification, segmentation, pose, tracking, action recognition, anomaly detection, geometry, classical CV, and hybrid systems as appropriate.

Do not optimize a model solely for accuracy when deployment constraints are known.

Record important experiment inputs and outputs so results remain reproducible.

## 11. Platform Detection and NVIDIA / GPU Tooling

Before platform-specific installation, training, profiling, inference, or deployment, detect and verify the execution environment. At minimum distinguish macOS, Linux, Windows, and NVIDIA Jetson, plus architecture, accelerator, driver/runtime state, and relevant framework support.

Use a verified platform profile to choose installation commands, accelerator backends, optimization tools, and runtime settings. Do not claim GPU acceleration from device presence alone; validate that the selected framework and workload actually execute on the accelerator.

Use the project's available NVIDIA/CUDA-related skills and tooling when relevant rather than reinventing established workflows.

Relevant areas include:

- CUDA
- TensorRT
- DeepStream
- GStreamer
- Jetson
- NVIDIA TAO
- Model Optimizer
- GPU profiling
- kernel optimization
- FP16 / INT8
- PTQ / QAT

GPU-specific work should remain isolated from the core runtime when practical and must include appropriate validation.

## 12. Training, Optimization and NAS

Training and optimization must be baseline-driven and experiment-driven.

```text
Baseline
 → Profile
 → Identify bottleneck
 → Generate candidates
 → Estimate cost/risk
 → Approval when required
 → Execute
 → Evaluate
 → Benchmark
 → Accept / Reject
```

NAS is optional. It must not be the default response to an optimization request. Establish a baseline, justify the search space and expected value, estimate compute cost, and obtain approval when required before expensive searches.

## 13. Testing and Validation

Before opening a PR, run the applicable project checks.

At minimum, determine whether the change requires:

```text
formatting
linting
type checking
unit tests
integration tests
security checks
build/package validation
```

For ML/GPU changes, also consider:

```text
model validation
accuracy regression checks
latency/FPS
GPU memory
CPU utilization
GPU utilization
power/resource constraints
TensorRT/DeepStream validation
```

Never claim a test passed unless it was actually run or its result is otherwise directly verified.

## 14. Pull Requests

Feature PRs target **`dev-munna` only**.

PRs should clearly state:

- problem;
- scope;
- implementation;
- architecture impact;
- tests;
- risks;
- dependencies;
- acceptance criteria;
- documentation impact.

Keep the PR focused on one feature.

Use squash merging for normal feature branches when repository settings permit it.

## 15. Approval Boundary

The agent may implement, test, inspect, and prepare a PR.

The agent must stop at the required approval boundary.

For normal feature work:

```text
Agent
 ↓
PR → dev-munna
 ↓
CI + Review
 ↓
AJ approval
```

Do not self-approve and merge a feature when PM approval is required.

## 16. Git Operations

Safe development sequence:

```bash
git fetch origin
git switch dev-munna
git pull --ff-only origin dev-munna
git switch -c feature/<name>
```

Before PR:

```bash
git fetch origin
git rebase origin/dev-munna
```

If rebasing requires updating the feature branch:

```bash
git push --force-with-lease
```

Never use force-push against `dev-munna` or `main`.

## 17. Documentation

When a feature changes architecture, interfaces, behavior, configuration, deployment, or operational procedures, update the relevant documentation in the same feature branch.

Do not create duplicate documentation when an existing document can be updated.

The canonical GitHub workflow is documented in:

```text
docs/development/GITHUB_FLOW_V1.md
```

## 18. Milestone Discipline

Important milestones must be committed and pushed to GitHub.

A milestone is not complete merely because local code works.

Completion requires the applicable:

```text
implementation
→ tests
→ documentation
→ CI when applicable
→ review
→ PM approval
→ dev-munna integration
```

## 19. Current V1.0 Development Sequence

Unless explicitly changed by the Development PM, follow this dependency order:

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

Only the current feature should be implemented unless explicit approval is given to change the sequence.

## 20. Current Branch Policy Summary

```text
main
  🚫 DO NOT TOUCH

 dev-munna
  ✅ development integration trunk
  🚫 no direct feature commits

 feature/*
  ✅ implementation work
  ✅ short-lived
  ✅ PR → dev-munna

 dev-munna → main
  ⛔ outside normal agent development
  ⛔ requires Official PM process
```

## 21. Final Rule

When uncertain, **do not make a broad change**.

Inspect the current repository state, keep the change small, use a short-lived branch from `dev-munna`, validate it, create the PR to `dev-munna`, and stop for the required approval.

**`main` is never part of the agent's normal development workflow.**
