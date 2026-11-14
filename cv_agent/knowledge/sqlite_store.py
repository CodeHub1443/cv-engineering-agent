"""
cv_agent.knowledge.sqlite_store — the durable, append-only KnowledgeStore backend (ADR-0024).

Responsibility (ADR-0024 §2): durable, append-only persistence of ``KnowledgeItem`` revisions
together with their retrieval keys; a deterministic latest view; and a fail-closed lifecycle
(explicit init, explicit additive migrate, version check). It does NOT own the validity of an
item (the constructors do), hosted-payload eligibility (the gateway does), acquisition, or ranking.
This is the ONLY module in ``cv_agent/knowledge/`` allowed to import ``sqlite3``.

Slices: K1a the lifecycle; K1b revisions (record/put/get/list_items/query/history, the content hash,
row rebuild, staleness from a passed ``as_of``). ``search`` arrives in K1c.

Rules (copied from ``cv_agent/llm/sqlite_store.py``):
- The file is created only by ``SqliteKnowledgeStore.initialise``. The constructor and every other
  method open it with ``mode=rw`` and never create it.
- Every step is one short ``BEGIN IMMEDIATE`` transaction with a busy timeout (5 s by default), so
  two processes serialise instead of failing or losing a row.
- Rollback journal, no WAL: the store is one file, so a copy is a complete backup.
- No SQL CHECK on enum columns: SQLite cannot alter one without a table rebuild, which is not an
  additive migration. Enum validity is enforced by the typed dataclasses.
- A read never skips a bad row: every row is rebuilt through the typed constructors and a failure
  raises ``KnowledgeStoreError`` naming its ``revision_id``.
- The store never reads a clock for staleness (``as_of`` is passed in); the injected ``now`` only
  stamps ``recorded_at`` on a write.
- Migration is additive only. Schema version 1 has no older version, so ``migrate`` verifies the
  store and changes nothing.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Collection, Final, Iterator

from cv_agent.knowledge.models import IngestPath, ItemId, KnowledgeItem, Provenance, SourceClass
from cv_agent.knowledge.store import (
    KnowledgeStore,
    KnowledgeStoreError,
    KnowledgeWriter,
    RetrievalKeys,
    StoredItem,
)

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

    # --- KnowledgeStore Protocol (latest view) ---------------------------------------------------

    def put(self, item: KnowledgeItem, *, keys: RetrievalKeys = RetrievalKeys()) -> None:
        """Record ``item`` (see ``record``); the Protocol method, so it returns nothing."""
        self.record(item, keys=keys)

    def get(self, item_id: ItemId) -> KnowledgeItem | None:
        rows = self._select("SELECT * FROM knowledge_latest WHERE item_id = ?", (str(item_id),))
        return _rebuild(rows[0], None).item if rows else None

    def list_items(self) -> list[KnowledgeItem]:
        return [s.item for s in self._latest()]

    def query(
        self,
        *,
        topic_tags: Collection[str] | None = None,
        source_class: SourceClass | None = None,
        exclude_stale_as_of: date | None = None,
    ) -> list[KnowledgeItem]:
        """Same filters as ``InMemoryKnowledgeStore.query``, over the latest view, ``item_id`` ascending."""
        wanted = set(topic_tags) if topic_tags is not None else None
        results: list[KnowledgeItem] = []
        for stored in self._latest():
            item = stored.item
            if wanted is not None and not wanted.issubset(item.topic_tags):
                continue
            if source_class is not None and item.provenance.source_class != source_class:
                continue
            if exclude_stale_as_of is not None and item.is_stale(exclude_stale_as_of):
                continue
            results.append(item)
        return results

    # --- durable-only surface ---------------------------------------------------------------------

    def record(self, item: KnowledgeItem, *, keys: RetrievalKeys = RetrievalKeys()) -> int:
        """Append a revision unless the content is identical to the latest; return the latest revision.

        One ``BEGIN IMMEDIATE`` transaction reads the latest revision and inserts the next, so racing
        writers serialise; ``UNIQUE(item_id, revision)`` is the backstop. No row is ever changed.
        """
        if not isinstance(item, KnowledgeItem):
            raise TypeError(f"record() needs a KnowledgeItem, got {item!r}")
        if not isinstance(keys, RetrievalKeys):
            raise TypeError(f"keys must be RetrievalKeys, got {keys!r}")
        recorded_at = self._recorded_at()
        digest = _content_hash(item, keys)
        prov = item.provenance
        with self._txn() as conn:
            latest = conn.execute(
                "SELECT revision, content_sha256 FROM knowledge_revisions WHERE item_id = ? "
                "ORDER BY revision DESC LIMIT 1",
                (str(item.item_id),),
            ).fetchone()
            if latest is not None and latest[1] == digest:
                return int(latest[0])
            revision = 1 if latest is None else int(latest[0]) + 1
            conn.execute(
                "INSERT INTO knowledge_revisions (item_id, revision, recorded_at, writer, content_sha256, "
                "claim, conditions, topic_tags_json, staleness_horizon_days, ingest, url, source_class, "
                "date_published, date_accessed, author_or_org, model_names_json, metric) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(item.item_id),
                    revision,
                    recorded_at,
                    self._writer.value,
                    digest,
                    item.claim,
                    item.conditions,
                    json.dumps(list(item.topic_tags), ensure_ascii=False),
                    item.staleness_horizon_days,
                    item.ingest.value,
                    prov.url,
                    prov.source_class,
                    prov.date_published,
                    prov.date_accessed,
                    prov.author_or_org,
                    json.dumps(list(keys.model_names), ensure_ascii=False),
                    keys.metric,
                ),
            )
            return revision

    def history(self, item_id: ItemId, *, as_of: date) -> list[StoredItem]:
        """Every revision of ``item_id``, oldest first, with ``stale`` computed from the passed ``as_of``."""
        rows = self._select(
            "SELECT * FROM knowledge_revisions WHERE item_id = ? ORDER BY revision ASC", (str(item_id),)
        )
        return [_rebuild(r, as_of) for r in rows]

    def _latest(self) -> list[StoredItem]:
        rows = self._select("SELECT * FROM knowledge_latest ORDER BY item_id ASC")
        return [_rebuild(r, None) for r in rows]

    def _select(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        try:
            with closing(self._connect()) as conn:
                return conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise KnowledgeStoreError(f"cannot read knowledge store {self._path}: {exc}") from exc

    def _recorded_at(self) -> str:
        moment = self._now()
        if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
            raise KnowledgeStoreError("the store clock must return a timezone-aware datetime")
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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


def _as_protocol(store: SqliteKnowledgeStore) -> KnowledgeStore:
    """Static proof (mypy) that the store implements the ``KnowledgeStore`` Protocol."""
    return store


def _content_hash(item: KnowledgeItem, keys: RetrievalKeys) -> str:
    """SHA-256 of the canonical JSON of the item and keys; not ``recorded_at``, ``writer`` or ``revision``."""
    prov = item.provenance
    payload = {
        "item_id": str(item.item_id),
        "claim": item.claim,
        "conditions": item.conditions,
        "topic_tags": list(item.topic_tags),
        "staleness_horizon_days": item.staleness_horizon_days,
        "ingest": item.ingest.value,
        "url": prov.url,
        "source_class": prov.source_class,
        "date_published": prov.date_published,
        "date_accessed": prov.date_accessed,
        "author_or_org": prov.author_or_org,
        "model_names": list(keys.model_names),
        "metric": keys.metric,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _string_list(raw: Any, what: str) -> tuple[str, ...]:
    value = json.loads(raw)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{what} must be a JSON array of strings")
    return tuple(value)


def _rebuild(row: tuple[Any, ...], as_of: date | None) -> StoredItem:
    """Rebuild a row through the typed constructors; any failure names the row's ``revision_id``."""
    revision_id = row[0] if row else None
    try:
        if len(row) != len(_REVISION_COLUMNS):
            raise ValueError(f"expected {len(_REVISION_COLUMNS)} columns, got {len(row)}")
        (_, item_id, revision, recorded_at, writer, _digest, claim, conditions, tags_json, horizon,
         ingest, url, source_class, published, accessed, author, names_json, metric) = row
        item = KnowledgeItem(
            item_id=ItemId(item_id),
            claim=claim,
            conditions=conditions,
            provenance=Provenance(
                url=url,
                source_class=source_class,
                date_published=published,
                date_accessed=accessed,
                author_or_org=author,
            ),
            topic_tags=_string_list(tags_json, "topic_tags_json"),
            staleness_horizon_days=horizon,
            ingest=IngestPath(ingest),
        )
        names = _string_list(names_json, "model_names_json")
        keys = RetrievalKeys(model_names=names, metric=metric)
        if keys.model_names != names or keys.metric != metric:
            raise ValueError("stored retrieval keys are not normalised")
        if not isinstance(revision, int) or not isinstance(recorded_at, str):
            raise ValueError("revision or recorded_at has the wrong type")
        return StoredItem(
            item=item,
            keys=keys,
            revision=revision,
            recorded_at=recorded_at,
            writer=KnowledgeWriter(writer),
            stale=as_of is not None and item.is_stale(as_of),
        )
    except (ValueError, TypeError) as exc:  # JSONDecodeError is a ValueError
        raise KnowledgeStoreError(f"bad knowledge row revision_id={revision_id}: {exc}") from exc


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
