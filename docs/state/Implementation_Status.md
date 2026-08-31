# IMPLEMENTATION STATUS

> **Rewritten each session** as code changes. This is the ledger of what is **actually
> coded** vs what is specified in ADRs or the roadmap. It is the ground truth for
> skeleton progress and feature readiness. Do not assume a feature is implemented because
> it appears in an ADR.
>
> Legend: ✅ coded + tested + CI | ⚠️ partial | ❌ not coded | 📋 spec only | 🔍 needs audit

**Last updated:** 2026-08-31 · **Phase:** 1 (Architecture Complete) in progress

---

## Layer 0 — Configuration & Package

| Component | ADR | Coded | Tested | CI | Status | Notes |
|---|---|---|---|---|---|---|
| Config loading (TOML + package resources) | — | ✅ | ✅ | ✅ | ✅ | `config/settings.py`; `importlib.resources` |
| Package resource embedding (config/spec) | — | ✅ | ✅ | ✅ | ✅ | `pyproject.toml` force-include |
| CLI health check (`python -m cv_agent`) | — | ✅ | ✅ | ✅ | ✅ | `__main__.py` |
| CLI subcommands (capabilities/skills/resolve) | — | ❌ | ❌ | ❌ | ❌ | Args silently ignored; Phase 2 skeleton |

---

## Layer 1 — Capability Registry (ADR-0001)

| Component | ADR | Coded | Tested | CI | Status | Notes |
|---|---|---|---|---|---|---|
| Typed registry storage (single boundary) | ADR-0001 | ✅ | ✅ | ✅ | ✅ | `capabilities/registry.py` |
| `list()` — by type | ADR-0001 | ✅ | ✅ | ✅ | ✅ | |
| `describe()` — by id + type | ADR-0001 | ✅ | ✅ | ✅ | ✅ | |
| `check()` — availability metadata | ADR-0001 | ✅ | ✅ | ✅ | ✅ | |
| `select()` — task-type match | ADR-0001 | ✅ | ✅ | ✅ | ✅ | |
| `resolve()` — task → skill → tool chain | ADR-0001 | ❌ | ❌ | ❌ | ❌ | Phase 1 ADR requirement; not coded |
| Cross-type typed identity (same id, different type) | ADR-0001 | ✅ | ✅ | ✅ | ✅ | |
| `capability_registry.json` spec | ADR-0001 | ✅ | ✅ | ✅ | ✅ | `spec/capability_registry.json` |

---

## Layer 2 — LLM Gateway (ADR-0002)

| Component | ADR | Coded | Tested | CI | Status | Notes |
|---|---|---|---|---|---|---|
| `LLMProvider` abstract interface | ADR-0002 (pending) | ✅ | ✅ | ✅ | ⚠️ | `llm/base.py`; needs audit vs ADR-0002 |
| `LLMRequest` / `LLMResponse` dataclasses | ADR-0002 (pending) | ✅ | ✅ | ✅ | ⚠️ | Needs audit |
| Mock provider | ADR-0002 (pending) | ✅ | ✅ | ✅ | ⚠️ | `llm/mock.py`; needs audit |
| Provider registry (`get_provider()`) | ADR-0002 (pending) | ✅ | ✅ | ✅ | ⚠️ | `llm/registry.py`; needs audit |
| Anthropic provider adapter | ADR-0002 (pending) | ❌ | ❌ | ❌ | ❌ | Phase 3 real implementation |
| OpenAI provider adapter | ADR-0002 (pending) | ❌ | ❌ | ❌ | ❌ | Phase 3 real implementation |
| Model routing / fallback policy | ADR-0002 (pending) | ❌ | ❌ | ❌ | ❌ | Phase 3 |
| Streaming support | ADR-0002 (pending) | ❌ | ❌ | ❌ | ❌ | Phase 3 |

---

## Layer 3 — Orchestration State & Approval Interrupts (ADR-0003)

| Component | ADR | Coded | Tested | CI | Status | Notes |
|---|---|---|---|---|---|---|
| `AgentState` TypedDict | ADR-0003 (pending) | ✅ | ✅ | ✅ | ⚠️ | `graph/state.py`; needs audit vs ADR-0003 |
| LangGraph graph (START→initialize→END) | ADR-0003 (pending) | ✅ | ✅ | ✅ | ⚠️ | `graph/builder.py`; minimal; needs audit |
| MemorySaver checkpointer | ADR-0003 (pending) | ✅ | ✅ | ✅ | ⚠️ | In-memory; Phase 3 = persistent |
| HITL fields reserved in AgentState | ADR-0003 (pending) | ✅ | ✅ | ✅ | ⚠️ | Reserved; not wired |
| Approval gate node | ADR-0003 (pending) | ❌ | ❌ | ❌ | ❌ | Phase 3 real implementation |
| Persisted approval store | ADR-0003 (pending) | ❌ | ❌ | ❌ | ❌ | Phase 3 (D-009: must survive restart) |
| Approval resume after restart | ADR-0003 (pending) | ❌ | ❌ | ❌ | ❌ | Phase 3 |

---

## Layer 4 — Project Memory & Experiment Ledger (ADR-0004)

