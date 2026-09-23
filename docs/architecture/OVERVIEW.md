# Architecture overview

Derived from `[P§19]`, `[P§21]`, `[P§22]`, `[P§23]`, `[P§33]`, `[P§34]`.
This file describes **boundaries**. Concrete decisions live in `adr/`.

## The one rule

> Every subsystem must answer: **what responsibility does this own, and why does that
> responsibility not belong somewhere else?** `[P§34]`

A subsystem that cannot answer that cleanly is not yet designed. This question is a
merge gate, not a formality.

## Layers

```
                        CV ENGINEERING AGENT
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
    REASONING               KNOWLEDGE               EXECUTION
        │                       │                       │
   LLM Gateway            RAG / Retrieval          MCP / Tools
        │                  Web Research                 │
  Claude/OpenAI/           Provenance              Skills registry
  Qwen/DeepSeek            Freshness               NVIDIA skills
                                │                  CUDA agent
                         Project Memory            Training
                         Experiment History        Profiling
                         Dataset Knowledge         Deployment

                    ORCHESTRATION  =  LangGraph
        (state, branching, iteration, retries, checkpoints, approval gates)
```

## Responsibility table

Status as of `main` `0e86979` (2026-09-22) — see `docs/roadmap/ROADMAP.md` for the
phase each row belongs to and its full evidence. **Implemented** means real `cv_agent`
code behind an accepted ADR; **Partial** means real code exists but does not yet cover
the row's full stated responsibility; **Planned** means the ADR/module does not exist
yet.

