"""
cv_agent.llm.sqlite_store — the gateway's append-only call log.

Responsibility: persist one ``CallRecord`` per governed provider call in a SQLite file and
fail closed when that file is missing, corrupt, of a foreign schema version or busy
(ADR-0020 §3 item 5(6) and §5.1, D-092, Q42). This is the ONLY module in ``cv_agent/llm/``
allowed to import ``sqlite3`` (``tests/test_llm_structure.py`` enforces it).

Rules:
- The file is created only by ``LLMCallStore.initialise`` (``cv-agent llm-log init``). The
  constructor and ``append`` open it with ``mode=rw`` and never create it.
- Each append is one short transaction: ``BEGIN IMMEDIATE`` with a busy timeout, so two
  processes serialise instead of failing or losing a row.
- Tables: ``llm_calls`` and ``meta`` (``schema_version``). No budget table yet; G3 adds it
  with a schema bump.
- The log holds no key and no thinking text; prompt and response text only when the caller
  passes it in (``[llm.log] store_text``, off by default).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import astuple, dataclass, fields
from pathlib import Path
from typing import Optional

from cv_agent.llm.errors import LLMStoreError

SCHEMA_VERSION = "1"
LLM_CALLS_FILENAME = "llm_calls.sqlite"
INIT_HINT = "run `cv-agent llm-log init` to create it"

_SCHEMA = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE llm_calls (
    call_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    task_class TEXT NOT NULL,
    tier TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    adapter_version TEXT,
    sdk_version TEXT,
    local_model_digest TEXT,
    local_quantization TEXT,
    max_tokens INTEGER,
    thinking TEXT,
    effort TEXT,
    prompt_sha256 TEXT NOT NULL,
    response_sha256 TEXT,
    request_id TEXT,
    input_tokens INTEGER NOT NULL,
    cache_creation_input_tokens INTEGER NOT NULL,
    cache_read_input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    thinking_tokens INTEGER NOT NULL,
    stop_reason TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    prompt_text TEXT,
    response_text TEXT
)""",
)


@dataclass(frozen=True)
class CallRecord:
    """One governed call: the D4 fields plus the provider ``request_id`` (ADR-0020 §5.1).

    Field order is the column order. ``max_tokens`` is None while no tier supplies a default
    (before G5); ``response_sha256`` is None when no answer came back; ``prompt_text`` and
    ``response_text`` are None unless text storage is switched on.
    """

    call_id: str
    ts_utc: str
    task_class: str
    tier: str
    provider: str
    model: str
    adapter_version: Optional[str]
    sdk_version: Optional[str]
    local_model_digest: Optional[str]
    local_quantization: Optional[str]
    max_tokens: Optional[int]
    thinking: Optional[str]
    effort: Optional[str]
    prompt_sha256: str
    response_sha256: Optional[str]
    request_id: Optional[str]
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int
    thinking_tokens: int
    stop_reason: str
    latency_ms: int
    prompt_text: Optional[str] = None
    response_text: Optional[str] = None


_COLUMNS = tuple(f.name for f in fields(CallRecord))
_INSERT = f"INSERT INTO llm_calls ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})"


class LLMCallStore:
    """Append-only SQLite call log. Raises ``LLMStoreError`` on every failure (fail closed)."""

    def __init__(self, path: Path, *, busy_timeout_s: float = 5.0) -> None:
        if busy_timeout_s < 0:
            raise ValueError("busy_timeout_s must not be negative")
        self._path = Path(path)
        self._busy_timeout_s = busy_timeout_s
        if not self._path.is_file():
            raise LLMStoreError(f"LLM call log {self._path} does not exist; {INIT_HINT}.")
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
            raise LLMStoreError(f"LLM call log {target} already exists; refusing to touch it.") from None
        except OSError as exc:
            raise LLMStoreError(f"cannot create LLM call log {target}: {exc}") from exc
        try:
            conn = sqlite3.connect(target, isolation_level=None)
            with closing(conn):
                conn.execute("BEGIN IMMEDIATE")
                for statement in _SCHEMA:  # not executescript: it would commit first
                    conn.execute(statement)
                conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
                conn.execute("COMMIT")
        except sqlite3.Error as exc:
            target.unlink(missing_ok=True)  # never leave a half-initialised store behind
            raise LLMStoreError(f"cannot initialise LLM call log {target}: {exc}") from exc

    def append(self, record: CallRecord) -> None:
        """Insert one row in its own ``BEGIN IMMEDIATE`` transaction."""
        try:
            with closing(self._connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute(_INSERT, astuple(record))
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
        except sqlite3.Error as exc:
            raise LLMStoreError(f"cannot write to LLM call log {self._path}: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        # mode=rw: open an existing file only, so a deleted store is an error, not a new empty one.
        uri = self._path.resolve().as_uri() + "?mode=rw"
        return sqlite3.connect(uri, uri=True, timeout=self._busy_timeout_s, isolation_level=None)

    def _verify(self) -> None:
        try:
            with closing(self._connect()) as conn:
                row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
                columns = tuple(r[1] for r in conn.execute("PRAGMA table_info(llm_calls)"))
        except sqlite3.Error as exc:
            raise LLMStoreError(f"LLM call log {self._path} is corrupt or unreadable: {exc}") from exc
        if row is None or row[0] != SCHEMA_VERSION:
            found = None if row is None else row[0]
            raise LLMStoreError(
                f"LLM call log {self._path} has schema version {found!r}; expected {SCHEMA_VERSION!r}."
            )
        if columns != _COLUMNS:
            raise LLMStoreError(f"LLM call log {self._path} has an unexpected llm_calls schema.")
