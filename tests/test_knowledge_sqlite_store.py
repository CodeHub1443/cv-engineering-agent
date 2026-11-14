"""ADR-0024 slices K1a/K1b: the durable SQLite KnowledgeStore.

K1a covers the lifecycle (criteria 4, 5 lifecycle part, 10); K1b the records (criteria 1, 2, 3, 5 bad
row, 8 store part) plus lock-wait and racing writers, ADR-0024 §7.1. Every test uses ``tmp_path`` only
(never the real state root), no network, no ``.env``; connections are closed before teardown (Q53).
"""

from __future__ import annotations

import ast
import sqlite3
import threading
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

import cv_agent
from cv_agent.knowledge import models as knowledge_models
from cv_agent.knowledge import sqlite_store
from cv_agent.knowledge import store as knowledge_store
from cv_agent.knowledge.models import IngestPath, ItemId, KnowledgeItem, Provenance
from cv_agent.knowledge.sqlite_store import SCHEMA_VERSION, SqliteKnowledgeStore
from cv_agent.knowledge.store import (
    KNOWLEDGE_FILENAME,
    InMemoryKnowledgeStore,
    KnowledgeStore,
    KnowledgeStoreError,
    KnowledgeWriter,
    RetrievalKeys,
    StoredItem,
    normalise_key,
)

