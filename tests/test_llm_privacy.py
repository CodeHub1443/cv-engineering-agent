"""Slice G4 acceptance tests: privacy default-deny for hosted calls.

ADR-0020 §3 item 5(1), §3 item 7 and §7 "G4"; D-092; issue #95. No network, no real key,
no real state root: every store lives under ``tmp_path``, every adapter is a fake.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from cv_agent.graph.research import perform_research
from cv_agent.knowledge.models import IngestPath
from cv_agent.knowledge.store import InMemoryKnowledgeStore
from cv_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cv_agent.llm.catalog import load_catalog
from cv_agent.llm.errors import LLMDataClassNotAllowedError, LLMError
from cv_agent.llm.governed import GovernedProvider
from cv_agent.llm.mock import FakeLLMProvider
from cv_agent.llm.policy import DEFAULT_HOSTED_ALLOWED, DataClass, TaskClass
from cv_agent.llm.sqlite_store import LLMCallStore
from cv_agent.model_selection.models import ModelCandidate
from cv_agent.model_selection.selector import build_candidate, select_candidate
from cv_agent.requirements.analyzer import RequirementsAnalyzer
from tests.test_model_selection import _REQS, _comparison, _item
from tests.test_research_orchestration import _llm_json, _make_executor, _minimal_request

T0 = datetime(2026, 11, 12, 9, 30, 0, tzinfo=timezone.utc)
SECRET = "TOPSECRET-PROMPT-TEXT"
PW, PM, PD = DataClass.PUBLIC_WEB, DataClass.PROJECT_METADATA, DataClass.PROJECT_DATA


class FakeClock:
    def now_utc(self) -> datetime:
        return T0

    def monotonic(self) -> float:
        return 1.0


class CountingAdapter(LLMProvider):
    """Counts how many times the 'network' was reached."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return "fakeprovider"

    @property
    def model_name(self) -> str:
        return "claude-haiku-5-5"

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            content="ok",
            model=self.model_name,
            provider="fakeprovider",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            stop_reason="end_turn",
        )


def _setup(
    tmp_path: Path, *, hosted: bool = True, allowed: Optional[frozenset[DataClass]] = None
) -> tuple[GovernedProvider, CountingAdapter, Path]:
    path = tmp_path / "llm_calls.sqlite"
    LLMCallStore.initialise(path)
    adapter = CountingAdapter()
    kwargs = {} if allowed is None else {"allowed_hosted": allowed}
    governed = GovernedProvider(
        task_class="extraction",
        tier="fast",
        adapter=adapter,
        store=LLMCallStore(path),
        clock=FakeClock(),
        catalog=load_catalog(),
        hosted=hosted,
        **kwargs,
    )
    return governed, adapter, path


def _rows(path: Path) -> tuple[int, int]:
    conn = sqlite3.connect(path)
    try:
        return (
            conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM llm_budget").fetchone()[0],
        )
    finally:
        conn.close()


def _req(classes: frozenset[DataClass] = frozenset(), prompt: str = SECRET) -> LLMRequest:
    return LLMRequest(prompt=prompt, system="sys " + SECRET, max_tokens=100, data_classes=classes)


def test_defaults_are_the_owner_decision() -> None:
    assert DEFAULT_HOSTED_ALLOWED == frozenset({PW, PM})
    assert {t.value for t in TaskClass} == {"extraction", "selection", "narrative"}
    assert LLMRequest(prompt="x").data_classes == frozenset()


def test_project_data_refused_without_network_or_rows(tmp_path: Path) -> None:
    governed, adapter, path = _setup(tmp_path)
    with pytest.raises(LLMDataClassNotAllowedError):
        governed.complete(_req(frozenset({PD})))
    assert adapter.calls == 0
    assert _rows(path) == (0, 0)


def test_empty_data_classes_count_as_project_data(tmp_path: Path) -> None:
    governed, adapter, path = _setup(tmp_path)
    with pytest.raises(LLMDataClassNotAllowedError) as info:
        governed.complete(_req(frozenset()))
    assert info.value.blocked == frozenset({PD})
    assert adapter.calls == 0
    assert _rows(path) == (0, 0)


def test_public_web_and_metadata_are_allowed(tmp_path: Path) -> None:
    governed, adapter, path = _setup(tmp_path)
    response = governed.complete(_req(frozenset({PW, PM})))
    assert response.content == "ok"
    assert adapter.calls == 1
    assert _rows(path) == (1, 1)


