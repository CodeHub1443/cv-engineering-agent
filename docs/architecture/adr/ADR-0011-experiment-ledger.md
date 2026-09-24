# ADR-0011: Experiment Ledger — SQLite-backed persistence for the [P§25] schema

- **Status:** Accepted (owner decision, 2026-09-24: Q16 resolved as SQLite; implemented same session)
- **Date:** 2026-09-24
- **Layer:** memory
- **Canon:** `[P§25]`, `[P§29.2]`, `[P§29.5]`, `[P§34]`, `[P§35]`
- **Supersedes / Superseded by:** —
- **Issue:** #57

## 1. Context

`docs/roadmap/ROADMAP.md` Phase 1 names "ADR-0004 project memory & experiment
ledger" as one deliverable; ADR-0004 (accepted) explicitly split the two apart —
it owns Project Understanding's persistence, and states plainly: *"no migration of
`docs/state/EXPERIMENTS.md` into SQLite or code/the store... the experiment
ledger's own backend question is split off as new `OPEN_QUESTIONS.md` Q16, still
open, and does not block this ADR."* Phase 1's own exit test #4 ("an experiment
row can be written and read back with the full `[P§25]` schema enforced") has
been unmet since. `docs/state/EXPERIMENTS.md` already fully specifies the schema
and rules (`[P§25]`) as a hand-maintained Markdown table — zero real rows, no
code reads or writes it.

**Q16 is now resolved by explicit owner decision (2026-09-24): SQLite**, mirroring
the exact backend `cv_agent/memory/` uses for project memory (`OPEN_QUESTIONS.md`
Q8/D-017). This ADR does not choose the backend — that choice was made by the
owner outside this document — it defines the boundary and ships the implementation
the decision authorizes, the same relationship ADR-0004 had to Q8's answer.

This directly follows this repository's own established architectural pattern:
`ProjectMemoryStore` (Protocol) → `SqliteProjectMemoryStore` (implementation),
behind a factory (`open_store()`) that hides the concrete type from every caller.
`cv_agent/memory/sqlite_store.py`, `store.py`, and `models.py` were read in full
before designing this ADR; nothing here invents a second persistence architecture
— it reuses the identical shape.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** the typed `ExperimentRecord` representation of the `[P§25]`
  schema `docs/state/EXPERIMENTS.md` already defines, fail-closed validation of
  that schema at construction, and its SQLite-backed persistence behind a
  technology-neutral `ExperimentLedger` `Protocol`.
- **This does NOT own:**
  - *running* an experiment (training, evaluation, optimization) — a future
    Training/Evaluation subsystem (`ROADMAP.md` Phases 5–6, no ADR yet); this
    ledger records results, it does not produce them;
  - *the schema itself* — `docs/state/EXPERIMENTS.md` remains the authoritative,
    human-facing definition of what a valid experiment row means (`[P§25]`); this
    ADR gives that existing schema a typed, enforced, machine-readable shape, it
    does not redefine it (§3 states explicitly which fields were newly
    interpreted, and why, where the source table's prose was ambiguous);
  - *dataset/model registry validation* — no dataset subsystem exists yet
    (`ROADMAP.md` Phase 5, not started; `OPEN_QUESTIONS.md` Q10, open), so
    `dataset_version`/`model` are validated as well-formed strings only, never
    cross-referenced against a real manifest;
  - *wiring into `CVAgent`, the CLI, or any reasoning/execution node* — deliberately
    out of scope, mirroring how ADR-0004's interface (drafted first) and its later
    `CVAgent`/CLI wiring (D-020) were two separate decisions; nothing calls
    `cv_agent.experiments` yet;
  - *project memory* — `cv_agent/memory/` is untouched; this is a second,
    independent store, not a new table inside it (§3 explains why).
- **Why this responsibility does not belong to an existing component:**
  `cv_agent/memory/` owns Project Understanding and session records — a different
  *mutability* model (Project Understanding: immutable-append; sessions: freely
  upsertable) from an experiment record's actual rule (upsertable while
  non-terminal, then immutable — `docs/state/EXPERIMENTS.md` rule 1), and ADR-0004
  §2 explicitly declines to own the experiment schema. No other package has ever
  claimed this responsibility; `docs/state/EXPERIMENTS.md` has stood as
  documentation-only since the project's governance scaffold session.

