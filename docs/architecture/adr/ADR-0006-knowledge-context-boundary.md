# ADR-0006: Knowledge / Context boundary — a provenance-gated context store

- **Status:** Accepted (self-reviewed and implemented under owner's continuous-execution
  authorization, 2026-09-24 — see §9. Subject to the normal PR review gate before landing
  on `main`.)
- **Date:** 2026-09-24
- **Layer:** knowledge
- **Canon:** `[P§16]`, `[P§17]`, `[P§18]`, `[P§19]`, `[P§29.3]`, `[P§34]`
- **Supersedes / Superseded by:** —
- **Issue:** #55

## 1. Context

`docs/architecture/OVERVIEW.md`'s responsibility table lists **Knowledge / RAG** —
"Retrieval, indexing, provenance, freshness, credibility weighting `[P§16]`, `[P§18]`,
`[P§19]`" — as `ADR-0006 (not yet written)`, `Status: Planned — no code`. Its own
"Design sequence" fixes the build order as *1 capability → 2 LLM gateway →
3 orchestration → 4 project memory+experiment ledger → 5 tool/MCP boundary →
6 knowledge: retrieval, provenance, freshness → 7 skills → 8 stage workflows →
9 training*. Step 5 (ADR-0005, tool/MCP boundary) is now accepted and merged
(D-036). This ADR is step 6.

`docs/roadmap/ROADMAP.md` Phase 2 ("Knowledge & research") names this ADR directly and
gives it a concrete exit test (§7 below quotes the relevant half). `docs/RESEARCH_POLICY.md`
(derived from `[P§16]`–`[P§19]`, `[P§29.3]`, `[P§29.7]`) already fully specifies the
*contract* this ADR must implement: two mechanisms kept separate (persistent knowledge
vs. live research), a source-class/evidence-weight table (8 classes), a 7-step research
pipeline (Find → Relevance → Credibility → Extract → Provenance → Freshness → Make
available), and one hard rule stated twice in that document: *"A stored item missing
provenance or date is deleted, not kept."* This ADR does not invent any of that policy —
it gives it a typed, enforced shape.

