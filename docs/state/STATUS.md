# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-24 · **Phase:** 0 → 1 (mostly done) → 3 (partial) → 4 (partial) →
6 (partial, execution planning) · **Health:** green

## Where we are

`main` is at `ca6da85`. PR #52 (`feature/codehub1443/llm-gateway-anthropic`, ADR-0002)
is open, pushed, mergeable — awaiting owner review/merge. **ADR-0005 (Tool/MCP
boundary) is Accepted (owner: Tanvir) and implemented**, on branch
`feature/claude/adr-0005-tool-mcp-boundary` (issue #53): `cv_agent/tools/` —
`ToolSpec`/`ToolRequest`/`ToolResult`/`ToolOutcome`/`ToolEvidence`/
`ToolRequiredFieldGroup`, `ToolInvoker` protocol, `ToolRegistry` (invoker-registration-
generation tracking, `pin()`), `ToolExecutor` (fail-closed, mirrors `SkillExecutor` as
amended by ADR-0009 §14). 71 new tests (`tests/test_tools.py`), suite 646 → 717,
`ruff`/`mypy cv_agent` clean. Zero tools/invokers registered, no MCP SDK selected,
nothing wired into `CVAgent`/`LangGraph`/`SkillExecutor` — the boundary only.

**Implemented:** LLM gateway w/ one real provider (ADR-0002, PR #52 pending merge),
skill discovery/resolution (ADR-0007), requirements analysis + skill_links (ADR-0008),
execution boundary (ADR-0009, one real `ExecutionRuntime`), **Tool/MCP boundary
(ADR-0005, this branch, no real tool yet)**, orchestration + four interrupt kinds
(ADR-0003, ADR-0010 §13/§16), project memory (ADR-0004), planning + true-XOR recovery
+ candidate disambiguation (ADR-0010 §9–§16), approval integrity (ADR-0003 §10, #43),
enforced CI (ruff+mypy+pytest on push/PR to `main`).

**Still NOT implemented:** any real `ToolInvoker`/MCP client, bindings for 83 other
skills, RAG, research, autonomous training, multi-provider routing/fallback, call/
spend-limit enforcement (Q6/Q19), a persistent checkpointer (Q3), real-skill CLI
reachability of `provide_execution_inputs`/`choose_candidate` (#44).

## In flight

| Item | Issue | State |
|---|---|---|
| ADR-0002 LLM gateway (Anthropic) | D-033/D-034 | PR #52 open; awaiting owner review/merge |
| ADR-0005 Tool/MCP boundary | #53 | implemented, branch pushed; PR open, awaiting owner review/merge |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decisions |

## Next 3 actions

1. Owner reviews and merges PR #52 and the ADR-0005 implementation PR (#53).
2. Owner decides whether/when a first real `ToolInvoker` is built (mirrors ADR-0009's
   `trt-perf-analysis` precedent) — not started, no candidate chosen.
3. Owner decisions on #44, Q6/Q19/Q3/Q16/Q10/Q2 — batched, independent.

## Blockers

- Nothing blocked on engineering — every open item above needs owner decision/review.

## Do not start yet

A real `ToolInvoker`/MCP client, RAG, MCP vendor selection, autonomous training, a
second LLM provider or automatic fallback, cost estimation, registering an unverified
binding, a second `ExecutionRuntime`/skill binding, skill ranking/auto-selection,
unrestricted autonomous execution, merging the two graphs, wiring `cv_agent.tools`
into `CVAgent`/`LangGraph`, a second `ProjectMemoryStore` backend — `[P§34]`.