## 3. Decision

New package, `cv_agent/experiments/`, structured identically to `cv_agent/memory/`:
`models.py` (`ExperimentRecord` and the schema's two-numbers-under-one-field cases,
below), `store.py` (`ExperimentLedgerError`, `ExperimentLedger` `Protocol`,
`default_db_path()`, `open_ledger()`), `sqlite_store.py`
(`SqliteExperimentLedger` — the only module anywhere in this codebase, besides
`cv_agent/memory/sqlite_store.py`, permitted to import `sqlite3`; enforced by the
existing repo-wide structural test in `tests/test_memory.py`, which already scans
every package by filename, not only `cv_agent/memory/`).

**Every field name is taken verbatim from `docs/state/EXPERIMENTS.md`'s schema
table** — none renamed, none dropped. Three rows in that table name a value that
is intrinsically two numbers/strings under one field, not one: `hardware`
("training hardware **and** target hardware"), `latency` ("end-to-end **and**
inference-only"), `memory` ("VRAM + RAM"). Each is represented as a small nested
frozen dataclass (`HardwareInfo`, `LatencyMeasurement`, `MemoryFootprint`) under
that exact same top-level field name — the alternative of splitting each into two
new top-level field names not present in the schema table would itself be a
silent rename; collapsing to one number would silently drop required information.
This was a necessary interpretation, not an invention: the schema table's own
prose states both values are needed, it just does not give each one a distinct
column name.

**Mutability follows `docs/state/EXPERIMENTS.md` rule 1 exactly**, not
`cv_agent/memory/`'s existing patterns verbatim: *"One row per run. Never edit a
row after the run completes."* This is neither pure immutable-append
(`ProjectUnderstandingRevision`) nor unrestricted upsert (`SessionRecord`) — it is
upsertable while `status` is non-terminal (`proposed`/`running`), then rejected
(fail-closed) once `status` becomes terminal (`completed`/`failed`/`cancelled`).
`record_experiment()`'s name mirrors `record_session()`'s upsert-shaped method
name, because the *lifecycle* (a record accumulates fields as a run progresses)
is closer to a session's than to a Project Understanding revision's — but its
*locking* behavior is new, required directly by rule 1's own wording, and has no
precedent in `cv_agent/memory/` to copy from.

**A separate SQLite database file** (`experiments.sqlite`, alongside
`memory.sqlite` under the same gitignored `.cv_agent/` directory
`cv_agent/memory/store.py` already establishes) — not a new table inside
`cv_agent/memory/`'s existing database. `cv_agent/memory/` has no established
mechanism for a second package to add its own table to that store's schema or
connection; the `ProjectMemoryStore` `Protocol` is scoped to Project
Understanding and sessions only. A separate file keeps the two stores'
lifecycles, schemas, and mutability rules independent, exactly as `ADR-0004` §8
left open ("[whether they] eventually share one physical backend is left as a
revisit trigger, not decided now") — this ADR does not decide that question
either; it takes the simpler, independent-file default `ADR-0004` itself used at
its own drafting.

**Where `docs/state/EXPERIMENTS.md` is silent, only the smallest deterministic
integrity constraint is applied**, documented per field in `models.py` — no
cross-reference validation against a dataset/model registry (none exists),
no strict format assumed for `commit`/`precision`/`input_resolution` beyond
non-blank (the schema's own prose is free-text for these), and no attempt to
mechanically enforce rule 3 ("accuracy metrics without system metrics are
incomplete") — that rule is a judgment about whether a run is *good*, not a
statement about whether a *row* is valid, and enforcing it would reject a
legitimate `proposed`/`running` record that simply hasn't reached the metrics
stage yet.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Add experiment tables to `cv_agent/memory/`'s existing SQLite database/module | One database file instead of two; reuses an open connection | `cv_agent/memory/`'s `Protocol` and module boundary are scoped to Project Understanding/sessions (ADR-0004 §2); no existing mechanism lets a second package extend that schema without editing `cv_agent/memory/sqlite_store.py` directly, which ADR-0004 keeps `cv_agent/memory/`-internal | Rejected; a separate package/file preserves both modules' independent boundaries, matching `[P§34]`'s boundary test |
| Files (e.g. one JSONL row per run) instead of SQLite | Simplest possible mechanism; matches `docs/state/EXPERIMENTS.md`'s own current Markdown-table style | The owner's explicit decision for Q16 is SQLite, not files — this alternative describes what was rejected by that decision, not a live option | Rejected by owner decision |
| An ORM (SQLAlchemy or similar) over raw `sqlite3` | Less hand-written SQL; familiar to some ML-platform conventions | `cv_agent/memory/sqlite_store.py` uses raw `sqlite3` with parameterized SQL directly, no ORM — this task's own instructions explicitly forbid a new ORM, and introducing one here would make the two SQLite-backed packages inconsistent for no stated benefit | Rejected; raw `sqlite3`, mirroring the existing precedent exactly |
| Flatten `hardware`/`latency`/`memory` into new field names (e.g. `latency_end_to_end_ms`, `latency_inference_only_ms`) | Simpler flat schema, no nested dataclasses | Introduces field names absent from `docs/state/EXPERIMENTS.md`'s schema table — exactly the "do not silently rename fields" instruction this work is bound by | Rejected; nested value objects preserve the table's own field names |

## 5. Interface

```python
# module: cv_agent.experiments.models  (new)

ExperimentStatus = Literal["proposed", "running", "completed", "failed", "cancelled"]

@dataclass(frozen=True)
class HardwareInfo:
    training: str
    target: str

@dataclass(frozen=True)
class LatencyMeasurement:
    end_to_end: float
    inference_only: float

@dataclass(frozen=True)
class MemoryFootprint:
    vram: float
    ram: float

@dataclass(frozen=True)
class ExperimentRecord:
    exp_id: str                              # "EXP-YYYYMMDD-NN"
    status: ExperimentStatus
    hypothesis: str
    success_criteria: str
    baseline_id: str                         # "SELF" or another exp_id
    created_at: str                          # ISO-8601
    parent_exp_id: str | None = None
    completed_at: str | None = None          # required once status is terminal
    commit: str | None = None
    approval_ref: str | None = None
    model: str | None = None
    dataset_version: str | None = None
    input_resolution: str | None = None
    batch_size: int | None = None
    optimizer: str | None = None
    lr: float | None = None
    scheduler: str | None = None
    augmentations: str | None = None
    epochs: int | None = None
    precision: str | None = None
    hardware: HardwareInfo | None = None
    params: float | None = None
    flops: float | None = None
    train_time: float | None = None
    gpu_hours: float | None = None
    val_metrics: dict[str, float] | None = None
    test_metrics: dict[str, float] | None = None
    latency: LatencyMeasurement | None = None
    fps: float | None = None
    memory: MemoryFootprint | None = None
    power: float | None = None
    failure_analysis: str | None = None
    decision: str | None = None
    notes: str = ""

    def __post_init__(self) -> None: ...   # fail-closed, see §3/§6
    def is_terminal(self) -> bool: ...

# module: cv_agent.experiments.store  (new)

class ExperimentLedgerError(Exception): ...

def default_db_path(workspace_root: Path | None = None) -> Path: ...

class ExperimentLedger(Protocol):
    def record_experiment(self, record: ExperimentRecord) -> None: ...
    def get_experiment(self, exp_id: str) -> ExperimentRecord | None: ...
    def list_experiments(self) -> list[ExperimentRecord]: ...

def open_ledger(
    *, workspace_root: Path | None = None, db_path: Path | None = None,
) -> ExperimentLedger: ...

# module: cv_agent.experiments.sqlite_store  (new)

class SqliteExperimentLedger:
    def __init__(self, db_path: Path) -> None: ...
    def close(self) -> None: ...
    def record_experiment(self, record: ExperimentRecord) -> None: ...
    def get_experiment(self, exp_id: str) -> ExperimentRecord | None: ...
    def list_experiments(self) -> list[ExperimentRecord]: ...
```

## 6. Consequences

- **Enables:** Phase 1's exit test #4 is now demonstrable — a real experiment row
  with the full `[P§25]` schema can be written and read back, enforced. A future
  training/evaluation subsystem has a ready, tested persistence boundary to call
  rather than inventing one under schedule pressure.
- **Makes harder:** nothing existing — no interface changed, no existing call site
  touched (`cv_agent/memory/`, `CVAgent`, the CLI, and `docs/state/EXPERIMENTS.md`'s
  own content are all untouched by code).
- **Costs:** one new package (4 modules), one new test file, no new third-party
  dependency (`sqlite3` is standard library, already used identically by
  `cv_agent/memory/`).
- **Migration / blast radius if reversed:** contained — deleting
  `cv_agent/experiments/` restores the exact pre-ADR state; nothing else
  references it by name.

## 7. Acceptance test

`tests/test_experiments.py`, 90 tests:
- **Domain:** valid minimal/full record construction; every documented rejection
  (malformed `exp_id`/`baseline_id`/`parent_exp_id` format, invalid `status`,
  blank required fields, non-positive counts, negative non-negative fields, NaN/
  Infinity metric values, empty metrics dict, terminal status without
  `completed_at`, `completed_at` before `created_at`, malformed nested
  `HardwareInfo`/`LatencyMeasurement`/`MemoryFootprint`).
- **SQLite:** schema initialization (fresh nested path, reopen), init-failure
  wrapping, empty-store reads, insert/read round-trip including every nested
  field, the SQL-keyword-collision `commit`/`commit_sha` column rename verified
  round-trips correctly, list ordering, upsert while non-terminal, rejection once
  terminal for **each** terminal status, the original terminal row proven
  untouched after a rejected write, a real `sqlite3.IntegrityError` proving the
  DB-level `CHECK` constraint on `status` is genuine defense-in-depth (bypassing
  the domain layer entirely), persistence across three sequential close/reopen
  cycles, closed-connection reads/writes raising `ExperimentLedgerError` chained
  from the underlying `sqlite3.Error`.
- **Contract:** `open_ledger()`'s default-path and explicit-path forms, protocol
  surface satisfaction, a dedicated test confirming the experiment and project
  memory databases use different filenames (no collision).
- **Architecture boundary:** no `sqlite3` import outside `sqlite_store.py`
  (verified against the existing repo-wide test in `tests/test_memory.py`, not
  duplicated); no import from `cv_agent.execution`/`graph`/`tools`/`llm`/
  `knowledge`.

Full suite: 772 → 862 passing, zero regressions. `ruff check cv_agent tests` and
`mypy cv_agent` both clean (52 source files).

## 8. Revisit trigger

- When `CVAgent`/the CLI/a training-execution subsystem is ready to actually write
  real experiment rows — at that point this package gets wired in, mirroring
  ADR-0004's own interface-then-integration sequence (D-020).
- When a dataset subsystem (`ROADMAP.md` Phase 5) exists — `dataset_version`
  could then be validated against a real manifest instead of only as a
  well-formed string.
- If SQLite is found unsuitable in practice (the same trigger ADR-0004 §8 names
  for project memory) — the backend choice is reopened as a new decision, not
  silently swapped, exactly like ADR-0004's own revisit trigger.
- When project memory and the experiment ledger's relationship (separate files
  vs. a shared backend) is revisited — named as open by ADR-0004 §8 already; this
  ADR does not resolve it either.
