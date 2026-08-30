# CV Engineering Agent — Agent Instructions

## 1. Scope

These instructions govern all AI/coding-agent work in this repository.

The agent must follow the repository's GitHub workflow and must not bypass its approval gates.

## 2. Branch Safety — NON-NEGOTIABLE

### `main` is OFF LIMITS

The agent must **never modify `main`** during normal development.

Do not commit, push, create branches from, edit through, create PRs targeting, merge into, or change/bypass protections on `main`.

`main` is reserved for the Official Project Manager's eventual promotion process.

### Development branch

All current development is based on `dev-munna`.

Do not commit feature work directly to `dev-munna`. Feature work must use a short-lived branch created from the current `dev-munna`.

## 3. Required Development Flow

```text
Issue → short-lived branch from dev-munna → implement → test locally → PR → dev-munna → CI/CD → technical review → AJ / Development PM approval → merge to dev-munna → post-merge validation → delete feature branch
```

Do not skip a gate merely because the change is small unless explicitly permitted by repository policy.

## 4. One Feature at a Time

Default to one coherent feature at a time. Before starting work, inspect current `dev-munna`, identify the next approved feature, check dependencies and existing implementation, create one appropriately scoped short-lived branch, and implement only that feature.

Do not start unrelated work without explicit approval. Split oversized features into independently reviewable features.

## 5. Branch Naming

Use `feature/<name>`, `fix/<name>`, `docs/<name>`, `ci/<name>`, or `hotfix/<name>`. Keep branches short-lived; prefer less than one day and 1–3 days for larger bounded work.

## 6. Before Changing Code

Inspect relevant repository structure, existing documentation and contracts, current `dev-munna` state, existing implementations, smallest viable change, and required tests. Do not make speculative architecture changes unrelated to the current feature.

## 7. Implementation Standards

Changes must be production-oriented, modular, testable, typed where supported, observable where runtime behavior matters, secure by default, and compatible with existing contracts unless the feature explicitly changes them.

Prefer small, reversible changes. Do not introduce dependencies without checking existing dependencies and justification.

## 8. AI / LLM Provider Policy

The CV Engineering Agent supports interchangeable LLM providers and models. Provider-specific logic must not be unnecessarily coupled to business logic. Use provider abstractions/interfaces so Claude, OpenAI, Qwen, DeepSeek, local models, and future providers can be added without redesigning orchestration.

## 9. Knowledge / RAG / Research

Research-driven changes must distinguish repository-defined facts, official documentation, research/papers, community or practitioner signals, and agent inference. Verify current information when features depend on rapidly changing technologies. Community sources such as LinkedIn may be used for discovery, but important engineering decisions should be corroborated with stronger primary sources where possible.

## 10. CV / ML Engineering

Consider the complete lifecycle where relevant:

```text
Requirements → Data → Dataset Versioning → Architecture → Training → Evaluation → Benchmarking → Optimization → Deployment → Monitoring
```

Do not optimize solely for accuracy when deployment constraints are known. Record important experiment inputs and outputs for reproducibility.

## 11. Platform Detection and NVIDIA / GPU Tooling

Before platform-specific installation, training, profiling, inference, or deployment, detect and verify the execution environment. At minimum distinguish macOS, Linux, Windows, and NVIDIA Jetson, plus architecture, accelerator, driver/runtime state, and relevant framework support.

Use a verified platform profile to choose installation commands, accelerator backends, optimization tools, and runtime settings. Do not claim GPU acceleration from device presence alone; validate that the selected framework and workload execute on the accelerator.

Relevant areas include CUDA, TensorRT, DeepStream, GStreamer, Jetson, NVIDIA TAO, Model Optimizer, GPU profiling, kernel optimization, FP16/INT8, and PTQ/QAT.

## 12. Testing and Validation

Before opening a PR, run applicable formatting, linting, type checking, unit/integration tests, security checks, and build/package validation. For ML/GPU changes, consider model validation, accuracy regression, latency/FPS, GPU memory, CPU/GPU utilization, power/resource constraints, and TensorRT/DeepStream validation.

Never claim a test passed unless actually run or directly verified.

## 13. Pull Requests

Feature PRs target `dev-munna` only. PRs should state problem, scope, implementation, architecture impact, tests, risks, dependencies, acceptance criteria, and documentation impact. Keep the PR focused on one feature. Use squash merging when repository settings permit it.

## 14. Approval Boundary

The agent may implement, test, inspect, and prepare a PR, then must stop at the required approval boundary.

```text
Agent → PR → dev-munna → CI + Review → AJ approval
```

Do not self-approve and merge when PM approval is required.

## 15. Git Operations

```bash
git fetch origin
git switch dev-munna
git pull --ff-only origin dev-munna
git switch -c feature/<name>
```

Before PR: `git fetch origin` then `git rebase origin/dev-munna`. If required, update the feature branch with `git push --force-with-lease`. Never force-push against `dev-munna` or `main`.

## 16. Documentation

When a feature changes architecture, interfaces, behavior, configuration, deployment, or operational procedures, update relevant documentation in the same feature branch. Do not create duplicate documentation when an existing document can be updated.

Canonical GitHub workflow: `docs/development/GITHUB_FLOW_V1.md`.

## 17. Milestone Discipline

Important milestones must be committed and pushed to GitHub. Completion requires the applicable implementation, tests, documentation, CI, review, PM approval, and `dev-munna` integration.

## 18. Current V1.0 Development Sequence

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

## 19. Current Branch Policy Summary

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

## 20. Final Rule

When uncertain, do not make a broad change. Inspect the current repository state, keep the change small, use a short-lived branch from `dev-munna`, validate it, create the PR to `dev-munna`, and stop for the required approval.

**`main` is never part of the agent's normal development workflow.**