| Layer | Owns | Must NOT own | Talks to | ADR | Status |
|---|---|---|---|---|---|
| **LLM Gateway** | Provider abstraction, model selection by task class & cost, retries/limits, token accounting `[P§20]` | Prompts as business logic, orchestration, knowledge, tool execution | Reasoning nodes only | ADR-0002 | Partial — one real adapter (`AnthropicProvider`, `cv_agent/llm/anthropic_provider.py`), lazily registered, `FakeLLMProvider` still the default; single configured model, no automatic fallback/routing by task class, no call/spend limit enforcement (`OPEN_QUESTIONS.md` Q6/Q19, still open). |
| **Reasoning nodes** | Judgment: problem framing, task decomposition, architecture choice, diagnosis `[P§4]`, `[P§5]` | Provider details, retrieval mechanics, tool implementations, workflow control flow | Gateway, knowledge (read), capability registry | ADR-0008 | Partial — `cv_agent/requirements/` performs deterministic (non-LLM) task decomposition and field elicitation; the LLM Gateway now has a real adapter (above), but no reasoning node calls it for anything beyond ADR-0008's existing mock-only narrative hook. |
| **Orchestration (LangGraph)** | Workflow state, stage transitions, branching, iteration, retries, checkpoints, approval interrupts `[P§21]` | Domain knowledge, skill registry, prompts, retrieval | All layers, as coordinator | ADR-0003 (+ §10, approval-integrity pinning) | Implemented for what exists — real interrupt/resume graph, four interrupt kinds, approval-pause pinning (issue #43). Checkpointing is in-process only (`MemorySaver`), not restart-survivable. |
| **Capability registry** | The typed catalogue of *what the system can do*; capability → skill → tool resolution `[P§23]` | Executing anything itself; storing knowledge | Skills, tools, reasoning | ADR-0001 | Implemented. |
| **Skills** | Specialized procedural knowledge: *how* to accomplish a capability `[P§23]`, `[P§15]` | Being the capability; owning execution transport | Registry, tools | ADR-0007 | Partial — discovery/resolution implemented for all installed skills; only 1 of 84 (`trt-perf-analysis`) has a verified, invocable binding (ADR-0009). |
| **Tools / MCP** | Executable interfaces and their transport boundary `[P§22]` | Deciding *whether* something should be done | Skills, orchestration | ADR-0005 (not yet written) | Planned as a generic MCP boundary. `cv_agent/execution/` (ADR-0009) implements a narrower execution/invocation boundary for skill bindings specifically — real, but not the generic tool/MCP transport this row describes. |
| **Knowledge / RAG** | Retrieval, indexing, provenance, freshness, credibility weighting `[P§16]`, `[P§18]`, `[P§19]` | Reasoning, decision-making, execution | Reasoning (read-only) | ADR-0006 (not yet written) | Planned — no code. |
| **Web research** | Acquisition of current external information + source classification `[P§17]`, `[P§18]` | Long-term storage semantics (that is Knowledge) | Knowledge layer | ADR-0006 (not yet written) | Planned — no code. |
| **Project memory** | Persistent project state: understanding, constraints, decisions `[P§25]`, `[P§33]` | Conversation transcript storage; being a cache for RAG | Orchestration, reasoning | ADR-0004 | Implemented — `cv_agent/memory/` (SQLite-backed, wired into `CVAgent`). |
| **Experiment ledger** | Reproducible experiment metadata and results `[P§25]` | Running experiments | Training, evaluation | ADR-0004 | Planned — `docs/state/EXPERIMENTS.md`'s `[P§25]` schema is a hand-maintained document convention only; no code reads or writes it, and it has zero real rows. |
| **Dataset subsystem** | Manifests, versions, lineage, splits, leakage checks `[P§26]` | Annotation UI, model logic | Training, evaluation | not yet assigned (ADR-0009 is now the skill execution boundary — see ROADMAP Phase 5) | Planned — no code. |
| **Training subsystem** | Experiment *execution* `[P§10]`, `[P§24]` | Deciding what to train; measuring success | Ledger, tools, approvals | not yet assigned (ADR-0010 is now the execution-planning contract — see ROADMAP Phase 6) | Planned — no code. |
| **Evaluation subsystem** | Measurement and failure analysis `[P§12]`, `[P§27]` | Training; choosing the fix | Ledger, reasoning | ADR-0011 (not yet written) | Planned — no code. |
| **Optimization / deployment** | Export, quantization, TensorRT/DeepStream, hardware profiling `[P§13]`, `[P§14]` | Accuracy claims without evaluation | Tools, NVIDIA skills, benchmarks | ADR-0012 (not yet written) | Planned — no code. `trt-perf-analysis` (Skills row) analyzes already-produced TensorRT artifacts; it does not export, quantize, or deploy. |
| **Monitoring** | Post-deployment drift and system-health observation `[P§28]` | Retraining decisions | Knowledge, reasoning | ADR-0013 (not yet written) | Planned — no code. |

**Note on ADR numbering:** this table's ADR column originally recorded a *planned*
mapping decided before any ADR was written. In practice, ADR numbers were assigned in
implementation order, not in this table's original order — `ADR-0009` and `ADR-0010`
now denote the skill execution boundary and the execution-planning contract (both real,
accepted, implemented) rather than the dataset and training subsystems this table
originally reserved them for. The Dataset/Training rows above are corrected to say so
explicitly; `ROADMAP.md` Phases 5–6 document the same fact for anyone tracing an ADR
number back to its row. This is a record of what happened, not a new design decision.

## Vocabulary that must not blur `[P§23]`

- **Capability** — what the system can accomplish (`model.optimize.quantization`).
- **Skill** — specialized instructions for accomplishing it (NVIDIA Model Optimizer PTQ).
- **Tool** — an executable interface (a TensorRT profiling command).
- **Agent** — an autonomous reasoning/execution worker (CUDA optimization agent).

Resolution order: `user task → required capability → appropriate skill → required tools →
execution agent`.

## Design sequence

Build in dependency order. Do not start at the demo-shaped layer.

1. Capability model & registry `[P§23]`
2. LLM gateway `[P§20]`
3. Orchestration state + approval gates `[P§21]`, `[P§24]`
4. Project memory + experiment ledger `[P§25]`, `[P§26]`
5. Tool/MCP boundary `[P§22]`
6. Knowledge: retrieval, provenance, freshness `[P§16]`–`[P§19]`
7. Skills, incl. NVIDIA skill discovery `[P§15]`
8. Stage workflows DISCOVER → DEFINE → … `[P§6]`
9. Training / evaluation / optimization execution `[P§10]`–`[P§14]`

## Known anti-patterns for this repo

- A stage workflow built before the registry and memory exist — produces a demo with no
  substrate `[P§34]`.
- RAG expanding into decision-making `[P§19]`.
- LangGraph nodes holding domain knowledge inline `[P§21]`.
- Provider SDK imports outside the gateway `[P§20]`.
- Reimplementing TAO/TensorRT/DeepStream knowledge inside the agent `[P§15]`.
