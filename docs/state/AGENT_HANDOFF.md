# AGENT HANDOFF

> **Rewrite this file every session.** One authoritative context snapshot for any incoming
> agent. Read this first — before STATUS.md, before DECISIONS.md, before any ADR.
>
> Read order: this file → `STATUS.md` → `DECISIONS.md` → relevant ADR → the issue.

---

## Snapshot

| Field | Value |
|---|---|
| **Last updated** | 2026-08-31 |
| **Updated by** | AJ + agent (Claude Sonnet 4.6) |
| **Active branch** | `docs/issue-11-adr-0002-llm-gateway` (Target: `dev-munna`) |
| **Phase** | Phase 1 — Architecture & ADR Specification |
| **Testing & CI** | Local: ✅ 95/95 tests pass; Remote CI: runs on PR to `dev-munna` |
| **Worktree** | uncommitted changes on short-lived branch |
| **Python env** | `uv run --extra dev` or `.venv/bin/python` |

---

## 3-Tier Project Model (D-007) — THE GOVERNING STRUCTURE

```
Tier 0: DOCUMENTATION (Phase 0 ✅ + Phase 1 current)
        All ADRs 0001–0013 written + all Q1–Q14 answered + Implementation_Status.md
        ↓  [no skeleton code until this is done]
Tier 1: SKELETON (Phase 2)
        Every layer wired with demo/mock implementations, E2E provable
        ↓  [no real features until skeleton passes exit test]
Tier 2+: FEATURES (Phase 3–10)
        Real implementations one at a time, fully confirmed before next begins
```

---

## AGREED (Human-confirmed — do NOT re-debate)

| ID | Decision | Source |
|---|---|---|
| A-01 | `docs/PROJECT.md` is frozen canon; never edit it | D-001 |
| A-02 | Rolling state: STATUS.md (rewrite) / JOURNAL.md (append) | D-002 |
| A-03 | No implementation without issue; no architecture without ADR | D-003 |
| A-04 | Design order: registry → gateway → orchestration → memory → tools → knowledge → skills → stages | D-004 |
| A-05 | Single typed-registry storage boundary (ADR-0001 accepted) | D-006 |
| A-06 | uv.lock is NOT tracked; delete if appears untracked | Session 2026-08-31 |
| A-07 | `importlib.resources` only — no `_REPO_ROOT` path assumptions | JOURNAL 2026-08-30 |
| A-08 | CI: ruff + mypy + pytest + build + pip-audit on every PR | `.github/workflows/ci.yml` |
| A-09 | Three-tier phase model governs all future work | D-007 |
| A-10 | "Skeleton" = demo/mock at every layer, not just type stubs | D-008 |
| A-11 | Approvals must persist across process restart (file or DB) | D-009 |
| A-12 | First real target = prison escape detection project | D-010 |
| A-13 | Existing code audited against each ADR as written; keep/change/delete | D-011 |
| A-14 | Q1 (project unit) deferred — kept as open parameter in ADR-0003/0004 | D-012 |
| A-15 | LLM gateway must be location-agnostic (local/remote/cloud) | D-013 |
| A-16 | No skeleton code until all 13 ADRs accepted + Q1–Q14 answered | CLAUDE.md §5 |
| A-17 | **Show changes to AJ first — await approval — then commit and push.** Never push without showing changes and receiving explicit approval. | D-014 |
| A-18 | Short-lived branch rule applies to all work types; 6-file rolling state exception only | D-015 |
| A-19 | Accepted Q7 decision: LLM gateway supports Anthropic, OpenAI, Local/Ollama with config routing & transient fallback (formalized by ADR-0002, currently Draft / Awaiting approval) | D-016 |
| A-20 | Accepted Q8 persistence strategy: Dual-layer (Git structured state + SQLite experiment ledger; to be formally specified by ADR-0004) | D-017 |

---

## PENDING HUMAN APPROVAL

None from previous sessions. Next session's items will appear here.

| ID | Question | Options | Blocks |
|---|---|---|---|
| Q-D1 | Q5: Which NVIDIA tools are installed and invocable? | List them | ADR-0005, ADR-0007 |
| Q-D2 | Q6: Default cost thresholds? | $ / GPU-hours / wall-clock | `docs/APPROVALS.md` |
| Q-D3 | Q7: LLM provider classes & routing policy | Resolved (D-016 → ADR-0002 Draft) | — |
| Q-D4 | Q8: Persistence backend for memory & ledger | Resolved (D-017 → ADR-0004 pending) | — |
| Q-D5 | Q9: LinkedIn access mechanism? | Describe access | ADR-0006 |
| Q-D6 | Q10: Dataset storage/versioning? | DVC / Git LFS / object store | ADR-0009 |
| Q-D7 | Q11–Q14: Multi-camera, monitoring backend, fine-tuning, multi-user? | Answers | Various ADRs |

Answer these and ADR-0002 can be written immediately.

---

## ADR STATUS