| Component | ADR | Coded | Tested | CI | Status | Notes |
|---|---|---|---|---|---|---|
| Project memory interface | ADR-0004 (pending) | ❌ | ❌ | ❌ | ❌ | Not started |
| Experiment ledger (`[P§25]` schema) | ADR-0004 (pending) | ❌ | ❌ | ❌ | ❌ | Not started |
| `EXPERIMENTS.md` rolling state file | — | ✅ | — | — | ✅ | Empty (correct; no runs yet) |

---

## Layer 5 — Tool / MCP Boundary (ADR-0005)

| Component | ADR | Coded | Tested | CI | Status | Notes |
|---|---|---|---|---|---|---|
| Tool interface definition | ADR-0005 (pending, Q5 blocks) | ❌ | ❌ | ❌ | 📋 | Blocked by Q5 (NVIDIA installed?) |
| MCP server adapter | ADR-0005 (pending) | ❌ | ❌ | ❌ | 📋 | |

---

## Layer 6 — Knowledge & RAG (ADR-0006)

| Component | ADR | Coded | Tested | CI | Status | Notes |
|---|---|---|---|---|---|---|
| Retrieval interface | ADR-0006 (pending) | ❌ | ❌ | ❌ | 📋 | Not started |
| Provenance enforcement | ADR-0006 (pending) | ❌ | ❌ | ❌ | 📋 | |
| Freshness horizon logic | ADR-0006 (pending) | ❌ | ❌ | ❌ | 📋 | |

---

## Layer 7 — Skill Registry (ADR-0007)

| Component | ADR | Coded | Tested | CI | Status | Notes |
|---|---|---|---|---|---|---|
| Skill discovery interface | ADR-0007 (pending, Q5 blocks) | ❌ | ❌ | ❌ | 📋 | Blocked by Q5 |
| NVIDIA skill adapters (DeepStream/TAO/TRT) | ADR-0007 (pending) | ❌ | ❌ | ❌ | 📋 | Phase 5 |

---

## Layer 8 — CV Reasoning Agents (ADR-0008)

| Component | ADR | Coded | Tested | CI | Status | Notes |
|---|---|---|---|---|---|---|
| Reasoning node interface | ADR-0008 (pending) | ❌ | ❌ | ❌ | 📋 | Not started |
| Requirement agent | ADR-0008 (pending) | ❌ | ❌ | ❌ | 📋 | |
| Research agent | ADR-0008 (pending) | ❌ | ❌ | ❌ | 📋 | |
| Architecture agent | ADR-0008 (pending) | ❌ | ❌ | ❌ | 📋 | |
| Dataset agent | ADR-0008 (pending) | ❌ | ❌ | ❌ | 📋 | |
| Model / Training / Eval agents | ADR-0008 (pending) | ❌ | ❌ | ❌ | 📋 | |
| Optimization / Deployment agents | ADR-0008 (pending) | ❌ | ❌ | ❌ | 📋 | |
| Monitoring agent | ADR-0008 (pending) | ❌ | ❌ | ❌ | 📋 | |

---

## Layer 9 — Dataset Subsystem (ADR-0009)

| Component | ADR | Coded | Tested | CI | Status | Notes |
|---|---|---|---|---|---|---|
| Dataset manifest / versioning | ADR-0009 (pending) | ❌ | ❌ | ❌ | 📋 | Not started |
| Leakage check | ADR-0009 (pending) | ❌ | ❌ | ❌ | 📋 | |

---

## Layer 10 — Training Execution (ADR-0010)

| Component | ADR | Coded | Tested | CI | Status | Notes |
|---|---|---|---|---|---|---|
| Training launcher interface | ADR-0010 (pending) | ❌ | ❌ | ❌ | 📋 | Not started |
| Approval gate integration | ADR-0010 (pending) | ❌ | ❌ | ❌ | 📋 | |

---

## Layer 11 — Evaluation & Failure Analysis (ADR-0011)

| Component | ADR | Coded | Tested | CI | Status | Notes |
|---|---|---|---|---|---|---|
| Composite evaluation per `docs/EVALUATION.md` | ADR-0011 (pending) | ❌ | ❌ | ❌ | 📋 | Not started |
| Failure category ranking | ADR-0011 (pending) | ❌ | ❌ | ❌ | 📋 | |

---

## Layer 12 — Optimization & Deployment (ADR-0012)

| Component | ADR | Coded | Tested | CI | Status | Notes |
|---|---|---|---|---|---|---|
| ONNX → TensorRT pipeline | ADR-0012 (pending) | ❌ | ❌ | ❌ | 📋 | Not started |
| Accuracy regression guard | ADR-0012 (pending) | ❌ | ❌ | ❌ | 📋 | |

---

## Layer 13 — Monitoring (ADR-0013)

| Component | ADR | Coded | Tested | CI | Status | Notes |
|---|---|---|---|---|---|---|
| Drift detection vs validated baseline | ADR-0013 (pending) | ❌ | ❌ | ❌ | 📋 | Not started |

---

## Summary

| Phase | Layer | ADR | Skeleton (Phase 2) | Real (Phase 3+) |
|---|---|---|---|---|
| 0 — Governance | Config, CLI | — | ✅ done | ✅ done |
| 1 — Architecture | All ADRs | 1/13 accepted | — | — |
| 2 — Skeleton | All layers | — | 🔍 to be done after Phase 1 | — |
| 3 — Real substrate | Gateway, orchestration, memory | ADR-0002/0003/0004 | — | ❌ Phase 3+ |
| 4+ — Features | Knowledge through monitoring | ADR-0005–0013 | — | ❌ Phase 4+ |