def test_mixed_request_refused_and_lists_only_project_data(tmp_path: Path) -> None:
    governed, adapter, _ = _setup(tmp_path)
    with pytest.raises(LLMDataClassNotAllowedError) as info:
        governed.complete(_req(frozenset({PW, PD})))
    assert info.value.blocked == frozenset({PD})
    assert "project_data" in str(info.value)
    assert "public_web" not in str(info.value)
    assert adapter.calls == 0


def test_not_hosted_has_no_privacy_refusal(tmp_path: Path) -> None:
    governed, adapter, _ = _setup(tmp_path, hosted=False)
    governed.complete(_req(frozenset({PD})))
    governed.complete(_req(frozenset()))
    assert adapter.calls == 2


def test_owner_override_allows_project_data(tmp_path: Path) -> None:
    governed, adapter, _ = _setup(tmp_path, allowed=frozenset({PW, PM, PD}))
    governed.complete(_req(frozenset({PD})))
    assert adapter.calls == 1


def test_privacy_runs_before_input_cap(tmp_path: Path) -> None:
    governed, adapter, path = _setup(tmp_path)
    with pytest.raises(LLMDataClassNotAllowedError):
        governed.complete(_req(frozenset({PD}), prompt="x" * 100_000))
    assert adapter.calls == 0
    assert _rows(path) == (0, 0)


def test_error_text_has_no_prompt_text(tmp_path: Path) -> None:
    governed, _, _ = _setup(tmp_path)
    with pytest.raises(LLMDataClassNotAllowedError) as info:
        governed.complete(_req(frozenset({PD})))
    assert isinstance(info.value, LLMError)
    assert SECRET not in str(info.value)
    assert SECRET not in repr(info.value)
    assert "extraction" in str(info.value) and "fast" in str(info.value)


class CapturingLLM(FakeLLMProvider):
    def __init__(self, response: Optional[str] = None) -> None:
        super().__init__(fixed_response=response)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return super().complete(request)


def test_research_extraction_declares_public_web_and_metadata() -> None:
    llm = CapturingLLM(_llm_json())
    executor, _ = _make_executor()
    perform_research(
        _minimal_request(), tool_executor=executor, llm_provider=llm, knowledge_store=InMemoryKnowledgeStore()
    )
    assert [r.data_classes for r in llm.requests] == [frozenset({PW, PM})]


def test_selector_sends_a_payload_with_derived_classes_never_project_data() -> None:
    """ADR-0023 §3.5: the selector sends a SelectionPayloadV1 and declares no class itself. The derived
    classes are {PROJECT_METADATA} (no eligible public claim) or {PROJECT_METADATA, PUBLIC_WEB}, never
    PROJECT_DATA."""
    llm = CapturingLLM("{}")
    select_candidate(_comparison(), requirements=_REQS, llm_provider=llm)  # items default to ingest=UNSPECIFIED
    web = _comparison((_web_candidate(),))
    select_candidate(web, requirements=_REQS, llm_provider=llm)
    assert [r.data_classes for r in llm.requests] == [frozenset(), frozenset()]
    assert all(r.payload is not None and r.prompt == "" and r.system is None for r in llm.requests)
    assert [r.payload.data_classes for r in llm.requests] == [frozenset({PM}), frozenset({PM, PW})]  # type: ignore[union-attr]
    assert all(PD not in r.payload.data_classes for r in llm.requests)  # type: ignore[union-attr]


def _web_candidate() -> ModelCandidate:
    item = dataclasses.replace(_item("web-1", "A public claim"), ingest=IngestPath.WEB_FETCH)
    return build_candidate(
        candidate_id="w", model_family="W", task_support=("object_detection",), evidence_items=(item,),
        strengths=(), limitations=(), compatibility_constraints=(),
    )


def test_analyzer_narrative_sends_a_payload_not_a_label() -> None:
    """ADR-0023 §3.2, §3.3: the LLM narrative carries NarrativePayloadV1, declares no label, and its
    derived classes are PROJECT_METADATA only. The default (template) mode makes no call at all."""
    llm = CapturingLLM("narrative")
    RequirementsAnalyzer(task_resolver=MagicMock(), llm=llm).analyze(f"detect people {SECRET}")
    assert llm.requests == []
    RequirementsAnalyzer(task_resolver=MagicMock(), llm=llm, narrative="llm").analyze(f"detect people {SECRET}")
    (req,) = llm.requests
    assert req.data_classes == frozenset() and req.prompt == "" and req.payload is not None
    assert req.payload.data_classes == frozenset({PM}) and SECRET not in req.payload.body_json
