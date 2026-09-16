"""
cv_agent.memory.store — ProjectMemoryStore boundary.

This module is the one place other packages should ever import from to talk
to project memory. It names no storage technology: `ProjectMemoryStore` is a
`Protocol`, and `ProjectMemoryError` is the technology-neutral exception any
implementation raises on failure. Neither symbol here imports `sqlite3` or
any other backend-specific module (ADR-0004 §2/§5) — the concrete SQLite
implementation lives in `cv_agent.memory.sqlite_store` and is the only module
in this package, or the codebase, allowed to import `sqlite3`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from cv_agent.memory.models import ProjectUnderstandingRevision, SessionRecord

DEFAULT_MEMORY_DIRNAME = ".cv_agent"
DEFAULT_DB_FILENAME = "memory.sqlite"


class ProjectMemoryError(Exception):
    """
    Raised when project memory cannot be initialized, read, or written.

    Callers must not treat a `ProjectMemoryError` as "no data" — that is
    `get_current_understanding()`/`get_session()` returning `None`. This
    exception means the store itself failed (bad path, disk full, corrupt
    database, a backend-specific error) and must not be silently swallowed
    (ADR-0004 implementation requirement 6).
    """


def default_db_path(workspace_root: Path | None = None) -> Path:
    """
    The default, gitignored, project-local persistent-state path for this
    workspace's one project (ADR-0004 §1 items 8-12; `OPEN_QUESTIONS.md`
    Q15/Q8, D-015/D-016).

    Deliberately resolved from the **current working directory** (or an
    explicit `workspace_root`), not from this package's own install
    location: `docs/state/OPEN_QUESTIONS.md` Q1's "the workspace/repository
    IS the project boundary" only holds if every project using an installed
    `cv-agent` gets its own database — resolving relative to `__file__`
    would instead point every installed copy at one shared path inside
    site-packages, silently reintroducing the multi-project conflation V1
    explicitly rejected. Callers that need a different location (tests,
    multiple workspaces in one process) pass `workspace_root` explicitly or
    construct a store with an explicit path — this helper is only the
    convenience default.
    """
    root = workspace_root if workspace_root is not None else Path.cwd()
    return root / DEFAULT_MEMORY_DIRNAME / DEFAULT_DB_FILENAME


class ProjectMemoryStore(Protocol):
    """
    Storage boundary for this workspace's one project (ADR-0004 §1-§3).

    The V1 implementation is SQLite (`cv_agent.memory.sqlite_store.
    SqliteProjectMemoryStore`, `OPEN_QUESTIONS.md` Q8/D-016) — local,
    project-scoped, gitignored, durable across process restarts. Every
    caller depends on this `Protocol` only, never on a SQLite-specific type,
    so a future backend can replace it without changing a caller.

    Wired into `CVAgent` (D-019) via `open_store()`/`CVAgent.memory` —
    `start_workflow()`/`resume_workflow()` read and write through this
    Protocol. `cv_agent.graph.workflow` itself remains intentionally
    untouched — no graph node calls this Protocol; `CVAgent` wraps the
    graph invocation instead, keeping ADR-0003's checkpoint/interrupt
    mechanics and this store two separate concerns (ADR-0004 §2).
    """

    def get_current_understanding(self) -> ProjectUnderstandingRevision | None:
        """The most recently appended revision, or `None` if this project
        has never had one written."""
        ...

    def append_understanding_revision(self, revision: ProjectUnderstandingRevision) -> None:
        """
        Appends a new, immutable revision.

        Must never overwrite or delete a prior revision. Raises
        `ProjectMemoryError` if `revision.revision_id` already exists (a
        revision is identified once, permanently) or if the write fails for
        any other reason.
        """
        ...

    def list_understanding_revisions(self) -> list[ProjectUnderstandingRevision]:
        """Full history, ordered oldest -> newest (insertion order)."""
        ...

    def record_session(self, session: SessionRecord) -> None:
        """
        Upsert by `session.session_id`: a session's own record may be
        replaced in place as it progresses (unlike an understanding
        revision, which is immutable once written) — see
        `SessionRecord`'s own docstring.
        """
        ...

    def get_session(self, session_id: str) -> SessionRecord | None:
        ...

    def list_sessions(self) -> list[SessionRecord]:
        """Ordered oldest -> newest, by `started_at` then `session_id`."""
        ...


def open_store(
    *, workspace_root: Path | None = None, db_path: Path | None = None
) -> ProjectMemoryStore:
    """
    Construct the V1 `ProjectMemoryStore` (SQLite — `OPEN_QUESTIONS.md`
    Q8/D-016) without the caller needing to import a SQLite-specific type.

    Mirrors `cv_agent.llm.registry.get_provider()`'s factory pattern:
    callers ask for "the store," never for `SqliteProjectMemoryStore`
    directly — that keeps SQLite confined to `cv_agent/memory/` even for
    this package's own public entry point (ADR-0004 §2/§5).

    `workspace_root` is forwarded to `default_db_path()` unchanged — this
    function resolves nothing itself either (ADR-0004 §1 item 13): a caller
    that wants the `Path.cwd()` convenience default passes nothing; a real
    application caller resolves `workspace_root` explicitly and passes it.
    `db_path` is an escape hatch to bypass `default_db_path()` entirely and
    point at an exact file (used by tests that don't want to reason about
    the default directory layout at all).
    """
    from cv_agent.memory.sqlite_store import SqliteProjectMemoryStore  # noqa: PLC0415 — deferred to avoid a module-level import cycle (sqlite_store imports ProjectMemoryError from this module)

    path = db_path if db_path is not None else default_db_path(workspace_root=workspace_root)
    return SqliteProjectMemoryStore(path)
