"""ADR-0023 S2: payload columns in the call log and the explicit ``llm-log migrate`` (#106).

Every case runs on a temporary store; the real call log is never touched.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pytest

import cv_agent.__main__ as cli
from cv_agent.llm.errors import LLMStoreError
from cv_agent.llm.sqlite_store import CallRecord, LLMCallStore

HINT = "cv-agent llm-log migrate"


def _record(call_id: str, **extra: object) -> CallRecord:
    return CallRecord(
        call_id=call_id,
        ts_utc="2026-01-01T00:00:00.000000+00:00",
        task_class="extraction",
        tier="fast",
        provider="p",
        model="m",
        adapter_version=None,
        sdk_version=None,
        local_model_digest=None,
        local_quantization=None,
        max_tokens=8,
        thinking=None,
        effort=None,
        prompt_sha256="0" * 64,
        response_sha256=None,
        request_id=None,
        input_tokens=1,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=1,
        thinking_tokens=0,
        stop_reason="end_turn",
        latency_ms=1,
        **extra,  # type: ignore[arg-type]
    )


def _old_store(path: Path, rows: int = 2) -> None:
    """A schema-2 store as it exists on the owner's PC: a fresh one with the new columns dropped."""
    LLMCallStore.initialise(path)
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("ALTER TABLE llm_calls DROP COLUMN payload_schema")
        conn.execute("ALTER TABLE llm_calls DROP COLUMN payload_sha256")
        conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
        for i in range(rows):
            old = dataclasses.asdict(_record(f"c{i}"))
            for k in ("payload_schema", "payload_sha256"):
                del old[k]
            conn.execute(
                f"INSERT INTO llm_calls ({', '.join(old)}) VALUES ({', '.join('?' * len(old))})",
                tuple(old.values()),
            )
        conn.execute(
            "INSERT INTO llm_budget VALUES ('c0', '2026-01-01', '2026-01-01T00:00:00.000000+00:00', 0.5, 0.25, 1, 'x')"
        )
    finally:
        conn.close()


def _dump(path: Path) -> dict[str, list[tuple[object, ...]]]:
    conn = sqlite3.connect(path)
    try:
        return {
            t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
            for t in ("llm_calls", "llm_budget")
        }
    finally:
        conn.close()


def _columns(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(llm_calls)")]
    finally:
        conn.close()


def _version(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return str(conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0])
    finally:
        conn.close()


def test_new_store_has_payload_columns_last_and_extraction_rows_are_null(tmp_path: Path) -> None:
    path = tmp_path / "s.sqlite"
    LLMCallStore.initialise(path)
    assert _columns(path)[-2:] == ["payload_schema", "payload_sha256"]
    assert _version(path) == "3"
    store = LLMCallStore(path)
    store.append(_record("a"))
    store.append(_record("b", payload_schema="selection/1", payload_sha256="f" * 64))
    rows = {r[0]: r[-2:] for r in _dump(path)["llm_calls"]}
    assert rows["a"] == (None, None)
    assert rows["b"] == ("selection/1", "f" * 64)


def test_unmigrated_store_fails_closed_with_the_hint(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    _old_store(path)
    with pytest.raises(LLMStoreError, match=HINT):
        LLMCallStore(path)


def test_migrate_keeps_every_row_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    _old_store(path)
    before = _dump(path)
    LLMCallStore.migrate(path)
    after = _dump(path)
    assert _columns(path)[-2:] == ["payload_schema", "payload_sha256"]
    assert _version(path) == "3"
    assert after["llm_budget"] == before["llm_budget"]
    assert [r[:-2] for r in after["llm_calls"]] == before["llm_calls"]
    assert all(r[-2:] == (None, None) for r in after["llm_calls"])
    LLMCallStore(path)  # opens cleanly now
    LLMCallStore.migrate(path)  # second run: no-op
    assert _dump(path) == after


def test_migrate_refuses_missing_and_foreign_stores_without_changing_them(tmp_path: Path) -> None:
    missing = tmp_path / "none.sqlite"
    with pytest.raises(LLMStoreError):
        LLMCallStore.migrate(missing)
    assert not missing.exists()
    foreign = tmp_path / "v1.sqlite"
    _old_store(foreign)
    conn = sqlite3.connect(foreign)
    conn.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    before = _dump(foreign)
    with pytest.raises(LLMStoreError):
        LLMCallStore.migrate(foreign)
    assert _dump(foreign) == before
    assert _version(foreign) == "1"


@pytest.fixture
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "checkout" / ".cv_agent"
    monkeypatch.setattr(
        "cv_agent.experiments.provenance.repository_state_root", lambda start=None: root
    )
    return root


def test_cli_migrate(state_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = state_root / "llm_calls.sqlite"
    assert cli.main(["llm-log", "migrate"]) == 2  # missing store
    assert not target.exists()
    _old_store(target)
    assert cli.main(["llm-log", "migrate"]) == 0
    assert _version(target) == "3"
    assert cli.main(["llm-log", "migrate"]) == 0  # idempotent
    with pytest.raises(SystemExit):
        cli.main(["llm-log"])
    capsys.readouterr()
