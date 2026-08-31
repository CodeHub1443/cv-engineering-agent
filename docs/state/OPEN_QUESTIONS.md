# OPEN QUESTIONS

> Questions the canon does not answer that must be answered before certain work can
> proceed. **Answered questions are struck through, not deleted** — the answer and its
> date stay, because "why is it like this" is asked more often than "what is it."
>
> An agent that hits an unanswered question adds it here and stops; it does not invent
> the answer `[P§35]`.

## Blocking — work cannot proceed until answered

~~**Q1. What is the unit of a "project"?**~~ — **Answered 2026-08-31 (D-012):** Deferred to
implementation. ADR-0003 and ADR-0004 will keep this as an open parameter and decide when
memory/ledger scope is implemented. `[P§25]`, `[P§33]`

~~**Q2. Where does the agent run, and where does training run?**~~ — **Answered 2026-08-31
(D-013):** The substrate must support all three (local, remote GPU, cloud) without location
assumptions. The ADR must not hard-code a deployment location. `[P§10]`, `[P§13]`, `[P§24]`

~~**Q3. What is the human-approval transport?**~~ — **Answered 2026-08-31 (D-009):** Approvals
must survive process restart. They are persisted entities (file or DB), not in-process
interrupts. `[P§24]`

~~**Q4. Is the first target a real project or a reference project?**~~ — **Answered 2026-08-31
(D-010):** Real project — prison escape detection. `[P§30]`

**Q5. Which NVIDIA capabilities are actually installed and invocable today?** `[P§15]` —
The design says "discover and invoke, do not duplicate." Discovery mechanism depends on
whether these are MCP servers, CLI tools, Python SDKs, or agent skills.
*Blocks: ADR-0005, ADR-0007.*

## Soon — needed within one or two phases

**Q6.** What are the default cost thresholds for approval gates (GPU-hours, $, dataset
mutation scope)? `docs/APPROVALS.md` has placeholders. `[P§24]`

**Q7.** Which LLM providers are actually available with keys, and what is the routing
policy per task class? `[P§20]`

**Q8.** What is the persistence backend for project memory and the experiment ledger —
files in-repo, SQLite, or a service? Reproducibility `[P§29.5]` favors in-repo; scale
favors otherwise.

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

~~**Q1.** Unit of a "project."~~ — **Answered 2026-08-31:** Deferred to ADR-0003/0004 as an
open parameter. See D-012.

~~**Q2.** Where does agent/training run?~~ — **Answered 2026-08-31:** Location-agnostic; substrate
must support all three. See D-013.

~~**Q3.** Human-approval transport.~~ — **Answered 2026-08-31:** Persisted entities — survive
process restart. See D-009.

~~**Q4.** Real project or reference/fixture?~~ — **Answered 2026-08-31:** Real project — prison
escape detection. See D-010.

