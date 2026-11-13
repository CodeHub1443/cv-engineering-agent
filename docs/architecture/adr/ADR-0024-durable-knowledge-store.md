# ADR-0024: Durable KnowledgeStore backend — append-only SQLite revisions with a latest view

- **Status:** Accepted (2026-11-13, owner; D-101), with OQ1 to OQ4 decided as recommended (§7.3).
- **Date:** 2026-11-13
- **Layer:** knowledge (one new module in the existing `cv_agent/knowledge/` package); CLI wiring
- **Canon:** `[P§16]`, `[P§17]`, `[P§19]`, `[P§24]`, `[P§25]`, `[P§29.3]`, `[P§34]`
- **Supersedes / Superseded by:** — . Answers the first revisit trigger of [ADR-0006](ADR-0006-knowledge-context-boundary.md) §8 ("when a durable `KnowledgeStore` backend is authorized"). On acceptance, the acceptance PR adds an "Amended by ADR-0024" note to ADR-0006. **ADR-0006 is not edited by this PR.**
- **Issue:** #125
- **Open question:** Q54 (`docs/state/OPEN_QUESTIONS.md`)

## 1. Context

Q54 (owner, 2026-11-12): *"Durable KnowledgeStore backend (ADR-0006 §8): needed before research results can feed SELECTION across processes."*

ADR-0006 shipped the `KnowledgeStore` Protocol and an in-memory reference implementation only, and deliberately left the durable backend as "an explicit future decision" (ADR-0006 §3, §8). Since then:

- Q41 merged a user-facing research command, `cv-agent research`. Its extraction can run on a hosted tier and costs money; its result is kept in a throwaway in-process store.
- ADR-0023 (Accepted, D-095) made SELECTION consume `KnowledgeItem`s through `PublicClaim.from_item`, with eligibility that depends on `KnowledgeItem.ingest` (ADR-0023 §2.3, §3.4).
- ADR-0023 slice S4 (in flight, `wt\a23s4`) adds `select_claims` (ADR-0023 amendment, item 5).

The repository has two durable-store precedents to copy, not reinvent:

- the experiment ledger (SQLite, ADR-0011, path rule ADR-0016 §3);
- the LLM call log (SQLite, ADR-0020 §5, `cv_agent/llm/sqlite_store.py`). The call log has an explicit `initialise` and an explicit additive `migrate`, opens with `mode=rw` so it never creates the file, uses `BEGIN IMMEDIATE` with a busy timeout, keeps `meta.schema_version`, and fails closed in `_verify`.

Both resolve their location through `repository_state_root()` (`cv_agent/experiments/provenance.py:91-109`): the main checkout's `.cv_agent/`, shared by every worktree and gitignored (`.gitignore:9`).

### 1.1 Inventory: the interface today (fd1aaf1)

| Symbol | Location | Notes |
|---|---|---|
| `KnowledgeStore` Protocol | `cv_agent/knowledge/store.py:17-32` | `put`, `get`, `list_items`, `query(topic_tags, source_class, exclude_stale_as_of)` |
| `InMemoryKnowledgeStore` | `cv_agent/knowledge/store.py:35-70` | dict keyed by `item_id`; `put` **overwrites** (no history) |
| `KnowledgeItem`, `Provenance`, `IngestPath` | `cv_agent/knowledge/models.py:69-135` | validated at construction; `is_stale(as_of)` at `:133-135` |
| `assemble_context` | `cv_agent/knowledge/context.py:44-70` | consumes `store.query(...)` and `is_stale` |
| Leaf-package rule | `tests/test_knowledge.py:397-428` | `cv_agent/knowledge/` must not import `execution`, `skills`, `graph`, `tools` or `llm` |
| `sqlite3` rule | `tests/test_memory.py:369-382` | `import sqlite3` only in files named `sqlite_store.py` |

### 1.2 Inventory: writers and readers

| Role | Site | What it does | `ingest` today → after S4 |
|---|---|---|---|
| Writer | `perform_research`, `cv_agent/graph/research.py:389-415` | builds a `KnowledgeItem` from a fetched page and calls `knowledge_store.put(item)` | `UNSPECIFIED` (default) → `WEB_FETCH` (ADR-0023 §3.4) |
| Writer's caller | `_cmd_research`, `cv_agent/__main__.py:907-1014` | passes `InMemoryKnowledgeStore()` (`:966`), prints the item as JSON (`:981-1009`) and the note "not persisted (ADR-0006 §8)" (`:1011`) | — |
| Writer | `build_reference_knowledge_store`, `cv_agent/model_selection/reference_task_research.py:390-413` | builds code-defined curated items into an in-memory store | `UNSPECIFIED` → `CURATED_REFERENCE` |
| Reader | `_items`, `reference_task_research.py:420-428` | `store.get(item_id)` for each named item; feeds `build_candidate(evidence_items=...)` (`cv_agent/model_selection/selector.py:150-160`) | — |
| Reader | `assemble_context`, `cv_agent/knowledge/context.py:44` | `store.query(...)` | — |
| Reader (S4, in flight) | `select_claims` | applies `PublicClaim.from_item` (`cv_agent/llm/payload.py:202`) and the N = 10 / M = 30 caps (`payload.py:57-58`) to items already attached to candidates | — |

