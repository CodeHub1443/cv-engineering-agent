# CV Engineering Agent — GitHub Development & Delivery Flow

**Status:** Approved Working Process
**Version:** V1.1 — supersedes the two-trunk (`main` / `dev-munna`) model in V1.0
**Repository:** `CodeHub1443/cv-engineering-agent`

> **V1.1 change:** V1.0 of this document specified a permanent `dev-munna` development
> trunk with a two-stage PM approval gate. That model is retired. `dev-munna` is not a
> mandatory or permanent branch. The current model is a single trunk (`main`) with
> short-lived feature branches integrated by PR, reviewed and merged by the project
> owner. See `docs/state/DECISIONS.md` for the decision record.

## 1. Purpose

This document defines how CV Engineering Agent is developed, reviewed, tested, and
merged through GitHub.

The project follows:

- Trunk-based development on a single trunk, `main`
- Short-lived feature branches
- Pull requests, reviewed before merge
- Mandatory CI/CD validation
- Project owner performs final integration into `main`
- Small, isolated feature increments
- One feature at a time (default)

---

## 2. Branching Model

```text
main
    = verified integration baseline (protected, no direct commits)

feature/<owner>/<work>
    = short-lived development branch, one per feature/fix
```

Flow:

```text
feature/<owner>/<work>
      |
      v
   Pull Request
      |
      v
     CI/CD
      |
      v
  Review + project owner approval
      |
      v
     main
```

### Rules

1. `main` is never used for day-to-day development and never receives direct commits or
   pushes.
2. All work happens on a short-lived `feature/<owner>/<work>` branch cut from `main`.
3. A PR targets `main` directly. There is no intermediate integration trunk.
4. The **project owner performs final integration into `main`** — i.e. approves and
   merges the PR, after CI is green and review is complete.
5. Branches are deleted after merge.

There is no permanent development trunk distinct from `main`. A long-lived integration
branch (e.g. for a large multi-PR effort) may be created ad hoc when explicitly agreed,
but it is the exception, not the default model, and does not replace this section.

---

## 3. One Feature at a Time

```text
Feature A
   |
   v
feature/<owner>/<work>
   |
   v
implementation + local tests
   |
   v
PR -> main
   |
   v
CI/CD
   |
   v
review + owner approval
   |
   v
merge to main
   |
   v
Feature B
```

We do not start unrelated feature branches unless there is a clear dependency or
project-management reason. If a feature becomes too large, split it into smaller
features (CLAUDE.md §6: diffs stay under ~400 lines).

---

## 4. Branch Naming

```text
feature/<owner>/<work>      # e.g. feature/tanvir/llm-gateway
fix/<owner>/<work>          # bug fixes
docs/<owner>/<work>         # documentation-only changes
ci/<owner>/<work>           # CI/CD changes
hotfix/<owner>/<work>       # urgent fixes, see §12
```

`<owner>` is the person or agent session doing the work; `<work>` is a short slug for
what it does. This matches `CLAUDE.md` §6 and `AGENTS.md`'s branch-naming rule — keep
all three in sync if this changes. Traceability to a GitHub issue is carried in the PR
description (§5), not the branch name.

Target branch lifetime:

```text
Ideal:       < 1 day
Acceptable:  1–3 days
Exceptional: > 3 days
```

---

## 5. Pull Request Requirements

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

## 6. CI/CD Gate

Every PR must pass automated validation before merge.

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

GPU-specific CI (CUDA, TensorRT, DeepStream, GPU integration) is added when GPU
infrastructure is available. CPU CI must remain capable of validating the core software
architecture without it.

---

## 7. Local Validation Before Push

Before opening a PR, run the local equivalent of the CI checks:

```bash
pytest tests/ -v
```

plus the project's configured formatting, linting, typing, and build commands. A PR
should not be the first place an obvious failure is discovered.

---

## 8. Review and Merge

### Technical review