**Why not step 4's remaining half instead (experiment ledger)?** `docs/state/
OPEN_QUESTIONS.md` Q16 ("What is the persistence backend for the experiment ledger?
Files, SQLite, or a service?") is still open. Building the ledger's persistence layer
would require picking one of those three — exactly the silent invention `[P§35]`
forbids. This ADR's own store (§3) sidesteps an equivalent trap for knowledge/context
by deliberately not deciding a persistence backend either (see §3, §8).

**Why not skill/CLI expansion instead (Phase 3/4 gaps)?** Both remaining gaps there
— a second real `ExecutionRuntime` binding, and opt-in binding registration from
`workflow` — are on `docs/state/STATUS.md`'s "Do not start yet" list and are named in
`OPEN_QUESTIONS.md` Q23 as "an execution-surface design decision for the owner" /
"blocked on that decision, not on engineering." Neither is available to implement
without an owner decision this session is not authorized to make.

Nothing in `cv_agent/graph/`, `cv_agent/requirements/`, `cv_agent/execution/`, or
`cv_agent/tools/` imports anything resembling a knowledge/context module today —
confirmed by inspection; no existing call site is touched by this ADR.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** the typed contract for a *stored knowledge item* (claim + provenance +
  source class + freshness horizon), fail-closed provenance validation at construction
  time, deterministic (non-ML) storage/retrieval by explicit tag/source-class/staleness
  filters, and bounded, deterministic context assembly for a reasoning node to consume.
- **This does NOT own:**
  - *acquiring* information — web fetching, live research execution, LinkedIn or any
    other external source access (`docs/RESEARCH_POLICY.md`'s "Find" step) — that is a
    future **Web research** layer (`OVERVIEW.md` row, ADR-0006-or-later scope per that
    table's own note that Web research shares this ADR slot only provisionally); this
    ADR accepts already-extracted items as input, it does not go get them;
  - *reasoning about* a claim, ranking claims by ML relevance, or deciding what a
    reasoning node does with assembled context — `[P§19]`: "RAG provides knowledge; the
    LLM provides reasoning; they do not merge." Ranking here is limited to an explicit,
    stable, fully-deterministic tie-break (§3) — never a learned or fuzzy relevance
    score;
  - *durable persistence* — this ADR ships an in-memory reference `KnowledgeStore` only
    (§3); a durable backend is an explicit future decision (§8), not invented here,
    mirroring the exact gap Q16 already names for the experiment ledger;
  - *skills or tools* — `cv_agent/skills/` (ADR-0007) and `cv_agent/tools/` (ADR-0005)
    are untouched; this ADR does not become a third way to invoke anything, and a
    `KnowledgeStore` has no path to execution or approval;
  - *credibility scoring as a tunable weight per item* — `SourceClass → EvidenceWeight`
    is a fixed, deterministic mapping taken directly from `docs/RESEARCH_POLICY.md`'s
    table (§3), not a per-item override an item can claim for itself.
- **Why this responsibility does not belong to an existing component:** `cv_agent/
  memory/` (ADR-0004) owns *project* state (sessions, requirements revisions) — a
  different lifecycle and a different trust model (write-your-own-project-facts vs.
  hold-externally-sourced-claims-with-provenance). `cv_agent/requirements/` and
  `cv_agent/graph/` are reasoning/orchestration, forbidden from holding domain
  knowledge inline (`OVERVIEW.md`'s anti-patterns list). No existing package can own
  "is this claim's provenance well-formed enough to keep" without either duplicating
  that check per call site or smuggling knowledge into a layer `[P§19]` forbids it in.

## 3. Decision

Add a new package, `cv_agent/knowledge/`, importing nothing from `cv_agent.execution`,
`cv_agent.skills`, `cv_agent.graph`, `cv_agent.tools`, or `cv_agent.llm` (enforced by a
structural test mirroring ADR-0005 §7's pattern) — read-only from the reasoning layer's
perspective, one-directional dependency.

**`Provenance` is mandatory, not optional**, on every stored item — there is no code
path to construct a `KnowledgeItem` with a missing or malformed `Provenance` (validated
in `__post_init__`, raising `ValueError`, the same fail-closed pattern `ExecutionBinding`
and `ToolSpec` already use). This directly implements `docs/RESEARCH_POLICY.md`'s "a
stored item missing provenance or date is deleted, not kept" — enforced even earlier,
at construction, so a malformed item can never reach a store's `put()` at all.

**`SourceClass → EvidenceWeight` is a fixed module-level mapping**, taken verbatim from
`docs/RESEARCH_POLICY.md`'s table (8 classes: `peer_reviewed_research`,
`official_documentation`, `official_repository_or_release_notes`,
`reputable_benchmark`, `engineering_blog`, `professional_post`,
`community_discussion`, `model_zoo_or_leaderboard`; weights: `high`, `medium`,
`low_medium`, `signal_not_evidence`) — a pure function of `source_class`, not a field a
caller can set independently, so "professional post" (LinkedIn etc.) can never silently
carry `high` weight.

**Freshness is caller-supplied, per item, never a default this layer invents.**
`staleness_horizon_days: int` is a required field on every item — `docs/
RESEARCH_POLICY.md` gives only qualitative buckets ("framework versions: weeks;
architecture families: months; fundamentals: years"), not numbers, and picking exact
day-counts as a system default would be exactly the kind of invented threshold `[P§35]`
forbids for Q6/Q19's cost thresholds. The store enforces the caller's stated horizon
(`is_stale(as_of)`); it does not decide what the horizon should be.

**Retrieval is deterministic, never semantic/embedded.** `KnowledgeStore.query()`
filters by exact `topic_tags` membership, `source_class`, and a `staleness` cutoff —
no embeddings, no vector similarity, no ranking model. `assemble_context()`'s
tie-break order (when trimming to `max_items`) is stated as an explicit, total,
reproducible order: `(evidence_weight desc, date_accessed desc, item_id asc)` — the
same claim set assembled twice, from the same store state, produces the same bundle.

**Only an in-memory reference `KnowledgeStore` ships in this ADR** (`InMemoryKnowledgeStore`)
— no SQLite, no file backend, no external service. This is the identical scoping choice
ADR-0005 made for tools ("zero registrations... the boundary only") and mirrors why Q16
stays open for the experiment ledger rather than being decided here by default. The
`KnowledgeStore` `Protocol` (§5) is the real interface; a durable implementation is
future, authorized work (§8), not blocked by this ADR.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Build the full retrieval pipeline now (live web fetch + storage + assembly in one ADR) | Matches Phase 2's full stated scope in one pass | Q9 (LinkedIn access mechanism) is open; no web-fetch tool exists yet (would need a real `ToolInvoker`, itself gated by an unmade owner decision per `STATUS.md`'s "do not start yet"); conflates two responsibilities (acquisition vs. storage/assembly) this ADR's own §2 separates | Rejected — scoped to the storage/provenance/assembly contract only; acquisition is explicitly future work, not silently dropped |
| A vector store / embedding-based similarity search | Standard RAG pattern; would generalize better to fuzzy queries | Explicitly forbidden by this task's own scope constraints; no embedding model has been authorized or selected; `[P§19]` explicitly separates retrieval from reasoning, and semantic ranking blurs that line; adds a real dependency and non-determinism this project's own architecture prefers to avoid until proven necessary | Rejected — deterministic tag/class/staleness filtering is the smallest mechanism that satisfies the stated exit test (provenance-gated storage, source-class-aware retrieval) |
| Make `Provenance` optional with a runtime check callers must remember to run | Slightly less boilerplate for a caller building test fixtures | Exactly the failure mode `docs/RESEARCH_POLICY.md` warns against — an item without provenance can exist transiently and be forwarded before the check runs; fail-open by construction | Rejected — mandatory, validated-at-construction `Provenance` mirrors `ExecutionBinding`/`ToolSpec`'s established fail-closed pattern in this codebase |
| A per-item, caller-settable `evidence_weight` field independent of `source_class` | More flexible — a caller could downweight a normally-"high" source for a specific claim | Lets a `professional_post` (LinkedIn) silently claim `high` weight, directly violating `docs/RESEARCH_POLICY.md`'s explicit LinkedIn rule ("never as a citation supporting a decision") | Rejected — weight is derived from `source_class` by a fixed table, not independently settable |
| A durable (SQLite-backed) `KnowledgeStore` in this same ADR, mirroring ADR-0004's project-memory decision | Would ship "real" persistence immediately, not just an in-memory reference | No owner decision authorizes a backend choice for this layer (no equivalent of Q8's answer exists for knowledge); inventing one here would repeat exactly the trap Q16 already names as open for the experiment ledger | Rejected for this ADR — the `KnowledgeStore` `Protocol` is durable-backend-ready; choosing SQLite/files/a service is future work behind an explicit decision (§8) |

## 5. Interface

```python
# module: cv_agent.knowledge.models  (new)

