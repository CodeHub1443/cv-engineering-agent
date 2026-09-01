# OPEN QUESTIONS

> Questions the canon does not answer that must be answered before certain work can
> proceed. **Answered questions are struck through, not deleted** — the answer and its
> date stay, because "why is it like this" is asked more often than "what is it."
>
> An agent that hits an unanswered question adds it here and stops; it does not invent
> the answer `[P§35]`.

## Blocking — work cannot proceed until answered

**Q1. What is the unit of a "project"?** `[P§25]`, `[P§33]` — Does the agent handle one
CV project per repository/workspace, or many projects with isolated memory? This
determines the shape of project memory and whether experiment IDs are globally or
project-scoped. *Blocks: ADR-0003, ADR-0004.*

**Q2. Where does the agent run, and where does training run?** `[P§10]`, `[P§13]`,
`[P§24]` — Local workstation, remote GPU box, cloud, or all three? Does the agent submit
jobs or execute them in-process? *Blocks: ADR-0003 (state/checkpointing), ADR-0010.*

**Q3. What is the human-approval transport?** `[P§24]` — CLI prompt only, or must
approvals survive process restart (a queued request answered hours later)? The latter
makes approvals a persisted entity, not an interrupt. *Blocks: ADR-0003.*

**Q4. Is the first target a real project or a reference project?** `[P§30]` — Building
against the prison/garment examples as a real deliverable versus as a test fixture
changes Phase-1 scope substantially. *Blocks: ROADMAP Phase 1 exit test.*

**Q5. Which NVIDIA capabilities are actually installed and invocable today?** `[P§15]` —
The design says "discover and invoke, do not duplicate." Discovery mechanism depends on
whether these are MCP servers, CLI tools, Python SDKs, or agent skills.
*Blocks: ADR-0005, ADR-0007.*

## Soon — needed within one or two phases

~~**Q7.** Which LLM providers are actually available with keys, and what is the routing
policy per task class? `[P§20]`~~ — **Answered 2026-09-01:** initial gateway provider
classes are Anthropic, OpenAI, and Local/Ollama; routing is configuration-driven;
transient rate-limit/server/timeout failures may fall back sequentially; authentication,
invalid-request, context-length, and unsupported-model failures fail fast. See D-016 /
ADR-0002.

~~**Q8.** What is the persistence backend for project memory and the experiment ledger —
files in-repo, SQLite, or a service? Reproducibility `[P§29.5]` favors in-repo; scale
favors otherwise.~~ — **Answered 2026-09-01:** dual-layer persistence: Git-tracked
structured project memory plus local SQLite at `.cv_agent/state/experiments.sqlite`
for high-volume experiment rows. See D-017 / ADR-0004.

**Q6.** What are the default cost thresholds for approval gates (GPU-hours, $, dataset
mutation scope)? `docs/APPROVALS.md` has placeholders. `[P§24]`

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
