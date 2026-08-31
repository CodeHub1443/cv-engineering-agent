# CV Engineering Agent — Development Model

**Status:** Active  
**Repository:** `CodeHub1443/cv-engineering-agent`  
**Audience:** Project Manager, Development PM, developers, AI agents

> This is the single authoritative document for how this project is developed, reviewed,
> tested, approved, merged, and released. It replaces `GITHUB_FLOW_V1.md` and
> `GITHUB_DEVELOPMENT_MODEL.md`, both of which have been deleted.

---

## 1. Branch Roles

```text
                     OFFICIAL PROJECT TRUNK
                            `main`
                               ▲
                               │  Official PM approval
                               │
                         Promotion PR
                               │
                          `dev-munna`
                   DEVELOPMENT INTEGRATION TRUNK
                               ▲
                               │  Development PM (AJ) approval
                               │
                         Feature PR
                               │
                       short-lived branch
                               ▲
                               │
                    developer / coding agent
```

| Branch | Role | Who approves merge into it |
|---|---|---|
| `main` | Official trunk; release authority | Official Project Manager only |
| `dev-munna` | Working development trunk | AJ (Development PM) |
| `<type>/<issue>-<slug>` | Short-lived feature branch | — (PR required before merge) |

---

## 2. Non-Negotiable Rules

1. **Never develop directly on `main`.**
2. **Never push directly to `main`.**
3. **Never develop directly on `dev-munna`.** The sole exception is **rolling-state-only
   commits** — changes limited exclusively to `AGENT_HANDOFF.md`, `STATUS.md`,
   `JOURNAL.md`, `DECISIONS.md`, `OPEN_QUESTIONS.md`, or `EXPERIMENTS.md` — and only
   with explicit PM approval granted per commit. Any source file, ADR, test, config,
   ROADMAP, or documentation change requires a short-lived branch and PR. No exceptions.
4. All feature work uses a short-lived branch — one coherent feature per branch.
5. CI/CD must pass before any feature is approved.
6. Technical review is required.
7. Development PM (AJ) approval is required before merging into `dev-munna`.
8. Official PM approval is required before merging `dev-munna` into `main`.
9. A feature is not complete because it works locally — it is complete after the PR passes all integration gates.
10. Destructive or high-risk agent operations are governed by `docs/APPROVALS.md`.

---

## 3. Feature Development Flow

Every feature follows this sequence:

```text
GitHub Issue (with ADR if architectural)
         ↓
Create branch: <type>/<issue-number>-<slug> from dev-munna
         ↓
Write acceptance test first (show it failing)
         ↓
Implement the minimum that makes it pass
         ↓
Lint + type-check + full test suite locally
         ↓
Update rolling state (AGENT_HANDOFF.md, STATUS.md, JOURNAL.md, DECISIONS.md)
         ↓
Show full diff/summary to AJ — await explicit approval
         ↓
Commit (conventional: body cites issue + ADR)
         ↓
Pull Request → dev-munna
         ↓
Automated CI (ruff + mypy + pytest + build + pip-audit)
         ↓
Technical review + Development PM approval
         ↓
Squash merge → dev-munna
         ↓
Post-merge CI passes
         ↓
Feature complete — next feature starts
```

**One feature at a time.** The next feature starts only after the current one is fully merged and CI is green. Parallel work requires explicit PM authorization.

---

## 4. Official Promotion Flow (`dev-munna` → `main`)

```text
dev-munna
         ↓
Promotion Pull Request → main
         ↓
Full CI/CD
         ↓
Technical review
         ↓
Official Project Manager review + approval
         ↓
Merge → main
         ↓
Post-merge CI passes
         ↓
Official project state updated
```

The Official PM may approve, request changes, reject, or require additional milestones before promotion.

---

## 5. Branch Naming

```
feature/<issue-number>-<slug>   — new capability or layer
fix/<issue-number>-<slug>       — bug fix or correction
docs/<issue-number>-<slug>      — documentation only
ci/<issue-number>-<slug>        — CI/tooling changes
chore/<issue-number>-<slug>     — maintenance, deps, cleanup
```

Branches live **less than 3 days**. If a branch grows larger, split it into smaller features.

---

## 6. Workstreams (Areas of Responsibility — not Git branches)

| Workstream | Owns |
|---|---|
| Architecture & Documentation | ADRs, contracts, governance, lifecycle, API contracts |
| Core Runtime | LangGraph, state, sessions, checkpointing, approval interrupts |
| LLM / AI Integration | LLM gateway, provider adapters, model routing, streaming |
| Knowledge / RAG | Canonical knowledge, ingestion, retrieval, embeddings, provenance |
| Research | NVIDIA, CUDA, TensorRT, DeepStream, Jetson, YOLO, papers, live research |
| MCP / Tooling | Typed execution interfaces for all external tools and services |
| CV Intelligence | Reasoning agents (Requirement, Dataset, Model, Evaluation, Optimization, etc.) |
| Training / Experimentation | Experiment registry, dataset lineage, training launcher, metrics |
| Evaluation / Benchmarking | Accuracy evaluation, runtime benchmarking, failure analysis |

Workstreams are introduced incrementally; they are responsibility boundaries, not a delivery schedule.

---

## 7. Agent-Specific Rules

- No implementation code without a GitHub issue.
- No architectural code without an ADR in `docs/architecture/adr/`.
- Architect sessions produce ADR + interface stubs only — implementation is a separate session.
- When acting as architect: propose, await PM approval, then commit.
- Report what you changed, what you deliberately did not change, and what you are unsure about.
- Rolling state (`AGENT_HANDOFF.md`, `STATUS.md`, `JOURNAL.md`) must be updated before closing any session.

---

## 8. Commit Message Convention

```
<type>(<scope>): <short summary>

<body — what changed, why, what was deliberately excluded>
Closes #<issue>
ADR: ADR-XXXX-<slug>
```

Types: `feat` `fix` `docs` `ci` `chore` `test` `style` `refactor`

---

## 9. CI Gates (must pass before any merge)

| Check | Tool |
|---|---|
| Lint | `ruff check .` |
| Format | `ruff format --check .` |
| Type check | `mypy cv_agent` |
| Tests | `pytest -q` |
| Package build | `python -m build` |
| Dependency audit | `pip-audit` |
