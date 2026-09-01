# CV Engineering Agent — GitHub Development Model

**Audience:** Project owner, developers, AI/CV coding agents
**Status:** Approved operating model
**Repository:** `CodeHub1443/cv-engineering-agent`

> The project uses a three-level development flow: `main` → `dev-munna` → short-lived
> branches. `dev-munna` is the PM integration branch; `main` is the official
> integration/release branch. Short-lived work branches are reviewed and merged into
> `dev-munna`; the Official PM reviews and promotes `dev-munna` to `main`.

## 1. Executive Summary

- **`main`** is the official verified integration/release baseline.
- **`dev-munna`** is the active PM integration branch.
- Developers and coding agents never commit directly to `main` or `dev-munna`.
- Work is performed on short-lived branches cut from `dev-munna`.
- Every short-lived branch requires CI and review before merge into `dev-munna`.
- Promotion from `dev-munna` to `main` is a separate Official PM review/merge gate.

## 2. Branch Roles

```text
                         main
                          ▲
                          │ Official PM review + merge
                          │
                      dev-munna
                          ▲
                          │ PM review + CI
                          │
             short-lived feature/fix/docs/ci branch
```

### `main`

- Official integration and release baseline.
- No direct commits or pushes.
- Updated only through the Official PM promotion PR from `dev-munna`.

### `dev-munna`

- PM integration branch for the current development stream.
- Receives completed short-lived work after review and green CI.
- May contain multiple completed increments before promotion to `main`.
- No direct commits or pushes.

### Short-lived branches

- Cut from `dev-munna`.
- One issue/work item per branch.
- Prefixes: `feature/`, `fix/`, `docs/`, `ci/`, `hotfix/`.
- Deleted after merge into `dev-munna`.

## 3. Non-Negotiable Rules

```text
1. main is never used for day-to-day development.
2. dev-munna is never used for direct development commits.
3. Short-lived work branches start from dev-munna.
4. Every work branch requires CI and PM review before merge to dev-munna.
5. Official PM approval is required to promote dev-munna to main.
6. Never force-push main or dev-munna.
7. Expensive/destructive CV-agent operations remain subject to docs/APPROVALS.md.
```

## 4. Pull Request and CI/CD Requirements

See `docs/development/GITHUB_FLOW_V1.md` for the procedural PR template, CI/CD
requirements, branch naming, and review gates. Both documents must remain consistent.

## 5. Development Sequence

The project is implemented in dependency order, matching the architecture roadmap:

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

## 6. Traceability

```text
Requirement
   ↓
GitHub Issue
   ↓
Short-lived Branch (from dev-munna)
   ↓
Commit(s)
   ↓
PR → dev-munna
   ↓
CI/CD + PM Review
   ↓
dev-munna
   ↓
Promotion PR → main
   ↓
Official PM Review + Merge
   ↓
main
```

## 7. Completion Definition

```text
[ ] Implementation complete
[ ] Tests complete
[ ] Documentation updated
[ ] Local validation passes
[ ] CI passes
[ ] PM technical review complete
[ ] PR merged to dev-munna
[ ] Promotion PR reviewed by Official PM
[ ] dev-munna merged to main
[ ] Post-merge main CI passes
[ ] Short-lived branch deleted
```

This is the canonical GitHub development model for the current project.
