# AGENT HANDOFF

> **Rewrite this file every session.** One authoritative context snapshot for any incoming
> agent. Covers: current state, agreed decisions, pending approvals, known contradictions,
> implementation truth, and what NOT to do. Complements `STATUS.md`; does not replace it.
>
> Read order: this file → `STATUS.md` → `DECISIONS.md` → relevant ADR → the issue.

---

## Snapshot

| Field | Value |
|---|---|
| **Last updated** | 2026-08-31 |
| **Updated by** | AJ + agent (Claude Sonnet 4.6) |
| **Active branch** | `fix/runtime-baseline-cleanup` |
| **Phase** | 0 → transitioning (see PENDING) |
| **CI** | ✅ runs on dev-munna; 89/89 tests pass locally |
| **Worktree** | clean |
| **Python env** | `uv run --extra dev` or `.venv/bin/python` |

---

## What Was Done This Session

| # | Work | Result |
|---|---|---|
| 1 | `git fetch` + switched to `fix/runtime-baseline-cleanup` | ✅ branch tracks `origin/fix/runtime-baseline-cleanup` |
| 2 | Ran `python3 -m pytest -v` | ✅ 89/89 passed, 0 failed |
| 3 | Inspected `uv.lock` (untracked) | ✅ confirmed not in any branch; deleted |
| 4 | CLI smoke test: `python -m cv_agent [capabilities\|skills\|resolve]` | ⚠️ all args silently ignored — only health-check runs |
| 5 | Package build + isolated install smoke test | ✅ wheel builds, installs, resources load outside repo |
| 6 | Full documentation audit per `docs/agents/DOCUMENTATION_GOVERNANCE.md` | ✅ 12 contradictions found (C1–C12); 6 questions raised (Q-D1–Q-D6) |

---

## AGREED (Human-confirmed decisions)

These are settled. Do not re-debate them.

| ID | Decision | Evidence |
|---|---|---|
| A-01 | `docs/PROJECT.md` is frozen canon; never edit it | D-001 in DECISIONS.md |
| A-02 | Rolling state split: STATUS.md (rewrite) / JOURNAL.md (append) | D-002 |
| A-03 | No implementation without issue; no architecture without ADR | D-003 |
| A-04 | Design order: registry → gateway → orchestration → memory → tools → knowledge → skills → stages | D-004 |
| A-05 | Single typed-registry storage boundary (ADR-0001 accepted) | D-006; supersedes D-005 |
| A-06 | uv.lock is NOT tracked; delete if appears untracked | Confirmed this session |
| A-07 | Package resources (`importlib.resources`) must be used; no `_REPO_ROOT` path assumptions | JOURNAL 2026-08-30 |
| A-08 | CI workflow exists and runs: ruff + mypy + pytest + build + pip-audit | `.github/workflows/ci.yml` |
| A-09 | `CV Engineering Agent.md` (root) is a duplicate of `docs/PROJECT.md` — **pending deletion approval** | Audit C7 |

---

## PENDING HUMAN APPROVAL

No work can proceed on these until you answer. State your decision next session.

| ID | Question | Options | Blocks |
|---|---|---|---|
| Q-D1 | Is **Phase 0 officially complete**? | A=yes → update STATUS to Phase 1 / B=no → finish GitHub scaffolding first | STATUS.md update, JOURNAL entry |
| Q-D2 | Which branch gets documentation updates? | A=this PR (`fix/runtime-baseline-cleanup`) / B=new `docs/` branch from dev-munna | Rolling state commit |
| Q-D3 | Delete `CV Engineering Agent.md` (root)? | A=delete / B=keep / C=redirect | De-duplication |
| Q-D4 | Which dev model doc survives? | A=keep `GITHUB_FLOW_V1.md` / B=keep `GITHUB_DEVELOPMENT_MODEL.md` / C=merge / D=keep both | Documentation sprawl fix |
| Q-D5 | Create `Implementation_Status.md`? | A=yes / B=no | Optional ledger |
| Q-D6 | Phase label after STATUS.md update | A=`Phase: 1 — Substrate` / B=`Phase: 0` | STATUS.md |

---

## CONTRADICTIONS FOUND (Unresolved)

Agent must NOT silently reconcile these. Report and stop if encountered.

| ID | File | Claimed | Reality | Severity |
|---|---|---|---|---|
| C1 | `STATUS.md` line 12 | Branch `fix/phase-0-baseline-governance` in-progress | Merged to dev-munna (`91ee050`) 2026-08-30 | 🔴 High |
| C2 | `STATUS.md` line 14 | "CI has not yet run in GitHub" | CI ran; 90+ fix commits exist | 🔴 High |
| C3 | `STATUS.md` line 6 | `Updated: 2026-08-30` | Stale; audit was 2026-08-31 | 🟡 Medium |
| C4 | ROADMAP Phase 0 exit test | Claimed substantially complete | Exit test fails while STATUS.md is inaccurate | 🔴 High |
| C5 | `JOURNAL.md` last entry | "CI not yet executed" | CI ran and passed | 🟡 Medium (append-only → new entry needed) |
| C6 | `fix/runtime-baseline-cleanup` | Rolling state not updated per CLAUDE.md §7 | No STATUS/JOURNAL update for this branch's commits | 🟡 Medium |
| C7 | Repo root | `CV Engineering Agent.md` exists | Byte-identical to `docs/PROJECT.md` — duplicate source of truth | 🔴 High |
| C8 | `docs/development/` | Two near-identical files | `GITHUB_FLOW_V1.md` + `GITHUB_DEVELOPMENT_MODEL.md` both cover same content | 🟡 Medium |
| C9 | — | `Implementation_Status.md` absent | Governance permits it; evidence warrants it; needs approval | 🔵 Info |
| C10 | History | `docs/state/.phase0-pr-note` created+deleted | Violates no-temp-files rule (already removed; governance note only) | 🟢 Low |
| C11 | ADRs | ADR-0002/0003/0004 missing | Phase 1 requires them; known gap, not a contradiction per se | 🔵 Info |
| C12 | `config/settings.py` | `fix/runtime-baseline-cleanup` vs dev-munna differ | Branch has older `_REPO_ROOT` style; dev-munna has clean `_resource_path()` | 🟡 Medium |

