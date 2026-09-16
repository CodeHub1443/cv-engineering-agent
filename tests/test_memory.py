"""
Tests for cv_agent.memory — ProjectUnderstandingRevision, SessionRecord,
ProjectMemoryStore, SqliteProjectMemoryStore.

Every test uses a `tmp_path`-scoped SQLite file. None depend on this
repository's own path, an installed `cv-agent`, or the process's real
current working directory — `default_db_path()` is exercised only with an
explicit `workspace_root=tmp_path`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cv_agent.memory.models import ProjectUnderstandingRevision, SessionRecord
from cv_agent.memory.sqlite_store import SqliteProjectMemoryStore
from cv_agent.memory.store import (
    DEFAULT_DB_FILENAME,
    DEFAULT_MEMORY_DIRNAME,
    ProjectMemoryError,
    ProjectMemoryStore,
    default_db_path,
    open_store,
)


def _revision(
    revision_id: str = "PU-20260101-01",
    session_id: str = "session-1",
    supersedes: str | None = None,
    note: str = "",
) -> ProjectUnderstandingRevision:
    return ProjectUnderstandingRevision(
        revision_id=revision_id,
        created_at="2026-01-01T00:00:00+00:00",
        session_id=session_id,
        requirements_analysis={"original_request": "detect escape attempts", "fields": []},
        supersedes=supersedes,
        note=note,
    )


def _session(
    session_id: str = "session-1",
    status: str = "running",
    ended_at: str | None = None,
    produced_revision_id: str | None = None,
) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        started_at="2026-01-01T00:00:00+00:00",
        ended_at=ended_at,
        status=status,
        produced_revision_id=produced_revision_id,
    )


class TestDefaultDbPath:
    def test_uses_explicit_workspace_root_not_real_cwd(self, tmp_path: Path) -> None:
        path = default_db_path(workspace_root=tmp_path)
        assert path == tmp_path / DEFAULT_MEMORY_DIRNAME / DEFAULT_DB_FILENAME

    def test_default_dirname_and_filename_are_stable(self) -> None:
        # Locked in so a future change is deliberate, not accidental drift.
        assert DEFAULT_MEMORY_DIRNAME == ".cv_agent"
        assert DEFAULT_DB_FILENAME == "memory.sqlite"


class TestInitialization:
    def test_initializes_schema_on_fresh_nested_path(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nested" / "does" / "not" / "exist" / "memory.sqlite"
        with SqliteProjectMemoryStore(db_path) as store:
            assert db_path.is_file()
            assert store.get_current_understanding() is None

    def test_reopening_existing_database_does_not_error(self, tmp_path: Path) -> None:
        db_path = tmp_path / "memory.sqlite"
        with SqliteProjectMemoryStore(db_path):
            pass
        # Second open against the same, now-existing file/schema.
        with SqliteProjectMemoryStore(db_path) as store:
            assert store.list_understanding_revisions() == []

    def test_init_failure_raises_project_memory_error_not_raw_exception(
        self, tmp_path: Path
    ) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        # blocker exists as a *file* — mkdir(parents=True) under it must fail.
        db_path = blocker / "sub" / "memory.sqlite"
        with pytest.raises(ProjectMemoryError):
            SqliteProjectMemoryStore(db_path)

    def test_satisfies_project_memory_store_protocol_surface(self, tmp_path: Path) -> None:
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            for name in (
                "get_current_understanding",
                "append_understanding_revision",
                "list_understanding_revisions",
                "record_session",
                "get_session",
                "list_sessions",
            ):
                assert hasattr(ProjectMemoryStore, name)
                assert callable(getattr(store, name))


class TestEmptyStoreBehavior:
    def test_get_current_understanding_is_none_when_empty(self, tmp_path: Path) -> None:
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            assert store.get_current_understanding() is None

    def test_list_understanding_revisions_is_empty_list(self, tmp_path: Path) -> None:
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            assert store.list_understanding_revisions() == []

    def test_get_session_is_none_for_unknown_id(self, tmp_path: Path) -> None:
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            assert store.get_session("does-not-exist") is None

    def test_list_sessions_is_empty_list(self, tmp_path: Path) -> None:
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            assert store.list_sessions() == []


class TestUnderstandingRevisions:
    def test_append_then_get_current_understanding(self, tmp_path: Path) -> None:
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            revision = _revision()
            store.append_understanding_revision(revision)
            current = store.get_current_understanding()
            assert current == revision

    def test_requirements_analysis_dict_round_trips_exactly(self, tmp_path: Path) -> None:
        nested = {
            "original_request": "prison escape detection",
            "fields": [{"name": "cameras", "status": "unknown", "value": None}],
            "risks": ["low light", "occlusion"],
        }
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            store.append_understanding_revision(
                ProjectUnderstandingRevision(
                    revision_id="PU-1",
                    created_at="2026-01-01T00:00:00+00:00",
                    session_id="s1",
                    requirements_analysis=nested,
                )
            )
            current = store.get_current_understanding()
            assert current is not None
            assert current.requirements_analysis == nested

    def test_current_understanding_is_most_recently_appended(self, tmp_path: Path) -> None:
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            rev1 = _revision(revision_id="PU-1")
            rev2 = _revision(revision_id="PU-2", supersedes="PU-1")
            store.append_understanding_revision(rev1)
            store.append_understanding_revision(rev2)
            current = store.get_current_understanding()
            assert current is not None
            assert current.revision_id == "PU-2"

    def test_revision_history_preserves_every_prior_revision(self, tmp_path: Path) -> None:
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            store.append_understanding_revision(_revision(revision_id="PU-1"))
            store.append_understanding_revision(_revision(revision_id="PU-2", supersedes="PU-1"))
            store.append_understanding_revision(_revision(revision_id="PU-3", supersedes="PU-2"))
            history = store.list_understanding_revisions()
            assert [r.revision_id for r in history] == ["PU-1", "PU-2", "PU-3"]

    def test_revision_ordering_is_insertion_order_not_alphabetical(
        self, tmp_path: Path
    ) -> None:
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            store.append_understanding_revision(_revision(revision_id="PU-Z"))
            store.append_understanding_revision(_revision(revision_id="PU-A"))
            history = store.list_understanding_revisions()
            # Insertion order (Z then A), NOT alphabetical (A then Z).
            assert [r.revision_id for r in history] == ["PU-Z", "PU-A"]

    def test_duplicate_revision_id_is_rejected_not_overwritten(self, tmp_path: Path) -> None:
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            original = _revision(revision_id="PU-1", note="first")
            store.append_understanding_revision(original)
            duplicate = _revision(revision_id="PU-1", note="attempted overwrite")
            with pytest.raises(ProjectMemoryError):
                store.append_understanding_revision(duplicate)
            # The original must be untouched — no silent mutation.
            history = store.list_understanding_revisions()
            assert len(history) == 1
            assert history[0].note == "first"

    def test_auditability_metadata_is_preserved(self, tmp_path: Path) -> None:
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            revision = _revision(
                revision_id="PU-2",
                session_id="session-42",
                supersedes="PU-1",
                note="human answered the camera-count clarification question",
            )
            store.append_understanding_revision(revision)
            current = store.get_current_understanding()
            assert current is not None
            assert current.session_id == "session-42"
            assert current.supersedes == "PU-1"
            assert current.note == "human answered the camera-count clarification question"
            assert current.created_at == "2026-01-01T00:00:00+00:00"


class TestSessions:
    def test_record_then_get_session(self, tmp_path: Path) -> None:
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            session = _session()
            store.record_session(session)
            assert store.get_session("session-1") == session

    def test_session_identity_matches_caller_supplied_id_verbatim(
        self, tmp_path: Path
    ) -> None:
        # Mirrors the real contract: this must be the exact string CVAgent
        # uses as AgentState.session_id / the LangGraph thread id.
        real_shaped_id = "6f9619ff-8b86-d011-b42d-00c04fc964ff"
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            store.record_session(_session(session_id=real_shaped_id))
            fetched = store.get_session(real_shaped_id)
            assert fetched is not None
            assert fetched.session_id == real_shaped_id

    def test_recording_again_upserts_rather_than_duplicates(self, tmp_path: Path) -> None:
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            store.record_session(_session(status="running"))
            store.record_session(
                _session(status="done", ended_at="2026-01-01T01:00:00+00:00",
                          produced_revision_id="PU-1")
            )
            assert len(store.list_sessions()) == 1
            fetched = store.get_session("session-1")
            assert fetched is not None
            assert fetched.status == "done"
            assert fetched.ended_at == "2026-01-01T01:00:00+00:00"
            assert fetched.produced_revision_id == "PU-1"

    def test_list_sessions_ordered_by_started_at_then_id(self, tmp_path: Path) -> None:
        with SqliteProjectMemoryStore(tmp_path / "memory.sqlite") as store:
            store.record_session(
                SessionRecord(session_id="s-b", started_at="2026-01-01T00:00:00+00:00")
            )
            store.record_session(
                SessionRecord(session_id="s-a", started_at="2026-01-02T00:00:00+00:00")
            )
            ordered = [s.session_id for s in store.list_sessions()]
            assert ordered == ["s-b", "s-a"]

    def test_no_transcript_fields_exist_on_session_record(self) -> None:
        # Structural guarantee, not just a convention: SessionRecord cannot
        # accidentally grow a transcript/message-log field later without
        # this test being touched.
        field_names = {f for f in SessionRecord.__dataclass_fields__}
        assert field_names == {
            "session_id", "started_at", "ended_at", "status", "produced_revision_id",
        }


class TestPersistenceAcrossRestart:
    def test_understanding_and_sessions_survive_close_and_reopen(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "memory.sqlite"

        store = SqliteProjectMemoryStore(db_path)
        store.append_understanding_revision(_revision(revision_id="PU-1"))
        store.record_session(_session(status="done"))
        store.close()  # genuine close — not just a second open on top.

        reopened = SqliteProjectMemoryStore(db_path)
        try:
            current = reopened.get_current_understanding()
            assert current is not None
            assert current.revision_id == "PU-1"

            session = reopened.get_session("session-1")
            assert session is not None
            assert session.status == "done"
        finally:
            reopened.close()

    def test_multiple_reopen_cycles_accumulate_history_correctly(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "memory.sqlite"

        for i in range(3):
            store = SqliteProjectMemoryStore(db_path)
            store.append_understanding_revision(_revision(revision_id=f"PU-{i}"))
            store.close()

        store = SqliteProjectMemoryStore(db_path)
        try:
            history = store.list_understanding_revisions()
            assert [r.revision_id for r in history] == ["PU-0", "PU-1", "PU-2"]
        finally:
            store.close()


class TestErrorHandlingDoesNotSwallow:
    def test_read_against_a_closed_connection_raises_project_memory_error(
        self, tmp_path: Path
    ) -> None:
        store = SqliteProjectMemoryStore(tmp_path / "memory.sqlite")
        store.close()
        with pytest.raises(ProjectMemoryError):
            store.get_current_understanding()

    def test_write_against_a_closed_connection_raises_project_memory_error(
        self, tmp_path: Path
    ) -> None:
        store = SqliteProjectMemoryStore(tmp_path / "memory.sqlite")
        store.close()
        with pytest.raises(ProjectMemoryError):
            store.append_understanding_revision(_revision())

    def test_project_memory_error_wraps_sqlite_error_with_context(
        self, tmp_path: Path
    ) -> None:
        store = SqliteProjectMemoryStore(tmp_path / "memory.sqlite")
        store.close()
        with pytest.raises(ProjectMemoryError) as exc_info:
            store.record_session(_session())
        assert isinstance(exc_info.value.__cause__, sqlite3.Error)


class TestOpenStoreFactory:
    """open_store() — the factory CVAgent/other callers use instead of
    importing SqliteProjectMemoryStore directly (ADR-0004 §2/§5)."""

    def test_open_store_with_explicit_workspace_root(self, tmp_path: Path) -> None:
        store = open_store(workspace_root=tmp_path)
        try:
            assert isinstance(store, SqliteProjectMemoryStore)
            assert (tmp_path / DEFAULT_MEMORY_DIRNAME / DEFAULT_DB_FILENAME).is_file()
        finally:
            store.close()

    def test_open_store_with_explicit_db_path_bypasses_default_db_path(
        self, tmp_path: Path
    ) -> None:
        exact_path = tmp_path / "somewhere-else" / "custom.sqlite"
        store = open_store(db_path=exact_path)
        try:
            assert exact_path.is_file()
            assert not (tmp_path / DEFAULT_MEMORY_DIRNAME).exists()
        finally:
            store.close()

    def test_open_store_satisfies_protocol_and_persists(self, tmp_path: Path) -> None:
        store = open_store(workspace_root=tmp_path)
        try:
            store.append_understanding_revision(_revision())
            assert store.get_current_understanding() is not None
        finally:
            store.close()


class TestArchitectureBoundary:
    def test_sqlite_import_is_confined_to_sqlite_store_module(self) -> None:
        """ADR-0004 requirement: no SQLite-specific import outside
        cv_agent/memory/, and within cv_agent/memory/ only sqlite_store.py
        may import sqlite3 (store.py/models.py must stay backend-neutral)."""
        import cv_agent

        package_root = Path(cv_agent.__file__).parent
        offenders = []
        for py_file in package_root.rglob("*.py"):
            if py_file.name == "sqlite_store.py":
                continue
            text = py_file.read_text(encoding="utf-8")
            if "import sqlite3" in text:
                offenders.append(str(py_file.relative_to(package_root)))
        assert offenders == [], f"sqlite3 imported outside sqlite_store.py: {offenders}"