SourceClass = Literal[
    "peer_reviewed_research",
    "official_documentation",
    "official_repository_or_release_notes",
    "reputable_benchmark",
    "engineering_blog",
    "professional_post",
    "community_discussion",
    "model_zoo_or_leaderboard",
]

EvidenceWeight = Literal["high", "medium", "low_medium", "signal_not_evidence"]

def source_class_weight(source_class: SourceClass) -> EvidenceWeight: ...
    # Pure function over the fixed docs/RESEARCH_POLICY.md table. Not overridable per item.

ItemId = NewType("ItemId", str)

@dataclass(frozen=True)
class Provenance:
    url: str
    source_class: SourceClass
    date_published: str          # ISO 8601 date; non-empty, required
    date_accessed: str           # ISO 8601 date; non-empty, required
    author_or_org: str           # non-empty, required
    def __post_init__(self) -> None: ...  # raises ValueError if any field is malformed

@dataclass(frozen=True)
class KnowledgeItem:
    item_id: ItemId
    claim: str                             # the specific extracted claim (non-empty)
    conditions: str | None                 # hardware/dataset/settings the claim assumes
    provenance: Provenance                 # mandatory — no default, no Optional
    topic_tags: tuple[str, ...]            # deterministic retrieval keys, >=1 required
    staleness_horizon_days: int            # caller-supplied, > 0 required
    def __post_init__(self) -> None: ...   # raises ValueError; fail-closed
    def evidence_weight(self) -> EvidenceWeight: ...
    def is_stale(self, as_of: date) -> bool: ...