**What the in-memory store breaks:**

1. **Research results die with the process.** A paid hosted extraction is printed and discarded, so SELECTION in a later process cannot use it. This is Q54's case.
2. **No history.** `put` overwrites, so a re-run that refreshes a claim erases what was believed before and when. `[P§25]` (reproducibility) and `[P§29.3]` (evidence) both want the earlier revision kept.
3. **The research query keys are lost.** `--model-name` and `--metric` feed only `claim_query_from` (`cv_agent/graph/research.py:178-190`). `KnowledgeItem` has no field for either, so nothing can later find "the items about `yolo11n`".

## 2. Responsibility (required — `[P§34]`)

- **This owns:** durable, append-only persistence of `KnowledgeItem` revisions together with their retrieval keys; a deterministic latest view; deterministic query over it; and a fail-closed lifecycle (explicit init, explicit additive migrate, version check).
- **This does NOT own:**
  - *Validity of an item.* `KnowledgeItem`/`Provenance` construction already owns that (ADR-0006 §3). The store rebuilds every row through those constructors and adds no second set of rules.
  - *Hosted-payload eligibility.* The gateway owns it (`PublicClaim.from_item`, ADR-0023 §2.3). Storage never widens or narrows it (§3.6).
  - *Acquisition.* `perform_research` and the web-research tool own it (ADR-0006 §10, ADR-0005).
  - *Ranking or relevance.* Retrieval stays exact-match and deterministic (ADR-0006 §3, `[P§19]`). Assembly and tie-break stay in `knowledge/context.py`.
  - *Deciding which items back which candidate.* The reasoning layer (`cv_agent/model_selection/`) owns that, using the query surface (§3.7, slice K4).
- **Why not an existing component:**
  - **Experiment ledger** (`cv_agent/experiments/`, ADR-0011/0016). It records *our own measured* results, immutable, keyed by experiment, under the `[P§25]` schema with commit capture. Knowledge items are *third-party claims* that go stale and are refreshed. That is a different trust model and lifecycle; ADR-0006 §2 draws the same line against project memory. Storing claims in the ledger would put unmeasured external text next to measured results.
  - **LLM call log** (`cv_agent/llm/sqlite_store.py`, ADR-0020). The gateway owns it: one row per governed call plus budget books. Knowledge may not import `cv_agent.llm` (`tests/test_knowledge.py:397-403`), and curated items involve no LLM call. Keeping claims there would couple the knowledge layer to the gateway, which `CLAUDE.md` §3.7 forbids.
  - **Project memory** (`cv_agent/memory/`, ADR-0004). It holds project facts the user owns, a different data class (ADR-0006 §2).
  - **Boundary answer:** the store is a new module, `cv_agent/knowledge/sqlite_store.py`, *inside* the existing knowledge layer, behind the Protocol that layer already defines. It is not a new package or layer. The `sqlite_store.py` filename is the one the repo-wide `sqlite3` rule already permits.

## 3. Decision

Add `SqliteKnowledgeStore`, a durable `KnowledgeStore` backed by one SQLite file at `<repository_state_root()>/knowledge.sqlite`. It stores every `put` as an append-only revision, serves a latest view through the existing Protocol, and adds store-level retrieval keys (model names and metric) and a typed query. It copies the LLM call log's lifecycle exactly:
- explicit `cv-agent knowledge init`;
- explicit, additive, idempotent `cv-agent knowledge migrate`;
- a missing, foreign-version or corrupt store fails closed with a hint.

The research CLI persists through it (§3.8, OQ1).

### 3.1 Backend choice

Recommended: **(A) SQLite**, following the ledger and call-log pattern. The table below gives the evidence; §4 lists the rejected alternatives.

| | (A) SQLite (ledger / call-log pattern) | (B) JSONL append-only files | (C) Embedded vector store or RAG index |
|---|---|---|---|
| Atomic multi-process append | Yes: `BEGIN IMMEDIATE` plus busy timeout, proven in `llm/sqlite_store.py` | No transaction. Two research runs can race on the next revision number; a crash mid-write leaves a torn last line | Depends on the product |
| Revision numbering and the latest view | `UNIQUE(item_id, revision)` plus a SQL view | Recomputed by reading the whole file on every query | Not a native concept |
| Schema version and migration | `meta.schema_version` plus additive `ALTER TABLE ADD COLUMN`, as the call log does | Ad hoc, per line | Product-specific |
| Determinism | Exact SQL plus Python filters | Exact | **No**: similarity ranking; ADR-0006 §3/§4 forbids semantic retrieval |
| New dependency | None (stdlib `sqlite3`) | None | Yes, plus an embedding model nobody has selected |
| Human readability | Needs `cv-agent knowledge list/show` (K2) | `cat` | No |
| Precedent in repo | Two (ADR-0011/0016, ADR-0020) | None | None |

**(C) is not needed yet.** The corpus is tens of items (17 curated in `reference_task_research.py`, plus one per research run), every consumer queries by exact keys, and ADR-0006 forbids fuzzy retrieval. **Revisit trigger for (C):** a recorded case where exact-key retrieval missed an item a reasoning node needed, or a corpus large enough that keeping tags consistent becomes the bottleneck. Either needs its own ADR, an embedding-model selection and a dependency decision.

