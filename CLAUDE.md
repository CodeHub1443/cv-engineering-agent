# CLAUDE.md — Operating instructions for coding agents

**This file is instructions, not knowledge.** The knowledge lives in `docs/`. Keep this
file under 150 lines. If you are tempted to add CV knowledge here, it belongs in
`docs/PROJECT.md` (frozen), an ADR, or `docs/GLOSSARY.md`.

Project: **CV Engineering Agent** — an AI system that *performs* computer-vision
engineering, not one that merely knows computer vision.

---

## 1. Canon

`docs/PROJECT.md` is the frozen, authoritative project definition, numbered §1–§35.

- **Never edit, reorder, summarize, or "improve" it.** It changes only by an explicit
  human instruction, never as a side effect of another task.
- Every normative statement you write anywhere else must cite its origin as `[P§12]`.
- If the canon is silent on something you need, do **not** invent a requirement. Either
  add it to `docs/state/OPEN_QUESTIONS.md`, or make the call in an ADR that names the
  gap. Silent invention and silent omission are both defects.
- To override the canon, write an ADR that quotes the section it revises and states why.

## 2. Session start — read in this order

1. `docs/state/AGENT_HANDOFF.md` — session context: agreed decisions, pending approvals,
   known contradictions, implementation truth, and anti-patterns. Rewritten every session.
2. `docs/state/STATUS.md` — where the project actually is.
3. `docs/state/DECISIONS.md` — what is already settled.
4. Only the ADRs relevant to the task at hand.
5. The GitHub issue you are working.

Do **not** bulk-read `docs/`. If `STATUS.md` or `AGENT_HANDOFF.md` contradict the
repository, stop and say so rather than guessing which is right.

## 3. Hard rules — non-negotiable

Derived from `[P§29]`. If a request conflicts with these, say so and stop. Do not comply
quietly and do not work around them.

1. **Problem first.** Never propose a model, architecture, or framework before the
   operational problem is characterized `[P§29.1]`, `[P§5]`.
2. **Baseline first.** Never optimize before a measured baseline exists `[P§29.2]`,
   `[P§11]`. NAS and sweeps are instruments, not defaults.
3. **Evidence over hype.** Never claim an improvement without a quantitative comparison
   against that baseline `[P§29.3]`, `[P§29.10]`. Newer is not better.
4. **Hardware-aware.** Accuracy without deployability is incomplete. Any model
   recommendation states its latency/memory/power implications on the target
   `[P§29.4]`, `[P§12]`, `[P§13]`.
5. **Reproducibility.** No result is valid without the full experiment metadata schema in
   `docs/state/EXPERIMENTS.md` `[P§25]`, `[P§29.5]`.
6. **Boundary test.** No new module, package, or subsystem without answering *what
   responsibility does this own, and why does that responsibility not belong to an
   existing layer?* `[P§34]`. If you cannot answer cleanly, the boundary is wrong — say
   so instead of writing the code.
7. **No layer leakage.** Reasoning, orchestration, knowledge, and execution stay
   separate `[P§19]`, `[P§21]`, `[P§22]`. See `docs/architecture/OVERVIEW.md`.
8. **Provider boundary.** Provider SDKs, provider-specific execution logic, and provider
   semantics stay inside the LLM gateway `[P§20]`. Provider/model identifiers may appear
   in configuration and execution metadata; they must not become provider-specific logic
   in orchestration or reasoning.
9. **Don't reinvent.** Discover and invoke existing NVIDIA skills, CUDA agent, TAO,
   TensorRT, DeepStream tooling rather than reimplementing their knowledge `[P§15]`,
   `[P§29.9]`.
10. **Human approval.** Expensive, destructive, irreversible, or production-affecting
    actions require explicit approval per `docs/APPROVALS.md` `[P§24]`, `[P§29.8]`.
    Estimate the cost *before* asking.
