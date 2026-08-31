# AGENTS.md — Tool-neutral operating contract

This is the same operational contract as `CLAUDE.md`, for any coding agent (Codex, Cursor,
Aider, Copilot Workspace, an in-repo agent, or a human). `CLAUDE.md` is the authoritative
copy; if the two ever diverge, `CLAUDE.md` wins and this file must be updated in the same PR.

## Canon
`docs/PROJECT.md` (§1–§35) is frozen and authoritative. Cite it as `[P§n]` in every
normative statement. Never edit or summarize it. Gaps go to
`docs/state/OPEN_QUESTIONS.md` or an ADR — never silent invention, never silent omission.

## Read order at session start
`docs/state/AGENT_HANDOFF.md` → `docs/state/STATUS.md` → `docs/state/DECISIONS.md` → the relevant ADRs → the issue.

## Hard rules
1. Problem first — characterize before selecting `[P§29.1]`.
2. Baseline first — measure before optimizing `[P§29.2]`.
3. Evidence over hype — quantitative comparison or no claim `[P§29.3]`.
4. Hardware-aware — accuracy without deployability is incomplete `[P§29.4]`.
5. Reproducibility — full experiment metadata or the result is void `[P§25]`.
6. Boundary test — every module answers "what does this own, and why not elsewhere?" `[P§34]`.
7. No layer leakage between reasoning / orchestration / knowledge / execution `[P§19]`–`[P§22]`.
8. Provider boundary — provider SDKs, provider-specific execution logic, and provider semantics
   stay inside the LLM gateway `[P§20]`; provider/model identifiers are allowed in config and
   execution metadata but must not become provider-specific orchestration logic.
9. Don't reinvent existing NVIDIA/CUDA/vendor expertise — discover and invoke `[P§15]`.
10. Human approval for expensive, destructive, irreversible, or production-affecting actions,
    per `docs/APPROVALS.md` `[P§24]`.
11. Research and cite with dates when knowledge may be stale, weighted per
    `docs/RESEARCH_POLICY.md` `[P§17]`.
12. Prefer deleting a subsystem to bolting one on `[P§34]`.

## Gates
- No implementation code without an issue.
- No architectural code without an ADR.
- Architect sessions produce ADR + interface stubs only.

## Workflow
One issue → one branch (`<type>/<issue-number>-<slug>`) from current `dev-munna` → one PR
back to `dev-munna`. This applies to **all work types**: ADR writing, docs, skeleton layers,
and real feature implementations. Never commit directly to `dev-munna` or `main`. The sole
exception is rolling-state-only commits (limited to `AGENT_HANDOFF.md`, `STATUS.md`,
`JOURNAL.md`, `DECISIONS.md`, `OPEN_QUESTIONS.md`, `EXPERIMENTS.md`) with explicit PM
approval granted per commit. Show changes to AJ before committing or pushing anything.
Acceptance test first; diffs under ~400 lines.


## Rolling state
Rewrite `STATUS.md` and `AGENT_HANDOFF.md`; append to `JOURNAL.md`, `DECISIONS.md`, and
`EXPERIMENTS.md`; strike through answered `OPEN_QUESTIONS.md` entries rather than deleting them.

## What this is NOT `[P§31]`
Not a chatbot, not a YOLO wrapper, not NVIDIA-only, not unlimited autonomy, not a RAG dump,
not a fixed technique list, not a prompt pile.