---

## Implementation Truth Table

**Legend:** ✅ done+tested | ⚠️ partial | ❌ not implemented | 📋 spec only

| Component | Code | Tests | CI | Notes |
|---|---|---|---|---|
| Capability registry (typed, list/describe/check/select) | ✅ | ✅ | ✅ | `capabilities/registry.py` |
| `resolve()` contract (ADR-0001 Phase 1) | ❌ | ❌ | ❌ | Required for Phase 1 exit test |
| LLM gateway (ADR-0002) | ❌ ADR | ❌ | ❌ | ADR not written |
| `LLMProvider` abstract interface | ✅ | ✅ | ✅ | `llm/base.py`; mock only |
| Real LLM provider (Anthropic/OpenAI/etc.) | ❌ | ❌ | ❌ | Mock only; no keys configured |
| Orchestration state + approval interrupts (ADR-0003) | ❌ ADR | ❌ | ❌ | ADR not written; Q1–Q3 block it |
| Project memory + experiment ledger (ADR-0004) | ❌ ADR | ❌ | ❌ | ADR not written |
| LangGraph graph (START→initialize→END) | ✅ | ✅ | ✅ | `graph/builder.py`; MemorySaver checkpointer |
| AgentState TypedDict (incl. HITL fields reserved) | ✅ | ✅ | ✅ | `graph/state.py` |
| Config (TOML + package-safe resource loading) | ✅ | ✅ | ✅ | `config/settings.py` |
| CLI health check (`python -m cv_agent`) | ✅ | ✅ | ✅ | `__main__.py` |
| CLI subcommands (capabilities/skills/resolve) | ❌ | ❌ | ❌ | Args silently ignored |
| Package build + isolated install | ✅ | ✅ | ✅ | wheel + resources load outside repo |
| GitHub labels/milestones/branch protections | 📋 | — | — | Not verified; blocks Phase 0 exit (Q-D1) |

---

## OPEN QUESTIONS (from OPEN_QUESTIONS.md — do NOT answer without human input)

| ID | Question | Blocks |
|---|---|---|
| Q1 | Unit of a "project": one repo or many? | ADR-0003, ADR-0004 |
| Q2 | Where does agent run / where does training run? | ADR-0003, ADR-0010 |
| Q3 | Human-approval transport: CLI only or persisted across restart? | ADR-0003 |
| Q4 | First target: real project or reference/fixture? | ROADMAP Phase 1 exit test |
| Q5 | Which NVIDIA capabilities are installed and invocable? | ADR-0005, ADR-0007 |
| Q6 | Default cost thresholds for approval gates | `docs/APPROVALS.md` |
| Q7 | Which LLM providers have keys; what is routing policy? | ADR-0002 |

---

## DO NOT (Anti-patterns for this repo)

- ❌ Edit `docs/PROJECT.md` for any reason
- ❌ Commit directly to `dev-munna` or `main`
- ❌ Create implementation code without a GitHub issue
- ❌ Create architectural code without an ADR
- ❌ Silently reconcile contradictions — report and stop
- ❌ Invent answers to Q1–Q7 in OPEN_QUESTIONS.md
- ❌ Create temporary files (`.tmp`, `.phase0-pr-note`, `scratch.md`) in the repo
- ❌ Assume a feature is implemented because it appears in docs/ADR/ROADMAP
- ❌ Use `_REPO_ROOT`-based path assumptions — use `importlib.resources`
- ❌ Import provider SDKs outside `cv_agent/llm/` (provider boundary `[P§20]`)
- ❌ Bulk-read `docs/` at session start — read order: this file → STATUS.md → DECISIONS.md

---

## Branch and PR State

| Branch | Status | Notes |
|---|---|---|
| `main` | 3 commits; bootstrap only | No Phase 0 docs, CI, or tests |
| `dev-munna` | Ahead of main by ~95 commits | All Phase 0 work lives here |
| `fix/runtime-baseline-cleanup` | 1 commit ahead of dev-munna | Modifies: registry, config, pyproject, tests |
| `fix/phase-0-baseline-governance` | Remote only; merged | Source of dev-munna Phase 0 work |

**Diff of `fix/runtime-baseline-cleanup` vs `dev-munna` (6 files):**

| File | Change |
|---|---|
| `cv_agent/capabilities/registry.py` | `describe_item`/`check_item` signature refactor |
| `cv_agent/config/settings.py` | Older `_REPO_ROOT` + resource hybrid approach |
| `pyproject.toml` | Added `force-include` for package resources |
| `tests/test_agent.py` | New: 2 CVAgent behavioral tests |
| `tests/test_capabilities.py` | New: 2 cross-type identity tests |
| `tests/test_config.py` | Accepts `Traversable` in type assertion |

---

## Next Agent Actions (in priority order)

1. Read Q-D1 answer from human → determine Phase 0 status
2. Rewrite `STATUS.md` based on Q-D1/Q-D6 answer
3. Append entry to `JOURNAL.md` for this session
4. Process Q-D2 → commit rolling state to correct branch
5. Process Q-D3 → delete or keep `CV Engineering Agent.md`
6. Process Q-D4 → resolve duplicate dev model docs
7. Begin ADR-0002 (LLM gateway) — first Phase 1 architecture task after Phase 0 closes