# module: cv_agent.knowledge.store  (new)

class KnowledgeStore(Protocol):
    def put(self, item: KnowledgeItem) -> None: ...
    def get(self, item_id: ItemId) -> KnowledgeItem | None: ...
    def list_items(self) -> list[KnowledgeItem]: ...
    def query(
        self,
        *,
        topic_tags: Collection[str] | None = None,
        source_class: SourceClass | None = None,
        exclude_stale_as_of: date | None = None,
    ) -> list[KnowledgeItem]: ...

class InMemoryKnowledgeStore:
    """Reference implementation. In-process only — not durable across restarts.
    See ADR-0006 §8 revisit trigger for the future durable-backend decision."""
    def __init__(self) -> None: ...
    def put(self, item: KnowledgeItem) -> None: ...
    def get(self, item_id: ItemId) -> KnowledgeItem | None: ...
    def list_items(self) -> list[KnowledgeItem]: ...
    def query(
        self,
        *,
        topic_tags: Collection[str] | None = None,
        source_class: SourceClass | None = None,
        exclude_stale_as_of: date | None = None,
    ) -> list[KnowledgeItem]: ...

# module: cv_agent.knowledge.context  (new)

@dataclass(frozen=True)
class ContextBundle:
    items: tuple[KnowledgeItem, ...]
    assembled_at: str              # ISO 8601 timestamp
    query_topic_tags: tuple[str, ...]
    excluded_stale_count: int      # transparency: matched but excluded for staleness

def assemble_context(
    store: KnowledgeStore,
    *,
    topic_tags: Collection[str],
    as_of: date,
    max_items: int,
    source_class: SourceClass | None = None,
) -> ContextBundle: ...
    # Deterministic: exact-tag query, staleness filter, then a stable total order
    # (evidence_weight desc, date_accessed desc, item_id asc), truncated to max_items.