Every PR is reviewed for:

- correctness
- maintainability
- architecture consistency
- tests
- security
- performance implications
- API compatibility

### Project owner approval

The project owner reviews and merges every PR into `main`. There is no second,
separate promotion step — technical review and the owner's merge approval together are
the single integration gate.

### Merge strategy

Squash merge feature branches so `main` contains meaningful commits rather than noisy
fix-up history.

---

## 9. Keeping Branches Current

Before opening or merging a PR:

```bash
git fetch origin
git rebase origin/main
```

If a force push is needed after rebasing a feature branch:

```bash
git push --force-with-lease
```

Never force-push `main`.

---

## 10. Feature Completion Definition

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
[ ] Project owner approval received
[ ] PR merged to main
[ ] Post-merge main CI passes
[ ] Branch deleted
```

A feature is not complete merely because its code works locally.

---

## 11. Workstream Distribution

The project is divided into engineering workstreams for organizing branch names; these
are not long-lived branches.

| Workstream | Branch prefix | Owns |
|---|---|---|
| Architecture & Documentation | `docs/*` | architecture, lifecycle, contracts, safety, approval policy, development standards |
| Core Runtime | `feature/*/runtime-*` | LangGraph, state, sessions, checkpointing, interrupts, resume, retries |
| LLM Gateway | `feature/*/llm-*`, `feature/*/provider-*` | provider abstraction, model routing, structured output, streaming, tool calling, retries, fallbacks |
| Knowledge / RAG | `feature/*/knowledge-*`, `feature/*/rag-*` | retrieval, embeddings, reranking, provenance, freshness |
| Research Engine | `feature/*/research-*` | web/GitHub/paper research, evidence verification |
| MCP / Tools | `feature/*/mcp-*`, `feature/*/tool-*` | typed execution boundaries for research, datasets, training, evaluation, benchmarking, GPU profiling, TensorRT, DeepStream |
| CV Intelligence | `feature/*/requirement-*`, `feature/*/*-agent-*` | the CV reasoning layer |
| Training / Experimentation | `feature/*/experiment-*`, `feature/*/training-*` | experiment registry, dataset lineage, training launcher, artifact tracking |
| Evaluation / Benchmarking | `feature/*/evaluation-*`, `feature/*/benchmark-*` | accuracy evaluation, runtime benchmarking, failure analysis |
| NVIDIA / Edge | `feature/*/nvidia-*`, `feature/*/tensorrt-*`, `feature/*/deepstream-*`, `feature/*/jetson-*` | CUDA, TensorRT, DeepStream, Jetson, quantization, kernel optimization |
| Deployment | `feature/*/deployment-*`, `feature/*/monitoring-*` | packaging, production deployment, validation, rollback, monitoring |

None of these workstreams are implemented yet — see `docs/state/STATUS.md` for what
currently exists.

---

## 12. Hotfix Flow

Critical fixes to `main` follow the same single-trunk model, just expedited:

```text
main
  |
  v
hotfix/<owner>/<work>
  |
  v
CI
  |
  v
review + project owner approval
  |
  v
main
```

---

## 13. Non-Negotiable Rules

```text
1. main is never used for day-to-day development.
2. No direct commits or pushes to main.
3. Feature work uses short-lived feature/<owner>/<work> branches.
4. One feature at a time is the default.
5. Every PR requires CI.
6. Every PR requires technical review.
7. Every PR requires project owner approval before merge to main.
8. No force push to main.
9. Expensive/destructive CV-agent operations remain subject to docs/APPROVALS.md,
   independent of this git workflow.
10. Documentation and tests are part of feature completion.
11. main must remain reproducible at every commit.
```

---

## 14. Current Operating State

```text
Trunk:
main

Integration model:
feature/<owner>/<work> -> PR -> review -> project owner merges to main

Current implementation milestone:
Runtime Foundation (see docs/state/STATUS.md)
```
