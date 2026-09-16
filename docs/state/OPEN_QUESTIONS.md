# OPEN QUESTIONS

> Questions the canon does not answer that must be answered before certain work can
> proceed. **Answered questions are struck through, not deleted** — the answer and its
> date stay, because "why is it like this" is asked more often than "what is it."
>
> An agent that hits an unanswered question adds it here and stops; it does not invent
> the answer `[P§35]`.

## Blocking — work cannot proceed until answered

**Q2. Where does the agent run, and where does training run?** `[P§10]`, `[P§13]`,
`[P§24]` — Local workstation, remote GPU box, cloud, or all three? Does the agent submit
jobs or execute them in-process? *Blocks: ADR-0010.* (No longer blocks ADR-0003 — nothing
in that ADR executes training or submits remote jobs; see ADR-0003 §1.)

**Q3. What is the human-approval transport?** `[P§24]` — CLI prompt only, or must
approvals survive process restart (a queued request answered hours later)? The latter
makes approvals a persisted entity, not an interrupt. **Partially resolved 2026-09-15
(ADR-0003 §1):** the transport is a LangGraph interrupt; whether it survives a process
restart is a property of the checkpointer (swappable), not the graph/node structure.
ADR-0003 ships with `MemorySaver` (confirmed: does not survive process restart) and
defers the durable/queued-approval decision. *Still blocks: a durable/async approval
transport (persistent checkpointer swap-in, ADR-0003 §8 revisit trigger).*

**Q4. Is the first target a real project or a reference project?** `[P§30]` — Building
against the prison/garment examples as a real deliverable versus as a test fixture
changes Phase-1 scope substantially. *Blocks: ROADMAP Phase 1 exit test.*

**Q5. Which NVIDIA capabilities are actually installed and invocable today?** `[P§15]` —
The design says "discover and invoke, do not duplicate." Discovery mechanism depends on
whether these are MCP servers, CLI tools, Python SDKs, or agent skills.
*Blocks: ADR-0005, ADR-0007.*

## Soon — needed within one or two phases

**Q6.** What are the default cost thresholds for approval gates (GPU-hours, $, dataset
mutation scope)? `docs/APPROVALS.md` has placeholders. `[P§24]`

**Q7.** Which LLM providers are actually available with keys, and what is the routing
policy per task class? `[P§20]`

**Q16.** What is the persistence backend for the experiment ledger (`docs/state/
EXPERIMENTS.md`)? Files, SQLite, or a service? — split off from the former Q8
2026-09-15 when Q8's project-memory half was resolved (SQLite; see Q8, Answered,
D-016) — the experiment-ledger half was explicitly **not** resolved by that decision
(ADR-0004 does not move `EXPERIMENTS.md` into SQLite or change its contract) and
remains open. Does not block ADR-0004/`cv_agent/memory/` implementation.

**Q9.** LinkedIn as a research source `[P§17]` — what is the actual access mechanism, and
what are the terms-of-service constraints? The requirement is clear; the mechanism is
not.

**Q10.** Dataset storage and versioning: DVC, Git LFS, or external object store? `[P§26]`

## Deferrable

**Q11.** Multi-camera / multi-stream orchestration model. `[P§9]`
**Q12.** Monitoring backend and alerting surface. `[P§28]`
**Q13.** Does the agent ever fine-tune or serve its own models, or only orchestrate? 
**Q14.** Multi-user / team usage, or single-operator? Affects memory and approvals.

## Answered

~~**Q0.** Should the canonical document be edited into the repository docs, or kept
verbatim?~~ — **Answered 2026-08-30:** kept verbatim and frozen as `docs/PROJECT.md`;
derived files cite it as `[P§n]`. See D-001.

~~**Q1. What is the unit of a "project"?**~~ `[P§25]`, `[P§33]` — Does the agent handle
one CV project per repository/workspace, or many projects with isolated memory? —
**Answered 2026-09-15 (owner decision):** **one CV project per repository/workspace**
in V1. The workspace/repository IS the project boundary — no `project_id`
abstraction, no project selection, no multi-tenant memory. Session identity
(`AgentState.session_id`) stays distinct from project identity; every session belongs
to the one implicit project (the workspace). No broader multi-repository workspace
abstraction in V1. Project Understanding is persistent current state with recoverable
revision history; experiments remain immutable append-only records. See D-014,
ADR-0004. *Clarified 2026-09-15 (D-018):* the boundary being "the workspace" does not
by itself guarantee any given process execution resolves it correctly — the
**calling application**, not `ProjectMemoryStore`, is responsible for resolving
`workspace_root` explicitly; `Path.cwd()` is a convenience default only.

~~**Q15. Is Project Understanding storage Git-tracked, and is it sensitive data?**~~
`[P§24]`, `[P§25]` — An ADR-0004 audit identified this as a missing decision: the ADR
named a storage backend as open (Q8) but never addressed whether persisted Project
Understanding is committed to the repository or kept local, nor whether it is
sensitive data under `docs/APPROVALS.md` — a real gap given `docs/PROJECT.md` §5/§30's
own worked examples (prison security, factory floors) can surface operationally
sensitive facility detail. — **Answered 2026-09-15 (owner decision):** Project
Understanding is classified as **potentially sensitive project data**, governed by
`docs/APPROVALS.md`'s data/privacy rule. It must be **durable across process
restarts** but must **NOT** be automatically stored in Git-tracked repository files —
V1 persistent storage is **local/project-scoped and gitignored by default**.
Durability does not imply Git tracking. This does not change `EXPERIMENTS.md`'s
contract (that ledger's own tracking status is unaffected). External-LLM transmission
remains governed by the existing approval/privacy rules regardless of persistence —
storing data locally grants no new permission to send it externally. *Distinct from
and does not resolve* **Q8**, which stays open (files vs. SQLite vs. a service — this
decision constrains *where implied by Git*, not *which technology*). See D-015,
ADR-0004.

~~**Q8. What is the persistence backend for project memory?**~~ files, SQLite, or a
service? — **Answered 2026-09-15 (owner decision):** **SQLite**, for V1. Local and
project-scoped — the database file lives in the project's gitignored
persistent-state area (per Q15/D-015: not Git-tracked). Must survive process
restarts. SQLite stays **behind** the `ProjectMemoryStore` `Protocol` (ADR-0004 §5) —
no `cv_agent` module outside `cv_agent/memory/` may import a SQLite-specific type or
depend on it directly, so a future backend can replace it without touching callers.
No external database/service is required for V1. This resolves Q8 for **project
memory only** — the experiment ledger's own backend question is unaffected and spun
off separately as **Q16** (Soon), since ADR-0004 does not move `EXPERIMENTS.md` into
SQLite or change its contract. See D-016, ADR-0004.
