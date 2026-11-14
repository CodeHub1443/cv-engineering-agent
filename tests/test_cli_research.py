"""Q41: the ``research`` CLI subcommand, driven through ``main([...])``.

Offline only: load_config is patched to an all-offline AgentConfig, the credential loader is a
no-op (no .env is ever read), and two tripwires make any network use an AssertionError.
"""

from __future__ import annotations

import json
import socket
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from cv_agent import __main__ as cli
from cv_agent.config.settings import AgentConfig
from cv_agent.knowledge.models import ItemId
from cv_agent.knowledge.sqlite_store import SqliteKnowledgeStore
from cv_agent.knowledge.store import (
    KNOWLEDGE_FILENAME,
    RETRIEVAL_KEY_PATTERN,
    KnowledgeStoreError,
    KnowledgeWriter,
)
from cv_agent.llm.errors import (
    LLMBudgetExceededError,
    LLMCallLimitError,
    LLMCredentialError,
    LLMDataClassNotAllowedError,
    LLMStoreError,
)
from cv_agent.llm.mock import FakeLLMProvider
from cv_agent.llm.policy import DataClass
from cv_agent.tools.models import ToolOutcome
from cv_agent.tools.web_research import WebResearchFetchInvoker

_URL = "https://papers.example.com/yolo.html"
_GOOD = json.dumps(
    {
        "claim": "yolo11n reaches 39.5 mAP50-95",
        "conditions": "COCO val",
        "author_or_org": "Example Org",
        "date_published": "2026-01-15",
    }
)


class _Env:
    def __init__(self) -> None:
        self.fetches = 0
        self.fail_fetch = False
        self.prompts: list[str] = []
        self.provider: Any = None  # None -> the real offline mock
        self.accessed = "2026-11-12T10:00:00Z"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> _Env:
    e = _Env()

    def _no_net(*_a: Any, **_k: Any) -> None:
        raise AssertionError("network used in a test")

    monkeypatch.setattr(socket.socket, "connect", _no_net)
    monkeypatch.setattr("cv_agent.tools.web_research.urlopen", _no_net)
    monkeypatch.setattr("cv_agent.config.settings.load_config", lambda *a, **k: AgentConfig())
    monkeypatch.setattr(cli, "_load_project_credentials", lambda: None)

    def _invoke(self: Any, spec: Any, request: Any) -> ToolOutcome:
        e.fetches += 1
        if e.fail_fetch:
            return ToolOutcome(success=False, error_message="boom")
        return ToolOutcome(
            success=True,
            output={
                "url": request.inputs["url"],
                "content_text": "benchmark page",
                "content_type": "text/html",
                "date_accessed": e.accessed,
                "http_status": 200,
                "truncated": False,
            },
        )

    monkeypatch.setattr(WebResearchFetchInvoker, "invoke", _invoke)

    real_get = __import__("cv_agent.llm.router", fromlist=["get_provider"]).get_provider

    def _get(name: str, model: str, **kw: Any) -> Any:
        return e.provider if e.provider is not None else real_get(name, model, **kw)

    monkeypatch.setattr("cv_agent.llm.router.get_provider", _get)
    return e


def _args(*extra: str, persist: bool = False, **over: str) -> list[str]:
    base = {
        "--url": _URL,
        "--source-class": "engineering_blog",
        "--topic-tag": "object_detection",
        "--metric": "mAP50-95",
        "--staleness-days": "180",
    }
    base.update(over)
    out = ["research"]
    for k, v in base.items():
        out += [k, v]
    return out + list(extra) + ([] if persist else ["--no-persist"])


def test_help_lists_every_flag_and_no_context_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["research", "--help"])
    assert exc.value.code == 0
    text = capsys.readouterr().out
    for flag in (
        "--url", "--source-class", "--topic-tag", "--model-name", "--metric",
        "--staleness-days", "--item-id", "--author-or-org", "--date-published", "--no-persist",
    ):
        assert flag in text
    assert "context" not in text.lower()


