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
| D-005 | 2026-08-30 | Capability / skill / tool / agent kept as four distinct typed registries | `[P§23]` | ADR-0001 | superseded |
| D-006 | 2026-08-30 | Capability, skill, tool, and agent remain semantically distinct, but V1 uses one typed registry storage boundary with an explicit future resolution contract | `[P§23]`, `[P§32]`, `[P§34]` | ADR-0001 | accepted |
| D-007 | 2026-08-31 | Three-tier phase model: (1) Architecture Complete — all ADRs + Q1–Q14 + Implementation_Status.md; (2) Skeleton — demo/mock at every layer, E2E provable; (3) Feature implementation — real features one at a time | `[P§33]`, `[P§34]` | — | accepted |
| D-008 | 2026-08-31 | "Skeleton" means every architecture layer present in code with a working demo/mock implementation — not just type stubs. Real implementations are Phase 3+. | `[P§33]` | — | accepted |
| D-009 | 2026-08-31 | Human approval transport must survive process restart — approvals are persisted entities (file or DB), not in-process interrupts | `[P§24]` | ADR-0003 (pending) | accepted |
| D-010 | 2026-08-31 | First real target is the prison escape detection project — not a synthetic fixture | `[P§30]` | — | accepted |
| D-011 | 2026-08-31 | Existing code is audited against each ADR as it is written; kept if it fits, marked for change if it does not, deleted if it has no place | `[P§32]`, `[P§34]` | — | accepted |
| D-012 | 2026-08-31 | Q1 (unit of a project) deferred to implementation — ADR-0003/0004 keep it as an open parameter | `[P§25]`, `[P§33]` | ADR-0003 (pending) | accepted |
| D-013 | 2026-08-31 | LLM gateway substrate (ADR-0002) must support any deployment location — local, remote GPU box, cloud — without location assumptions | `[P§20]` | ADR-0002 (pending) | accepted |


## Reversals

Record here when a decision is overturned. Never delete the original row — mark it
`superseded` and add the new row with a pointer.

| # | Date | Reverses | Why | New ADR |
|---|---|---|---|---|
| R-001 | 2026-08-30 | D-005 | ADR-0001 review found that four independent storage registries are unnecessary for the V1 substrate; semantic identity separation is retained through typed APIs and the future resolver contract. | ADR-0001 |
