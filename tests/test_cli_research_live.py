"""Q58 / D-102: ``cv-agent research --live`` (issue #137), driven through ``main([...])``.

No test touches the network: socket connect and ``urlopen`` are tripwires, the fetch is mocked and
counted, and the hosted SDK client is a fake from ``tests/llm_fakes.py``. Both key variables are
removed from the environment before each test; a fake key is set only where a test needs one.
"""

from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from cv_agent import __main__ as cli
from cv_agent.config.settings import AgentConfig
from cv_agent.llm import credentials
from cv_agent.llm.sqlite_store import LLM_CALLS_FILENAME, LLMCallStore
from cv_agent.tools.models import ToolOutcome
from cv_agent.tools.web_research import WebResearchFetchInvoker
from tests.llm_fakes import FakeAnthropicClient, text_message

_URL = "https://papers.example.com/yolo.html"
_FAKE_KEY = "fake-key-not-a-secret"
_GOOD = json.dumps(
    {
        "claim": "yolo11n reaches 39.5 mAP50-95",
        "conditions": "COCO val",
        "author_or_org": "Example Org",
        "date_published": "2026-01-15",
    }
)


class _Env:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.fetches = 0
        self.credential_lookups: list[str] = []


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Env:
    e = _Env(tmp_path)

    def _no_net(*_a: Any, **_k: Any) -> None:
        raise AssertionError("network used in a test")

    monkeypatch.setattr(socket.socket, "connect", _no_net)
    monkeypatch.setattr("cv_agent.tools.web_research.urlopen", _no_net)
    monkeypatch.setattr("cv_agent.config.settings.load_config", lambda *a, **k: AgentConfig())
    monkeypatch.setattr(cli, "_load_project_credentials", lambda: None)
    monkeypatch.setattr("cv_agent.experiments.provenance.repository_state_root", lambda *a, **k: tmp_path)
    monkeypatch.delenv("CV_AGENT_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    credentials._reset_for_tests()

    real_get = credentials.get_credential

    def _spy(name: str) -> str:
        e.credential_lookups.append(name)
        return real_get(name)

    monkeypatch.setattr(credentials, "get_credential", _spy)
    monkeypatch.setattr("cv_agent.llm.anthropic_provider.get_credential", _spy)

    def _invoke(self: Any, spec: Any, request: Any) -> ToolOutcome:
        e.fetches += 1
        return ToolOutcome(
            success=True,
            output={
                "url": request.inputs["url"],
                "content_text": "benchmark page",
                "content_type": "text/html",
                "date_accessed": "2026-11-12T10:00:00Z",
                "http_status": 200,
                "truncated": False,
            },
        )

    monkeypatch.setattr(WebResearchFetchInvoker, "invoke", _invoke)
    return e


def _args(*extra: str) -> list[str]:
    return [
        "research",
        "--url", _URL,
        "--source-class", "engineering_blog",
        "--topic-tag", "object_detection",
        "--metric", "mAP50-95",
        "--staleness-days", "180",
        *extra,
    ]


def test_without_live_reads_no_credential_and_routes_offline(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(_args())
    err = capsys.readouterr().err
    assert env.credential_lookups == []
    assert "route=offline/" in err
    assert env.fetches == 1


def test_live_without_a_key_refuses_before_any_fetch(
    env: _Env, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli.main(_args("--live"))
    err = capsys.readouterr().err
    assert rc == 2
    assert "LLMCredentialError" in err and "CV_AGENT_ANTHROPIC_API_KEY" in err
    assert env.fetches == 0


def test_live_with_a_fake_key_routes_to_fast_and_logs_tier_fast(
    env: _Env, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CV_AGENT_ANTHROPIC_API_KEY", _FAKE_KEY)
    LLMCallStore.initialise(env.state_dir / LLM_CALLS_FILENAME)
    client = FakeAnthropicClient(response=text_message(_GOOD))
    keys_seen: list[str] = []

    def _factory(*, api_key: str, **_k: Any) -> FakeAnthropicClient:
        keys_seen.append(api_key)
        return client

    monkeypatch.setattr("cv_agent.llm.anthropic_provider.anthropic.Anthropic", _factory)

    rc = cli.main(_args("--live"))
    cap = capsys.readouterr()
    assert rc == 0, cap.err
    doc = json.loads(cap.out)
    assert doc["route"]["tier"] == "fast" and doc["route"]["hosted"] is True
    assert keys_seen == [_FAKE_KEY]
    assert len(client.messages.calls) == 1
    assert env.fetches == 1

    with sqlite3.connect(env.state_dir / LLM_CALLS_FILENAME) as conn:
        rows = conn.execute("SELECT task_class, tier FROM llm_calls").fetchall()
    assert rows == [("extraction", "fast")]