```

## 6. Consequences

- **Enables:** a typed, fail-closed place to hold externally-sourced claims before any
  reasoning node consumes them, with provenance and source-class weighting enforced by
  construction rather than convention — directly implements `docs/RESEARCH_POLICY.md`'s
  rules as code rather than prose. Unblocks a future "Web research" acquisition layer
  and a future real LLM-reasoning call that needs cited, weighted context, without
  either having to invent this contract themselves.
- **Makes harder:** nothing existing — no interface changed, no existing call site
  touched, no existing test's behavior changed.
- **Costs (build, runtime, GPU, $):** three new modules (`models.py`, `store.py`,
  `context.py`), one new test file. No new third-party dependency. No GPU/API cost —
  `InMemoryKnowledgeStore` is pure Python, no network, no persistence I/O.
- **Migration / blast radius if reversed:** contained — deleting `cv_agent/knowledge/`
  restores the exact pre-ADR state; nothing else references it by name.

## 7. Acceptance test

`tests/test_knowledge.py`:
- `Provenance`/`KnowledgeItem` construction with any missing/blank/malformed field
  (`url`, `source_class`, `date_published`, `date_accessed`, `author_or_org`, `claim`,
  empty `topic_tags`, non-positive `staleness_horizon_days`) raises `ValueError` before
  any store interaction — proves "missing provenance is rejected," per `docs/roadmap/
  ROADMAP.md` Phase 2's exit test ("every stored item lacking provenance is rejected by
  the store"), enforced even earlier than the store itself.
- `source_class_weight()` returns the exact weight from `docs/RESEARCH_POLICY.md`'s
  table for all 8 classes; `professional_post` returns `"signal_not_evidence"`,
  never `"high"`.
- `InMemoryKnowledgeStore.put()`/`get()`/`list_items()` round-trip a valid item exactly.
- `query()` filters correctly by `topic_tags` (exact membership, not substring),
  `source_class`, and `exclude_stale_as_of` (an item past its
  `staleness_horizon_days` is excluded).
- `assemble_context()` is deterministic: two calls against the same store state and
  the same arguments return bundles with identical item order; the documented
  tie-break order (`evidence_weight` desc, `date_accessed` desc, `item_id` asc) is
  exercised with items designed to collide on the first two keys.
- `assemble_context()` truncates to `max_items` and reports `excluded_stale_count`
  correctly.
- Structural test: no file under `cv_agent/knowledge/` imports from `cv_agent.execution`,
  `cv_agent.skills`, `cv_agent.graph`, `cv_agent.tools`, or `cv_agent.llm` (mirrors
  ADR-0005 §7's import-confinement test).
- No test requires network access, an API key, or a real persistence backend.

## 8. Revisit trigger

- When a durable `KnowledgeStore` backend is authorized (files/SQLite/a service) — at
  that point this becomes a live decision, mirroring Q16's still-open equivalent for
  the experiment ledger; the `Protocol` in §5 is designed so a durable implementation
  requires no change to `assemble_context()` or any caller.
- When a real acquisition mechanism (web research, an NVIDIA-doc tool, a first
  `ToolInvoker`) is authorized — at that point something needs to actually call
  `KnowledgeStore.put()` with real extracted items; this ADR ships the contract, not a
  producer.
- When a reasoning node first consumes a `ContextBundle` for a real decision — at that
  point the deterministic tie-break order should be re-examined against real usage
  (today it is designed for reproducibility, not tuned against any real query set).

## 9. Status — self-reviewed under continuous-execution authorization (2026-09-24)

This ADR was authored, self-reviewed, and implemented in one pass under the project
owner's explicit instruction to continue milestone-by-milestone without an interim
review round-trip ("If it is unblocked: create feature branch; implement..."), unlike
ADR-0005's separate draft → review → revise → accept cycle. Self-review against the
same five criteria ADR-0005's independent review used:

1. **Boundary correctness:** confirmed — `cv_agent/knowledge/` imports nothing from
   `execution`/`skills`/`graph`/`tools`/`llm` (structural test); it does not duplicate
   `cv_agent/memory/`'s project-state responsibility (different data: externally-sourced
   claims vs. project facts) nor become a fourth way to invoke anything.
2. **Safety/integrity:** confirmed — no path from a `KnowledgeItem`/`ContextBundle` to
   execution, approval, or a tool invocation; provenance is fail-closed at construction,
   not a convention a caller can skip.
3. **Interface quality:** `EvidenceWeight` is derived, not independently settable
   (closes the exact "value-set consistency" class of gap ADR-0005's review found for
   `ApprovalPolicy`); every dataclass validates in `__post_init__`, consistent with
   `ExecutionBinding`/`ToolSpec`.
4. **Governance:** issue #55 exists before implementation; `OPEN_QUESTIONS.md` is
   unmodified; Q2/Q3/Q5/Q6/Q10/Q16/Q19/Q23 are not resolved by this ADR; no new open
   question was silently required — `docs/RESEARCH_POLICY.md` already answered what
   this ADR needed.
5. **Documentation consistency:** `OVERVIEW.md`'s Knowledge/RAG row and `ROADMAP.md`
   Phase 2 are updated to reference this ADR as accepted-and-implemented, matching the
   pattern ADR-0005's acceptance used.

No blocker was found. This status section is not a substitute for the PR review the
repository's governance still requires before this branch lands on `main`.
