"""
cv_agent.memory.sqlite_store — SqliteProjectMemoryStore.

The ONLY module in this codebase allowed to import `sqlite3` or reference a
SQLite-specific type (ADR-0004 §2/§5; `OPEN_QUESTIONS.md` Q8/D-016). Every
other caller — tests included, once a store is constructed — talks to this
class only through the `ProjectMemoryStore` `Protocol` it implements.

Schema is initialized with idempotent `CREATE TABLE IF NOT EXISTS`
statements on every open — safe to call against an existing database, a
fresh empty file, or (via `default_db_path()`) a path whose parent
directory does not exist yet. No separate migration/version-detection
system is built (ADR-0004 implementation requirement 5 — the simplest
deterministic policy, not an elaborate change-detection system); the two
tables below are the entire V1 schema.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from cv_agent.memory.models import ProjectUnderstandingRevision, SessionRecord
from cv_agent.memory.store import ProjectMemoryError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS understanding_revisions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    revision_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    session_id TEXT NOT NULL,
    requirements_analysis TEXT NOT NULL,
    supersedes TEXT,
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    produced_revision_id TEXT
);
"""


class SqliteProjectMemoryStore:
    """
    SQLite-backed `ProjectMemoryStore` (structurally — it satisfies the
    `Protocol`, no inheritance declared, matching how `ExecutionRuntime`
    implementations are registered elsewhere in this codebase).

    Local, project-scoped, file-based, durable across process restarts.
    Every write is one transaction (`with self._conn:` — sqlite3's own
    commit-on-success/rollback-on-exception context manager), so a failure
    partway through a write cannot leave a partial row.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_path))
            with self._conn:
                self._conn.executescript(_SCHEMA)
        except (OSError, sqlite3.Error) as exc:
            raise ProjectMemoryError(
                f"Failed to initialize project memory store at {db_path}: {exc}"
            ) from exc

    def close(self) -> None:
        """Release the underlying SQLite connection. Not part of
        `ProjectMemoryStore` (the Protocol is backend-agnostic and a
        gitignored local file needs no handle other backends would), but
        real resource cleanup any caller holding a concrete instance should
        use — tests use it explicitly to prove restart-survival across a
        genuine close/reopen, not just a second connection to an open file."""
        self._conn.close()

    def __enter__(self) -> "SqliteProjectMemoryStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ── Project Understanding ───────────────────────────────────────────

    def get_current_understanding(self) -> ProjectUnderstandingRevision | None:
        try:
            row = self._conn.execute(
                "SELECT revision_id, created_at, session_id, requirements_analysis, "
                "supersedes, note FROM understanding_revisions "
                "ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error as exc:
            raise ProjectMemoryError(f"Failed to read current understanding: {exc}") from exc
        return _row_to_revision(row) if row is not None else None

    def append_understanding_revision(self, revision: ProjectUnderstandingRevision) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO understanding_revisions "
                    "(revision_id, created_at, session_id, requirements_analysis, "
                    "supersedes, note) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        revision.revision_id,
                        revision.created_at,
                        revision.session_id,
                        json.dumps(revision.requirements_analysis, sort_keys=True),
                        revision.supersedes,
                        revision.note,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ProjectMemoryError(
                f"Revision '{revision.revision_id}' already exists — revisions are "
                "immutable and cannot be overwritten."
            ) from exc
        except sqlite3.Error as exc:
            raise ProjectMemoryError(
                f"Failed to append understanding revision '{revision.revision_id}': {exc}"
            ) from exc

    def list_understanding_revisions(self) -> list[ProjectUnderstandingRevision]:
        try:
            rows = self._conn.execute(
                "SELECT revision_id, created_at, session_id, requirements_analysis, "
                "supersedes, note FROM understanding_revisions ORDER BY seq ASC"
            ).fetchall()
        except sqlite3.Error as exc:
            raise ProjectMemoryError(f"Failed to list understanding revisions: {exc}") from exc
        return [_row_to_revision(row) for row in rows]

    # ── Sessions ─────────────────────────────────────────────────────────

    def record_session(self, session: SessionRecord) -> None:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO sessions "
                    "(session_id, started_at, ended_at, status, produced_revision_id) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET "
                    "started_at=excluded.started_at, ended_at=excluded.ended_at, "
                    "status=excluded.status, "
                    "produced_revision_id=excluded.produced_revision_id",
                    (
                        session.session_id,
                        session.started_at,
                        session.ended_at,
                        session.status,
                        session.produced_revision_id,
                    ),
                )
        except sqlite3.Error as exc:
            raise ProjectMemoryError(
                f"Failed to record session '{session.session_id}': {exc}"
            ) from exc

    def get_session(self, session_id: str) -> SessionRecord | None:
        try:
            row = self._conn.execute(
                "SELECT session_id, started_at, ended_at, status, produced_revision_id "
                "FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise ProjectMemoryError(f"Failed to read session '{session_id}': {exc}") from exc
        return _row_to_session(row) if row is not None else None

    def list_sessions(self) -> list[SessionRecord]:
        try:
            rows = self._conn.execute(
                "SELECT session_id, started_at, ended_at, status, produced_revision_id "
                "FROM sessions ORDER BY started_at ASC, session_id ASC"
            ).fetchall()
        except sqlite3.Error as exc:
            raise ProjectMemoryError(f"Failed to list sessions: {exc}") from exc
        return [_row_to_session(row) for row in rows]


def _row_to_revision(row: tuple[Any, ...]) -> ProjectUnderstandingRevision:
    revision_id, created_at, session_id, requirements_analysis_json, supersedes, note = row
    return ProjectUnderstandingRevision(
        revision_id=revision_id,
        created_at=created_at,
        session_id=session_id,
        requirements_analysis=json.loads(requirements_analysis_json),
        supersedes=supersedes,
        note=note,
    )


def _row_to_session(row: tuple[Any, ...]) -> SessionRecord:
    session_id, started_at, ended_at, status, produced_revision_id = row
    return SessionRecord(
        session_id=session_id,
        started_at=started_at,
        ended_at=ended_at,
        status=status,
        produced_revision_id=produced_revision_id,
    )
