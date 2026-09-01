# CV Engineering Agent — GitHub Development & Delivery Flow

**Status:** Approved Working Process
**Version:** V1.2
**Repository:** `CodeHub1443/cv-engineering-agent`

> Current project flow: `main` → `dev-munna` → short-lived branches. `dev-munna` is the
> PM integration branch. Short-lived work is reviewed and CI-validated before merging
> into `dev-munna`. The Official PM reviews and promotes `dev-munna` to `main`.

## 1. Purpose

This document defines how CV Engineering Agent is developed, reviewed, tested, and
merged through GitHub.

The project follows:

- protected `main` as official integration/release baseline;
- `dev-munna` as the PM integration branch;
- short-lived work branches for each issue/work item;
- mandatory CI/CD validation;
- PM review before merge to `dev-munna`;
- Official PM review before promotion to `main`;
- small, isolated feature increments.

## 2. Branching Model

```text
                         main
                          ▲
                          │ Official PM review + merge
                          │
                      dev-munna
                          ▲
                          │ PM review + CI
                          │
             short-lived work branch
```

### Rules

1. `main` receives no direct development commits or pushes.
2. `dev-munna` receives no direct development commits or pushes.
3. Short-lived branches are cut from `dev-munna`.
4. PRs from short-lived branches target `dev-munna`.
5. CI and PM review are required before merging a work branch into `dev-munna`.
6. The Official PM promotes `dev-munna` to `main` through a separate PR/review gate.
7. Short-lived branches are deleted after merge.
8. Never force-push `main` or `dev-munna`.

## 3. One Work Item at a Time

```text
Issue
  ↓
short-lived branch from dev-munna
  ↓
implementation + tests
  ↓
PR → dev-munna
  ↓
CI + PM review
  ↓
dev-munna
  ↓
Promotion PR → main
  ↓
Official PM review + merge
```

Keep diffs reviewable; if a change is too large, split the issue.

## 4. Branch Naming

```text
feature/<owner>/<work>
fix/<owner>/<work>
docs/<owner>/<work>
ci/<owner>/<work>
hotfix/<owner>/<work>
```

Branches should normally live less than three days. Longer-lived work requires an
explicit project-management reason.

## 5. Pull Request Requirements

Every PR must contain:

- problem statement;
- scope;
- implementation summary;
- architecture impact;
- tests performed;
- acceptance criteria;
- risks and dependencies;
- documentation impact where applicable.

## 6. CI/CD Gate

Every PR must pass automated validation before merge.

```text
Formatting → Linting → Type Checking → Unit Tests → Integration Tests
→ Security Checks → Package Build → Architecture / Spec Checks
```

GPU-specific validation is added when GPU infrastructure is available. CPU CI must
remain capable of validating the core architecture without GPU infrastructure.

## 7. Local Validation

Before opening a PR, run the local equivalent of configured formatting, linting,
type-checking, tests, and build checks. The PR should not be the first place an obvious
failure is discovered.

## 8. Review and Merge

### PM review

The PM reviews work-branch PRs for correctness, architecture consistency, tests,
security, performance implications, API compatibility, and documentation.

### Official PM promotion

The Official PM reviews promotion PRs from `dev-munna` to `main` and performs the
final merge into `main`.

### Merge strategy

Prefer squash merging short-lived branches so `dev-munna` retains meaningful history.

## 9. Keeping Branches Current

Before opening or merging a PR, synchronize the work branch with the current
`dev-munna` state. Never force-push `main` or `dev-munna`.

## 10. Work Completion

```text
[ ] Issue identified
[ ] Acceptance criteria defined
[ ] Implementation complete
[ ] Tests complete
[ ] Documentation updated
[ ] Local validation passes
[ ] CI passes
[ ] PM review complete
[ ] PR merged to dev-munna
[ ] Promotion PR reviewed by Official PM
[ ] dev-munna merged to main
[ ] Post-merge main CI passes
[ ] Short-lived branch deleted
```

## 11. Workstreams

| Workstream | Branch prefix | Owns |
|---|---|---|
| Architecture & Documentation | `docs/*` | ADRs, architecture, lifecycle, contracts, governance |
| Core Runtime | `feature/*/runtime-*` | LangGraph, state, sessions, checkpoints, interrupts |
| LLM Gateway | `feature/*/llm-*`, `feature/*/provider-*` | provider abstraction, routing, structured output, streaming, fallbacks |
| Knowledge / RAG | `feature/*/knowledge-*`, `feature/*/rag-*` | retrieval, provenance, freshness |
| Research Engine | `feature/*/research-*` | web/GitHub/paper research and evidence verification |
| MCP / Tools | `feature/*/mcp-*`, `feature/*/tool-*` | typed execution boundaries |
| CV Intelligence | `feature/*/requirement-*`, `feature/*/*-agent-*` | CV reasoning layer |
| Training / Experimentation | `feature/*/experiment-*`, `feature/*/training-*` | experiments, datasets, training launchers |
| Evaluation / Benchmarking | `feature/*/evaluation-*`, `feature/*/benchmark-*` | metrics, benchmarks, failure analysis |
| NVIDIA / Edge | `feature/*/nvidia-*`, `feature/*/tensorrt-*`, `feature/*/deepstream-*`, `feature/*/jetson-*` | CUDA, TensorRT, DeepStream, Jetson |
| Deployment | `feature/*/deployment-*`, `feature/*/monitoring-*` | packaging, deployment, rollback, monitoring |

## 12. Non-Negotiable Rules

```text
1. No direct development commits to main or dev-munna.
2. Short-lived work branches start from dev-munna.
3. Every work PR requires CI and PM review.
4. Promotion to main requires Official PM review.
5. No force-push to main or dev-munna.
6. Expensive/destructive CV-agent operations remain subject to docs/APPROVALS.md.
7. Documentation and tests are part of feature completion.
```

## 13. Current Operating State

```text
Integration baseline: main
PM integration branch: dev-munna
Work branches: short-lived branches cut from dev-munna
Promotion: dev-munna -> main via Official PM PR
Current milestone: Phase 1 — Architecture & ADR Specification
```
