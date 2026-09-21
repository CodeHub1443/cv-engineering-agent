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
D-017) — the experiment-ledger half was explicitly **not** resolved by that decision
(ADR-0004 does not move `EXPERIMENTS.md` into SQLite or change its contract) and
remains open. Does not block ADR-0004/`cv_agent/memory/` implementation.

**Q9.** LinkedIn as a research source `[P§17]` — what is the actual access mechanism, and
what are the terms-of-service constraints? The requirement is clear; the mechanism is
not.

**Q10.** Dataset storage and versioning: DVC, Git LFS, or external object store? `[P§26]`

**Q19.** `docs/APPROVALS.md`'s real approval workflow — specifically, *producing a
cost estimate before asking* ("Before asking, the agent estimates the cost" — the
rule's own first line) — has no implementation anywhere in this codebase (confirmed:
ADR-0009 §8 already names this as open; the `approval_gate` graph node, ADR-0003,
interrupts with `{skill_id, binding_id, task, inputs}` only, no estimate field).
Distinct from **Q6** (which asks what numeric *thresholds* should trigger a gate,
assuming an estimation mechanism exists) — this asks whether any mechanism to
*produce* an estimate exists at all for a given binding, and if not, who's
responsible for building one. Currently moot for `trt-perf-analysis` (`"allowed"`
policy, never gated) but becomes load-bearing the moment ADR-0010's planning
connector — or anything else — ever selects a candidate whose binding is
`approval_required`. `[P§24]`, `[P§29.8]`. *Blocks: any `approval_required` binding
being exercised through a real, non-fake approval flow with an actual estimate
attached, including via ADR-0010's future planning connector.*

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
revision history; experiments remain immutable append-only records. See D-015,
ADR-0004. *Clarified 2026-09-15 (D-019):* the boundary being "the workspace" does not
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
decision constrains *where implied by Git*, not *which technology*). See D-016,
ADR-0004.

~~**Q8. What is the persistence backend for project memory?**~~ files, SQLite, or a
service? — **Answered 2026-09-15 (owner decision):** **SQLite**, for V1. Local and
project-scoped — the database file lives in the project's gitignored
persistent-state area (per Q15/D-016: not Git-tracked). Must survive process
restarts. SQLite stays **behind** the `ProjectMemoryStore` `Protocol` (ADR-0004 §5) —
no `cv_agent` module outside `cv_agent/memory/` may import a SQLite-specific type or
depend on it directly, so a future backend can replace it without touching callers.
No external database/service is required for V1. This resolves Q8 for **project
memory only** — the experiment ledger's own backend question is unaffected and spun
off separately as **Q16** (Soon), since ADR-0004 does not move `EXPERIMENTS.md` into
SQLite or change its contract. See D-017, ADR-0004.

~~**Q17.** Same-session recovery when `plan_execution` returns
`missing_required_inputs`.~~ *Narrowed 2026-09-17 (ADR-0010 §12):* a caller who
already knows a required execution input's value **before** a run starts got a real
channel — `CVAgent.start_workflow(execution_inputs=...)`. — **Answered 2026-09-17
(ADR-0010 §13):** a caller who only learns the missing value **after**
`plan_execution` already produced `planning_result.status ==
"missing_required_inputs"` now has a same-session recovery path — a third interrupt
kind, `provide_execution_inputs`, architecturally consistent with the existing
`clarify` interrupt (ADR-0003), bounded to exactly one prompt per run, gated by an
explicit identity+schema comparison against checkpointed state before any plan may
be produced from it, and bypassing `approval_gate` entirely on any
incomplete/invalid/cancelled/binding-mismatch outcome so a failed recovery can never
be read as "approval not required." See ADR-0010 §13 for the full design. Spun off a
new, separate, unresolved question, **Q20**, for the TRT `path`/`data` XOR contract
this work found `InputField`'s flat schema model cannot express.

