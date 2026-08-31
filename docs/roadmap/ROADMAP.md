# ROADMAP

Phases, not a task list. **Every phase has a measurable exit test.** A phase is not done
because the work feels done; it is done when the exit test passes.

The project follows a **3-tier model** (D-007):

1. **Tier 0 — Documentation & Architecture** (Phases 0–1): all decisions made, all ADRs
   written, all open questions answered, no implementation code.
2. **Tier 1 — Skeleton** (Phase 2): every architecture layer present with demo/mock
   implementations, provably connected end-to-end.
3. **Tier 2+ — Feature Implementation** (Phases 3–9): real features implemented one at a
   time, each fully confirmed before the next begins.

Sequence follows the dependency order in `docs/architecture/OVERVIEW.md` — substrate
before intelligence, intelligence before demo surface `[P§33]`, `[P§34]`.

Each phase maps to one GitHub milestone; the milestone description **is** the exit test.

---

## Phase 0 — Governance ✅ complete

**Goal:** the project can be worked on by any agent or human without re-deriving intent.

**Scope:** frozen canon; `CLAUDE.md` / `AGENTS.md`; `AGENT_HANDOFF.md`; architecture
overview + responsibility table; ADR template; rolling state files; approvals, research,
evaluation, data contracts; GitHub labels, templates, CI.

**Exit test:** a fresh session, given only the repo, reads `AGENT_HANDOFF.md` and
`STATUS.md` and produces a correct account of the project's next three actions and its
hard rules — without being told anything in chat.

**Status:** ✅ exit test passes as of 2026-08-31.

---

## Phase 1 — Architecture Complete ⟨current⟩

**Goal:** every architectural decision is made and written down before any skeleton code
is written. No implementation until this phase is done.

**Scope:**
- All ADRs 0001–0013 written and formally accepted (or rejected with rationale).
- ADR-0001 capability model — ✅ accepted.
- ADR-0002 LLM gateway — pending.
- ADR-0003 orchestration state + approval interrupts — pending (Q1 kept open in ADR).
- ADR-0004 project memory & experiment ledger — pending.
- ADR-0005 tool/MCP boundary — pending (blocked by Q5).
- ADR-0006 retrieval, provenance, freshness — pending.
- ADR-0007 skill registry & discovery — pending (blocked by Q5).
- ADR-0008 reasoning nodes — pending.
- ADR-0009 dataset subsystem — pending.
- ADR-0010 training execution — pending.
- ADR-0011 evaluation & failure analysis — pending.
- ADR-0012 optimization & deployment — pending.
- ADR-0013 monitoring — pending.
- All Q1–Q14 in `OPEN_QUESTIONS.md` answered or formally closed with rationale.
- `Implementation_Status.md` created, populated, and verified against every ADR.
- Existing code audited against every ADR as written (D-011).

**Exit test:**
1. All 13 ADRs (0001–0013) exist in `docs/architecture/adr/` with status `Accepted`.
2. `OPEN_QUESTIONS.md` has no unanswered question in the Blocking or Soon sections.
3. `Implementation_Status.md` has a row for every component in every ADR, with status
   correctly set to `coded` or `not coded`.
4. No ADR references an unanswered open question as a remaining blocker.
5. A fresh session can read the ADRs and implementation status and immediately begin
   writing skeleton code for any layer without needing to ask a design question.

---

## Phase 2 — Skeleton

**Goal:** every architecture layer is present in code with a working demo/mock
implementation. The full system is provably connected end-to-end before any real
feature is implemented. `[P§33]`, `[P§34]`

**What "skeleton" means (D-008):** every layer has a working demo/mock implementation —
not just type stubs. Each layer must be connected to adjacent layers, invokable with demo
data, and testable. Real provider implementations, real NVIDIA tools, real training
execution, and real RAG retrieval are **not** part of the skeleton.

**Scope:** demo/mock implementations of every layer in the architecture:
- Capability registry (existing — will be audited against ADR-0001).
- LLM gateway (mock provider — existing; real providers in Phase 3+).
- Orchestration graph with demo nodes (existing partial; approval persistence in Phase 3+).
- Project memory demo store (in-memory or file-based).
- Knowledge/RAG mock retriever.
- Tool/MCP stub executor.
- Skill stub registry.
- Demo CV reasoning agents (Requirement, Research, etc. — with stub responses).
- Demo stage workflow (DISCOVER → DEFINE → RESEARCH output with mock data).

**Exit test:**
1. Every architecture layer listed in `docs/architecture/OVERVIEW.md` is present in code.
2. The system receives "I have a prison project — escape attempt detection" and produces
   a written PROJECT UNDERSTANDING + CV TASK DECOMPOSITION routed through all layers
   using demo/mock implementations.
3. CI passes: ruff, mypy, pytest (all demo implementations tested).
4. AJ manually reviews the demo output and confirms it is coherent and correctly routed
   through all layers.
