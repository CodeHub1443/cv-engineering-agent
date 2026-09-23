# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-23 · **Phase:** 0 → 1 (mostly done) → 3 (partial) → 4 (partial) →
6 (partial, execution planning) · **Health:** green

## Where we are

`main` is at `ca6da85` (PR #51, CI green). **On branch
`feature/codehub1443/llm-gateway-anthropic`, uncommitted:** ADR-0002 (LLM gateway)
implemented per D-033 — Anthropic is the first real provider
(`cv_agent/llm/anthropic_provider.py`), lazily registered; `FakeLLMProvider` stays
default; single model (`claude-sonnet-4-5`), no fallback; credentials from
`ANTHROPIC_API_KEY` only, never `AgentConfig`/TOML. 24 new tests (mocked client, no
real network/credentials), suite 622 → 646, `ruff`/`mypy` clean. Approval-integrity
+ real skill binding (200 tests) re-run, confirmed unaffected.

**Implemented:** LLM gateway w/ one real provider (ADR-0002), skill
discovery/resolution (ADR-0007), requirements analysis + skill_links (ADR-0008),
execution boundary (ADR-0009, one real `ExecutionRuntime`), orchestration + four
interrupt kinds (ADR-0003, ADR-0010 §13/§16), project memory (ADR-0004), planning +
true-XOR recovery + candidate disambiguation (ADR-0010 §9–§16), real CLI input for
`workflow` (#34), approval integrity (ADR-0003 §10, #43), CLI prompt context (#47),
enforced CI (ruff+mypy+pytest on push/PR to `main`).

**Still NOT implemented:** bindings for 83 other skills, RAG, MCP, research,
autonomous training, multi-provider routing/fallback (deferred), call/spend-limit
enforcement (Q6/Q19, open), a persistent checkpointer (Q3), `pending_execution` in
`workflow`, real-skill CLI reachability of `provide_execution_inputs`/
`choose_candidate` (#44; needs a 2nd binding).

## In flight

| Item | Issue | State |
|---|---|---|
| ADR-0002 LLM gateway (Anthropic) | D-033 | implemented, uncommitted; awaiting commit/push authorization |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decisions |

## Next 3 actions

1. Owner authorization to commit/push `feature/codehub1443/llm-gateway-anthropic`
   and open a PR for ADR-0002.
2. Owner decisions on #44 (opt-in registration; second real binding is blocked).
3. Q19/Q3/Q6 — tracked in `OPEN_QUESTIONS.md`.

## Blockers

- None for ADR-0002 itself — implemented/validated; commit/push needs owner say-so.
- Q3/Q19/Q6 block restart-survivable approval/cost estimates and future limits.

## Do not start yet

RAG, MCP, autonomous training, a second LLM provider or automatic provider/model
fallback, cost estimation, registering an unverified binding, a second
`ExecutionRuntime`/skill binding, skill ranking/auto-selection, unrestricted
autonomous execution, merging the two graphs, a second `ProjectMemoryStore`
backend, wiring `pending_execution` into `workflow` (out of #34) — `[P§34]`.
