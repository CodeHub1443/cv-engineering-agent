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

## Reversals

Record here when a decision is overturned. Never delete the original row — mark it
`superseded` and add the new row with a pointer.

| # | Date | Reverses | Why | New ADR |
|---|---|---|---|---|
| — | — | — | — | — |