5. `Implementation_Status.md` is updated to reflect all skeleton implementations.

---

## Phase 3 — Real Substrate *(renumbered from former Phase 1)*

**Goal:** the real substrate that the intelligence layers plug into. `[P§20]`–`[P§23]`, `[P§32]`

**Scope:** replace demo/mock implementations with real ones, one at a time:
ADR-0002 real LLM gateway (real provider adapters) · ADR-0003 real approval persistence ·
ADR-0004 real project memory & experiment ledger.

**Exit test:**
1. A capability with no satisfying skill resolves to "known but unavailable" — not an error.
2. Two different LLM providers are swappable by config alone; `grep` finds no provider name
   outside the gateway.
3. A workflow run halts at an approval gate, the process is restarted, and the run resumes
   from the checkpoint with the approval still pending.
4. An experiment row can be written and read back with the full `[P§25]` schema enforced.

---

## Phase 4 — Knowledge & Research *(renumbered from former Phase 2)*

**Goal:** the agent stops answering ecosystem questions from pretrained memory.
`[P§16]`–`[P§19]`

**Scope:** ADR-0005 tool/MCP boundary · ADR-0006 retrieval, provenance, freshness ·
research pipeline per `docs/RESEARCH_POLICY.md` · source-class weighting.

**Exit test:** asked "what should we use to detect small objects on a Jetson today", the
agent returns candidates each carrying source, source class, and date; it declines to
rank them without a benchmark; and every stored item lacking provenance is rejected.

---

## Phase 5 — Skills & NVIDIA Integration *(renumbered from former Phase 3)*

**Goal:** external expertise invoked, not duplicated. `[P§15]`, `[P§23]`, `[P§29.9]`

**Scope:** ADR-0007 skill registry & discovery · NVIDIA skill adapters (DeepStream, TAO,
TensorRT, Model Optimizer, CUDA agent) as external-provenance skills.

**Exit test:** a quantization capability resolves to an external NVIDIA skill; the repo
contains **no** reimplementation of that skill's logic; and the agent can enumerate which
external capabilities are installed versus merely known.

---

## Phase 6 — DISCOVER / DEFINE Workflow *(renumbered from former Phase 4)*

**Goal:** the interaction in `[P§5]` and `[P§30]` actually works with real intelligence.

**Scope:** ADR-0008 reasoning nodes · the elicitation workflow · project understanding
written to memory · CV task decomposition.

**Exit test:** given "I have a prison project — escape-attempt detection", the agent asks
targeted operational questions before naming any model, and produces a written PROJECT
UNDERSTANDING + CV TASK DECOMPOSITION persisted to project memory. If it names YOLO
before the questions, the phase fails.

---

## Phase 7 — Data & Baseline *(renumbered from former Phase 5)*

**Goal:** measurable ground truth. `[P§26]`, `[P§29.2]`

**Scope:** ADR-0009 dataset subsystem · manifests, versions, splits, leakage checks ·
baseline establishment workflow.

**Exit test:** a dataset version is created, a temporal- and camera-leakage check runs
and **fails** a deliberately leaky split, and a baseline run is recorded with accuracy,
latency, memory, and power on a named target.

---

## Phase 8 — Train / Evaluate / Diagnose *(renumbered from former Phase 6)*

**Goal:** the experiment loop. `[P§10]`, `[P§12]`, `[P§24]`, `[P§27]`

**Scope:** ADR-0010 training execution · ADR-0011 evaluation & failure analysis.

**Exit test:** a training run requests approval with a cost estimate, runs after approval,
writes a complete ledger row, produces a composite result per `docs/EVALUATION.md`, and
returns a ranked failure-category analysis with a proposed next experiment.

---

## Phase 9 — Optimize / Benchmark / Deploy *(renumbered from former Phase 7)*

**Goal:** hardware-aware delivery. `[P§13]`, `[P§14]`

**Scope:** ADR-0012 optimization & deployment · ONNX → TensorRT → FP16 → INT8 pipeline ·
profiling · DeepStream integration.

**Exit test:** an optimization is applied, re-measured for accuracy **and** system
metrics, compared to baseline under identical conditions, and rejected automatically if
accuracy regressed beyond the stated tolerance.

---

## Phase 10 — Monitor & Iterate *(renumbered from former Phase 8)*

**Goal:** the system outlives deployment. `[P§28]`

**Scope:** ADR-0013 monitoring · drift detection against the validated baseline.

**Exit test:** a simulated production deviation (confidence-distribution shift, FPS drop,
camera degradation) is detected and reported against the validated baseline.

---

## Standing rules

1. If a phase's exit test cannot be written as something runnable, the phase is not
   understood well enough to start.
2. No phase begins until the previous phase's exit test passes.
3. No skeleton code (Phase 2) begins until Phase 1 exit test passes — all 13 ADRs must
   exist and be accepted.
4. No real feature implementation (Phase 3+) begins until the skeleton exit test passes.
