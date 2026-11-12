"""Slice G2 acceptance tests: the SQLite call log and the GovernedProvider skeleton.

ADR-0020 §3 item 5(6), §5.1 and §7 "G2"; D-092. No network, no real key, no real state
root: every store lives under ``tmp_path`` and every adapter is a fake.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

import cv_agent.__main__ as cli
from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.catalog import parse_catalog
from cv_agent.llm.clock import Clock, SystemClock
from cv_agent.llm.errors import (
    LLMRefusalError,
    LLMRequestError,
    LLMStoreError,
    LLMTruncatedError,
)
from cv_agent.llm.governed import GovernedProvider, prompt_digest
from cv_agent.llm.sqlite_store import CallRecord, LLMCallStore

EXPECTED_COLUMNS = [
    "call_id",
    "ts_utc",
    "task_class",
    "tier",
    "provider",
    "model",
    "adapter_version",
    "sdk_version",
    "local_model_digest",
    "local_quantization",
    "max_tokens",
    "thinking",
    "effort",
    "prompt_sha256",
    "response_sha256",
    "request_id",
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
    "thinking_tokens",
    "stop_reason",
    "latency_ms",
    "prompt_text",
    "response_text",
]
FAKE_CATALOG = parse_catalog(
    """
[models."fake-model-1"]
provider = "fakeprovider"
prices_as_of = "2026-11-12"
prices_source = "https://example.invalid/pricing"
[[models."fake-model-1".price_steps]]
input_usd_per_mtok = 1.0
output_usd_per_mtok = 1.0
"""
)
FAKE_KEY = "sk-ant-FAKE-KEY-for-tests-0123456789"
T0 = datetime(2026, 11, 12, 9, 30, 0, tzinfo=timezone.utc)


# ── Fakes ────────────────────────────────────────────────────────────────────


class FakeClock:
    """Fixed wall clock; ``monotonic`` jumps by ``step`` seconds on every read."""

    def __init__(self, step: float = 0.25) -> None:
        self._mono = 100.0
        self._step = step

    def now_utc(self) -> datetime:
        return T0

    def monotonic(self) -> float:
        self._mono += self._step
        return self._mono


class FakeAdapter(LLMProvider):
    def __init__(
        self, *, response: Optional[LLMResponse] = None, exc: Optional[BaseException] = None
    ) -> None:
        self._response = response
        self._exc = exc
        self.requests: list[LLMRequest] = []

    @property
    def provider_name(self) -> str:
        return "fakeprovider"

    @property
    def model_name(self) -> str:
        return "fake-model-1"

    @property
    def adapter_version(self) -> Optional[str]:
        return "fake/1"

    @property
    def sdk_version(self) -> Optional[str]:
        return "9.9.9"

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def _response(text: str = "the answer") -> LLMResponse:
    return LLMResponse(
        content=text,
        model="fake-model-1",
        provider="fakeprovider",
        usage={
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "cache_creation_input_tokens": 3,
            "cache_read_input_tokens": 2,
            "thinking_tokens": 4,
            "total_tokens": 18,
        },
        stop_reason="end_turn",
        request_id="req_abc123",
    )


def _new_store(tmp_path: Path) -> tuple[LLMCallStore, Path]:
    path = tmp_path / "llm_calls.sqlite"
    LLMCallStore.initialise(path)
    return LLMCallStore(path), path


def _governed(
    store: LLMCallStore,
    adapter: LLMProvider,
    *,
    store_text: bool = False,
    clock: Optional[Clock] = None,
) -> GovernedProvider:
    return GovernedProvider(
        hosted=False,
        task_class="narrative",
        tier="fast",
        adapter=adapter,
        store=store,
        store_text=store_text,
        clock=clock or FakeClock(),
        thinking="disabled",
        effort="low",
        catalog=FAKE_CATALOG,
    )


def _rows(path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM llm_calls ORDER BY rowid")]
    finally:
        conn.close()


def _record(call_id: str) -> CallRecord:
    return CallRecord(
        call_id=call_id,
        request_id=None,
        ts_utc=T0.isoformat(),
        task_class="narrative",
        tier="fast",
        provider="fakeprovider",
        model="fake-model-1",
        adapter_version=None,
        sdk_version=None,
        local_model_digest=None,
        local_quantization=None,
        max_tokens=64,
        thinking=None,
        effort=None,
        prompt_sha256="0" * 64,
        response_sha256=None,
        input_tokens=1,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=1,
        thinking_tokens=0,
        stop_reason="end_turn",
        latency_ms=1,
    )


# ── The store: fail closed, explicit initialisation ──────────────────────────


def test_missing_store_raises_and_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "llm_calls.sqlite"
    with pytest.raises(LLMStoreError, match="llm-log init"):
        LLMCallStore(path)
    assert not path.exists()


def test_corrupt_store_raises(tmp_path: Path) -> None:
    path = tmp_path / "llm_calls.sqlite"
    path.write_bytes(b"this is not a sqlite database " * 40)
    with pytest.raises(LLMStoreError):
        LLMCallStore(path)


def test_uninitialised_empty_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "llm_calls.sqlite"
    path.write_bytes(b"")
    with pytest.raises(LLMStoreError):
        LLMCallStore(path)


def test_foreign_schema_version_raises(tmp_path: Path) -> None:
    _, path = _new_store(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(LLMStoreError, match="schema"):
        LLMCallStore(path)


def test_initialise_creates_exactly_the_call_log_schema(tmp_path: Path) -> None:
    _, path = _new_store(tmp_path)
    conn = sqlite3.connect(path)
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        columns = [r[1] for r in conn.execute("PRAGMA table_info(llm_calls)")]
        version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    finally:
        conn.close()
    assert tables == {"llm_calls", "llm_budget", "meta"}  # budget table since G3 (schema 2)
    assert columns == EXPECTED_COLUMNS
    assert version == ("2",)


def test_initialise_creates_missing_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / ".cv_agent" / "llm_calls.sqlite"
    LLMCallStore.initialise(path)
    assert path.is_file()


def test_initialise_refuses_an_existing_file_and_leaves_it_alone(tmp_path: Path) -> None:
    store, path = _new_store(tmp_path)
    store.append(_record("keep-me"))
    with pytest.raises(LLMStoreError, match="already exists"):
        LLMCallStore.initialise(path)
    assert [r["call_id"] for r in _rows(path)] == ["keep-me"]


def test_busy_timeout_is_validated_and_stored_default() -> None:
    with pytest.raises(ValueError):
        LLMCallStore(Path("x"), busy_timeout_s=-1.0)


# ── The CLI: explicit `llm-log init`, never implicit ─────────────────────────


@pytest.fixture
def state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "checkout" / ".cv_agent"
    monkeypatch.setattr(
        "cv_agent.experiments.provenance.repository_state_root", lambda start=None: root
    )
    return root


def test_cli_init_creates_store_under_state_root(
    state_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["llm-log", "init"]) == 0
    target = state_root / "llm_calls.sqlite"
    assert target.is_file()
    assert str(target) in capsys.readouterr().out
    LLMCallStore(target)  # opens cleanly: the schema is in place


def test_cli_second_init_refuses_with_a_clear_message(
    state_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["llm-log", "init"]) == 0
    capsys.readouterr()
    assert cli.main(["llm-log", "init"]) == 1
    err = capsys.readouterr().err
    assert "already exists" in err
    assert "llm_calls.sqlite" in err


def test_cli_init_unresolvable_root_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from cv_agent.experiments.provenance import ProvenanceError

    def boom(start: Any = None) -> Path:
        raise ProvenanceError("not a git repository")

    monkeypatch.setattr("cv_agent.experiments.provenance.repository_state_root", boom)
    assert cli.main(["llm-log", "init"]) == 2
    assert "not a git repository" in capsys.readouterr().err


def test_cli_llm_log_requires_a_subcommand(state_root: Path) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["llm-log"])
    assert info.value.code == 2
    assert not state_root.exists()


def test_health_check_never_creates_the_store(state_root: Path) -> None:
    cli.main([])
    assert not (state_root / "llm_calls.sqlite").exists()
    assert not state_root.exists()


# ── GovernedProvider: one row per call ───────────────────────────────────────


def test_successful_call_writes_exactly_one_row_with_the_d4_columns(tmp_path: Path) -> None:
    store, path = _new_store(tmp_path)
    adapter = FakeAdapter(response=_response("the answer"))
    request = LLMRequest(prompt="why?", system="be brief", max_tokens=64)

    result = _governed(store, adapter).complete(request)

    rows = _rows(path)
    assert len(rows) == 1
    row = rows[0]
    assert list(row) == EXPECTED_COLUMNS  # exactly the D4 fields plus request_id
    assert result.content == "the answer"
    assert result.call_id == row["call_id"]
    assert row["call_id"]
    assert row["ts_utc"] == T0.isoformat()
    assert row["task_class"] == "narrative"
    assert row["tier"] == "fast"
    assert row["provider"] == "fakeprovider"
    assert row["model"] == "fake-model-1"
    assert row["adapter_version"] == "fake/1"
    assert row["sdk_version"] == "9.9.9"
    assert row["local_model_digest"] is None
    assert row["local_quantization"] is None
    assert row["max_tokens"] == 64
    assert row["thinking"] == "disabled"
    assert row["effort"] == "low"
    assert row["request_id"] == "req_abc123"
    assert row["input_tokens"] == 11
    assert row["output_tokens"] == 7
    assert row["cache_creation_input_tokens"] == 3
    assert row["cache_read_input_tokens"] == 2
    assert row["thinking_tokens"] == 4
    assert row["stop_reason"] == "end_turn"
    assert row["latency_ms"] == 250  # FakeClock: one 0.25 s step between the two reads
    assert adapter.requests == [request]


def test_each_call_gets_its_own_call_id(tmp_path: Path) -> None:
    store, path = _new_store(tmp_path)
    governed = _governed(store, FakeAdapter(response=_response()))
    first = governed.complete(LLMRequest(prompt="a", max_tokens=8))
    second = governed.complete(LLMRequest(prompt="b", max_tokens=8))
    assert first.call_id != second.call_id
    assert [r["call_id"] for r in _rows(path)] == [first.call_id, second.call_id]


def test_governed_provider_reports_adapter_identity(tmp_path: Path) -> None:
    store, _ = _new_store(tmp_path)
    governed = _governed(store, FakeAdapter(response=_response()))
    assert governed.provider_name == "fakeprovider"
    assert governed.model_name == "fake-model-1"
    assert governed.adapter_version == "fake/1"
    assert governed.sdk_version == "9.9.9"


# ── Hashes: the byte encoding is part of the contract ────────────────────────


def test_prompt_sha256_encoding_is_canonical_json_of_system_and_prompt() -> None:
    expected_payload = b'{"prompt":"why?","system":"be brief"}'
    assert prompt_digest("be brief", "why?") == hashlib.sha256(expected_payload).hexdigest()


def test_prompt_sha256_is_ascii_escaped_and_distinguishes_none_from_empty() -> None:
    payload = '{"prompt":"caf\\u00e9 \\u09ac\\u09be\\u0982\\u09b2\\u09be","system":null}'.encode("ascii")
    assert prompt_digest(None, "café বাংলা") == hashlib.sha256(payload).hexdigest()
    assert prompt_digest(None, "x") != prompt_digest("", "x")


def test_prompt_sha256_has_no_concatenation_ambiguity() -> None:
    assert prompt_digest("ab", "c") != prompt_digest("a", "bc")


def test_logged_hashes_match_the_documented_encoding(tmp_path: Path) -> None:
    store, path = _new_store(tmp_path)
    _governed(store, FakeAdapter(response=_response("héllo"))).complete(
        LLMRequest(prompt="why?", system="be brief", max_tokens=8)
    )
    row = _rows(path)[0]
    assert row["prompt_sha256"] == hashlib.sha256(b'{"prompt":"why?","system":"be brief"}').hexdigest()
    assert row["response_sha256"] == hashlib.sha256("héllo".encode("utf-8")).hexdigest()


# ── Text is opt-in ───────────────────────────────────────────────────────────


def test_text_columns_are_null_by_default(tmp_path: Path) -> None:
    store, path = _new_store(tmp_path)
    _governed(store, FakeAdapter(response=_response())).complete(
        LLMRequest(prompt="secret-ish prompt", system="sys", max_tokens=8)
    )
    row = _rows(path)[0]
    assert row["prompt_text"] is None
    assert row["response_text"] is None
    assert b"secret-ish prompt" not in path.read_bytes()


def test_text_columns_filled_only_when_store_text_is_true(tmp_path: Path) -> None:
    store, path = _new_store(tmp_path)
    _governed(store, FakeAdapter(response=_response("the answer")), store_text=True).complete(
        LLMRequest(prompt="why?", system="be brief", max_tokens=8)
    )
    row = _rows(path)[0]
    assert row["response_text"] == "the answer"
    # prompt_text is the exact payload that prompt_sha256 covers, so the hash is verifiable.
    assert hashlib.sha256(row["prompt_text"].encode("utf-8")).hexdigest() == row["prompt_sha256"]
    assert json.loads(row["prompt_text"]) == {"system": "be brief", "prompt": "why?"}


# ── The key never reaches the log ────────────────────────────────────────────


def test_api_key_never_appears_in_any_row_or_in_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CV_AGENT_ANTHROPIC_API_KEY", FAKE_KEY)
    store, path = _new_store(tmp_path)
    ok = _governed(store, FakeAdapter(response=_response()), store_text=True)
    ok.complete(LLMRequest(prompt="why?", system="sys", max_tokens=8))
    failing = _governed(
        store,
        FakeAdapter(exc=LLMRequestError("boom", status_code=500, request_id="req_x")),
        store_text=True,
    )
    with pytest.raises(LLMRequestError):
        failing.complete(LLMRequest(prompt="why?", system="sys", max_tokens=8))

    rows = _rows(path)
    assert len(rows) == 2
    for row in rows:
        for column, value in row.items():
            assert FAKE_KEY not in str(value), column
    assert FAKE_KEY.encode() not in path.read_bytes()
    assert not any("key" in c.lower() for c in EXPECTED_COLUMNS)


# ── Errors after send are logged, then re-raised unchanged ───────────────────


@pytest.mark.parametrize(
    ("make_error", "expected_stop", "expected_request_id"),
    [
        (
            lambda: LLMTruncatedError(
                "cut off",
                thinking_only=True,
                reason="max_tokens",
                stop_reason="max_tokens",
                usage={"prompt_tokens": 20, "completion_tokens": 64, "thinking_tokens": 64},
                request_id="req_t",
            ),
            "max_tokens",
            "req_t",
        ),
        (
            lambda: LLMRefusalError(
                "refused", stop_reason="refusal", usage={"prompt_tokens": 5}, request_id="req_r"
            ),
            "refusal",
            "req_r",
        ),
        (lambda: LLMRequestError("503", status_code=503), "error:LLMRequestError", None),
    ],
)
def test_adapter_error_writes_one_row_then_reraises_the_same_error(
    tmp_path: Path,
    make_error: Any,
    expected_stop: str,
    expected_request_id: Optional[str],
) -> None:
    store, path = _new_store(tmp_path)
    error = make_error()
    governed = _governed(store, FakeAdapter(exc=error), store_text=True)

    with pytest.raises(type(error)) as info:
        governed.complete(LLMRequest(prompt="why?", system="sys", max_tokens=64))

    assert info.value is error  # the very same object, not a wrapper
    rows = _rows(path)
    assert len(rows) == 1
    row = rows[0]
    assert row["stop_reason"] == expected_stop
    assert row["request_id"] == expected_request_id
    assert row["response_sha256"] is None
    assert row["response_text"] is None
    assert row["latency_ms"] == 250
    assert error.call_id == row["call_id"]  # the caller can find the row from the error
    assert error.tier == "fast"


def test_error_usage_is_logged(tmp_path: Path) -> None:
    store, path = _new_store(tmp_path)
    error = LLMTruncatedError(
        "cut off",
        thinking_only=True,
        reason="max_tokens",
        stop_reason="max_tokens",
        usage={"prompt_tokens": 20, "completion_tokens": 64, "thinking_tokens": 64},
    )
    with pytest.raises(LLMTruncatedError):
        _governed(store, FakeAdapter(exc=error)).complete(LLMRequest(prompt="p", max_tokens=64))
    row = _rows(path)[0]
    assert (row["input_tokens"], row["output_tokens"], row["thinking_tokens"]) == (20, 64, 64)
    assert row["cache_creation_input_tokens"] == 0


# ── Fail closed on a store failure ───────────────────────────────────────────


def _failing_settle(*args: Any, **kwargs: Any) -> None:
    raise LLMStoreError("disk full")


def test_store_vanishing_before_the_call_fails_closed_without_sending(tmp_path: Path) -> None:
    store, path = _new_store(tmp_path)
    adapter = FakeAdapter(response=_response("unlogged answer"))
    governed = _governed(store, adapter)
    path.unlink()  # the log vanishes between construction and the call

    with pytest.raises(LLMStoreError):
        governed.complete(LLMRequest(prompt="p", max_tokens=8))

    assert adapter.requests == []  # the budget could not be reserved, so nothing was sent
    assert not path.exists()  # and the store was not silently re-created


def test_store_failure_after_a_successful_call_raises_and_returns_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _new_store(tmp_path)
    adapter = FakeAdapter(response=_response("unlogged answer"))
    governed = _governed(store, adapter)
    monkeypatch.setattr(store, "settle", _failing_settle)

    with pytest.raises(LLMStoreError):
        governed.complete(LLMRequest(prompt="p", max_tokens=8))

    assert len(adapter.requests) == 1  # the call was sent; the answer is not handed out


def test_store_failure_while_logging_an_adapter_error_is_chained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _new_store(tmp_path)
    original = LLMRefusalError("refused", stop_reason="refusal")
    governed = _governed(store, FakeAdapter(exc=original))
    monkeypatch.setattr(store, "settle", _failing_settle)

    with pytest.raises(LLMStoreError) as info:
        governed.complete(LLMRequest(prompt="p", max_tokens=8))
    assert info.value.__cause__ is original


def test_adapter_errors_before_send_are_not_call_rows(tmp_path: Path) -> None:
    from cv_agent.llm.errors import LLMConfigError

    store, path = _new_store(tmp_path)
    governed = _governed(store, FakeAdapter(exc=LLMConfigError("bad setting")))
    with pytest.raises(LLMConfigError):
        governed.complete(LLMRequest(prompt="p", max_tokens=8))
    assert _rows(path) == []


# ── Concurrency: two processes both land ─────────────────────────────────────


def _writer(path: str, worker: int, count: int) -> None:
    store = LLMCallStore(Path(path), busy_timeout_s=30.0)
    for i in range(count):
        store.append(_record(f"w{worker}-{i}"))


def test_two_processes_writing_concurrently_both_land(tmp_path: Path) -> None:
    _, path = _new_store(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_writer, args=(str(path), w, 30)) for w in (1, 2)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=120)
    assert [p.exitcode for p in procs] == [0, 0]
    ids = [r["call_id"] for r in _rows(path)]
    assert len(ids) == 60
    assert set(ids) == {f"w{w}-{i}" for w in (1, 2) for i in range(30)}


# ── The clock ────────────────────────────────────────────────────────────────


def test_system_clock_is_utc_aware_and_monotonic() -> None:
    clock = SystemClock()
    now = clock.now_utc()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    first = clock.monotonic()
    assert clock.monotonic() >= first