### 3.2 Schema v1

```sql
-- PROPOSED — <state root>/knowledge.sqlite, schema_version "1"
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- meta: ('schema_version', '1')

CREATE TABLE knowledge_revisions (
    revision_id            INTEGER PRIMARY KEY AUTOINCREMENT,  -- global insertion order
    item_id                TEXT    NOT NULL,
    revision               INTEGER NOT NULL CHECK (revision >= 1),  -- 1..n per item_id
    recorded_at            TEXT    NOT NULL,   -- UTC, ISO 8601 with 'Z'
    writer                 TEXT    NOT NULL,   -- KnowledgeWriter value (§5)
    content_sha256         TEXT    NOT NULL,   -- canonical JSON of item fields + retrieval keys
    -- KnowledgeItem
    claim                  TEXT    NOT NULL,
    conditions             TEXT,               -- NULL = None
    topic_tags_json        TEXT    NOT NULL,   -- JSON array, order preserved
    staleness_horizon_days INTEGER NOT NULL CHECK (staleness_horizon_days > 0),
    ingest                 TEXT    NOT NULL,   -- IngestPath value
    -- Provenance
    url                    TEXT    NOT NULL,
    source_class           TEXT    NOT NULL,   -- SourceClass value
    date_published         TEXT    NOT NULL,   -- YYYY-MM-DD
    date_accessed          TEXT    NOT NULL,   -- YYYY-MM-DD, UTC date (§3.4)
    author_or_org          TEXT    NOT NULL,
    -- Retrieval keys (store-level; §3.3, OQ2)
    model_names_json       TEXT    NOT NULL,   -- JSON array of normalised keys, may be []
    metric                 TEXT,               -- normalised key or NULL
    UNIQUE (item_id, revision)
);

CREATE VIEW knowledge_latest AS
    SELECT r.* FROM knowledge_revisions r
    WHERE r.revision = (SELECT MAX(revision) FROM knowledge_revisions WHERE item_id = r.item_id);
```

**Field coverage.** Every `KnowledgeItem` field (`item_id`, `claim`, `conditions`, `topic_tags`, `staleness_horizon_days`, `ingest`) and every `Provenance` field (`url`, `source_class`, `date_published`, `date_accessed`, `author_or_org`) has a column. `evidence_weight` is **not** stored: it is a pure function of `source_class` (ADR-0006 §3) and is derived on read, so a stored weight could never disagree with the table.

**Primary identity.** The identity is `item_id`. The research CLI already derives it deterministically, `"research-" + sha256(url + "\n" + claim_query)[:16]` (`cv_agent/__main__.py:939-941`), so re-running the same research targets the same item.

**History semantics: append-only revisions.**
- `put` never updates or deletes a row.
- Inside one `BEGIN IMMEDIATE` transaction it reads the latest revision of `item_id`. If the new `content_sha256` equals the latest one, nothing is written (idempotent re-put). Otherwise it inserts `revision = latest + 1`.
- A genuine re-run always appends, because `date_accessed` changes. So a refresh keeps the full provenance history: which claim was believed, from which source, accessed when.
- `content_sha256` covers the item and the retrieval keys, not `recorded_at`, `writer` or `revision`. An identical re-put from another writer is therefore a no-op that keeps the original writer.
- **Rejected alternative:** in-place update (an upsert). It is simpler, but it erases the earlier claim and its access date, which `[P§25]` and `[P§29.3]` need in order to explain a past decision.

**No SQL CHECK on enum columns** (`writer`, `ingest`, `source_class`). SQLite cannot alter a CHECK constraint without rebuilding the table. A rebuild is not an additive migration, and a new `SourceClass` (ADR-0023 §2.3) or a new writer would force one. Enum validity is enforced on write by the typed dataclasses, and on read by rebuilding every row through `KnowledgeItem`/`Provenance`/`IngestPath`/`KnowledgeWriter`. A row that fails reconstruction raises `KnowledgeStoreError` naming its `revision_id`. A read never skips a bad row silently.

### 3.3 Retrieval keys and normalisation (OQ2, OQ3)

Model names and metric are **store-level `RetrievalKeys`** recorded next to each revision. `KnowledgeItem` is unchanged. They are retrieval metadata supplied by the writer (the research request), not part of the extracted claim, and adding them to `KnowledgeItem` would amend ADR-0006's item contract for every writer.

**One normalisation rule, applied at both write and read.** `normalise_key(value)`:

1. `value.strip()`, removing leading and trailing whitespace;
2. validate against the identifier-token pattern used today by `claim_query_from` (`cv_agent/graph/research.py:166`): `[A-Za-z0-9][A-Za-z0-9._/+:-]{0,63}`. A non-token raises `ValueError`;
3. `.lower()`.

The rule runs in `RetrievalKeys.__post_init__` (write) and in `KnowledgeQuery.__post_init__` (read). Both go through constructors, so no code path can store or query an un-normalised key. Model names are de-duplicated after normalisation, keeping first-occurrence order. The original spelling is not stored as a key; the claim text still carries the model name verbatim.

