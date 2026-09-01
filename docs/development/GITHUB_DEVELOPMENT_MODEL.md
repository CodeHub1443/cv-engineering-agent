# CV Engineering Agent — GitHub Development Model

**Audience:** Project owner, developers, AI/CV coding agents
**Status:** Approved operating model
**Repository:** `CodeHub1443/cv-engineering-agent`

> **Supersedes the two-trunk (`main` / `dev-munna`) model.** Earlier versions of this
> document specified a permanent `dev-munna` development trunk with a two-stage PM
> approval gate (a Development PM and an Official Project Manager). That model is
> retired — `dev-munna` is not a mandatory or permanent branch, and there is no
> two-stage approval. See `docs/state/DECISIONS.md` for the decision record.
>
> This file is the executive summary. `docs/development/GITHUB_FLOW_V1.md` is the
> full procedural reference (PR template, CI/CD pipeline, branch naming, workstream
> list). Keep the two in sync — this file must not restate procedural detail that
> drifts from it.

## 1. Executive Summary

CV Engineering Agent uses trunk-based development on a single trunk, with short-lived
feature branches.

- **`main`** is the verified integration baseline and the release source.
- Developers and coding agents never commit directly to `main`.
- Every change is implemented on a short-lived `feature/<owner>/<work>` branch, opened
  as a PR against `main`, validated by CI/CD, reviewed, and merged.
- **The project owner performs final integration into `main`** — there is no separate
  promotion step or second approval trunk.

This keeps `main` clean, stable, auditable, and always releasable, without the
overhead of a second permanent integration branch.

---

## 2. Branch Roles

```text
                 main
      (verified integration baseline)
                   ▲
                   │
        review + project owner approval
                   │
             Pull Request
                   │
                   │
    feature/<owner>/<work>  (short-lived)
```

### `main`

- Protected: no direct commits or pushes.
- Every change arrives via a reviewed, CI-passing PR.
- Always represents a working, reproducible state.

### `feature/<owner>/<work>`

- Cut from `main`.
- One feature or fix per branch.
- Short-lived (see target lifetimes in `GITHUB_FLOW_V1.md` §4).
- Deleted after merge.

There is no permanent `dev-munna`-style development trunk. A long-lived integration
branch for an unusually large, explicitly-agreed multi-PR effort may exist temporarily,
but it is the exception, not part of the default model.

---

## 3. Non-Negotiable Rules

```text
1. main is never used for development.
2. No direct commits or pushes to main.
3. All feature work uses short-lived feature/<owner>/<work> branches.
4. One feature at a time is the default.
5. Every PR requires CI, technical review, and project owner approval.
6. No force push to main.
7. Expensive/destructive CV-agent operations remain subject to docs/APPROVALS.md,
   independent of this git workflow.
```

---

## 4. Pull Request and CI/CD Requirements

See `docs/development/GITHUB_FLOW_V1.md` §5–§8 for the PR template, the CI/CD pipeline
stages, and the review/merge process. Both documents describe the same gate — do not
add a second one here.

---

## 5. Workstream Model

See `docs/development/GITHUB_FLOW_V1.md` §11 for the current workstream-to-branch-prefix
mapping. None of the listed workstreams are implemented yet — `docs/state/STATUS.md` is
authoritative on what currently exists.

---

## 6. Development Sequence

The project is implemented in dependency order, matching `docs/roadmap/ROADMAP.md`'s
phases:

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

Each item becomes one or more small issues and short-lived branches. This is a
development-order list, not a claim that any of these exist yet.

---

## 7. Traceability

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
Project Owner Approval
   ↓
main
```

ML experiments additionally follow the lineage in `docs/state/EXPERIMENTS.md`
(requirement → experiment → dataset version → code commit → model/config → metrics →
benchmark → decision).

---

## 8. Releases and Hotfixes

`main` is the sole release source; releases are tagged from approved `main` commits
(`v0.1.0`, `v0.2.0`, …). Hotfixes follow the same single-trunk model on an expedited
timeline — see `docs/development/GITHUB_FLOW_V1.md` §12.

---

## 9. Operating Principle

```text
ONE FEATURE
     ↓
ONE SHORT-LIVED BRANCH
     ↓
IMPLEMENT
     ↓
TEST
     ↓
CI
     ↓
REVIEW
     ↓
PROJECT OWNER APPROVAL
     ↓
MERGE TO main
     ↓
NEXT FEATURE
```

This is the canonical GitHub development model for CV Engineering Agent.
