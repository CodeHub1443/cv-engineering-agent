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
| D-005 | 2026-08-30 | Capability / skill / tool / agent kept as four distinct typed registries | `[P§23]` | ADR-0001 | **proposed** |
| D-006 | 2026-08-30 | Two independent canons, not one chain: `docs/PROJECT.md` (knowledge) and `CLAUDE.md` (instructions, mirrored by `AGENTS.md`). Raw pre-canon draft moved from repo root to `docs/archive/PROJECT_SOURCE_DRAFT.md`, marked superseded and non-authoritative | `[P§35]` | — | accepted |
| D-007 | 2026-09-01 | Retired `spec/00,01,02,07,09` (fully duplicated `docs/PROJECT.md` or conflicted with ADR-governed `docs/architecture/OVERVIEW.md` / `docs/APPROVALS.md` / `docs/state/EXPERIMENTS.md`); reduced `spec/03,05` to technical elaborations citing the canon; merged unique gated actions from `spec/07` into `docs/APPROVALS.md`; extended `docs/state/EXPERIMENTS.md`'s schema with `spec/09`'s useful fields (`status`, `parent_exp_id`, `approval_ref`, timestamps) | `[P§35]` | — | accepted |
| D-008 | 2026-09-01 | Git workflow: single trunk `main` + short-lived `feature/<owner>/<work>` branches, PR reviewed and merged by the project owner. Two-trunk `main`/`dev-munna` model with a two-stage PM approval gate is retired — `dev-munna` is not a mandatory or permanent branch. `CLAUDE.md`, `AGENTS.md`, `docs/development/GITHUB_FLOW_V1.md`, `docs/development/GITHUB_DEVELOPMENT_MODEL.md` all updated to describe the same model | — | — | accepted |
| D-009 | 2026-09-01 | Capability registry semantics: DECLARED CAPABILITY != EXECUTABLE CAPABILITY. Introduced `status: "planned"` (specified, no executable binding) distinct from `"available"` (specified AND a verified executable binding exists). All 20 capabilities in `spec/capability_registry.json` corrected from `"available"`/`"partial"` to `"planned"` — none has an executable binding. `check_item()` no longer hardcodes `available: True`; reports `executable: False` with a reason for every registry item. `select()`/`is_available` now require `status == "available"` strictly | `[P§23]` | ADR-0001 (§8a) | accepted |

## Reversals

Record here when a decision is overturned. Never delete the original row — mark it
`superseded` and add the new row with a pointer.

| # | Date | Reverses | Why | New ADR |
|---|---|---|---|---|
| — | — | — | — | — |
