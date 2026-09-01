# CV Engineering Agent

An AI system that **performs** computer-vision engineering — not one that merely knows
computer vision `[P§35]`.

It takes a CV problem from **problem definition → research → architecture → dataset →
training → evaluation → optimization → deployment → benchmarking → monitoring**, keeping
humans in control of consequential decisions `[P§3]`.

It is **not** a chatbot, a YOLO wrapper, an NVIDIA-only agent, an unlimited-autonomy
system, a RAG dump, a fixed technique list, or a pile of prompts `[P§31]`.

## Start here

| If you are… | Read |
|---|---|
| a coding agent starting a session | `CLAUDE.md`, then `docs/state/STATUS.md` |
| a non-Claude agent | `AGENTS.md` |
| a human joining the project | this file → `docs/PROJECT.md` → `docs/architecture/OVERVIEW.md` |
| about to make a design choice | `docs/architecture/adr/` + `ADR-0000-template.md` |
| about to run anything expensive | `docs/APPROVALS.md` |
| about to claim an improvement | `docs/EVALUATION.md` |
| about to open a branch or PR | `docs/development/GITHUB_FLOW_V1.md` |
| looking for a technical elaboration of a spec area | `spec/` (index below) |

## Document map

```
CLAUDE.md                    operating rules for coding agents (short, imperative)
AGENTS.md                    the same contract, tool-neutral
docs/
  PROJECT.md                 FROZEN canon, §1–§35 — cited everywhere as [P§n]
  GLOSSARY.md                capability/skill/tool/agent, stages, metrics
  APPROVALS.md               what needs human authorization, and how to ask [P§24]
  RESEARCH_POLICY.md         source weighting, provenance, freshness [P§17][P§18]
  EVALUATION.md              measurement contract, baseline discipline [P§12][P§27]
  DATA.md                    dataset versioning, splits, leakage [P§26]
  architecture/
    OVERVIEW.md              layers + responsibility table [P§34]
    adr/                     one decision per file, numbered
  roadmap/ROADMAP.md         phases with measurable exit tests
  state/
    STATUS.md                where we are NOW (rewritten, ≤60 lines)
    JOURNAL.md               how we got here (append-only)
    DECISIONS.md             what is settled (append-only)
    OPEN_QUESTIONS.md        what is unresolved (strike through, never delete)
    EXPERIMENTS.md           reproducible experiment ledger [P§25]
  development/
    GITHUB_FLOW_V1.md        full git workflow: branching, PR, CI/CD, review/merge
    GITHUB_DEVELOPMENT_MODEL.md  executive summary of the same workflow
  archive/
    PROJECT_SOURCE_DRAFT.md  historical, non-authoritative, not a session-start read
spec/                         technical elaborations of specific canon areas — NOT
                               independent authority; each cites the docs/PROJECT.md
                               or docs/architecture/OVERVIEW.md section it elaborates
  03-agent-runtime.md          elaborates the orchestration layer (pre-ADR-0003)
  04-knowledge-and-research.md elaborates the knowledge/RAG layer (pre-ADR-0006)
  05-cv-engineering-lifecycle.md  elaborates docs/PROJECT.md §6 per-stage
  06-tooling-and-mcp.md        elaborates the tools/MCP boundary (pre-ADR-0005)
  08-training-and-optimization.md elaborates training/optimization (pre-ADR-0010/12)
  10-capability-registry.md    the ONLY spec file with real code behind it — governs
                                spec/capability_registry.json, read by
                                cv_agent/capabilities/registry.py
  11-platform-detection-and-optimization.md  elaborates platform detection
```

None of the `spec/*.md` files (except `10-capability-registry.md`, which has real
code behind it) describe anything implemented today — each states its implementation
status at the top. If a `spec/*.md` file conflicts with `docs/PROJECT.md` or an
accepted ADR, the canon/ADR wins.

## The three conventions that hold this together

1. **The canon is frozen.** `docs/PROJECT.md` is never edited or summarized. Every
   normative statement elsewhere cites it as `[P§12]`, so drift from intent is
   `grep`-able rather than a matter of opinion.
2. **State and history are separate files.** `STATUS.md` is rewritten and stays short;
   `JOURNAL.md` only ever grows. Conflating them is why project memory usually rots.
3. **Two gates.** No implementation code without an issue; no architectural code without
   an ADR that answers *what does this own, and why not elsewhere* `[P§34]`.

## Workflow

One issue → one branch `feature/<owner>/<work>` → one PR targeting `main` directly,
reviewed and merged by the project owner. Never commit to `main`. No intermediate
development trunk. Acceptance test written first and shown failing. Rolling state
updated before every commit. Full process: `docs/development/GITHUB_FLOW_V1.md`.

## Status

Phase 0 — governance. The code baseline `[P§32]` exists; the intelligence layers do not.
See `docs/state/STATUS.md`.