EXPECTED_COLUMNS = (
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


def _store_path(tmp_path: Path) -> Path:
    return tmp_path / "state" / KNOWLEDGE_FILENAME


def _fresh(tmp_path: Path) -> Path:
    path = _store_path(tmp_path)
    SqliteKnowledgeStore.initialise(path)
    return path


def _dump(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as conn:
        return list(conn.iterdump())


def _exec(path: Path, sql: str) -> None:
    with closing(sqlite3.connect(path, isolation_level=None)) as conn:
        conn.execute(sql)


# --- init / open -------------------------------------------------------------------------------


def test_filename_is_knowledge_sqlite() -> None:
    assert KNOWLEDGE_FILENAME == "knowledge.sqlite"


def test_missing_store_refuses_with_init_hint_and_creates_nothing(tmp_path: Path) -> None:
    path = _store_path(tmp_path)
    with pytest.raises(KnowledgeStoreError, match="cv-agent knowledge init"):
        SqliteKnowledgeStore(path, writer=KnowledgeWriter.RESEARCH_CLI)
    assert not path.exists()
    assert not path.parent.exists()


def test_migrate_on_missing_store_refuses_with_init_hint_and_creates_nothing(tmp_path: Path) -> None:
    path = _store_path(tmp_path)
    with pytest.raises(KnowledgeStoreError, match="cv-agent knowledge init"):
        SqliteKnowledgeStore.migrate(path)
    assert not path.exists()


def test_initialise_creates_schema_v1_and_store_opens(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    store = SqliteKnowledgeStore(path, writer=KnowledgeWriter.RESEARCH_CLI)
    assert store.path == path
    with closing(sqlite3.connect(path)) as conn:
        version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        columns = tuple(r[1] for r in conn.execute("PRAGMA table_info(knowledge_revisions)"))
        view = conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'").fetchall()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert version == (SCHEMA_VERSION,) and SCHEMA_VERSION == "1"
    assert columns == EXPECTED_COLUMNS
    assert view == [("knowledge_latest",)]
    assert mode == "delete"  # rollback journal, no WAL


def test_initialise_refuses_existing_store_and_leaves_it_untouched(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    before = path.read_bytes()
    with pytest.raises(KnowledgeStoreError, match="already exists"):
        SqliteKnowledgeStore.initialise(path)
    assert path.read_bytes() == before


def test_initialise_refuses_an_arbitrary_existing_file(tmp_path: Path) -> None:
    path = _store_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a database")
    with pytest.raises(KnowledgeStoreError):
        SqliteKnowledgeStore.initialise(path)
    assert path.read_bytes() == b"not a database"


def test_initialise_failure_mid_schema_leaves_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlite_store, "_SCHEMA", (*sqlite_store._SCHEMA, "THIS IS NOT SQL"))
    path = _store_path(tmp_path)
    with pytest.raises(KnowledgeStoreError):
        SqliteKnowledgeStore.initialise(path)
    assert not path.exists()  # connection closed before unlink, so Windows lets go of the file


def test_constructor_argument_checks(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    with pytest.raises(ValueError):
        SqliteKnowledgeStore(path, writer=KnowledgeWriter.RESEARCH_CLI, busy_timeout_s=-1)
    with pytest.raises(TypeError):
        SqliteKnowledgeStore(path, writer="research_cli")  # type: ignore[arg-type]


# --- fail closed -------------------------------------------------------------------------------


def _break_version(path: Path) -> None:
    _exec(path, "UPDATE meta SET value = '99' WHERE key = 'schema_version'")


def _delete_version(path: Path) -> None:
    _exec(path, "DELETE FROM meta")


def _drop_table(path: Path) -> None:
    _exec(path, "DROP VIEW knowledge_latest")
    _exec(path, "DROP TABLE knowledge_revisions")


def _drop_view(path: Path) -> None:
    _exec(path, "DROP VIEW knowledge_latest")


def _add_column(path: Path) -> None:
    _exec(path, "ALTER TABLE knowledge_revisions ADD COLUMN extra TEXT")


@pytest.mark.parametrize("damage", [_break_version, _delete_version, _drop_table, _drop_view, _add_column])
def test_damaged_store_is_refused_without_guessing(tmp_path: Path, damage) -> None:  # type: ignore[no-untyped-def]
    path = _fresh(tmp_path)
    damage(path)
    before = path.read_bytes()
    with pytest.raises(KnowledgeStoreError) as opened:
        SqliteKnowledgeStore(path, writer=KnowledgeWriter.RESEARCH_CLI)
    with pytest.raises(KnowledgeStoreError):
        SqliteKnowledgeStore.migrate(path)
    assert "migrate" not in str(opened.value)  # a foreign shape is never offered a migration
    assert path.read_bytes() == before


def test_non_sqlite_file_is_refused(tmp_path: Path) -> None:
    path = _store_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is not an sqlite database at all" * 10)
    before = path.read_bytes()
    with pytest.raises(KnowledgeStoreError, match="corrupt or unreadable"):
        SqliteKnowledgeStore(path, writer=KnowledgeWriter.RESEARCH_CLI)
    with pytest.raises(KnowledgeStoreError):
        SqliteKnowledgeStore.migrate(path)
    assert path.read_bytes() == before


# --- migrate -----------------------------------------------------------------------------------


def test_migrate_on_current_store_is_idempotent(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    before = _dump(path)
    SqliteKnowledgeStore.migrate(path)
    SqliteKnowledgeStore.migrate(path)
    assert _dump(path) == before
    SqliteKnowledgeStore(path, writer=KnowledgeWriter.RESEARCH_CLI)  # still opens


# --- source-level and structural rules ---------------------------------------------------------

_FORBIDDEN_SQL = ("UPDATE", "DELETE", "REPLACE", "JOURNAL_MODE")
_EXECUTE_NAMES = {"execute", "executemany"}


def _sql_strings(source: str) -> list[str]:
    """SQL statement strings only: ``_SCHEMA`` entries and string arguments of execute/executemany.

    Docstrings and comments are never collected, so prose cannot trip the scan.
    """
    tree = ast.parse(source)
    found: list[str] = []

    def strings_in(node: ast.AST) -> list[str]:
        return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_SCHEMA" for t in node.targets):
            found.extend(strings_in(node.value))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _EXECUTE_NAMES
        ):
            for arg in node.args[:1]:
                found.extend(strings_in(arg))
    return found


def _violations(source: str) -> list[str]:
    bad = [s for s in _sql_strings(source) if any(word in s.upper() for word in _FORBIDDEN_SQL)]
    tree = ast.parse(source)
    if any(isinstance(n, ast.Attribute) and n.attr == "executescript" for n in ast.walk(tree)):
        bad.append("executescript")
    return bad


def test_detector_catches_a_planted_update() -> None:
    planted = 'def f(conn):\n    """UPDATE in prose is fine."""\n    conn.execute("UPDATE meta SET value = 1")\n'
    assert _violations(planted) == ["UPDATE meta SET value = 1"]
    assert _violations('def f(conn):\n    conn.execute("PRAGMA journal_mode=WAL")\n') != []
    assert _violations('def f(conn):\n    conn.executescript("SELECT 1")\n') == ["executescript"]
    assert _violations('"""UPDATE and DELETE, in a docstring."""\n# UPDATE comment\n') == []


def test_module_contains_no_update_or_delete_statement() -> None:
    source = Path(sqlite_store.__file__).read_text(encoding="utf-8")
    assert _sql_strings(source), "scanner found no SQL at all; it is broken"
    assert _violations(source) == []


def test_knowledge_package_does_not_import_experiments() -> None:
    root = Path(cv_agent.__file__).parent / "knowledge"
    for py_file in root.rglob("*.py"):
        for node in ast.walk(ast.parse(py_file.read_text(encoding="utf-8"))):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                assert not name.startswith("cv_agent.experiments"), f"{py_file.name} imports {name}"


# === K1b: records ================================================================================

_NOW = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)
_THREADS = 8
_JOIN_S = 60.0


def _item(
    item_id: str = "research-aaa",
    claim: str = "YOLO11n reaches 39.5 mAP on COCO.",
    *,
    conditions: str | None = "640px, FP16",
    tags: tuple[str, ...] = ("detection", "edge"),
    horizon: int = 90,
    ingest: IngestPath = IngestPath.WEB_FETCH,
    accessed: str = "2026-11-01",
    source_class: Any = "official_documentation",
) -> KnowledgeItem:
    return KnowledgeItem(
        item_id=ItemId(item_id),
        claim=claim,
        conditions=conditions,
        provenance=Provenance(
            url="https://docs.example.org/yolo11",
            source_class=source_class,
            date_published="2026-01-05",
            date_accessed=accessed,
            author_or_org="Example Org",
        ),
        topic_tags=tags,
        staleness_horizon_days=horizon,
        ingest=ingest,
    )


def _open(path: Path, **kw: Any) -> SqliteKnowledgeStore:
    kw.setdefault("now", lambda: _NOW)
    return SqliteKnowledgeStore(path, writer=KnowledgeWriter.RESEARCH_CLI, **kw)


def _rows(path: Path) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT * FROM knowledge_revisions ORDER BY revision_id").fetchall()


def _poke(path: Path, revision_id: int, column: str, value: Any) -> None:
    with closing(sqlite3.connect(path, isolation_level=None)) as conn:
        conn.execute(f"UPDATE knowledge_revisions SET {column} = ? WHERE revision_id = ?", (value, revision_id))


# --- keys --------------------------------------------------------------------------------------


def test_normalise_key_strips_and_lowers_and_rejects_non_tokens() -> None:
    assert normalise_key(" YOLO11n ") == "yolo11n"
    assert normalise_key("mAP50-95") == "map50-95"
    for bad in ("", "  ", "yolo 11n", "-yolo", "a" * 65):
        with pytest.raises(ValueError):
            normalise_key(bad)


def test_retrieval_keys_normalise_and_dedupe_in_first_occurrence_order() -> None:
    keys = RetrievalKeys(model_names=("YOLO11n", " rtdetr-r50 ", "yolo11N"), metric="mAP50-95")
    assert keys.model_names == ("yolo11n", "rtdetr-r50")
    assert keys.metric == "map50-95"
    assert RetrievalKeys() == RetrievalKeys(model_names=(), metric=None)


@pytest.mark.parametrize("name", ["yolo 11n", ""])
def test_retrieval_keys_reject_non_tokens(name: str) -> None:
    with pytest.raises(ValueError):
        RetrievalKeys(model_names=(name,))
    with pytest.raises(ValueError):
        RetrievalKeys(metric=name)


# --- criterion 1: round-trip -------------------------------------------------------------------


@pytest.mark.parametrize("ingest", list(IngestPath))
def test_every_field_round_trips_through_put_get_and_history(tmp_path: Path, ingest: IngestPath) -> None:
    store = _open(_fresh(tmp_path))
    item = _item(ingest=ingest, tags=("zeta", "alpha", "mid"))
    keys = RetrievalKeys(model_names=("YOLO11n", "rtdetr-r50"), metric="mAP50-95")
    store.put(item, keys=keys)
    got = store.get(item.item_id)
    assert got == item
    assert got is not None and got.topic_tags == ("zeta", "alpha", "mid")
    assert got.evidence_weight() == item.evidence_weight()
    (stored,) = store.history(item.item_id, as_of=date(2026, 11, 14))
    assert isinstance(stored, StoredItem)
    assert stored.item == item
    assert stored.keys == keys
    assert stored.revision == 1
    assert stored.recorded_at == "2026-11-14T12:00:00Z"
    assert stored.writer is KnowledgeWriter.RESEARCH_CLI


def test_conditions_none_and_missing_item(tmp_path: Path) -> None:
    store = _open(_fresh(tmp_path))
    store.put(_item(conditions=None))
    got = store.get(ItemId("research-aaa"))
    assert got is not None and got.conditions is None
    assert store.get(ItemId("nope")) is None


def test_naive_clock_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    store = _open(path, now=lambda: datetime(2026, 11, 14, 12, 0, 0))
    with pytest.raises(KnowledgeStoreError, match="timezone"):
        store.put(_item())
    assert _rows(path) == []


def test_non_utc_clock_is_recorded_as_utc_seconds(tmp_path: Path) -> None:
    plus6 = timezone(timedelta(hours=6))
    store = _open(_fresh(tmp_path), now=lambda: datetime(2026, 11, 14, 2, 0, 0, 999, tzinfo=plus6))
    store.put(_item())
    (stored,) = store.history(ItemId("research-aaa"), as_of=date(2026, 11, 14))
    assert stored.recorded_at == "2026-11-13T20:00:00Z"


# --- criterion 2: revision history -------------------------------------------------------------


def test_three_changed_puts_give_revisions_1_2_3(tmp_path: Path) -> None:
    store = _open(_fresh(tmp_path))
    assert [store.record(_item(claim=f"claim {n}")) for n in (1, 2, 3)] == [1, 2, 3]
    history = store.history(ItemId("research-aaa"), as_of=date(2026, 11, 14))
    assert [h.revision for h in history] == [1, 2, 3]
    assert [h.item.claim for h in history] == ["claim 1", "claim 2", "claim 3"]


def test_identical_reput_adds_no_row_and_record_returns_same_revision(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    store = _open(path)
    assert store.record(_item()) == 1
    assert store.record(_item()) == 1
    store.put(_item())
    assert _open(path).record(_item()) == 1  # a second store instance agrees
    assert len(_rows(path)) == 1


def test_earlier_rows_are_never_updated(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    store = _open(path)
    store.record(_item(claim="one"))
    before = _rows(path)
    store.record(_item(claim="two"))
    after = _rows(path)
    assert len(after) == 2
    assert after[:1] == before


def test_a_key_only_change_adds_a_revision(tmp_path: Path) -> None:
    store = _open(_fresh(tmp_path))
    assert store.record(_item(), keys=RetrievalKeys(model_names=("yolo11n",))) == 1
    assert store.record(_item(), keys=RetrievalKeys(model_names=("yolo11n",))) == 1
    assert store.record(_item(), keys=RetrievalKeys(model_names=("yolo11n",), metric="map")) == 2
    assert store.record(_item(), keys=RetrievalKeys(model_names=("YOLO11N",), metric="MAP")) == 2


def test_record_validates_argument_types(tmp_path: Path) -> None:
    store = _open(_fresh(tmp_path))
    with pytest.raises(TypeError):
        store.record("not an item")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        store.record(_item(), keys=("yolo11n",))  # type: ignore[arg-type]


# --- criterion 3: latest view ------------------------------------------------------------------


def test_get_list_and_query_return_only_the_newest_revision_in_item_id_order(tmp_path: Path) -> None:
    store = _open(_fresh(tmp_path))
    store.put(_item("b-item", claim="b old"))
    store.put(_item("a-item", claim="a only"))
    store.put(_item("b-item", claim="b new"))
    assert [i.claim for i in store.list_items()] == ["a only", "b new"]
    assert [i.claim for i in store.query()] == ["a only", "b new"]
    got = store.get(ItemId("b-item"))
    assert got is not None and got.claim == "b new"


def test_query_filters_match_the_in_memory_store_as_sets(tmp_path: Path) -> None:
    sql = _open(_fresh(tmp_path))
    mem = InMemoryKnowledgeStore()
    items = [
        _item("i1", tags=("detection",), source_class="official_documentation", accessed="2026-11-01", horizon=10),
        _item("i2", tags=("detection", "edge"), source_class="engineering_blog", accessed="2026-06-01", horizon=10),
        _item("i3", tags=("edge",), source_class="engineering_blog", accessed="2026-11-10", horizon=10),
    ]
    for it in items:
        sql.put(it)
        mem.put(it)
    cases: list[dict[str, Any]] = [
        {},
        {"topic_tags": ["detection"]},
        {"topic_tags": ["detection", "edge"]},
        {"source_class": "engineering_blog"},
        {"exclude_stale_as_of": date(2026, 11, 12)},
        {"topic_tags": ["edge"], "source_class": "engineering_blog", "exclude_stale_as_of": date(2026, 11, 12)},
    ]
    for kw in cases:
        assert set(sql.query(**kw)) == set(mem.query(**kw)), kw


def test_sqlite_store_satisfies_the_knowledge_store_protocol(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    store: KnowledgeStore = sqlite_store._as_protocol(_open(path))  # mypy checks the conformance
    store.put(_item())
    assert [i.item_id for i in store.list_items()] == ["research-aaa"]


# --- criterion 5: a bad row fails closed, naming its revision_id -------------------------------

_BAD_ROWS = [
    ("source_class", "bogus_class"),
    ("ingest", "bogus_ingest"),
    ("writer", "bogus_writer"),
    ("date_accessed", "11/01/2026"),
    ("topic_tags_json", "not json"),
    ("topic_tags_json", "[]"),
    ("topic_tags_json", '{"a": 1}'),
    ("model_names_json", '["YOLO11n"]'),  # un-normalised key (D-107)
    ("model_names_json", '["a", "a"]'),  # not de-duplicated
    ("model_names_json", '"yolo11n"'),
    ("metric", "MAP"),  # un-normalised key (D-107)
    ("claim", "   "),
]


@pytest.mark.parametrize(("column", "value"), _BAD_ROWS)
def test_a_bad_row_raises_naming_its_revision_id_on_every_read(tmp_path: Path, column: str, value: str) -> None:
    path = _fresh(tmp_path)
    store = _open(path)
    store.put(_item("a-good", claim="good"))
    store.put(_item("b-bad", claim="bad"))
    (bad_id,) = [r[0] for r in _rows(path) if r[1] == "b-bad"]
    _poke(path, bad_id, column, value)
    needle = f"revision_id={bad_id}"
    with pytest.raises(KnowledgeStoreError, match=needle):
        store.get(ItemId("b-bad"))
    with pytest.raises(KnowledgeStoreError, match=needle):
        store.list_items()
    with pytest.raises(KnowledgeStoreError, match=needle):
        store.query()
    with pytest.raises(KnowledgeStoreError, match=needle):
        store.history(ItemId("b-bad"), as_of=date(2026, 11, 14))


# --- criterion 8 (store part): staleness from a passed as_of, never from a clock --------------


def test_staleness_boundary_is_strict_and_stale_items_are_flagged_not_deleted(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    store = _open(path)
    store.put(_item(accessed="2026-11-01", horizon=10))
    (fresh,) = store.history(ItemId("research-aaa"), as_of=date(2026, 11, 11))
    (stale,) = store.history(ItemId("research-aaa"), as_of=date(2026, 11, 12))
    assert (fresh.stale, stale.stale) == (False, True)
    assert len(store.query(exclude_stale_as_of=date(2026, 11, 11))) == 1
    assert store.query(exclude_stale_as_of=date(2026, 11, 12)) == []
    assert len(store.query()) == 1 and len(_rows(path)) == 1


class _PoisonedDatetime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> Any:  # type: ignore[override]
        raise AssertionError("the store read a clock")

    @classmethod
    def utcnow(cls) -> Any:
        raise AssertionError("the store read a clock")

    @classmethod
    def today(cls) -> Any:
        raise AssertionError("the store read a clock")


class _PoisonedDate(date):
    @classmethod
    def today(cls) -> Any:
        raise AssertionError("the store read a clock")


def test_reads_and_staleness_never_touch_a_clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _fresh(tmp_path)
    _open(path).put(_item(accessed="2026-11-01", horizon=10), keys=RetrievalKeys(model_names=("yolo11n",)))

    def no_clock() -> datetime:
        raise AssertionError("the injected clock was read")

    store = _open(path, now=no_clock)
    for module in (sqlite_store, knowledge_store, knowledge_models):
        if hasattr(module, "datetime"):
            monkeypatch.setattr(module, "datetime", _PoisonedDatetime)
        if hasattr(module, "date"):
            monkeypatch.setattr(module, "date", _PoisonedDate)
    as_of = date(2026, 11, 12)
    assert store.get(ItemId("research-aaa")) is not None
    assert len(store.list_items()) == 1
    assert store.query(exclude_stale_as_of=as_of) == []
    (stored,) = store.history(ItemId("research-aaa"), as_of=as_of)
    assert stored.stale is True
    with pytest.raises(AssertionError, match="injected clock"):
        store.put(_item(claim="changed"))  # only a write may read the injected clock


# --- concurrency: lock-wait and racing writers (events and barriers; no elapsed-time asserts) --


def _run_threads(workers: list[Callable[[], None]]) -> list[BaseException]:
    errors: list[BaseException] = []

    def wrap(fn: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001 - reported to the test
                errors.append(exc)

        return run

    threads = [threading.Thread(target=wrap(w), daemon=True) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=_JOIN_S)
    assert not any(t.is_alive() for t in threads), "a writer thread did not finish"
    return errors


def test_concurrency_a_held_write_lock_makes_a_short_timeout_fail_closed(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    blocker = sqlite3.connect(path, isolation_level=None)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        store = _open(path, busy_timeout_s=0.05)
        with pytest.raises(KnowledgeStoreError):
            store.put(_item())
        blocker.execute("ROLLBACK")
    finally:
        blocker.close()
    assert _rows(path) == []
    assert _open(path).record(_item()) == 1  # usable again once the lock is gone


def test_concurrency_a_writer_waits_for_the_lock_and_then_succeeds(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    blocker = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    blocker.execute("BEGIN IMMEDIATE")
    started = threading.Event()
    results: list[int] = []

    def writer() -> None:
        store = _open(path, busy_timeout_s=_JOIN_S)
        started.set()
        results.append(store.record(_item()))

    def releaser() -> None:
        assert started.wait(timeout=_JOIN_S)
        threading.Event().wait(0.3)  # lets the writer reach the lock; correctness never depends on it
        blocker.execute("ROLLBACK")

    try:
        errors = _run_threads([writer, releaser])
    finally:
        blocker.close()
    assert errors == []
    assert results == [1]
    assert len(_rows(path)) == 1


def test_concurrency_racing_writers_of_distinct_content_get_gapless_unique_revisions(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    barrier = threading.Barrier(_THREADS, timeout=_JOIN_S)
    revisions: list[int] = []

    def make(n: int) -> Callable[[], None]:
        def run() -> None:
            store = _open(path, busy_timeout_s=_JOIN_S)
            barrier.wait()
            revisions.append(store.record(_item(claim=f"claim {n}")))

        return run

    assert _run_threads([make(n) for n in range(_THREADS)]) == []
    assert sorted(revisions) == list(range(1, _THREADS + 1))
    assert sorted(r[2] for r in _rows(path)) == list(range(1, _THREADS + 1))


def test_concurrency_racing_writers_of_identical_content_write_exactly_one_row(tmp_path: Path) -> None:
    path = _fresh(tmp_path)
    barrier = threading.Barrier(_THREADS, timeout=_JOIN_S)
    revisions: list[int] = []

    def run() -> None:
        store = _open(path, busy_timeout_s=_JOIN_S)
        barrier.wait()
        revisions.append(store.record(_item()))

    assert _run_threads([run for _ in range(_THREADS)]) == []
    assert revisions == [1] * _THREADS
    assert len(_rows(path)) == 1