~~**Q21.** `cv_agent/graph/workflow.py`'s `_route_after_analysis` decides whether to
route back to the `clarify` interrupt again using
`bool(state.get("clarification_answers"))` — truthiness, not "was clarify already
attempted this run". A human who declines to answer *every* clarification question
resumes with an empty answers value; `clarification_answers` stays falsy, and the
graph re-raises the same `clarify` interrupt indefinitely rather than treating
"asked and declined" as answered — confirmed empirically: reproduced a genuine,
unbounded loop via the real graph. What should the real fix be, and does `clarify`'s
own separately-documented empty-dict-`Command(resume=...)`-not-reliably-delivered
gap need fixing in the same pass?~~ — **Answered 2026-09-19 (ADR-0003 §9, D-026):**
new `AgentState["clarification_attempted"]: bool`, set unconditionally by
`_node_clarify` on every resume — mirrors `execution_input_recovery["attempted"]`'s
existing pattern (ADR-0010 §13). `_route_after_analysis` now routes on this flag,
never on `clarification_answers`' truthiness. The empty-dict-delivery gap **was**
confirmed to need fixing in the same pass — not the same root cause (routing logic
vs. LangGraph transport), but both compound into the same symptom and neither fix
alone was sufficient — resolved by having the CLI resume with `""`, never `{}`, when
every question is declined, the same convention already established for
`provide_execution_inputs`. See ADR-0003 §9 for the full design and empirical
confirmation.

~~**Q20.** *New 2026-09-17 (ADR-0010 §13, discovered while resolving Q17).*
`ExecutionBinding.input_schema`/`InputField.required: bool` (ADR-0009 §11) is
deliberately flat and cannot express `trt-perf-analysis`'s real input contract,
confirmed by direct inspection of `_build_argv()`: exactly one of `path`/`data` is
required (a genuine XOR), not `path` unconditionally. Marking either field
`required=True` would misrepresent the contract (`[P§35]`); marking both
`required=False` would be truthful but could never trigger
`missing_required_inputs` for this binding at all. What should the schema model
gain — a oneOf/XOR field-group construct, a separate validation callback, something
else — and who owns designing it?~~ — **Answered 2026-09-18 (owner decision, asked
directly alongside Q18): a oneOf/XOR field-group construct.** New
`RequiredFieldGroup` (ADR-0009 §12) on `ExecutionBinding.input_field_groups`.
**Corrected 2026-09-18, same day, on independent PR #40 review (D-028):** the
first implementation checked presence only ("at least one member supplied"),
deferring "reject more than one" entirely to the runtime — this under-enforced
the decision's own "EXACTLY ONE alternative" wording. Fixed before merge: a
group is now satisfied only when *exactly* one member is present; two or more
together is a new, distinct `"conflicting_inputs"`/`"conflicting"` outcome,
caught and reported before any plan, approval interrupt, or execution is ever
attempted (ADR-0010 §15). `plan_execution()` and the `provide_execution_inputs`
recovery interrupt are both group-aware (ADR-0010 §14/§15); `ExecutionBinding.
__post_init__` also rejects a field belonging to more than one group (ADR-0009
§13). `trt_perf_analysis.build_binding()` populates its real `path`/`data`/
`model_name` contract. The blocked genuine, unfaked end-to-end recovery test
against the real binding — including the true-XOR "both supplied" rejection
path — is now written and passing (skipped, not faked, on a machine without
the skill installed) — see ADR-0009 §12/§13, ADR-0010 §14/§15, D-027, D-028.

~~**Q18.** When ADR-0010's V1 selection rule finds **more than one** executable
`SkillLink` candidate for a task component, it explicitly produces no plan rather than
silently picking one (`[P§35]`) — surfaced via `AgentState.planning_result.
candidate_skill_ids` (ADR-0010 §11). What should actually happen instead — an explicit
CLI `--skill <id>` override (mirroring `_cmd_execute`'s existing explicit-skill_id
CLI contract), a clarification-style interrupt asking the human to choose, or something
else?~~ — **Answered 2026-09-18 (owner decision, asked directly alongside Q20): a
clarification-style interrupt**; **implemented 2026-09-20 (ADR-0010 §16, D-029, issue
#41):** a fourth interrupt kind, `choose_candidate`, fires when `plan_execution()`
reports `"ambiguous_candidates"`, presents every candidate's skill_id + description,
validates the human's bare-skill_id answer against the exact checkpointed offered set,
persists it (`AgentState.candidate_choice`/`candidate_selection`) and resumes planning
via `plan_execution(..., selected_skill_id=...)`, whose retry independently re-confirms
the choice against the current registry. One shot: an invalid/cancelled/no-longer-valid
choice is terminal and never silently defaults. **Audit-corrected 2026-09-20 (D-030):**
the choice is pinned to the exact binding *shown* (`binding_id` + description snapshotted
at ask time), not merely a `skill_id`; a terminal recovery failure clears
`planning_result.plan`; a malformed offer fails closed; and empty `{}`/`None` resumes are
documented as LangGraph behavior, not classified answers. No CLI `--skill` override was built
(not chosen). Caller-supplied `pending_execution` and `python -m cv_agent execute` are
untouched.
