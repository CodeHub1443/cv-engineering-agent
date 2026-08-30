# CV Engineering Agent — Agent Instructions

These instructions govern all AI/coding-agent work in this repository. The agent must follow the repository GitHub workflow and must not bypass approval gates.

## Branch Safety — NON-NEGOTIABLE

`main` is OFF LIMITS during normal development. Never commit to, push to, create feature branches from, edit through, create PRs targeting, merge into, or change/bypass protections on `main`. `main` is reserved for the Official Project Manager's eventual promotion process.

All current development is based on `dev-munna`. Do not commit feature work directly to `dev-munna`; feature work uses a short-lived branch created from the current `dev-munna`.

## Required Development Flow

```text
Issue → short-lived branch from dev-munna → implement → test locally → PR → dev-munna → CI/CD → technical review → AJ / Development PM approval → merge to dev-munna → post-merge validation → delete feature branch
```

## Before Changing Code

Inspect relevant repository structure, documentation/contracts, current `dev-munna` state, existing implementations, smallest viable change, and required tests. Do not make speculative architecture changes unrelated to the current feature.

## Implementation Standards

Changes must be production-oriented, modular, testable, typed where supported, observable where runtime behavior matters, secure by default, and compatible with existing contracts unless the feature explicitly changes them. Prefer small, reversible changes and justify new dependencies.

## AI / LLM Provider Policy

Support interchangeable providers/models. Keep provider-specific logic behind abstractions/interfaces so Claude, OpenAI, Qwen, DeepSeek, local models, and future providers can be added without redesigning orchestration.

## Knowledge / RAG / Research

Distinguish repository facts, official documentation, research/papers, community/practitioner signals, and agent inference. Verify current information when rapidly changing technologies matter. Community sources such as LinkedIn are discovery signals; important engineering decisions should be corroborated with stronger primary sources where possible.

## CV / ML Engineering

Consider the complete lifecycle where relevant: Requirements → Data → Dataset Versioning → Architecture → Training → Evaluation → Benchmarking → Optimization → Deployment → Monitoring. Do not optimize solely for accuracy when deployment constraints are known. Record important experiment inputs and outputs for reproducibility.

## Platform Detection and NVIDIA / GPU Tooling

Before platform-specific installation, training, profiling, inference, or deployment, detect and verify macOS, Linux, Windows, or NVIDIA Jetson plus architecture, accelerator, driver/runtime state, and framework support. Use a verified platform profile to choose installation commands, accelerator backends, optimization tools, and runtime settings. Never claim GPU acceleration from device presence alone; validate actual workload execution.

Relevant areas include CUDA, TensorRT, DeepStream, GStreamer, Jetson, NVIDIA TAO, Model Optimizer, GPU profiling, kernel optimization, FP16/INT8, and PTQ/QAT.

## Testing and Validation

Before a PR, run applicable formatting, linting, type checking, unit/integration tests, security checks, and build/package validation. For ML/GPU changes consider model validation, accuracy regression, latency/FPS, memory, CPU/GPU utilization, power/resource constraints, and TensorRT/DeepStream validation. Never claim a test passed unless actually run or directly verified.

## Pull Requests

Feature PRs target `dev-munna` only. PRs should state problem, scope, implementation, architecture impact, tests, risks, dependencies, acceptance criteria, and documentation impact. Keep PRs focused. Use squash merging when permitted.

## Approval Boundary

The agent may implement, test, inspect, and prepare a PR, then must stop for the required approval. Do not self-approve and merge when PM approval is required.

## Git Operations

```bash
git fetch origin
git switch dev-munna
git pull --ff-only origin dev-munna
git switch -c feature/<name>
```

Before PR: `git fetch origin` then `git rebase origin/dev-munna`. If required, use `git push --force-with-lease` on the feature branch only. Never force-push `dev-munna` or `main`.

## Documentation

When architecture, interfaces, behavior, configuration, deployment, or operations change, update relevant documentation in the same feature branch. Do not duplicate existing documentation. Canonical GitHub workflow: `docs/development/GITHUB_FLOW_V1.md`.

## Milestone Discipline

Important milestones must be committed and pushed. Completion requires applicable implementation, tests, documentation, CI, review, PM approval, and `dev-munna` integration.

## Current V1.0 Development Sequence

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

Only the current feature should be implemented unless explicitly approved otherwise.

## Branch Policy Summary

```text
main → 🚫 DO NOT TOUCH
dev-munna → ✅ integration trunk; 🚫 no direct feature commits
feature/* → ✅ short-lived; ✅ PR → dev-munna
dev-munna → main → ⛔ outside normal agent development; requires Official PM process
```

## Final Rule

When uncertain, do not make a broad change. Inspect current state, keep the change small, use a short-lived branch from `dev-munna`, validate it, create the PR to `dev-munna`, and stop for required approval.

**`main` is never part of the agent's normal development workflow.**
