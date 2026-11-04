"""
cv_agent.experiments.store — ExperimentLedger boundary.

Mirrors cv_agent.memory.store's shape exactly (ADR-0004 §5, Q8/D-017): a
technology-neutral Protocol, a technology-neutral exception, a default-path
helper, and a factory that hides the concrete backend. Neither symbol here
depends on sqlite3 — the concrete implementation lives in
cv_agent.experiments.sqlite_store, the only module anywhere in this codebase
permitted to reference that standard-library module (a structural test in
tests/test_memory.py already enforces this repo-wide, by filename, for every
package — not only cv_agent/memory/).

A separate database file from project memory (cv_agent/memory/) — a
different logical store recording a different kind of fact (immutable
research/training results vs. mutable project understanding), not merely a
second table an existing store could hold; cv_agent/memory/ has no
established multi-store/multi-table-namespace mechanism for a caller to
extend, so a separate file is the pattern-consistent choice, not a deviation
from one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from cv_agent.experiments.models import ExperimentRecord

DEFAULT_EXPERIMENTS_DIRNAME = ".cv_agent"
DEFAULT_DB_FILENAME = "experiments.sqlite"


class ExperimentLedgerError(Exception):
    """
    Raised when the Experiment Ledger cannot be initialized, read, or written.

    Callers must not treat this as "no data" — that is `get_experiment()`
    returning `None`. This means the store itself failed (bad path, disk
    full, a constraint violation, a corrupt database) and must not be
    silently swallowed — mirrors `cv_agent.memory.store.ProjectMemoryError`.
    """


def default_db_path(workspace_root: Path | None = None) -> Path:
    """
    The experiment ledger path.

    - With ``workspace_root``: ``<workspace_root>/.cv_agent/experiments.sqlite``, explicit and unchanged.
    - Without it: the **repository's** ledger, ``<main checkout>/.cv_agent/experiments.sqlite``,
      resolved from the package location (never the current directory). Every worktree of the
      repository maps to the same file, so a run from a worktree cannot create a silent empty ledger.

    Fails closed (ExperimentLedgerError) when the package is not inside a git repository.
    See docs/architecture/adr/ADR-0016-experiment-provenance.md §3.
    """
    if workspace_root is not None:
        return workspace_root / DEFAULT_EXPERIMENTS_DIRNAME / DEFAULT_DB_FILENAME
    from cv_agent.experiments.provenance import (  # noqa: PLC0415 — avoid import cost/cycle
        ProvenanceError,
        repository_state_root,
    )

    try:
        state_root = repository_state_root()
    except ProvenanceError as exc:
        raise ExperimentLedgerError(
            f"cannot resolve the repository's experiment ledger location: {exc}"
        ) from exc
    return state_root / DEFAULT_DB_FILENAME


class ExperimentLedger(Protocol):
    """
    Storage boundary for the [P§25] experiment schema (docs/state/
    EXPERIMENTS.md).

    The V1 implementation is SQLite
    (`cv_agent.experiments.sqlite_store.SqliteExperimentLedger`,
    `OPEN_QUESTIONS.md` Q16) — local, gitignored, durable across process
    restarts, following the exact pattern `cv_agent.memory.store.
    ProjectMemoryStore`/`SqliteProjectMemoryStore` already established.
    Every caller depends on this Protocol only, never on a SQLite-specific
    type, so a future backend can replace it without changing a caller.

    Not yet wired into `CVAgent` or the CLI — this ADR/change ships the
    boundary and its SQLite implementation only, mirroring how ADR-0004's
    interface and its later `CVAgent` wiring (D-020) were two separate
    decisions.
    """

    def record_experiment(self, record: ExperimentRecord) -> None:
        """
        Upsert by `record.exp_id`.

        A non-terminal record (`status` in `proposed`/`running`) may be
        replaced in place as the run progresses — mirrors
        `cv_agent.memory.models.SessionRecord`'s upsert semantics. Once the
        stored record's `status` is terminal (`completed`/`failed`/
        `cancelled`), any further `record_experiment()` call for the same
        `exp_id` raises `ExperimentLedgerError` — docs/state/EXPERIMENTS.md
        rule 1: "never edit a row after the run completes... errors are
        corrected by a new row plus a note."
        """
        ...

    def get_experiment(self, exp_id: str) -> ExperimentRecord | None:
        """`None` if no record with this `exp_id` has ever been written."""
        ...

    def list_experiments(self) -> list[ExperimentRecord]:
        """Ordered oldest -> newest, by `created_at` then `exp_id`."""
        ...


def open_ledger(
    *,
    workspace_root: Path | None = None,
    db_path: Path | None = None,
    create: bool = False,
) -> ExperimentLedger:
    """
    Construct the V1 `ExperimentLedger` (SQLite — `OPEN_QUESTIONS.md` Q16)
    without the caller needing to import a SQLite-specific type. Mirrors
    `cv_agent.memory.store.open_store()`'s factory pattern exactly.

    By default an **existing** ledger file is required. A missing file raises
    ExperimentLedgerError instead of silently creating an empty ledger (the failure mode that
    produced empty ledgers in worktrees). Pass ``create=True`` only when a new ledger is intended.
    """
    from cv_agent.experiments.sqlite_store import (  # noqa: PLC0415 — deferred to avoid a module-level import cycle (sqlite_store imports ExperimentLedgerError from this module)
        SqliteExperimentLedger,
    )

    path = db_path if db_path is not None else default_db_path(workspace_root=workspace_root)
    if not create and not path.exists():
        raise ExperimentLedgerError(
            f"no experiment ledger at {path}; refusing to create an empty one "
            "(pass create=True only for a deliberately new ledger)"
        )
    return SqliteExperimentLedger(path)
