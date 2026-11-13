"""ADR-0023 §5 (governed log step) and §7.1 criterion 8, NARRATIVE part (slice S3c, issue #119).

A payload call writes ``payload_schema = "<schema_id>/<version>"`` and the payload's sha256 into its
call-log row; an unstructured (EXTRACTION) call leaves both NULL. No network: the adapter is a fake.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.catalog import load_catalog
from cv_agent.llm.errors import LLMCallError, LLMUnstructuredRequestError
from cv_agent.llm.governed import GovernedProvider
from cv_agent.llm.payload import HostedPayload, build_payload
from cv_agent.llm.policy import DataClass
from cv_agent.llm.sqlite_store import LLMCallStore
from cv_agent.requirements.structured import NarrativePayloadV1, structured_view
from tests.test_requirements_structured import _analyzer


class _Clock:
    def now_utc(self) -> datetime:
        return datetime(2026, 11, 13, 9, 30, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        return 1.0


class _Adapter(LLMProvider):
    provider_name = "fakeprovider"  # type: ignore[assignment]
    model_name = "claude-haiku-5-5"  # type: ignore[assignment]

    def __init__(self, fail: bool = False) -> None:
        self.requests: list[LLMRequest] = []
        self._fail = fail

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self._fail:
            raise LLMCallError("refused", stop_reason="refusal")
        return LLMResponse(content="ok", model=self.model_name, provider="fakeprovider",
                           usage={"prompt_tokens": 10, "completion_tokens": 5}, stop_reason="end_turn")


def governed(tmp_path: Path, task: str = "narrative", *, fail: bool = False,
             store_text: bool = False) -> tuple[GovernedProvider, _Adapter, Path]:
    path = tmp_path / "llm_calls.sqlite"
    LLMCallStore.initialise(path)
    adapter = _Adapter(fail)
    gov = GovernedProvider(hosted=True, task_class=task, tier="fast", adapter=adapter, store=LLMCallStore(path),
                           clock=_Clock(), catalog=load_catalog(), store_text=store_text)
    return gov, adapter, path


def rows(path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM llm_calls")]
    finally:
        conn.close()


def narrative_payload(request: str = "Detect people on a Jetson edge box.",
                      assumptions: Optional[dict[str, str]] = None) -> HostedPayload:
    view = structured_view(_analyzer().analyze(request, assumptions=assumptions))
    return build_payload(NarrativePayloadV1(view=view))


def test_a_narrative_payload_call_logs_schema_and_hash(tmp_path: Path) -> None:
    gov, adapter, path = governed(tmp_path)
    payload = narrative_payload()
    gov.complete(LLMRequest(payload=payload, max_tokens=100))
    (row,) = rows(path)
    assert row["payload_schema"] == "narrative/1"
    assert row["payload_sha256"] == payload.payload_sha256 and len(row["payload_sha256"]) == 64
    assert adapter.requests[0].payload is None  # the adapter sees rendered text only


def test_a_failed_payload_call_still_logs_schema_and_hash(tmp_path: Path) -> None:
    gov, _, path = governed(tmp_path, fail=True)
    payload = narrative_payload()
    with pytest.raises(LLMCallError):
        gov.complete(LLMRequest(payload=payload, max_tokens=100))
    (row,) = rows(path)
    assert (row["payload_schema"], row["payload_sha256"]) == ("narrative/1", payload.payload_sha256)
    assert row["stop_reason"] == "refusal"


def test_an_extraction_call_leaves_the_payload_columns_null(tmp_path: Path) -> None:
    gov, _, path = governed(tmp_path, "extraction")
    gov.complete(LLMRequest(prompt="p", max_tokens=100,
                            data_classes=frozenset({DataClass.PUBLIC_WEB, DataClass.PROJECT_METADATA})))
    (row,) = rows(path)
    assert row["payload_schema"] is None and row["payload_sha256"] is None


def test_a_refused_unstructured_narrative_writes_no_row(tmp_path: Path) -> None:
    gov, adapter, path = governed(tmp_path)
    with pytest.raises(LLMUnstructuredRequestError):
        gov.complete(LLMRequest(prompt="free text", max_tokens=100))
    assert adapter.requests == [] and rows(path) == []


def test_the_logged_hash_is_the_golden_hash_of_the_body_actually_sent(tmp_path: Path) -> None:
    """Review D3 / criterion 8: the row's hash equals the golden hash and the sha256 of the body the
    adapter received (the prompt is the schema instructions, a blank line, then the body)."""
    from tests.test_llm_payload_golden import CASES, GOLDEN

    case = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"][0]
    assert case["name"] == CASES[0]["name"]
    gov, adapter, path = governed(tmp_path)
    gov.complete(LLMRequest(payload=narrative_payload(case["request"], case["assumptions"] or None), max_tokens=100))
    body = adapter.requests[0].prompt.split("\n\n", 1)[1]
    (row,) = rows(path)
    assert row["payload_sha256"] == case["payload_sha256"] == hashlib.sha256(body.encode("utf-8")).hexdigest()
