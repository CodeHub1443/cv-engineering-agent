# STATUS

> **Rewritten** every session. Describes **now**, never history — history lives in
> `JOURNAL.md`. Hard cap: 60 lines. If it exceeds that, you are logging, not stating.

**Updated:** 2026-09-24 · **Phase:** 0 → 1 (partial) → 2 (partial) → 3 (partial) →
4 (partial) → 6 (partial, execution planning) · **Health:** green

## Where we are

`main` is at `d730838`. **PR #52 (ADR-0002) and PR #54 (ADR-0005) are both merged.**
**ADR-0006 (Knowledge/Context boundary) is drafted, self-reviewed, and implemented**
on `feature/claude/adr-0006-knowledge-context-boundary` (issue #55), PR pending:
`cv_agent/knowledge/` — `Provenance`/`KnowledgeItem` (fail-closed at construction),
`SourceClass`→`EvidenceWeight` per `docs/RESEARCH_POLICY.md`, `KnowledgeStore`
protocol + in-memory reference impl, deterministic `assemble_context()`. 55 new
tests, suite 717 → 772, `ruff`/`mypy cv_agent` clean. No durable backend, no
acquisition/web-research mechanism, no embeddings — storage/provenance contract only.

**Implemented:** LLM gateway w/ one real provider (ADR-0002), skill discovery/
resolution (ADR-0007), requirements analysis + skill_links (ADR-0008), execution
boundary (ADR-0009, one real `ExecutionRuntime`), Tool/MCP boundary (ADR-0005, no
real tool), **Knowledge/Context boundary (ADR-0006, this branch)**, orchestration +
four interrupt kinds (ADR-0003, ADR-0010 §13/§16), project memory (ADR-0004),
planning + true-XOR recovery + candidate disambiguation (ADR-0010 §9–§16), approval
integrity (ADR-0003 §10, #43), enforced CI (ruff+mypy+pytest on push/PR to `main`).

**Still NOT implemented:** any real `ToolInvoker`/MCP client or research/acquisition
producing `KnowledgeItem`s, a durable `KnowledgeStore` backend, bindings for 83
other skills, autonomous training, multi-provider routing/fallback, call/spend-limit
enforcement (Q6/Q19), a persistent checkpointer (Q3), an experiment-ledger backend
(Q16), real-skill CLI reachability (#44).

## In flight

| Item | Issue | State |
|---|---|---|
| ADR-0006 Knowledge/Context boundary | #55 | implemented, branch pushed; PR pending |
| `workflow` CLI real-skill reachability | #44 | tracked; needs owner decisions |

## Next 3 actions

1. Owner reviews and merges the ADR-0006 PR (#55).
2. Owner decides whether/when a first real `ToolInvoker`/acquisition mechanism is
   built (would populate `KnowledgeStore` for real) — not started.
3. Owner decisions on Q3/Q16/Q23 — each blocks a concrete next increment.

## Blockers

- Nothing blocked on engineering — every open item needs owner decision/review.

## Do not start yet

A real `ToolInvoker`/MCP client, real web-research/acquisition, a durable
`KnowledgeStore` backend, MCP vendor selection, autonomous training, a second LLM
provider/fallback, cost estimation, an unverified binding, a second
`ExecutionRuntime`/skill binding, skill ranking, unrestricted autonomous execution,
merging the two graphs, wiring `cv_agent.tools`/`cv_agent.knowledge` into
`CVAgent`/`LangGraph`, a second `ProjectMemoryStore` backend, embeddings/vector
search — `[P§34]`.
