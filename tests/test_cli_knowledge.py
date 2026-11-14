"""ADR-0024 K2: ``cv-agent knowledge init | migrate | list | show``, driven through ``main([...])``.

Tmp state roots only: ``repository_state_root`` is monkeypatched to ``tmp_path`` (as in
tests/test_ledger_path.py), the credential loader is a no-op (no ``.env`` is read), and nothing
touches the network or an LLM. stdout is machine-readable JSON; human text goes to stderr.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from cv_agent import __main__ as cli
from cv_agent.experiments import provenance
from cv_agent.knowledge.sqlite_store import SqliteKnowledgeStore
from cv_agent.knowledge.store import KNOWLEDGE_FILENAME, RetrievalKeys
from tests.knowledge_fakes import _item, _open


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cli, "_load_project_credentials", lambda: None)
    monkeypatch.setattr(provenance, "repository_state_root", lambda start=None: tmp_path)
    monkeypatch.setattr(cli, "_utc_today", lambda: date(2026, 11, 12))
    return tmp_path


def _target(root: Path) -> Path:
    return root / KNOWLEDGE_FILENAME


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(["knowledge", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def _seeded(root: Path) -> Path:
    path = _target(root)
    SqliteKnowledgeStore.initialise(path)
    store = _open(path)
    store.put(_item("a-item", accessed="2026-11-01", horizon=10, tags=("detection",)), keys=RetrievalKeys(model_names=("YOLO11n",), metric="mAP50-95"))
    store.put(_item("b-item", accessed="2026-11-10", horizon=90, tags=("edge",)), keys=RetrievalKeys(model_names=("rtdetr",)))
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- init / migrate ----------------------------------------------------------------------------


def test_init_creates_then_refuses_and_leaves_it_untouched(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, "init")
    assert code == 0 and _target(root).is_file() and str(_target(root)) in out
    SqliteKnowledgeStore(_target(root), writer=_writer())  # opens cleanly
    before = _digest(_target(root))
    code, out, err = _run(capsys, "init")
    assert code == 1 and "already exists" in err and out == ""
    assert _digest(_target(root)) == before


def _writer() -> Any:
    from cv_agent.knowledge.store import KnowledgeWriter

    return KnowledgeWriter.RESEARCH_CLI


def test_init_with_unlocatable_state_root_exits_2(root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def boom(start: Any = None) -> Path:
        raise provenance.ProvenanceError("no repository")

    monkeypatch.setattr(provenance, "repository_state_root", boom)
    for sub in ("init", "migrate", "list", "show"):
        argv = (sub, "x") if sub == "show" else (sub,)
        code, _, err = _run(capsys, *argv)
        assert code == 2 and "state root" in err


def test_init_cannot_create_exits_2(root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    blocker = root / "blocked"
    blocker.write_text("a file, not a directory")
    monkeypatch.setattr(provenance, "repository_state_root", lambda start=None: blocker)
    code, _, err = _run(capsys, "init")
    assert code == 2 and "not created" in err


def test_migrate_current_store_is_a_no_op(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _seeded(root)
    before = _digest(path)
    code, out, _ = _run(capsys, "migrate")
    assert code == 0 and "up to date" in out
    assert _digest(path) == before


def test_migrate_missing_store_exits_2_with_the_init_hint_and_creates_nothing(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _run(capsys, "migrate")
    assert code == 2 and "cv-agent knowledge init" in err and not _target(root).exists()


def test_migrate_foreign_version_exits_2(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import sqlite3
    from contextlib import closing

    path = _seeded(root)
    with closing(sqlite3.connect(path, isolation_level=None)) as conn:
        conn.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    before = _digest(path)
    code, _, err = _run(capsys, "migrate")
    assert code == 2 and "not migrated" in err and _digest(path) == before


# --- list --------------------------------------------------------------------------------------


def _list(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, list[dict[str, Any]], str]:
    code, out, err = _run(capsys, "list", *argv)
    return code, (json.loads(out) if out else []), err


def test_list_empty_store(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    SqliteKnowledgeStore.initialise(_target(root))
    code, rows, err = _list(capsys)
    assert code == 0 and rows == [] and "0 items" in err


def test_list_missing_store_exits_2_with_hint_and_creates_nothing(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(capsys, "list")
    assert code == 2 and out == "" and "cv-agent knowledge init" in err and not _target(root).exists()


def test_list_json_on_stdout_human_table_on_stderr_stale_flagged_not_hidden(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seeded(root)
    code, rows, err = _list(capsys)  # as-of 2026-11-12: a-item (accessed 11-01, horizon 10) is stale
    assert code == 0
    assert [r["item_id"] for r in rows] == ["a-item", "b-item"]
    assert [r["stale"] for r in rows] == [True, False]
    assert rows[0]["revision"] == 1 and rows[0]["writer"] == "research_cli"
    assert rows[0]["keys"] == {"model_names": ["yolo11n"], "metric": "map50-95"}
    assert "STALE" in err and "a-item" in err and "2 items, 1 stale" in err


def test_list_fresh_only_hides_the_stale_item_but_the_row_remains(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _seeded(root)
    code, rows, _ = _list(capsys, "--fresh-only")
    assert code == 0 and [r["item_id"] for r in rows] == ["b-item"]
    assert [r["item_id"] for r in _list(capsys)[1]] == ["a-item", "b-item"]
    assert _open(path).get("a-item") is not None  # type: ignore[arg-type]


def test_list_filters_are_exact_after_normalisation(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seeded(root)
    ids = lambda *a: [r["item_id"] for r in _list(capsys, *a)[1]]  # noqa: E731
    assert ids("--model-name", "YOLO11N") == ["a-item"]
    assert ids("--model-name", "yolo11") == []
    assert ids("--model-name", "yolo11n", "--model-name", "rtdetr") == ["a-item", "b-item"]
    assert ids("--metric", "MAP50-95") == ["a-item"]
    assert ids("--topic-tag", "edge") == ["b-item"]
    assert ids("--topic-tag", "edge", "--topic-tag", "detection") == []
    assert ids("--source-class", "official_documentation") == ["a-item", "b-item"]
    assert ids("--source-class", "engineering_blog") == []
    assert ids("--ingest", "web_fetch") == ["a-item", "b-item"]


def test_list_bad_arguments_exit_2(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seeded(root)
    for bad in (("--as-of", "12/11/2026"), ("--source-class", "nope"), ("--ingest", "nope")):
        with pytest.raises(SystemExit) as exc:
            cli.main(["knowledge", "list", *bad])
        assert exc.value.code == 2
    capsys.readouterr()
    code, _, err = _run(capsys, "list", "--model-name", "yolo 11n")  # not a token
    assert code == 2 and err


# --- as-of (criterion 8, CLI part) ---------------------------------------------------------------


def test_default_as_of_is_the_injected_utc_date(root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _seeded(root)
    monkeypatch.setattr(cli, "_utc_today", lambda: date(2026, 11, 11))
    assert [r["stale"] for r in _list(capsys)[1]] == [False, False]  # horizon boundary: fresh on 11-11
    monkeypatch.setattr(cli, "_utc_today", lambda: date(2026, 11, 12))
    assert [r["stale"] for r in _list(capsys)[1]] == [True, False]  # stale on 11-12


def test_utc_today_is_the_utc_date_not_the_local_one(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timezone

    class _Late(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Any:  # 2026-11-12T20:00Z; UTC+06:00 would already be the 13th
            assert tz is timezone.utc
            return datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(cli, "datetime", _Late)
    assert cli._utc_today() == date(2026, 11, 12)


def test_explicit_as_of_overrides_the_default(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seeded(root)
    assert [r["stale"] for r in _list(capsys, "--as-of", "2026-11-11")[1]] == [False, False]
    assert [r["stale"] for r in _list(capsys, "--as-of", "2026-02-01")[1]] == [False, False]
    assert [r["stale"] for r in _list(capsys, "--as-of", "2027-06-01")[1]] == [True, True]


# --- show --------------------------------------------------------------------------------------


def _two_revisions(root: Path) -> Path:
    path = _seeded(root)
    _open(path).put(_item("a-item", claim="YOLO11n reaches 40.1 mAP on COCO.", accessed="2026-11-10", horizon=10), keys=RetrievalKeys(model_names=("yolo11n",)))
    return path


def test_show_latest_revision(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _two_revisions(root)
    code, out, _ = _run(capsys, "show", "a-item")
    obj = json.loads(out)
    assert code == 0 and obj["revision"] == 2 and "40.1" in obj["claim"] and obj["stale"] is False


def test_show_history_lists_every_revision_in_order(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _two_revisions(root)
    code, out, _ = _run(capsys, "show", "a-item", "--history")
    rows = json.loads(out)
    assert code == 0 and [r["revision"] for r in rows] == [1, 2]
    assert [r["stale"] for r in rows] == [True, False]


def test_show_unknown_item_exits_1_with_empty_stdout(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seeded(root)
    code, out, err = _run(capsys, "show", "nope")
    assert code == 1 and out == "" and "nope" in err
    code, out, _ = _run(capsys, "show", "nope", "--history")
    assert code == 1 and out == ""


def test_show_missing_store_exits_2_and_creates_nothing(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(capsys, "show", "a-item")
    assert code == 2 and out == "" and "cv-agent knowledge init" in err and not _target(root).exists()


def test_list_and_show_never_write(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _two_revisions(root)
    before = _digest(path)
    for argv in (("list",), ("list", "--fresh-only"), ("show", "a-item"), ("show", "a-item", "--history"), ("show", "nope")):
        _run(capsys, *argv)
    assert _digest(path) == before
