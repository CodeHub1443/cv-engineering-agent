"""ADR-0024 slice K1a: lifecycle of the durable SQLite KnowledgeStore.

Covers criteria 4, 5 (lifecycle part) and 10 of ADR-0024 §7.1. Every test uses ``tmp_path`` only
(never the real state root), no network, no ``.env``; connections are closed before teardown (Q53).
"""

from __future__ import annotations

import ast
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import cv_agent
from cv_agent.knowledge import sqlite_store
from cv_agent.knowledge.sqlite_store import SCHEMA_VERSION, SqliteKnowledgeStore
from cv_agent.knowledge.store import KNOWLEDGE_FILENAME, KnowledgeStoreError, KnowledgeWriter

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
