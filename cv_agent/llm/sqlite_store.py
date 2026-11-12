"""
cv_agent.llm.sqlite_store — the gateway's call log and daily budget books.

Responsibility: persist one ``CallRecord`` per governed provider call, and the reserve/settle
ledger behind the daily USD ceiling and call limit, in one SQLite file; fail closed when that
file is missing, corrupt, of a foreign schema version or busy (ADR-0020 §3 items 5(6) and 6,
§5.1, D-092, Q42). This is the ONLY module in ``cv_agent/llm/`` allowed to import ``sqlite3``
(``tests/test_llm_structure.py`` enforces it).

Rules:
- The file is created only by ``LLMCallStore.initialise`` (``cv-agent llm-log init``). The
  constructor and every other method open it with ``mode=rw`` and never create it.
- Every step (append, reserve, settle, release) is one short transaction: ``BEGIN IMMEDIATE``
  with a busy timeout, so two processes serialise instead of failing or losing a row. The
  clock, ceiling and call-limit checks and the reservation insert share one transaction, so
  two processes cannot both pass the ceiling.
- Tables: ``llm_calls``, ``llm_budget`` (one row per reserved call; ``spent_usd`` is the
  reservation until settle replaces it with the actual cost) and ``meta`` (``schema_version``).
  Schema version 2 (G3). A version-1 store is refused, never migrated: re-initialise it.
- The log holds no key and no thinking text; prompt and response text only when the caller
  passes it in (``[llm.log] store_text``, off by default).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from dataclasses import astuple, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from cv_agent.llm.errors import (
    LLMBudgetExceededError,
    LLMCallLimitError,
    LLMClockSkewError,
    LLMStoreError,
)

SCHEMA_VERSION = "2"
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
    """CREATE TABLE llm_budget (
    call_id TEXT PRIMARY KEY,
    day_key TEXT NOT NULL,
    ts_utc TEXT NOT NULL,
    reserved_usd REAL NOT NULL,
    spent_usd REAL NOT NULL,
    settled INTEGER NOT NULL,
    prices_as_of TEXT NOT NULL
)""",
    "CREATE INDEX llm_budget_day ON llm_budget (day_key)",
)
_BUDGET_COLUMNS = ("call_id", "day_key", "ts_utc", "reserved_usd", "spent_usd", "settled", "prices_as_of")


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


@dataclass(frozen=True)
class Reservation:
    """A worst-case amount held against the day's ceiling until ``settle`` or ``release``."""

    call_id: str
    day_key: str
    reserved_usd: float


def _utc_text(moment: datetime) -> str:
    """Fixed-width UTC text, so SQL ``MAX`` and string order agree with time order."""
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


_COLUMNS = tuple(f.name for f in fields(CallRecord))
_INSERT = f"INSERT INTO llm_calls ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})"
_DAY_TOTALS = "SELECT COALESCE(SUM(spent_usd), 0.0), COUNT(*) FROM llm_budget WHERE day_key = ?"


class LLMCallStore:
    """SQLite call log and budget books. Raises ``LLMStoreError`` on every failure (fail closed)."""

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
        """Insert one call row in its own transaction."""
        with self._txn() as conn:
            conn.execute(_INSERT, astuple(record))

    def reserve(
        self,
        *,
        call_id: str,
        now_utc: datetime,
        day_key: str,
        worst_usd: float,
        ceiling_usd: float,
        call_limit: int,
        skew_tolerance_s: float,
        prices_as_of: str,
        resets_at_utc: str,
    ) -> Reservation:
        """Check clock, ceiling and call limit, then book ``worst_usd``; all in one transaction.

        Raises ``LLMClockSkewError``, ``LLMBudgetExceededError`` or ``LLMCallLimitError`` with
        nothing booked, so the caller never reaches the network.
        """
        ts = _utc_text(now_utc)
        with self._txn() as conn:
            latest = conn.execute("SELECT MAX(ts_utc) FROM llm_budget").fetchone()[0]
            if latest is not None:
                behind = (datetime.fromisoformat(latest) - now_utc).total_seconds()
                if behind > skew_tolerance_s:
                    raise LLMClockSkewError(
                        f"clock is {behind:.0f} s behind the last recorded LLM call "
                        f"(tolerance {skew_tolerance_s:.0f} s); refusing to spend."
                    )
            spent, calls = conn.execute(_DAY_TOTALS, (day_key,)).fetchone()
            if spent + worst_usd > ceiling_usd:
                raise LLMBudgetExceededError(
                    day_key=day_key,
                    ceiling_usd=ceiling_usd,
                    spent_usd=spent,
                    call_worst_usd=worst_usd,
                    resets_at_utc=resets_at_utc,
                )
            if calls >= call_limit:
                raise LLMCallLimitError(day_key=day_key, limit=call_limit, resets_at_utc=resets_at_utc)
            conn.execute(
                "INSERT INTO llm_budget (call_id, day_key, ts_utc, reserved_usd, spent_usd, settled, prices_as_of)"
                " VALUES (?, ?, ?, ?, ?, 0, ?)",
                (call_id, day_key, ts, worst_usd, worst_usd, prices_as_of),
            )
        return Reservation(call_id, day_key, worst_usd)

    def settle(self, reservation: Reservation, record: CallRecord, actual_usd: Optional[float]) -> None:
        """Replace the reservation by ``actual_usd`` (None keeps it) and log the call, atomically."""
        spent = reservation.reserved_usd if actual_usd is None else actual_usd
        with self._txn() as conn:
            updated = conn.execute(
                "UPDATE llm_budget SET spent_usd = ?, settled = 1 WHERE call_id = ? AND settled = 0",
                (spent, reservation.call_id),
            ).rowcount
            if updated != 1:
                raise LLMStoreError(f"no open reservation {reservation.call_id} in {self._path}.")
            conn.execute(_INSERT, astuple(record))

    def release(self, reservation: Reservation) -> None:
        """Drop a reservation whose request never left the process."""
        with self._txn() as conn:
            conn.execute("DELETE FROM llm_budget WHERE call_id = ? AND settled = 0", (reservation.call_id,))

    def spent_today(self, day_key: str) -> tuple[float, int]:
        """(USD counted, calls counted) for ``day_key``; open reservations count as spent."""
        try:
            with closing(self._connect()) as conn:
                spent, calls = conn.execute(_DAY_TOTALS, (day_key,)).fetchone()
        except sqlite3.Error as exc:
            raise LLMStoreError(f"cannot read LLM call log {self._path}: {exc}") from exc
        return float(spent), int(calls)

    @contextmanager
    def _txn(self) -> Iterator[sqlite3.Connection]:
        """One ``BEGIN IMMEDIATE`` transaction; any sqlite error becomes ``LLMStoreError``."""
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
                budget_columns = tuple(r[1] for r in conn.execute("PRAGMA table_info(llm_budget)"))
        except sqlite3.Error as exc:
            raise LLMStoreError(f"LLM call log {self._path} is corrupt or unreadable: {exc}") from exc
        if row is None or row[0] != SCHEMA_VERSION:
            found = None if row is None else row[0]
            raise LLMStoreError(
                f"LLM call log {self._path} has schema version {found!r}; expected {SCHEMA_VERSION!r}. "
                "There is no automatic migration: move the old file away, then run "
                "`cv-agent llm-log init` to re-create it."
            )
        if columns != _COLUMNS or budget_columns != _BUDGET_COLUMNS:
            raise LLMStoreError(f"LLM call log {self._path} has an unexpected llm_calls or llm_budget schema.")