**Matching is exact after normalisation.** A query for `yolo11n` (or `YOLO11n`, or `" yolo11N "`) matches an item stored with `YOLO11n`. **`yolo11` does not match `yolo11n`**: no prefix, substring or fuzzy match. The reference candidate ids (`yolo11n`, `rtdetr-r50`, `nvidia-peoplenet`; `reference_task_research.py:441`, `:487`, `:533`) are already tokens of this form.

**The token pattern is defined once.** The pattern moves to `cv_agent/knowledge/store.py` as `RETRIEVAL_KEY_PATTERN`. `cv_agent/graph/research.py` imports it in slice K3 instead of keeping its own `_TOKEN`. The graph layer may import knowledge; the reverse is forbidden.

**Topic tags are not normalised.** They are a `KnowledgeItem` field, and ADR-0006 §3 defines exact tag membership. Normalising them would rewrite stored item data. Tag case drift is listed as a risk (§6) with a revisit trigger (§8).

### 3.4 Staleness clock: UTC dates

**Convention: `as_of` and `date_accessed` are both UTC calendar dates.** `is_stale(as_of)` keeps its current definition: `(as_of − date_accessed).days > staleness_horizon_days` (`knowledge/models.py:133-135`). An item accessed exactly `staleness_horizon_days` ago is still fresh.

- **Reason 1: like-for-like comparison.** The only live writer already records `date_accessed` as a UTC date. The fetch timestamp is UTC (`cv_agent/tools/web_research.py:153`), it is cut to its date (`cv_agent/graph/research.py:222-230`), and the fallback is today's UTC date. A UTC `as_of` compares the same clock with itself.
- **Reason 2: host independence.** CI (Linux), the Windows PC and the Linux PC compute the same `stale` flag for the same row, whatever their local timezone.
- **Why not the gateway's UTC+06:00 day.** That boundary (Q-F, ADR-0020) is a *spending* day, chosen so the daily budget matches the owner's local calendar. Staleness is not a spending period. Mixing the two would let the same item be fresh for the writer and stale for a reader for up to six hours. Horizons are weeks to years (`docs/RESEARCH_POLICY.md`), so the choice never matters for a decision. What matters is that there is exactly one convention.
- **The store never reads a clock for staleness.** `search` takes `as_of` as a required argument. Only the CLI supplies a default, `datetime.now(timezone.utc).date()`, and `--as-of YYYY-MM-DD` overrides it.
- **Curated items.** Code-defined items carry a literal date (`_ACCESS_DATE = "2026-09-28"`, `reference_task_research.py:66`), read as a UTC date.
- **Stale items are flagged (`StoredItem.stale`) and never deleted, automatically or otherwise** (§3.5).

### 3.5 Lifecycle

- **Init.** `SqliteKnowledgeStore.initialise(path)` creates the parent directory, the file, the tables, the view and the version, in one transaction. It refuses an existing file. CLI: `cv-agent knowledge init`, exit 0 created, 1 already exists (left untouched), 2 cannot create. Nothing else ever creates the file.
- **Open.** The constructor opens with `mode=rw` (never creates) and verifies the version and table shapes, as `LLMCallStore._verify` does. Failure cases:
  - **missing file:** `KnowledgeStoreError` with the hint `run 'cv-agent knowledge init'`;
  - **older known version:** refused with the hint `run 'cv-agent knowledge migrate'`;
  - **unknown version, unexpected shape or corruption:** refused, without guessing.
- **Migrate.** `SqliteKnowledgeStore.migrate(path)` is explicit and idempotent, and is the only code that changes a schema. Allowed steps are additive only: `ADD COLUMN` (nullable or with a default), a new table, a new view, and a version bump. It never rewrites or deletes a row. In v1 there is no older version, so `migrate` verifies the store and reports "up to date (schema version 1)". The command ships now so the mechanism and its idempotence test exist before the first v2. CLI: `cv-agent knowledge migrate`, exit 0 migrated or current, 2 error.
- **Location.** The CLI computes `repository_state_root() / KNOWLEDGE_FILENAME` (`"knowledge.sqlite"`) and passes the path in, as `_cmd_llm_log_init` does (`__main__.py:882-904`). The knowledge package gains no import of `cv_agent.experiments`. All worktrees share one file.
- **Concurrency.** One expected writer at a time: a CLI invocation. Two concurrent `research` runs are still safe, because each `put` is one short `BEGIN IMMEDIATE` transaction with a 5 s busy timeout. The latest-revision read and the insert share that transaction, and `UNIQUE(item_id, revision)` is the backstop. Reads are short transactions too.
- **No WAL** (the default rollback journal), for the same reasons as the call log and the ledger (neither uses WAL; `grep -rn WAL cv_agent` finds none at fd1aaf1):
  - the store is one file, so a copy is a complete backup whenever no writer is running;
  - there are no `-wal`/`-shm` sidecar files to forget or orphan on Windows;
  - writes are rare (one per research run), so WAL's reader/writer concurrency buys nothing.

  **Revisit if** a long-running reader (a service) ever blocks writers.
- **Backup and restore.**
  - **Backup:** copy `knowledge.sqlite` while no `cv-agent` process is writing (no `knowledge.sqlite-journal` present).
  - **Restore:** replace the file, then run `cv-agent knowledge migrate`.
  - The file is gitignored and never committed.
  - The store is **per machine**: the Windows PC (the only hosted-research machine, Q-G) and the Linux PC each have their own. Moving items between them means copying the file. No sync is proposed.
