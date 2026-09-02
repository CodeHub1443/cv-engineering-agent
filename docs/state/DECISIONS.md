# DECISIONS

> **Append-only, one line per decision.** The ledger of what is settled, so a fresh
> session can absorb the project's commitments in thirty seconds without reading every
> ADR. Any *architectural* decision listed here must have an ADR; if it does not, write
> the ADR before committing.

| # | Date | Decision | Canon | ADR | Status |
|---|---|---|---|---|---|
| D-001 | 2026-08-30 | `docs/PROJECT.md` is frozen canon; all normative statements cite `[P§n]`; changes to intent happen only via ADR | `[P§35]` | — | accepted |
| D-002 | 2026-08-30 | Rolling state split into *state* (`STATUS.md`, rewritten) and *history* (`JOURNAL.md`, append-only) | `[P§25]` | — | accepted |
| D-003 | 2026-08-30 | No implementation code without an issue; no architectural code without an ADR | `[P§34]` | — | accepted |
| D-004 | 2026-08-30 | Design order fixed: registry → gateway → orchestration state → memory → tools → knowledge → skills → stages → execution | `[P§33]`, `[P§34]` | — | accepted |
| D-005 | 2026-08-30 | Capability / skill / tool / agent kept as four distinct typed registries | `[P§23]` | ADR-0001 | **superseded** |
| D-006 | 2026-08-30 | Two independent canons, not one chain: `docs/PROJECT.md` (knowledge) and `CLAUDE.md` (instructions, mirrored by `AGENTS.md`). Raw pre-canon draft moved from repo root to `docs/archive/PROJECT_SOURCE_DRAFT.md`, marked superseded and non-authoritative | `[P§35]` | — | accepted |
| D-007 | 2026-09-01 | Retired `spec/00,01,02,07,09` (fully duplicated `docs/PROJECT.md` or conflicted with ADR-governed `docs/architecture/OVERVIEW.md` / `docs/APPROVALS.md` / `docs/state/EXPERIMENTS.md`); reduced `spec/03,05` to technical elaborations citing the canon; merged unique gated actions from `spec/07` into `docs/APPROVALS.md`; extended `docs/state/EXPERIMENTS.md`'s schema with `spec/09`'s useful fields (`status`, `parent_exp_id`, `approval_ref`, timestamps) | `[P§35]` | — | accepted |
| D-008 | 2026-09-01 | Git workflow: single trunk `main` + short-lived `feature/<owner>/<work>` branches, PR reviewed and merged by the project owner. Two-trunk `main`/`dev-munna` model with a two-stage PM approval gate is retired — `dev-munna` is not a mandatory or permanent branch. `CLAUDE.md`, `AGENTS.md`, `docs/development/GITHUB_FLOW_V1.md`, `docs/development/GITHUB_DEVELOPMENT_MODEL.md` all updated to describe the same model | — | — | superseded |
| D-009 | 2026-09-01 | Capability registry semantics: DECLARED CAPABILITY != EXECUTABLE CAPABILITY. Introduced `status: "planned"` (specified, no executable binding) distinct from `"available"` (specified AND a verified executable binding exists). All 20 capabilities in `spec/capability_registry.json` corrected from `"available"`/`"partial"` to `"planned"` — none has an executable binding. `check_item()` no longer hardcodes `available: True`; reports `executable: False` with a reason for every registry item. `select()`/`is_available` now require `status == "available"` strictly | `[P§23]` | ADR-0001 (§8a) | accepted |
| D-010 | 2026-09-01 | Three-level development flow: short-lived work branches merge into `dev-munna`; milestone changes are promoted from `dev-munna` to `main` by a final PR reviewed by the Official PM. `dev-munna` is the PM development/integration trunk; `main` is the official integration/release trunk. | — | — | accepted |
| D-011 | 2026-09-01 | ADR-0001 capability model is accepted. The four registry identities are semantic/type boundaries; independent storage backends are not required by this decision. This supersedes the proposed state of D-005 while preserving its four-way identity distinction. | `[P§23]`, `[P§34]` | ADR-0001 | accepted |
| D-012 | 2026-09-01 | ADR-0002 LLM Gateway and Provider Abstraction is accepted: provider isolation, configuration-driven routing, transient fallback taxonomy, fast-fail request/configuration errors, normalized responses/errors, and reproducibility metadata are the Phase 1 gateway contract. | `[P§20]`, `[P§29.3]`, `[P§29.5]`, `[P§34]` | ADR-0002 | accepted |
| D-013 | 2026-09-01 | Q1 — one CV Engineering Agent project per repository/workspace; project memory and experiment records are isolated to that project, with experiment identifiers scoped to the project. | `[P§25]`, `[P§33]` | ADR-0004 | accepted |
| D-014 | 2026-09-01 | Q2 — the agent runs on the local workstation; training is submitted as an external job to a configured local, remote, or cloud GPU target and is not executed in-process. | `[P§10]`, `[P§13]`, `[P§24]` | ADR-0003 / ADR-0010 | accepted |
| D-015 | 2026-09-01 | Q3 — human approvals are persistent workflow entities. The initial interaction surface may be CLI-based, but approval requests and state survive process restarts and support asynchronous approval. | `[P§24]` | ADR-0003 | accepted |
| D-016 | 2026-09-01 | Q4 — Phase 1 architecture targets a real CV project; prison/garment examples are reference workloads and validation fixtures, not the architectural scope itself. | `[P§30]` | — | accepted |
| D-017 | 2026-09-01 | Q7 — initial LLM provider classes are Anthropic, OpenAI, and Local/Ollama; routing is configuration-driven; transient failures may fall back sequentially; request/configuration failures fail fast; metadata is preserved. | `[P§20]` | ADR-0002 | accepted |
| D-018 | 2026-09-01 | Q8 — dual-layer persistence: Git-tracked structured project memory plus local SQLite at `.cv_agent/state/experiments.sqlite` for high-volume experiment rows. | `[P§25]` | ADR-0004 | accepted |
| D-019 | 2026-09-01 | ADR-0003 Orchestration State Machine, Checkpointing, and Persistent Approvals is drafted and proposed: LangGraph StateGraph with SQLite checkpointer at `.cv_agent/state/checkpoints.sqlite`, persistent approval interrupts, and asynchronous external job handles. | `[P§21]`, `[P§24]`, `[P§25]`, `[P§34]` | ADR-0003 | proposed |
| D-020 | 2026-09-02 | ADR-0003 Orchestration State Machine, Checkpointing, and Persistent Approvals is accepted: LangGraph StateGraph with runtime checkpoint persistence at `.cv_agent/state/checkpoints.sqlite` with configurable retention, persistent approval interrupts surviving process restarts, and asynchronous external job handles. Reconciled with D-018 to preserve separate experiment ledger. | `[P§21]`, `[P§24]`, `[P§25]`, `[P§34]` | ADR-0003 | accepted |

## Reversals

Record here when a decision is overturned. Never delete the original row — mark it
`superseded` and add the new row with a pointer.

| # | Date | Reverses | Why | New ADR |
|---|---|---|---|---|
| R-001 | 2026-08-30 | D-005 | ADR-0001 review found that four independent storage registries are unnecessary for the V1 substrate; semantic identity separation is retained through typed APIs and the future resolver contract. | ADR-0001 |
| R-002 | 2026-09-01 | D-008 | The PM explicitly reinstated `dev-munna` as the development/integration trunk while retaining `main` as the Official PM's integration/release trunk. The two-trunk model is intentional: short-lived branches → `dev-munna` → final PR → `main`. | D-010 |