| ADR | Topic | Status | Blocks |
|---|---|---|---|
| ADR-0001 | Capability model (typed registry) | ✅ Accepted | — |
| ADR-0002 | LLM gateway | 📋 Draft / Awaiting approval | — |
| ADR-0003 | Orchestration state + approval interrupts | ❌ Not written | Q1 deferred (open param) |
| ADR-0004 | Project memory + experiment ledger | ❌ Not written | — |
| ADR-0005 | Tool/MCP boundary | ❌ Not written | Needs Q5 answer |
| ADR-0006 | Retrieval, provenance, freshness | ❌ Not written | Needs Q9 answer |
| ADR-0007 | Skill registry + discovery | ❌ Not written | Needs Q5 answer |
| ADR-0008 | CV reasoning nodes | ❌ Not written | — |
| ADR-0009 | Dataset subsystem | ❌ Not written | Needs Q10 answer |
| ADR-0010 | Training execution | ❌ Not written | — |
| ADR-0011 | Evaluation + failure analysis | ❌ Not written | — |
| ADR-0012 | Optimization + deployment | ❌ Not written | — |
| ADR-0013 | Monitoring | ❌ Not written | — |

---

## Implementation Truth (current — see Implementation_Status.md for full detail)

| Layer | What exists | Status |
|---|---|---|
| Config + CLI health check | coded + tested + CI | ✅ |
| Capability registry (list/describe/check/select) | coded + tested + CI | ✅ |
| `resolve()` contract | NOT coded | ❌ |
| LLM gateway (abstract + mock only) | coded + tested | ⚠️ needs ADR-0002 audit |
| LangGraph graph (START→init→END) | coded + tested | ⚠️ needs ADR-0003 audit |
| AgentState TypedDict + HITL fields reserved | coded + tested | ⚠️ needs audit |
| Real LLM providers (Anthropic/OpenAI/etc.) | NOT coded | ❌ Phase 3 |
| Approval gate + persistence | NOT coded | ❌ Phase 3 |
| Project memory, experiment ledger | NOT coded | ❌ Phase 2 (demo) / Phase 3 (real) |
| Tool/MCP, RAG, Skills, CV agents, Training, Eval, Optimize, Monitor | NOT coded | ❌ Phase 2+ |
| CLI subcommands (capabilities/skills/resolve) | NOT coded (args ignored) | ❌ Phase 2 |

---

## OPEN QUESTIONS (do NOT answer without human input)

| Q | Status | Blocks |
|---|---|---|
| Q5 | ❌ unanswered | ADR-0005, ADR-0007 |
| Q6 | ❌ unanswered | `docs/APPROVALS.md` thresholds |
| Q7 | ✅ Answered (D-016 → ADR-0002 Draft) | — |
| Q8 | ✅ Answered (D-017 → ADR-0004 pending) | — |
| Q9 | ❌ unanswered | ADR-0006 |
| Q10 | ❌ unanswered | ADR-0009 |
| Q11–Q14 | ❌ unanswered | Various ADRs |

Q1–Q4, Q7, Q8 answered. See `OPEN_QUESTIONS.md` for full context.

---

## DO NOT

- ❌ Edit `docs/PROJECT.md`
- ❌ Commit directly to `dev-munna` or `main` without PM approval
- ❌ **Push to remote without first showing AJ the changes and receiving explicit approval**
- ❌ Create implementation code without a GitHub issue
- ❌ Create architectural code without an ADR
- ❌ Begin skeleton code (Phase 2) until all 13 ADRs are accepted
- ❌ Begin real feature implementation (Phase 3+) until skeleton exit test passes
- ❌ Silently reconcile contradictions — report and stop
- ❌ Invent answers to Q5–Q14
- ❌ Use `_REPO_ROOT` path assumptions — use `importlib.resources`
- ❌ Import provider SDKs outside `cv_agent/llm/`
- ❌ Bulk-read `docs/` at session start

---

## Next Agent Actions (priority order)

1. **Ask the user:** Q5 (NVIDIA installed), Q7 (LLM providers + keys), Q8 (persistence backend)
2. Once Q7 answered → write ADR-0002 (LLM gateway) — first Phase 1 architecture task
3. Once Q5 answered → write ADR-0005 (tool/MCP) and ADR-0007 (skill registry)
4. Write ADR-0003 (orchestration, Q1 kept open), ADR-0004 (memory)
5. Continue writing remaining ADRs in design-order (D-004)
6. Verify GitHub labels/milestones/branch protections (Phase 0 remaining item)

## This Session Summary

- Created `AGENT_HANDOFF.md` and wired into CLAUDE.md/AGENTS.md read order
- Redesigned phase model (3-tier: docs → skeleton → features)
- Answered Q1–Q4; struck through in OPEN_QUESTIONS.md
- Rewrote ROADMAP.md with new phase structure and exit tests
- Created `Implementation_Status.md` (all 13 layers documented)
- Merged two dev model docs → `docs/development/DEVELOPMENT_MODEL.md`
- Moved `CV Engineering Agent.md` → `docs/ORIGINAL_BRIEF.md`; deleted root copy
- Updated CLAUDE.md §5 skeleton definition
- Appended to JOURNAL.md and DECISIONS.md (D-007 through D-013)
- Updated OPEN_QUESTIONS.md