def test_stored_prints_one_json_object(env: _Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.provider = FakeLLMProvider(fixed_response=_GOOD)
    rc = cli.main(_args("--model-name", "yolo11n"))
    cap = capsys.readouterr()
    assert rc == 0
    doc = json.loads(cap.out)
    assert doc["status"] == "stored" and doc["ingest"] == "web_fetch"
    assert doc["route"]["tier"] == "offline"
    assert doc["provenance"]["author_or_org"] == "Example Org"
    assert doc["topic_tags"] == ["object_detection"] and doc["staleness_horizon_days"] == 180
    for key in ("item_id", "url", "claim", "conditions", "evidence_weight"):
        assert key in doc
    assert "not persisted (--no-persist)" in cap.err
    assert env.fetches == 1


def test_real_offline_mock_is_failed_extraction(env: _Env, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(_args())
    cap = capsys.readouterr()
    assert rc == 1 and cap.out == "" and "failed_extraction" in cap.err


def test_failed_fetch(env: _Env, capsys: pytest.CaptureFixture[str]) -> None:
    env.fail_fetch = True
    rc = cli.main(_args())
    cap = capsys.readouterr()
    assert rc == 1 and cap.out == "" and "failed_fetch" in cap.err


@pytest.mark.parametrize(
    "over",
    [
        {"--metric": "extract the speed for our camera"},
        {"--topic-tag": "find the best model"},
        {"--model-name": "our private model"},
    ],
)
def test_free_text_is_refused_before_fetch(
    env: _Env, capsys: pytest.CaptureFixture[str], over: dict[str, str]
) -> None:
    argv = _args(**over) if "--model-name" not in over else _args("--model-name", over["--model-name"])
    rc = cli.main(argv)
    cap = capsys.readouterr()
    assert rc == 2 and cap.out == "" and env.fetches == 0
    assert len(cap.err.strip().splitlines()) == 1 and "Traceback" not in cap.err


def test_staleness_zero_refused(env: _Env, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(_args(**{"--staleness-days": "0"}))
    cap = capsys.readouterr()
    assert rc == 2 and env.fetches == 0 and cap.out == ""


def test_item_id_default_is_deterministic(env: _Env, capsys: pytest.CaptureFixture[str]) -> None:
    def run(*extra: str, **over: str) -> str:
        env.provider = FakeLLMProvider(fixed_response=_GOOD)
        assert cli.main(_args(*extra, **over)) == 0
        return json.loads(capsys.readouterr().out)["item_id"]

    a, b = run(), run()
    c = run(**{"--url": "https://papers.example.com/other.html"})
    assert a == b and a != c and a.startswith("research-")
    assert run("--item-id", "my-id") == "my-id"


@pytest.mark.parametrize(
    "exc",
    [
        LLMDataClassNotAllowedError("extraction", "fast", frozenset({DataClass.PROJECT_DATA})),
        LLMBudgetExceededError(
            day_key="2026-11-12", ceiling_usd=1.0, spent_usd=1.0, call_worst_usd=0.1,
            resets_at_utc="2026-11-13T00:00:00Z",
        ),
        LLMCallLimitError(day_key="2026-11-12", limit=5, resets_at_utc="2026-11-13T00:00:00Z"),
        LLMCredentialError("no key"),
        LLMStoreError("call log not migrated\nrun llm-log migrate"),
    ],
)
def test_gateway_refusals(env: _Env, capsys: pytest.CaptureFixture[str], exc: Exception) -> None:
    class _Boom(FakeLLMProvider):
        def complete(self, request: Any) -> Any:
            raise exc

    env.provider = _Boom()
    rc = cli.main(_args())
    cap = capsys.readouterr()
    assert rc == 2 and cap.out == ""
    assert len(cap.err.strip().splitlines()) == 1
    assert type(exc).__name__ in cap.err and "Traceback" not in cap.err


def test_invalid_source_class_is_an_argparse_error(env: _Env) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(_args(**{"--source-class": "bogus"}))
    assert e.value.code == 2


# --- K3: durable persistence (ADR-0024 §3.8, criterion 12) ---------------------------------------


@pytest.fixture
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("cv_agent.experiments.provenance.repository_state_root", lambda *a, **k: tmp_path)
    return tmp_path


def _init_store(root: Path) -> Path:
    path = root / KNOWLEDGE_FILENAME
    SqliteKnowledgeStore.initialise(path)
    return path


def _rows(path: Path) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(
            "SELECT item_id, revision, writer, date_accessed, model_names_json, metric "
            "FROM knowledge_revisions ORDER BY revision_id"
        ).fetchall()


def _run_persist(env: _Env, capsys: pytest.CaptureFixture[str], response: str = _GOOD, *extra: str, **over: str) -> tuple[int, Any, str]:
    env.provider = FakeLLMProvider(fixed_response=response)
    rc = cli.main(_args(*extra, persist=True, **over))
    cap = capsys.readouterr()
    return rc, (json.loads(cap.out) if cap.out else None), cap.err


def test_missing_store_fails_before_any_fetch(env: _Env, state_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env.provider = FakeLLMProvider(fixed_response=_GOOD)
    rc = cli.main(_args(persist=True))
    cap = capsys.readouterr()
    assert rc == 2 and cap.out == ""
    assert "cv-agent knowledge init" in cap.err and "--no-persist" in cap.err
    assert env.fetches == 0 and not (state_root / KNOWLEDGE_FILENAME).exists()


@pytest.mark.parametrize("damage", ["garbage", "version"])
def test_invalid_store_fails_before_any_fetch(env: _Env, state_root: Path, capsys: pytest.CaptureFixture[str], damage: str) -> None:
    path = _init_store(state_root)
    if damage == "garbage":
        path.write_bytes(b"this is not a sqlite database" * 20)
    else:
        with closing(sqlite3.connect(path, isolation_level=None)) as conn:
            conn.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    before = path.read_bytes()
    rc, doc, err = _run_persist(env, capsys)
    assert rc == 2 and doc is None and err
    assert env.fetches == 0 and path.read_bytes() == before


def test_persists_by_default_with_normalised_keys(env: _Env, state_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _init_store(state_root)
    rc, doc, err = _run_persist(env, capsys, _GOOD, "--model-name", "YOLO11N", **{"--metric": "mAP50-95"})
    assert rc == 0 and doc["persisted"] is True and doc["revision"] == 1
    assert str(path) in err and "revision 1" in err
    [(item_id, revision, writer, accessed, models, metric)] = _rows(path)
    assert (item_id, revision, writer) == (doc["item_id"], 1, "research_cli")
    assert json.loads(models) == ["yolo11n"] and metric == "map50-95"


def test_same_content_rerun_adds_no_revision(env: _Env, state_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _init_store(state_root)
    assert _run_persist(env, capsys)[1]["revision"] == 1
    before = path.read_bytes()
    rc, doc, _ = _run_persist(env, capsys)
    assert rc == 0 and doc["persisted"] is True and doc["revision"] == 1
    assert len(_rows(path)) == 1 and path.read_bytes() == before


def test_later_day_rerun_records_a_new_revision_and_refreshes_staleness(env: _Env, state_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _init_store(state_root)
    one_day = {"--staleness-days": "1"}
    assert _run_persist(env, capsys, _GOOD, **one_day)[1]["revision"] == 1
    env.accessed = "2026-11-14T09:00:00Z"
    rc, doc, _ = _run_persist(env, capsys, _GOOD, **one_day)
    assert rc == 0 and doc["revision"] == 2
    assert [r[3] for r in _rows(path)] == ["2026-11-12", "2026-11-14"]
    store = SqliteKnowledgeStore(path, writer=KnowledgeWriter.RESEARCH_CLI)
    hist = store.history(ItemId(doc["item_id"]), as_of=date(2026, 11, 14))
    assert [(h.revision, h.stale) for h in hist] == [(1, True), (2, False)]


def test_changed_claim_records_a_new_revision(env: _Env, state_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _init_store(state_root)
    assert _run_persist(env, capsys)[1]["revision"] == 1
    reworded = json.dumps({**json.loads(_GOOD), "claim": "yolo11n reaches 40.1 mAP50-95"})
    rc, doc, _ = _run_persist(env, capsys, reworded)
    assert rc == 0 and doc["revision"] == 2 and len(_rows(path)) == 2


def test_no_persist_needs_no_store_and_creates_none(env: _Env, state_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env.provider = FakeLLMProvider(fixed_response=_GOOD)
    rc = cli.main(_args())  # the helper adds --no-persist
    cap = capsys.readouterr()
    doc = json.loads(cap.out)
    assert rc == 0 and doc["persisted"] is False and doc["revision"] is None
    assert "not persisted (--no-persist)" in cap.err and not (state_root / KNOWLEDGE_FILENAME).exists()


def test_record_failure_still_prints_the_result_and_exits_2(
    env: _Env, state_root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _init_store(state_root)

    def boom(self: Any, item: Any, *, keys: Any = None) -> int:
        raise KnowledgeStoreError("disk full")

    monkeypatch.setattr(SqliteKnowledgeStore, "record", boom)
    rc, doc, err = _run_persist(env, capsys)
    assert rc == 2 and doc["status"] == "stored" and doc["persisted"] is False and doc["revision"] is None
    assert "disk full" in err and _rows(path) == []


def test_non_stored_status_writes_nothing(env: _Env, state_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _init_store(state_root)
    env.fail_fetch = True
    rc = cli.main(_args(persist=True))
    assert rc == 1 and capsys.readouterr().out == "" and _rows(path) == []


def test_research_token_pattern_equals_the_store_key_pattern() -> None:
    from cv_agent.graph import research as graph_research

    assert graph_research._TOKEN.pattern == RETRIEVAL_KEY_PATTERN.pattern