- **No delete command in v1.** Construction already enforces provenance (`docs/RESEARCH_POLICY.md`'s "missing provenance is deleted" is met before `put`). Stale items are flagged, not removed. The append-only history is the audit trail. **Revisit trigger:** the first writer of `PROJECT_INPUT` items, or an owner privacy request. Either would add a redact command (a tombstone revision that blanks claim and conditions), by amendment. Until then the manual recourse is restoring an older backup.

### 3.6 Privacy

- **The store may hold `PROJECT_INPUT` items** (ADR-0023 §3.4). No writer produces them today. `ingest` round-trips exactly. No command and no code path sets or changes `ingest` after construction, and there is no "promote" operation.
- **Storage never changes hosted-payload eligibility.** ADR-0023 §2.3 decides eligibility in `PublicClaim.from_item`, and the store adds no flag the builder consults. `KnowledgeQuery.ingest` is a convenience filter for listing; it is **never** the gate. The K4 reader must not pre-filter on `ingest`, so that the builder's `claims_excluded` counts stay truthful (§3.7).
- **What is never stored:** fetched page text, prompts, LLM responses (those belong to the call log, and `store_text` is off by default), route provider or model strings (`CLAUDE.md` §3.8; the call log already records the route), secrets, or anything from `.env`. The store never reads `.env`.
- The file lives in gitignored `.cv_agent/`.

### 3.7 Query surface for SELECTION

`SqliteKnowledgeStore.search(KnowledgeQuery)` returns `list[StoredItem]` from the latest view, in deterministic `item_id` ascending order. Filter semantics:

| Filter | Semantics |
|---|---|
| `topic_tags` | all-of, exact (the same as today's `query`) |
| `model_names` | any-of, exact after normalisation (§3.3) |
| `metric` | equal after normalisation |
| `source_classes` | any-of |
| `ingest` | any-of (listing convenience only, §3.6) |
| `as_of` | required; sets `StoredItem.stale` |
| `include_stale` | default `False` (matches `assemble_context`) |

One pure function, `matches(item, keys, query)`, implements the filters, and both stores use it, so in-memory and SQLite results cannot drift. The existing Protocol `query()` keeps its signature and meaning on the SQLite store and reads the latest view.

**SELECTION wiring (slice K4, after S4).** A new reasoning-layer module, `cv_agent/model_selection/stored_evidence.py`, loads each candidate's evidence with `search(model_names=(candidate_id,), topic_tags=..., as_of=...)`. It passes the items to `build_candidate(evidence_items=...)` (`selector.py:150-160`) and from there to `select_claims` unchanged. It lives outside `selector.py`, so the selector's import boundary (ADR-0023 §7.1 item 11) is untouched. It does not filter on `ingest` or `source_class`: exclusion is the builder's job and is counted there.

### 3.8 Research CLI persistence (OQ1)

- **Persist by default (recommended), with `--no-persist` to opt out.**
- **Before any fetch or LLM call,** the CLI opens the store. A missing or invalid store exits 2 with the hint (`cv-agent knowledge init`, or pass `--no-persist`), so no LLM spend is wasted.
- `perform_research` is **unchanged**. It still writes into an `InMemoryKnowledgeStore`. On a `stored` result the CLI then calls `durable.put(item, keys=RetrievalKeys(model_names=args.model_name, metric=args.metric))` with `writer=RESEARCH_CLI`. This keeps the graph layer free of retrieval-key concerns.
- The JSON output gains `"persisted": true|false` and `"revision": <n>|null`.
- **If the durable `put` fails** after a stored result, the JSON is still printed with `"persisted": false` (the paid result is not hidden), stderr says why, and the exit code is 2.
- With `--no-persist`: `"persisted": false`, exit 0, and the existing "not persisted" stderr note.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| **(A) SQLite, append-only revisions, latest view** | Two in-repo precedents with tested init/migrate/fail-closed code (`llm/sqlite_store.py`, `experiments/`); transactional; stdlib | Not human-readable without a CLI | **Chosen** |
| (B) JSONL append-only files | Human-readable, git-diffable, no schema | No transactions: the next revision number can race and a crash can tear a line. Every query reads everything. No version or migration mechanism. Zero precedent | Rejected (§3.1) |
| (C) Embedded vector store or RAG index | Fuzzy recall over large corpora | Forbidden by ADR-0006 §3/§4 (deterministic retrieval only, `[P§19]`); needs a dependency and an embedding model; corpus is tens of items | Rejected for now; revisit trigger in §3.1 |
| (D) In-place upsert keyed by `item_id` | Simplest; one row per item | A refresh erases the earlier claim and access date; `[P§25]`/`[P§29.3]` cannot explain a past decision | Rejected (§3.2) |
| (E) Store claims in the experiment ledger or the call log | No new file | Wrong owner and trust model (§2); knowledge may not import `cv_agent.llm` | Rejected |
| (F) Model names and metric as new `KnowledgeItem` fields | Keys travel with the item everywhere | Amends ADR-0006's item contract and every writer; curated items have no "query" | Not recommended; OQ2 |
| (G) Research CLI persists only behind `--persist` | Leaves the merged Q41 behaviour unchanged | A paid hosted extraction is discarded by default, which is the waste Q54 names; hosted calls already require an explicit `llm-log init`, so an explicit `knowledge init` is the same kind of step | Not recommended; OQ1 |

## 5. Interface

All stubs are **PROPOSED**: types and signatures only, no bodies. They are implemented in slices K1 to K4 (§7.2). No code file is changed by this ADR.

```python
# PROPOSED — cv_agent/knowledge/store.py (additions; backend-neutral, no sqlite3)
KNOWLEDGE_FILENAME: Final = "knowledge.sqlite"
RETRIEVAL_KEY_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+:-]{0,63}")  # moved from graph/research.py:166 (K3)

class KnowledgeStoreError(Exception):
    """The durable store is missing, of another schema version, corrupt, busy or unwritable.
    Never means "no data" (that is get() -> None). Messages carry the init or migrate hint."""

class KnowledgeWriter(str, Enum):
    RESEARCH_CLI = "research_cli"          # OQ4: CURATED_REFERENCE is added only if curated items move in

def normalise_key(value: str) -> str: ...  # strip -> RETRIEVAL_KEY_PATTERN fullmatch (else ValueError) -> lower

@dataclass(frozen=True)
class RetrievalKeys:
    model_names: tuple[str, ...] = ()      # normalised and de-duplicated in __post_init__
    metric: str | None = None              # normalised in __post_init__

@dataclass(frozen=True)
class KnowledgeQuery:
    as_of: date                            # UTC date (§3.4); required, the store reads no clock
    topic_tags: tuple[str, ...] = ()       # all-of, exact
    model_names: tuple[str, ...] = ()      # any-of, normalised in __post_init__
    metric: str | None = None              # normalised in __post_init__
    source_classes: frozenset[SourceClass] | None = None
    ingest: frozenset[IngestPath] | None = None   # listing convenience; never an eligibility gate
    include_stale: bool = False

@dataclass(frozen=True)
class StoredItem:
    item: KnowledgeItem
    keys: RetrievalKeys
    revision: int
    recorded_at: str                       # UTC ISO 8601 'Z'
    writer: KnowledgeWriter
    stale: bool                            # item.is_stale(query.as_of)

def matches(item: KnowledgeItem, keys: RetrievalKeys, query: KnowledgeQuery) -> bool: ...
    # The single filter used by both stores (parity).

# KnowledgeStore Protocol: unchanged. InMemoryKnowledgeStore gains, for parity only:
#   put(item, *, keys: RetrievalKeys = RetrievalKeys()) -> None   and   search(query) -> list[StoredItem]
```

```python
# PROPOSED — cv_agent/knowledge/sqlite_store.py (the only knowledge module importing sqlite3)
SCHEMA_VERSION: Final = "1"

class SqliteKnowledgeStore:
    """Durable KnowledgeStore: append-only revisions, latest view, fail-closed lifecycle (ADR-0024)."""

    def __init__(self, path: Path, *, writer: KnowledgeWriter, busy_timeout_s: float = 5.0,
                 now: Callable[[], datetime] = ...) -> None: ...
        # mode=rw, never creates; verifies schema version and table shape; KnowledgeStoreError otherwise

    @staticmethod
    def initialise(path: Path) -> None: ...      # refuses an existing file
    @staticmethod
    def migrate(path: Path) -> None: ...         # additive only, idempotent; v1: verify and report current

    # KnowledgeStore Protocol (latest view)
    def put(self, item: KnowledgeItem, *, keys: RetrievalKeys = RetrievalKeys()) -> None: ...
    def get(self, item_id: ItemId) -> KnowledgeItem | None: ...
    def list_items(self) -> list[KnowledgeItem]: ...
    def query(self, *, topic_tags: Collection[str] | None = None,
              source_class: SourceClass | None = None,
              exclude_stale_as_of: date | None = None) -> list[KnowledgeItem]: ...

    # Durable-only surface
    def record(self, item: KnowledgeItem, *, keys: RetrievalKeys = RetrievalKeys()) -> int: ...
        # what put() does, returning the latest revision number (unchanged on an identical re-put)
    def search(self, query: KnowledgeQuery) -> list[StoredItem]: ...   # item_id asc
    def history(self, item_id: ItemId, *, as_of: date) -> list[StoredItem]: ...  # revision asc
```

```text
# PROPOSED — CLI (cv_agent/__main__.py)
cv-agent knowledge init                       exit 0 created | 1 exists (untouched) | 2 error
cv-agent knowledge migrate                    exit 0 migrated or current | 2 error
cv-agent knowledge list [--topic-tag T]... [--model-name M]... [--metric X]
                        [--source-class C]... [--ingest I]... [--fresh-only]
                        [--as-of YYYY-MM-DD] [--json]
                                              latest revisions, item_id asc, with a stale column
cv-agent knowledge show ITEM_ID [--history] [--as-of YYYY-MM-DD]
                                              JSON of the latest revision (or all revisions)
cv-agent research ... [--no-persist]          persists by default (OQ1); store checked before any fetch
```

```python
# PROPOSED — cv_agent/model_selection/stored_evidence.py (slice K4, after ADR-0023 S4)
def evidence_for_candidate(store: SqliteKnowledgeStore, candidate_id: str, *,
                           topic_tags: tuple[str, ...], as_of: date) -> tuple[KnowledgeItem, ...]: ...
    # search(model_names=(candidate_id,), topic_tags=..., as_of=...), fresh only, item_id asc;
    # no ingest or source-class pre-filter (PublicClaim.from_item excludes and counts)
```

## 6. Consequences

- **Enables:**
  - research results survive the process and can feed SELECTION in a later process (Q54);
  - every refresh keeps the earlier claim and access date (`[P§25]`, `[P§29.3]`);
  - items can be found by model and metric;
  - `cv-agent knowledge list/show` makes the knowledge base inspectable.
- **Makes harder:**
  - one more explicit init step before `research` (OQ1);
  - schema changes need a version bump and a `migrate` step;
  - the store is per machine (§3.5).
- **Costs (build, runtime, GPU, $):**
  - about 1,050 lines over four slices (§7.2);
  - no new dependency;
  - one SQLite transaction per research run;
  - no GPU;
  - $0. Persisting makes no LLM call; it saves the spend that today's discard wastes.
- **Migration / blast radius if reversed:** reverting K3 restores in-process research. Deleting `knowledge.sqlite` loses only stored items, which the research CLI can re-fetch. The Protocol, `perform_research`, `assemble_context` and the payload builder are unchanged.
- **Risks:**
  - **Wrong `ingest`.** A future writer can set `ingest` wrongly (the same risk as ADR-0023 §6). The URL and source-class checks still apply in the builder.
  - **Tag drift.** Topic tags are exact and un-normalised, so `Person-Detection` and `person-detection` drift apart (§8).
  - **Wrong candidate keys.** A model name under-specified by the operator (`yolo11` for a `yolo11n` candidate) silently finds no evidence. That is the intended exact-match behaviour, and `knowledge list --model-name` shows it.
  - **Unbounded growth.** The file grows with every refresh; each row is about 1–2 KB, which is negligible at the expected volume.
- **Amended ADRs:** on acceptance, ADR-0006 gets an "Amended by ADR-0024" note (its §8 durable-backend trigger is answered). Not edited in this PR.

## 7. Acceptance tests and implementation slices

### 7.1 Acceptance criteria

All tests use `tmp_path` only: never the real state root, no network, no `.env`. Every test closes its connections before teardown, for Windows (Q53).

1. **Round-trip.** Every `KnowledgeItem` and `Provenance` field round-trips exactly through `put`/`get` and `search`, including `conditions=None`, multi-tag order, and each `IngestPath` value. `evidence_weight()` is equal before and after.
2. **Revision history:**
   - three puts of changed content give revisions 1, 2 and 3 in `history`;
   - an identical re-put adds no row, and `record` returns the same revision;
   - no row is ever updated: a row count and a checksum of the earlier rows are unchanged after a new revision.
3. **Latest view.** `get`, `list_items`, `query` and `search` return only the newest revision of each item.
4. **Migrate idempotence.** `migrate` on a current store, run twice, leaves the version, schema and every row unchanged. `migrate` on a missing file fails with the init hint.
5. **Fail closed:**
   - the constructor on a missing path raises `KnowledgeStoreError` with `cv-agent knowledge init`, and creates nothing;
   - a foreign `schema_version`, a missing table, or a non-SQLite file raises without guessing;
   - `initialise` on an existing file refuses and leaves it byte-identical;
   - a row edited to an invalid `source_class` raises on read, naming its `revision_id`.
6. **Eligibility unchanged.** Store and reload, through `SqliteKnowledgeStore`, items with `ingest=PROJECT_INPUT`, `ingest=UNSPECIFIED`, `source_class=professional_post`, and the private URLs of ADR-0023 §7.1 criterion 3(e). `PublicClaim.from_item` returns the same `ExclusionReason` for each reloaded item as for the original. A control `WEB_FETCH` item is admitted before and after storage. A `search(ingest=...)` filter changes nothing the builder decides.
7. **Normalisation (OQ3).**
   - Stored keys `("YOLO11n",)` are found by `model_names=("yolo11n",)`, by `("YOLO11N",)` and by `(" yolo11n ",)`.
   - `("yolo11",)` does **not** match. `("yolo 11n",)` and `("",)` raise `ValueError` at both `RetrievalKeys` and `KnowledgeQuery`.
   - `metric="mAP50-95"` is found by `metric="map50-95"`.
8. **Staleness (UTC).**
   - With `date_accessed = 2026-11-01` and a horizon of 10 days, an item is fresh at `as_of = 2026-11-11` and stale at `2026-11-12`.
   - `include_stale=False` excludes it and `True` returns it with `stale=True`; the row still exists.
   - The CLI default `as_of` is the UTC date: a test injects a clock at 2026-11-12T20:00Z (local UTC+06:00 would be the next day) and gets 2026-11-12.
9. **Parity.** On one fixture, `InMemoryKnowledgeStore.search` and `SqliteKnowledgeStore.search` return identical items in identical order for a table of queries.
10. **Structural.** `cv_agent/knowledge/` still imports nothing from the forbidden layers (`tests/test_knowledge.py`). `sqlite3` appears only in `sqlite_store.py` files (`tests/test_memory.py`). `cv_agent/knowledge/` does not import `cv_agent.experiments`.
11. **CLI (K2):**
    - `knowledge init` gives exit codes 0/1/2;
    - `migrate` gives 0/2;
    - `list` filters and shows the stale column;
    - `show --history` lists all revisions;
    - `repository_state_root` is monkeypatched to `tmp_path`, following `tests/test_ledger_path.py:79`.
12. **Research CLI (K3):**
    - with a missing store and no `--no-persist`: exit 2, and the fake fetcher and fake LLM are **never called**;
    - with a store: exit 0, `"persisted": true`, `"revision": 1`, and the keys stored normalised; a second run with new content gives revision 2;
    - `--no-persist` gives exit 0 and `"persisted": false`;
    - a `put` failure after a stored result: JSON printed with `"persisted": false`, exit 2.
13. **SELECTION wiring (K4).** `evidence_for_candidate(store, "yolo11n", ...)` returns exactly the fresh items keyed to `yolo11n`, in `item_id` order, and does not drop `PROJECT_INPUT` items, which the builder then excludes and counts.

### 7.2 Slices (each ≤ about 400 lines including tests; each with its own issue)

| Slice | Content | Lines (approx.) |
|---|---|---|
| **K1** | `knowledge/store.py` additions (§5); `knowledge/sqlite_store.py`; in-memory `search`/keys parity; criteria 1–10 | 380 |
| **K2** | `cv-agent knowledge init / migrate / list / show`; criterion 11 | 220 |
| **K3** | Research CLI persistence per the OQ1 answer; `RETRIEVAL_KEY_PATTERN` used by `graph/research.py`; criterion 12 | 200 |
| **K4** | `model_selection/stored_evidence.py` per the OQ3 answer; criterion 13. Needs ADR-0023 S4 merged | 250 |

**Order:** K1 → K2 → K3 (K2 and K3 both edit `cv_agent/__main__.py`, so they run one after the other). K4 after K1 **and** ADR-0023 S4. None of them switches an LLM route or changes `[llm.privacy]`.

### 7.3 Owner questions (decided at acceptance)

- **OQ1. Should the research CLI persist by default?** *Recommendation:* yes, with `--no-persist`, failing closed **before** the fetch when the store is missing (§3.8). *Alternative:* opt in with `--persist` (Alternative G).
  - **Decided (2026-11-13, owner; D-101):** as recommended: persist by default, with `--no-persist`; the store is checked before any fetch.
- **OQ2. Where do model names and metric live?** *Recommendation:* store-level `RetrievalKeys`, with `KnowledgeItem` unchanged (§3.3). *Alternative:* new `KnowledgeItem` fields (Alternative F, amends ADR-0006).
  - **Decided (2026-11-13, owner; D-101):** as recommended: store-level `RetrievalKeys`; `KnowledgeItem` unchanged.
- **OQ3. How does K4 map an item to a candidate?** *Recommendation:* an exact match after the single normalisation rule of §3.3 (`model_names ∋ normalise_key(candidate_id)`): `YOLO11n` matches `yolo11n`, `yolo11` does not.
  - **Decided (2026-11-13, owner; D-101):** as recommended: exact match after the trim, identifier check, lower-case rule (§3.3).
- **OQ4. Does the curated reference evidence move into the durable store?** *Recommendation:* no in v1. It stays code-defined (`reference_task_research.py`), versioned in git and rebuilt in memory, so the reference comparison and its goldens stay reproducible without a local file. `KnowledgeWriter.CURATED_REFERENCE` is added only if the owner says yes.
  - **Decided (2026-11-13, owner; D-101):** as recommended: curated reference evidence stays code-defined in v1.

## 8. Revisit trigger

- **Vector or semantic retrieval (§3.1 (C)):** a recorded miss by exact-key retrieval that a reasoning node needed, or a corpus where keeping tags consistent becomes the bottleneck.
- **A delete or redact command (§3.5):** the first `PROJECT_INPUT` writer, or an owner privacy request.
- **WAL (§3.5):** a long-running reader (a service or daemon) ever blocks writers.
- **Topic-tag drift:** `knowledge list` shows tags differing only by case or separator. Then consider a tag vocabulary, which would amend ADR-0006.
- **A second machine needs the same knowledge base** (for example SELECTION on the Linux PC from research done on the Windows PC). Then a sync or export design.
- **A writer outside §1.2 appears** (ADR-0023 §8 has the same trigger), or `perform_research` starts exposing its LLM `request_id`. Then add a nullable `llm_request_id` column by `migrate`, linking each revision to its call-log row (`[P§25]`).

## 9. Not verified at drafting time

- **`select_claims` signature.** ADR-0023 S4 had no commits at fd1aaf1 (`wt\a23s4`), so §3.7 and K4 describe its input as the `KnowledgeItem`s attached to candidates through `build_candidate(evidence_items=...)` and do not cite a signature. K4's issue must re-check it against the merged S4.
- **SQLite locking on synced or network folders.** `BEGIN IMMEDIATE` with a busy timeout is proven locally (the call log). If the main checkout is on a synced drive (OneDrive and similar), locking may be unreliable. That case is not tested.
- **Line estimates** (§7.2) are estimates, not measurements.
- **Row size** (about 1–2 KB) is an estimate from the reference claims (the longest is 220 characters, ADR-0023 §2.3), not a measurement.
