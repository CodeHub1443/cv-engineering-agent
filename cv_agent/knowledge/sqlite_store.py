"""
cv_agent.knowledge.sqlite_store — the durable, append-only KnowledgeStore backend (ADR-0024).

Responsibility (ADR-0024 §2): durable, append-only persistence of ``KnowledgeItem`` revisions
together with their retrieval keys; a deterministic latest view; and a fail-closed lifecycle
(explicit init, explicit additive migrate, version check). It does NOT own the validity of an
item (the constructors do), hosted-payload eligibility (the gateway does), acquisition, or ranking.
This is the ONLY module in ``cv_agent/knowledge/`` allowed to import ``sqlite3``.

Slice K1a (this file so far): the lifecycle only. Reading and writing revisions arrive in K1b/K1c.

Rules (copied from ``cv_agent/llm/sqlite_store.py``):
- The file is created only by ``SqliteKnowledgeStore.initialise``. The constructor and every other
  method open it with ``mode=rw`` and never create it.
- Every step is one short ``BEGIN IMMEDIATE`` transaction with a busy timeout (5 s by default), so
  two processes serialise instead of failing or losing a row.
- Rollback journal, no WAL: the store is one file, so a copy is a complete backup.
- No SQL CHECK on enum columns: SQLite cannot alter one without a table rebuild, which is not an
  additive migration. Enum validity is enforced by the typed dataclasses.
- Migration is additive only. Schema version 1 has no older version, so ``migrate`` verifies the
  store and changes nothing.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Final, Iterator

from cv_agent.knowledge.store import KnowledgeStoreError, KnowledgeWriter

SCHEMA_VERSION: Final = "1"
INIT_HINT: Final = "run `cv-agent knowledge init` to create it"

_SCHEMA = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE knowledge_revisions (
    revision_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id                TEXT    NOT NULL,
    revision               INTEGER NOT NULL CHECK (revision >= 1),
    recorded_at            TEXT    NOT NULL,
    writer                 TEXT    NOT NULL,
    content_sha256         TEXT    NOT NULL,
    claim                  TEXT    NOT NULL,
    conditions             TEXT,
    topic_tags_json        TEXT    NOT NULL,
    staleness_horizon_days INTEGER NOT NULL CHECK (staleness_horizon_days > 0),
    ingest                 TEXT    NOT NULL,
    url                    TEXT    NOT NULL,
    source_class           TEXT    NOT NULL,
    date_published         TEXT    NOT NULL,
    date_accessed          TEXT    NOT NULL,
    author_or_org          TEXT    NOT NULL,
    model_names_json       TEXT    NOT NULL,
    metric                 TEXT,
    UNIQUE (item_id, revision)
)""",
    """CREATE VIEW knowledge_latest AS
    SELECT r.* FROM knowledge_revisions r
    WHERE r.revision = (SELECT MAX(revision) FROM knowledge_revisions WHERE item_id = r.item_id)""",
)
_REVISION_COLUMNS: Final = (
    "revision_id",
    "item_id",
    "revision",
    "recorded_at",
    "writer",
    "content_sha256",
    "claim",
    "conditions",
    "topic_tags_json",
    "staleness_horizon_days",
    "ingest",
    "url",
    "source_class",
    "date_published",
    "date_accessed",
    "author_or_org",
    "model_names_json",
    "metric",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SqliteKnowledgeStore:
    """Durable KnowledgeStore: append-only revisions, latest view, fail-closed lifecycle."""

    def __init__(
        self,
        path: Path,
        *,
        writer: KnowledgeWriter,
        busy_timeout_s: float = 5.0,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        if busy_timeout_s < 0:
            raise ValueError("busy_timeout_s must not be negative")
        if not isinstance(writer, KnowledgeWriter):
            raise TypeError(f"writer must be a KnowledgeWriter, got {writer!r}")
        self._path = Path(path)
        self._writer = writer
        self._busy_timeout_s = busy_timeout_s
        self._now = now
        if not self._path.is_file():
            raise KnowledgeStoreError(f"knowledge store {self._path} does not exist; {INIT_HINT}.")
        self._verify()

    @property
    def path(self) -> Path:
        return self._path

    @staticmethod
    def initialise(path: Path) -> None:
        """Create the store with its schema. Refuses when the file already exists."""
        target = Path(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=False)
        except FileExistsError:
            raise KnowledgeStoreError(f"knowledge store {target} already exists; refusing to touch it.") from None
        except OSError as exc:
            raise KnowledgeStoreError(f"cannot create knowledge store {target}: {exc}") from exc
        failure: sqlite3.Error | None = None
        try:
            with closing(sqlite3.connect(target, isolation_level=None)) as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for statement in _SCHEMA:  # not executescript: it would commit first
                        conn.execute(statement)
                    conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
        except sqlite3.Error as exc:
            failure = exc
        if failure is not None:
            # The connection is closed by now; Windows will not delete a file a connection holds (Q53).
            target.unlink(missing_ok=True)  # never leave a half-initialised store behind
            raise KnowledgeStoreError(f"cannot initialise knowledge store {target}: {failure}") from failure

    @staticmethod
    def migrate(path: Path) -> None:
        """Verify the store and bring it to the current schema; idempotent, additive only.

        Version 1 has no older version, so this verifies and writes nothing. A missing file is
        refused (never created); an unknown version or shape is refused without guessing.
        """
        target = Path(path)
        if not target.is_file():
            raise KnowledgeStoreError(f"knowledge store {target} does not exist; {INIT_HINT}.")
        try:
            with closing(_connect(target, 5.0)) as conn:
                _check_shape(conn, target)
        except sqlite3.Error as exc:
            raise KnowledgeStoreError(f"knowledge store {target} is corrupt or unreadable: {exc}") from exc

    @contextmanager
    def _txn(self) -> Iterator[sqlite3.Connection]:
        """One ``BEGIN IMMEDIATE`` transaction; any sqlite error becomes ``KnowledgeStoreError``."""
        try:
            with closing(self._connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    yield conn
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
        except sqlite3.Error as exc:
            raise KnowledgeStoreError(f"cannot write to knowledge store {self._path}: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        return _connect(self._path, self._busy_timeout_s)

    def _verify(self) -> None:
        try:
            with closing(self._connect()) as conn:
                _check_shape(conn, self._path)
        except sqlite3.Error as exc:
            raise KnowledgeStoreError(f"knowledge store {self._path} is corrupt or unreadable: {exc}") from exc


def _connect(path: Path, busy_timeout_s: float) -> sqlite3.Connection:
    # mode=rw: open an existing file only, so a deleted store is an error, not a new empty one.
    uri = path.resolve().as_uri() + "?mode=rw"
    return sqlite3.connect(uri, uri=True, timeout=busy_timeout_s, isolation_level=None)


def _check_shape(conn: sqlite3.Connection, path: Path) -> None:
    """Fail closed unless version, columns and view are exactly schema v1."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None or row[0] != SCHEMA_VERSION:
        found = None if row is None else row[0]
        raise KnowledgeStoreError(
            f"knowledge store {path} has schema version {found!r}; expected {SCHEMA_VERSION!r}. "
            "It is not guessed at: move it away and re-create it."
        )
    columns = tuple(r[1] for r in conn.execute("PRAGMA table_info(knowledge_revisions)"))
    view = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'view' AND name = 'knowledge_latest'").fetchone()
    if columns != _REVISION_COLUMNS or view is None:
        raise KnowledgeStoreError(f"knowledge store {path} has an unexpected knowledge_revisions schema or no latest view.")
