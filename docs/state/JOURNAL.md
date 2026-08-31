# JOURNAL

> **Append-only.** Never edit or delete a past entry — if an entry was wrong, write a new
> entry saying so. One entry per session. This is the project's memory of *how* it got
> here; `STATUS.md` holds only *where* it is.

Entry format:

```
## YYYY-MM-DD — <session title> (<branch or PR>)
**Did:**       what changed, concretely
**Why:**       the reason, citing [P§n] or ADR-XXXX
**Broke:**     what went wrong, including dead ends — record these, they are the
               most valuable lines in this file
**Learned:**   what a future session should know
**Left open:** what was deliberately not done
```

---

## 2026-08-30 — Governance scaffold (docs bootstrap)

**Did:** Froze the project definition as `docs/PROJECT.md` (§1–§35, verbatim). Created
`CLAUDE.md`, `AGENTS.md`, architecture overview with the responsibility table, ADR
template, seed ADR-0001 (capability model), roadmap, rolling state files, and the
approvals / research / evaluation / data contracts.

**Why:** `[P§35]` — the canonical document must be turned into operational repository
files without losing or contradicting any of it. The `[P§__]` citation convention exists
so drift from canon is greppable rather than a matter of opinion.

**Broke:** Nothing yet — no code touched.

**Learned:** The document's own §29 principles and §34 boundary test are strong enough to
serve directly as machine-enforceable rules; they were lifted into `CLAUDE.md` rather
than paraphrased.

**Left open:** Every ADR except the seed. GitHub scaffolding. Answers to Q1–Q5 in
`OPEN_QUESTIONS.md`.

---

## 2026-08-30 — Phase 0 baseline reconciliation (#10, fix/phase-0-baseline-governance)

**Did:** Removed duplicate `describe_item` / `check_item` definitions from the capability
registry; standardized the typed item API. Reworked runtime resource loading to use
`importlib.resources` `Traversable` objects without repository-path assumptions. Accepted
ADR-0001 as a single typed-registry storage boundary with an explicit future resolution
contract. Aligned coding-agent contracts with the feature-branch → `dev-munna` workflow
and clarified that provider identifiers may exist in configuration/metadata while
provider-specific logic remains behind the gateway. Added CI for linting, formatting,
type checking, tests, package build, and dependency audit.

**Why:** `[P§20]`, `[P§23]`, `[P§32]`, `[P§34]` — the baseline contained a merge artifact,
resource-loading debt, and governance/ADR contradictions that would otherwise propagate
into Phase 1.

**Broke:** The first review exposed that ADR-0001 described four independent registries
while the implementation already used one typed registry. Treating that as an automatic
implementation mandate would have expanded Phase 0 unnecessarily, so the ADR was
reconciled instead of adding four storage systems.

**Learned:** Keep conceptual identities distinct while retaining a single storage boundary
until actual lifecycle, authorization, or discovery requirements justify separation.

**Left open:** CI has not yet executed; Phase 0 GitHub labels/milestones/protection still
need review. Q1–Q5 remain unanswered. ADR-0002/0003 are not started.

---

## 2026-08-31 — Documentation audit + AGENT_HANDOFF (dev-munna)

**Did:** Full repository and git audit per `docs/agents/DOCUMENTATION_GOVERNANCE.md`.
Found 12 contradictions (C1–C12). CI confirmed running (was incorrectly reported as
pending). Stale branch references corrected. Created `docs/state/AGENT_HANDOFF.md` — a
compact, token-efficient session context file for agent handoffs. Wired it into CLAUDE.md
and AGENTS.md as the mandatory first read at session start. Committed to `dev-munna`
(rolling-state exception, PM-approved).

**Why:** `[P§25]`, `[P§35]` — agent continuity across model switches was failing because
no compact session-context document existed. Each new agent re-derived findings from scratch,
wasting tokens and risking re-introducing contradictions.

**Broke:** Nothing — no source code touched.

**Learned:** STATUS.md accuracy is the Phase 0 exit test. Stale STATUS.md = failed exit
test. Must rewrite it at the close of every session without exception.

**Left open:** Q5–Q14 unanswered. ADR-0002 through ADR-0013 not started.
GitHub labels/milestones/branch protections not verified.

---

## 2026-08-31 — Phase structure redesign + documentation execution (dev-munna)

**Did:** Redesigned the project's phase model from interleaved (ADR+impl per phase) to
three explicit tiers: (1) Architecture Complete — all ADRs + Q1–Q14 answered +
Implementation_Status.md; (2) Skeleton — demo/mock at every layer, E2E provable;
(3) Feature implementation — real features one at a time. Rewrote ROADMAP.md with new
phase definitions and exit tests. Answered Q1–Q4 (project unit deferred, location-agnostic,
approvals must persist, first target = prison escape detection). Merged two duplicate
development model docs into `docs/development/DEVELOPMENT_MODEL.md`. Moved
`CV Engineering Agent.md` to `docs/ORIGINAL_BRIEF.md` with non-canonical header and
deleted root copy. Created `Implementation_Status.md` as implementation ledger. Updated
CLAUDE.md §5 with skeleton definition. Rewrote all rolling state files for this session.

**Why:** D-007 through D-013 — the original interleaved phase model risked premature
implementation before the full architecture picture was settled. The three-tier model
ensures every architectural decision is made before any skeleton code is written, and
every layer of skeleton is complete before real feature implementation begins.

**Broke:** Nothing — CLAUDE.md §5 architecture gate and §6 implementation loop are
unchanged in principle; only the skeleton definition was clarified.

**Learned:** The user's instinct to separate documentation, skeleton, and real
implementation into explicit phases is sound for a system with 13+ ADRs and multiple
unresolved open questions. Implementing before the architecture is complete risks
cascading rewrites.

**Left open:** Q5–Q14 still need answers (will drive ADR-0002 through ADR-0013).
GitHub scaffolding (labels, milestones, branch protections) not yet verified.