11. **Current knowledge.** When a fact may be stale — model releases, benchmarks, library
    behavior — research it and cite the source with a date. Weight sources per
    `docs/RESEARCH_POLICY.md` `[P§16]`, `[P§17]`.
12. **Not a pile of features.** Prefer deleting a subsystem to bolting one on `[P§34]`.

## 4. What this project is NOT `[P§31]`

Not a chatbot. Not a YOLO wrapper. Not NVIDIA-only. Not unlimited autonomy. Not a RAG
dump. Not a fixed technique list. Not hundreds of hardcoded prompts. If a change moves
the system toward any of these, flag it.

## 5. Architecture gate

- **No implementation code without a GitHub issue.**
- **No architectural code without an ADR.** Architectural = introduces a module, changes
  an interface between layers, chooses a dependency, or changes state shape.
- ADRs live in `docs/architecture/adr/`, numbered, from `ADR-0000-template.md`.
- When acting as architect: produce the ADR and **interface stubs only** — types and
  signatures, no bodies. Implementation is a separate session.
- **Skeleton (Phase 2) definition:** every architecture layer present in code with a
  working **demo/mock** implementation — not just type stubs. Each layer must be
  connected to adjacent layers, invokable with demo data, and testable. Real LLM
  providers, real NVIDIA tools, real training execution, and real RAG retrieval are
  **not** part of the skeleton — those are Phase 3+ feature implementations.
- **No skeleton code begins until Phase 1 is complete** (all 13 ADRs accepted, all
  Q1–Q14 answered, `Implementation_Status.md` verified).


## 6. Implementation loop — per issue

1. Read the issue and its governing ADR. No ADR + architectural change ⇒ stop.
2. Plan first: files, interfaces, tests, and explicitly what you will **not** change.
3. Branch `<type>/<issue-number>-<slug>` from current `dev-munna`. **Never commit to
   `dev-munna` or `main` directly.** Feature PRs target `dev-munna`.
4. Write the acceptance test first, from the issue's acceptance criteria. Show it
   failing.
5. Implement the minimum that makes it pass. No speculative abstraction. No unrelated
   refactors.
6. Lint, type-check, full test suite.
7. Update rolling state (§7).
8. **Show the full diff / summary of changes to AJ and await explicit approval before
   committing or pushing anything.** Do not combine "show" and "push" in the same step.
9. Commit (conventional commits, body cites issue + ADR), push, open a PR from the template.
10. Report what you changed, what you deliberately did not, and what you are unsure about.


Keep diffs reviewable — under ~400 lines. If the issue cannot fit, split the issue.

## 7. Rolling state protocol

Before every commit, and at the end of every session:

| File | Operation | Contents |
|---|---|---|
| `docs/state/AGENT_HANDOFF.md` | **Rewrite** | Session context: agreed decisions, pending approvals, contradictions, implementation truth, anti-patterns. |
| `docs/state/STATUS.md` | **Rewrite**, max 60 lines | Current phase, in-flight work, next 3 actions, blockers. Describes **now**, not history. |
| `docs/state/JOURNAL.md` | **Append** one dated entry | What changed, why, what broke, what was learned. Never edit or delete past entries. |
| `docs/state/DECISIONS.md` | **Append** one line per decision | Decision, date, link to ADR. Architectural decision without an ADR ⇒ write the ADR first. |
| `docs/state/OPEN_QUESTIONS.md` | Append new; strike through answered | Keep the strikethrough — do not delete answered questions. |
| `docs/state/EXPERIMENTS.md` | **Append** one row per run | Full `[P§25]` schema. Missing metadata ⇒ not a valid result. |

`STATUS.md` is the only file that shrinks. Everything else only grows.

## 8. Style

- Python, typed, `ruff` + `mypy` clean. Tests with `pytest`.
- Registries hold typed identities, not free strings `[P§32]`.
- Package-safe resource loading; explicit dependencies `[P§32]`.
- Docstrings state the responsibility the unit owns.
- No `TODO` without a corresponding GitHub issue number.
