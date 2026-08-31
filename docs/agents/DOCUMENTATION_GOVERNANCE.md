# Documentation Governance Procedure

## Purpose

Use this procedure when auditing, designing, or maintaining project Markdown documentation. It complements `CLAUDE.md`; it does not replace its hard rules.

## Absolute approval gate

Do not create, modify, delete, rename, or commit any Markdown file until the repository analysis is complete and the human owner explicitly approves the proposed changes.

Before editing any Markdown file:

1. Inspect the repository and GitHub state.
2. Read the relevant canon, state, roadmap, ADRs, and implementation evidence.
3. Report contradictions and documentation gaps.
4. Ask all questions needed to resolve ambiguity.
5. Propose the exact file list, structure, and changes.
6. Obtain explicit approval.
7. Show complete proposed content for new files and exact diffs for existing files.
8. Obtain approval for the exact content.

If approval is ambiguous, stop.

## Repository and Git discipline

- Never commit directly to `main`.
- Never commit directly to `dev-munna`.
- Documentation work normally uses a short-lived branch `<type>/<issue-number>-<slug>` from current `dev-munna`.
- Do not rewrite shared history.
- Do not delete branches unless explicitly requested.
- Do not create temporary repository artifacts for internal reasoning.
- GitHub state must be checked when documenting implementation status.

## Source hierarchy

Use these roles consistently:

- `docs/PROJECT.md` — frozen project canon. Never edit it unless explicitly instructed by a human.
- `README.md` — project entry point and high-level orientation.
- `CLAUDE.md` / `AGENTS.md` — agent operating rules.
- `docs/roadmap/ROADMAP.md` — phases, scope, and measurable exit tests.
- `docs/architecture/OVERVIEW.md` — system structure and layer responsibilities.
- `docs/architecture/adr/` — individual architectural decisions.
- `docs/state/STATUS.md` — current state only; rewrite, maximum 60 lines.
- `docs/state/JOURNAL.md` — historical record; append only.
- `docs/state/DECISIONS.md` — settled decisions; append only.
- `docs/state/OPEN_QUESTIONS.md` — unresolved questions; append new questions and strike through answered ones.
- `docs/state/EXPERIMENTS.md` — reproducible experiment ledger.
- `Implementation_Status.md` — only if approved and genuinely needed; tracks implementation reality rather than roadmap or current-session state.

Do not create overlapping sources of truth.

## Required investigation order

For a documentation/status audit, read in this order unless the task specifies otherwise:

1. `README.md`
2. `CLAUDE.md`
3. `AGENTS.md`
4. `docs/PROJECT.md`
5. `docs/GLOSSARY.md`
6. `docs/architecture/OVERVIEW.md`
7. `docs/state/STATUS.md`
8. `docs/state/DECISIONS.md`
9. `docs/state/OPEN_QUESTIONS.md`
10. `docs/state/JOURNAL.md`
11. `docs/state/EXPERIMENTS.md`
12. `docs/roadmap/ROADMAP.md`
13. `docs/APPROVALS.md`
14. `docs/RESEARCH_POLICY.md`
15. `docs/EVALUATION.md`
16. `docs/DATA.md`
17. ADRs relevant to the requested work

Then inspect relevant source, tests, Git history, PRs, and CI evidence.

## Implementation-status model

Never equate documentation with implementation. Track these independently where relevant:

`DOCUMENTED → DESIGNED → IMPLEMENTED → TESTED → CI VERIFIED → MERGED TO DEV-MUNNA → MERGED TO MAIN`

A feature is not considered implemented merely because it appears in a roadmap, ADR, architecture diagram, or status document.

For implementation-status claims, prefer repository and GitHub evidence over prose claims.

A useful status matrix is:

| Area | Specified | ADR | Implemented | Tested | CI | Merged to dev-munna | On main |
|---|---|---|---|---|---|---|---|
| component | evidence | ADR | evidence | evidence | run | PR/commit | commit |

Do not invent missing evidence.

## Implementation status document

If an `Implementation_Status.md` is approved, it should remain an implementation ledger, not another roadmap.

Recommended fields:

- Feature / component
- Purpose
- Phase
- GitHub issue
- Governing ADR
- Implementation status
- Implementation location
- Acceptance tests
- CI status
- Branch
- PR
- Merged to `dev-munna`
- Merged to `main`
- Known limitations
- Next action

Use precise status vocabulary and define it once. Avoid duplicating `STATUS.md`.

## Architecture documentation

Do not create a second architecture source if `docs/architecture/OVERVIEW.md` and the ADRs already provide the required coverage.

If architecture documentation is inadequate, propose the smallest change that closes the gap.

Architecture documentation must distinguish:

- project canon
- structural architecture
- architectural decisions
- implementation status
- runtime behavior
- future work

Do not claim a component is implemented merely because it appears in architecture documentation.

## Phase tracking

Validate phase claims against `docs/roadmap/ROADMAP.md` and its measurable exit test.

For Phase 1, validate at minimum the substrate sequence and acceptance boundaries for:

1. Capability model / resolution — ADR-0001.
2. LLM gateway — ADR-0002.
3. Orchestration state and approval interrupts — ADR-0003.
4. Project memory and experiment ledger — ADR-0004.

Do not assume these are implemented. Verify them against code, tests, CI, and Git history.

## Open questions

Never invent answers to unresolved questions.

For each proposed feature or architectural change, determine whether an open question blocks it. Distinguish:

- documented answer
- repository-supported inference
- proposed answer
- unresolved blocker

Only update `OPEN_QUESTIONS.md` after explicit approval.

## Contradiction handling

When documentation conflicts with repository evidence, do not silently reconcile it.

Report the contradiction, identify the authoritative source, and propose the smallest correction.

Examples:

- `STATUS.md` says CI pending but GitHub CI is green.
- Roadmap phase differs from current status.
- ADR interface differs from implementation.
- README describes an obsolete workflow.
- GitHub shows a merged PR while documentation says pending.

## Avoid documentation sprawl

Before creating a new Markdown file, prove that an existing file cannot cleanly serve the purpose.

Do not create separate documents that merely repeat:

- the roadmap
- current status
- architectural decisions
- Git history
- implementation details

Prefer one authoritative location for each class of information.

## No temporary repository files

Never create files such as `.tmp`, `.temp`, `.phase0-pr-note`, `scratch.md`, `debug.md`, or other temporary artifacts in the repository.

Use an external temporary workspace if needed.

## Final documentation checks

Before completion, verify:

- `docs/PROJECT.md` is untouched.
- No duplicate source of truth was introduced.
- `STATUS.md` contains current state only.
- `JOURNAL.md` remains append-only history.
- `DECISIONS.md` remains the decision ledger.
- `OPEN_QUESTIONS.md` preserves unanswered and answered questions correctly.
- `ROADMAP.md` remains the phase and exit-test authority.
- Architecture documentation describes architecture rather than progress.
- ADRs remain individual decisions.
- Implementation status is backed by repository/GitHub evidence.
- Phase claims match measurable exit tests.
- No speculative implementation claims were introduced.
- No unrelated files changed.

## Required interaction pattern

For any documentation task:

**Investigate → report → ask questions → propose changes → obtain approval → show exact content/diff → obtain approval → edit → verify → report.**

Never skip the approval gates.
