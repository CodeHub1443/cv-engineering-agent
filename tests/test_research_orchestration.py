"""
Tests for cv_agent.graph.research — perform_research() orchestration.

Coverage:
  1. Successful path: fetch → LLM extraction → KnowledgeItem → KnowledgeStore
  2. ToolExecutor failure (failed_fetch)
  3. LLM extraction failure (failed_extraction)
  4. Missing/invalid provenance (failed_provenance)
  5. Source-class handling
  6. Publication/access-date handling
  7. Staleness metadata
  8. KnowledgeStore interaction
  9. Architecture boundary: no direct invoker usage, no direct network access
 10. Approval / pin integrity of the underlying ToolExecutor is untouched

No real network calls and no real LLM API calls are made.  All HTTP
interactions go through a FakeInvoker registered in a real ToolRegistry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from cv_agent.graph.research import (
    MAX_CONTENT_FOR_LLM,
    ResearchRequest,
    ResearchResult,
    _date_accessed_from_timestamp,
    _extract_json,
    _truncate_for_llm,
    perform_research,
)
from cv_agent.knowledge.models import ItemId, KnowledgeItem
from cv_agent.knowledge.store import InMemoryKnowledgeStore
from cv_agent.llm.mock import FakeLLMProvider
from cv_agent.tools.executor import ToolExecutor
from cv_agent.tools.models import (
    ToolId,
    ToolOutcome,
    ToolRequest,
    ToolSpec,
)
from cv_agent.tools.registry import ToolRegistry
from cv_agent.tools.web_research import TOOL_ID


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_ITEM_ID = ItemId("test-item-001")
_URL = "https://papers.example.com/yolo-v9.html"


def _minimal_request(**overrides: Any) -> ResearchRequest:
    """ResearchRequest with sensible defaults, overridable per test."""
    defaults = dict(
        url=_URL,
        item_id=_ITEM_ID,
        source_class="engineering_blog",
        topic_tags=("person_detection", "yolo"),
        staleness_horizon_days=60,
        claim_query="extract the main mAP claim",
        author_or_org="Example Author",
        date_published="2026-01-15",
    )
    defaults.update(overrides)
    return ResearchRequest(**defaults)


def _llm_json(**overrides: Any) -> str:
    """Produce a valid JSON string the FakeLLMProvider will return."""
    doc = {
        "claim": "YOLO-v9 achieves 55.6 mAP on COCO val2017",
        "conditions": "NVIDIA A100 GPU, batch size 32",
        "author_or_org": "ArXiv Research Group",
        "date_published": "2026-01-15",
    }
    doc.update(overrides)
    return json.dumps(doc)


@dataclass
class FakeInvoker:
    """Minimal ToolInvoker fake — returns a configurable ToolOutcome."""

    tool_id: str = TOOL_ID
    outcome: ToolOutcome = field(
        default_factory=lambda: ToolOutcome(
            success=True,
            output={
                "url": _URL,
                "content_text": "<html>benchmark content</html>",
                "content_type": "text/html",
                "date_accessed": "2026-09-28T12:00:00Z",
                "http_status": 200,
                "truncated": False,
            },
        )
    )
    call_count: int = 0
    calls: list[dict] = field(default_factory=list)

    def invoke(self, spec: ToolSpec, request: ToolRequest) -> ToolOutcome:
        self.call_count += 1
        self.calls.append({"spec_id": spec.tool_id, "inputs": dict(request.inputs)})
        return self.outcome


def _make_executor(invoker: FakeInvoker | None = None) -> tuple[ToolExecutor, FakeInvoker]:
    """Return a real ToolExecutor backed by a FakeInvoker registered in a real ToolRegistry."""
    if invoker is None:
        invoker = FakeInvoker()
    registry = ToolRegistry()
    spec = ToolSpec(
        tool_id=ToolId(TOOL_ID),
        name="web-research-fetch",
        description="fake spec for tests",
        transport="http",
        side_effecting=False,
        approval_policy="allowed",
        verified=True,
    )
    registry.register_spec(spec)
    registry.register_invoker(invoker)
    return ToolExecutor(registry), invoker


def _run(
    request: ResearchRequest | None = None,
    *,
    invoker: FakeInvoker | None = None,
    llm_response: str | None = None,
    store: InMemoryKnowledgeStore | None = None,
) -> tuple[ResearchResult, FakeInvoker, InMemoryKnowledgeStore]:
    """End-to-end helper: run perform_research() with controllable fakes."""
    req = request or _minimal_request()
    executor, inv = _make_executor(invoker)
    llm = FakeLLMProvider(fixed_response=llm_response if llm_response is not None else _llm_json())
    ks = store or InMemoryKnowledgeStore()
    result = perform_research(req, tool_executor=executor, llm_provider=llm, knowledge_store=ks)
    return result, inv, ks


# ---------------------------------------------------------------------------
# 1. Successful path
# ---------------------------------------------------------------------------


class TestSuccessfulResearch:
    def test_status_is_stored(self):
        result, _, _ = _run()
        assert result.status == "stored"

    def test_knowledge_item_present(self):
        result, _, _ = _run()
        assert result.knowledge_item is not None
        assert isinstance(result.knowledge_item, KnowledgeItem)

    def test_item_written_to_store(self):
        result, _, ks = _run()
        item = ks.get(ItemId(result.item_id))
        assert item is not None

    def test_stored_item_matches_returned_item(self):
        result, _, ks = _run()
        stored = ks.get(ItemId(result.item_id))
        assert stored == result.knowledge_item

    def test_claim_from_llm(self):
        llm_json = _llm_json(claim="mAP = 55.6 on COCO")
        result, _, _ = _run(llm_response=llm_json)
        assert result.knowledge_item is not None
        assert result.knowledge_item.claim == "mAP = 55.6 on COCO"

    def test_conditions_from_llm(self):
        llm_json = _llm_json(conditions="A100, batch=32")
        result, _, _ = _run(llm_response=llm_json)
        assert result.knowledge_item.conditions == "A100, batch=32"

    def test_conditions_fallback_when_llm_returns_null(self):
        req = _minimal_request(conditions="baseline conditions")
        llm_json = _llm_json(conditions=None)
        result, _, _ = _run(request=req, llm_response=llm_json)
        assert result.knowledge_item.conditions == "baseline conditions"

    def test_result_url_matches_final_url(self):
        redirected_url = "https://papers.example.com/canonical"
        invoker = FakeInvoker(
            outcome=ToolOutcome(
                success=True,
                output={
                    "url": redirected_url,
                    "content_text": "paper content",
                    "content_type": "text/html",
                    "date_accessed": "2026-09-28T10:00:00Z",
                    "http_status": 200,
                    "truncated": False,
                },
            )
        )
        result, _, _ = _run(invoker=invoker)
        assert result.url == redirected_url

    def test_topic_tags_preserved(self):
        req = _minimal_request(topic_tags=("detection", "benchmark", "coco"))
        result, _, _ = _run(request=req)
        assert result.knowledge_item.topic_tags == ("detection", "benchmark", "coco")

    def test_staleness_horizon_preserved(self):
        req = _minimal_request(staleness_horizon_days=90)
        result, _, _ = _run(request=req)
        assert result.knowledge_item.staleness_horizon_days == 90

    def test_invoker_called_exactly_once(self):
        _, invoker, _ = _run()
        assert invoker.call_count == 1

    def test_no_error_message_on_success(self):
        result, _, _ = _run()
        assert result.error_message is None

    def test_context_hint_forwarded_to_invoker(self):
        req = _minimal_request(context_hint="for YOLO research")
        _, invoker, _ = _run(request=req)
        assert invoker.calls[0]["inputs"].get("context_hint") == "for YOLO research"

    def test_no_context_hint_not_in_inputs(self):
        req = _minimal_request(context_hint=None)
        _, invoker, _ = _run(request=req)
        assert "context_hint" not in invoker.calls[0]["inputs"]


# ---------------------------------------------------------------------------
# 2. ToolExecutor failure → failed_fetch
# ---------------------------------------------------------------------------


class TestToolExecutorFailure:
    def _run_with_failed_outcome(self, outcome: ToolOutcome) -> ResearchResult:
        result, _, _ = _run(invoker=FakeInvoker(outcome=outcome))
        return result

    def test_invoker_network_failure_yields_failed_fetch(self):
        outcome = ToolOutcome(success=False, error_message="DNS failure")
        result = self._run_with_failed_outcome(outcome)
        assert result.status == "failed_fetch"

    def test_failed_fetch_has_error_message(self):
        outcome = ToolOutcome(success=False, error_message="404 Not Found")
        result = self._run_with_failed_outcome(outcome)
        assert result.error_message is not None
        assert len(result.error_message) > 0

    def test_failed_fetch_no_knowledge_item(self):
        outcome = ToolOutcome(success=False, error_message="timeout")
        result = self._run_with_failed_outcome(outcome)
        assert result.knowledge_item is None

    def test_failed_fetch_nothing_written_to_store(self):
        outcome = ToolOutcome(success=False, error_message="timeout")
        ks = InMemoryKnowledgeStore()
        _run(invoker=FakeInvoker(outcome=outcome), store=ks)
        assert ks.list_items() == []

    def test_unregistered_tool_yields_failed_fetch(self):
        """An empty ToolRegistry means no invoker → not_executable → failed_fetch."""
        empty_registry = ToolRegistry()
        executor = ToolExecutor(empty_registry)
        llm = FakeLLMProvider(fixed_response=_llm_json())
        ks = InMemoryKnowledgeStore()
        result = perform_research(
            _minimal_request(),
            tool_executor=executor,
            llm_provider=llm,
            knowledge_store=ks,
        )
        assert result.status == "failed_fetch"

    def test_failed_fetch_url_preserved(self):
        outcome = ToolOutcome(success=False, error_message="error")
        result = self._run_with_failed_outcome(outcome)
        assert result.url == _URL


# ---------------------------------------------------------------------------
# 3. LLM extraction failure → failed_extraction
# ---------------------------------------------------------------------------


class TestLLMExtractionFailure:
    def test_non_json_response_yields_failed_extraction(self):
        result, _, _ = _run(llm_response="I found some interesting results but cannot summarize.")
        assert result.status == "failed_extraction"

    def test_empty_llm_response_yields_failed_extraction(self):
        result, _, _ = _run(llm_response="")
        assert result.status == "failed_extraction"

    def test_null_claim_yields_failed_extraction(self):
        llm_json = _llm_json(claim=None)
        result, _, _ = _run(llm_response=llm_json)
        assert result.status == "failed_extraction"

    def test_blank_claim_yields_failed_extraction(self):
        llm_json = _llm_json(claim="   ")
        result, _, _ = _run(llm_response=llm_json)
        assert result.status == "failed_extraction"

    def test_extraction_failure_has_error_message(self):
        result, _, _ = _run(llm_response="not json")
        assert result.error_message is not None

    def test_extraction_failure_no_knowledge_item(self):
        result, _, _ = _run(llm_response="not json")
        assert result.knowledge_item is None

    def test_extraction_failure_nothing_written_to_store(self):
        ks = InMemoryKnowledgeStore()
        _run(llm_response="not json", store=ks)
        assert ks.list_items() == []

    def test_json_wrapped_in_markdown_code_block_is_parsed(self):
        wrapped = f"```json\n{_llm_json()}\n```"
        result, _, _ = _run(llm_response=wrapped)
        # Should succeed — _extract_json finds the { } substring
        assert result.status == "stored"

    def test_json_with_leading_prose_is_parsed(self):
        with_prose = "Here is the extracted data:\n" + _llm_json()
        result, _, _ = _run(llm_response=with_prose)
        assert result.status == "stored"


# ---------------------------------------------------------------------------
# 4. Missing/invalid provenance → failed_provenance
# ---------------------------------------------------------------------------


class TestProvenanceFailure:
    def test_missing_author_and_no_fallback_yields_failed_provenance(self):
        req = _minimal_request(author_or_org=None)
        llm_json = _llm_json(author_or_org=None)
        result, _, _ = _run(request=req, llm_response=llm_json)
        assert result.status == "failed_provenance"

    def test_missing_date_published_and_no_fallback_yields_failed_provenance(self):
        req = _minimal_request(date_published=None)
        llm_json = _llm_json(date_published=None)
        result, _, _ = _run(request=req, llm_response=llm_json)
        assert result.status == "failed_provenance"

    def test_invalid_date_published_format_yields_failed_provenance(self):
        req = _minimal_request(date_published=None)
        llm_json = _llm_json(date_published="not-a-date")
        result, _, _ = _run(request=req, llm_response=llm_json)
        assert result.status == "failed_provenance"

    def test_blank_author_string_treated_as_absent(self):
        req = _minimal_request(author_or_org=None)
        llm_json = _llm_json(author_or_org="   ")
        result, _, _ = _run(request=req, llm_response=llm_json)
        assert result.status == "failed_provenance"

    def test_caller_fallback_author_used_when_llm_returns_null(self):
        req = _minimal_request(author_or_org="Fallback Author Inc.")
        llm_json = _llm_json(author_or_org=None)
        result, _, _ = _run(request=req, llm_response=llm_json)
        assert result.status == "stored"
        assert result.knowledge_item.provenance.author_or_org == "Fallback Author Inc."

    def test_caller_fallback_date_used_when_llm_returns_null(self):
        req = _minimal_request(date_published="2025-06-01")
        llm_json = _llm_json(date_published=None)
        result, _, _ = _run(request=req, llm_response=llm_json)
        assert result.status == "stored"
        assert result.knowledge_item.provenance.date_published == "2025-06-01"

    def test_llm_extracted_author_overrides_fallback(self):
        req = _minimal_request(author_or_org="Fallback Author")
        llm_json = _llm_json(author_or_org="LLM Extracted Author")
        result, _, _ = _run(request=req, llm_response=llm_json)
        assert result.knowledge_item.provenance.author_or_org == "LLM Extracted Author"

    def test_failed_provenance_nothing_written_to_store(self):
        req = _minimal_request(author_or_org=None)
        llm_json = _llm_json(author_or_org=None)
        ks = InMemoryKnowledgeStore()
        _run(request=req, llm_response=llm_json, store=ks)
        assert ks.list_items() == []


# ---------------------------------------------------------------------------
# 5. Source-class handling
# ---------------------------------------------------------------------------


class TestSourceClassHandling:
    @pytest.mark.parametrize(
        "source_class, expected_weight",
        [
            ("peer_reviewed_research", "high"),
            ("official_documentation", "high"),
            ("official_repository_or_release_notes", "high"),
            ("reputable_benchmark", "high"),
            ("engineering_blog", "medium"),
            ("model_zoo_or_leaderboard", "medium"),
            ("community_discussion", "low_medium"),
            ("professional_post", "signal_not_evidence"),
        ],
    )
    def test_evidence_weight_matches_policy_table(self, source_class, expected_weight):
        req = _minimal_request(source_class=source_class)
        result, _, _ = _run(request=req)
        assert result.status == "stored"
        assert result.knowledge_item.evidence_weight() == expected_weight

    def test_source_class_preserved_in_provenance(self):
        req = _minimal_request(source_class="peer_reviewed_research")
        result, _, _ = _run(request=req)
        assert result.knowledge_item.provenance.source_class == "peer_reviewed_research"

    def test_professional_post_cannot_claim_high_weight(self):
        req = _minimal_request(source_class="professional_post")
        result, _, _ = _run(request=req)
        assert result.knowledge_item.evidence_weight() != "high"
        assert result.knowledge_item.evidence_weight() == "signal_not_evidence"


# ---------------------------------------------------------------------------
# 6. Date handling
# ---------------------------------------------------------------------------


class TestDateHandling:
    def test_date_accessed_truncated_from_timestamp(self):
        invoker = FakeInvoker(
            outcome=ToolOutcome(
                success=True,
                output={
                    "url": _URL,
                    "content_text": "content",
                    "content_type": "text/html",
                    "date_accessed": "2026-09-28T14:32:01Z",
                    "http_status": 200,
                    "truncated": False,
                },
            )
        )
        result, _, _ = _run(invoker=invoker)
        assert result.knowledge_item.provenance.date_accessed == "2026-09-28"

    def test_date_accessed_already_ymd_form(self):
        assert _date_accessed_from_timestamp("2026-09-28T00:00:00Z") == "2026-09-28"

    def test_malformed_date_accessed_falls_back_to_today(self):
        result = _date_accessed_from_timestamp("not-a-date")
        # Should be YYYY-MM-DD format — just check length and separators
        assert len(result) == 10
        assert result[4] == "-" and result[7] == "-"

    def test_date_published_from_llm_preserved(self):
        llm_json = _llm_json(date_published="2026-03-15")
        result, _, _ = _run(llm_response=llm_json)
        assert result.knowledge_item.provenance.date_published == "2026-03-15"

    def test_date_published_from_fallback_preserved(self):
        req = _minimal_request(date_published="2025-11-01")
        llm_json = _llm_json(date_published=None)
        result, _, _ = _run(request=req, llm_response=llm_json)
        assert result.knowledge_item.provenance.date_published == "2025-11-01"


# ---------------------------------------------------------------------------
# 7. Staleness metadata
# ---------------------------------------------------------------------------


class TestStalenessMetadata:
    def test_staleness_horizon_days_stored(self):
        req = _minimal_request(staleness_horizon_days=30)
        result, _, _ = _run(request=req)
        assert result.knowledge_item.staleness_horizon_days == 30

    def test_item_not_stale_immediately_after_store(self):
        from datetime import date

        req = _minimal_request(staleness_horizon_days=180)
        result, _, _ = _run(request=req)
        today = date.today()
        assert result.knowledge_item.is_stale(today) is False

    def test_item_stale_when_past_horizon(self):
        from datetime import date

        invoker = FakeInvoker(
            outcome=ToolOutcome(
                success=True,
                output={
                    "url": _URL,
                    "content_text": "old content",
                    "content_type": "text/html",
                    "date_accessed": "2026-01-01T00:00:00Z",
                    "http_status": 200,
                    "truncated": False,
                },
            )
        )
        req = _minimal_request(staleness_horizon_days=7)
        result, _, _ = _run(request=req, invoker=invoker)
        future_date = date(2026, 9, 1)
        assert result.knowledge_item.is_stale(future_date) is True


# ---------------------------------------------------------------------------
# 8. KnowledgeStore interaction
# ---------------------------------------------------------------------------


class TestKnowledgeStoreInteraction:
    def test_successful_run_writes_exactly_one_item(self):
        ks = InMemoryKnowledgeStore()
        _run(store=ks)
        assert len(ks.list_items()) == 1

    def test_multiple_successful_runs_write_multiple_items(self):
        ks = InMemoryKnowledgeStore()
        for i in range(3):
            req = _minimal_request(item_id=ItemId(f"item-{i}"))
            _run(request=req, store=ks)
        assert len(ks.list_items()) == 3

    def test_stored_item_retrievable_by_id(self):
        ks = InMemoryKnowledgeStore()
        req = _minimal_request(item_id=ItemId("unique-item-xyz"))
        _run(request=req, store=ks)
        assert ks.get(ItemId("unique-item-xyz")) is not None

    def test_store_failure_returns_failed_store(self):
        class FailingStore:
            def put(self, item):  # noqa: ANN001, ANN201
                raise RuntimeError("disk full")

            def get(self, item_id):  # noqa: ANN001, ANN201
                return None

            def list_items(self):  # noqa: ANN201
                return []

            def query(self, **kwargs):  # noqa: ANN003, ANN201
                return []

        executor, _ = _make_executor()
        llm = FakeLLMProvider(fixed_response=_llm_json())
        result = perform_research(
            _minimal_request(),
            tool_executor=executor,
            llm_provider=llm,
            knowledge_store=FailingStore(),
        )
        assert result.status == "failed_store"
        assert "disk full" in (result.error_message or "")

    def test_store_failure_no_item_in_result(self):
        class FailingStore:
            def put(self, item):  # noqa: ANN001, ANN201
                raise RuntimeError("no space")

            def get(self, item_id):  # noqa: ANN001, ANN201
                return None

            def list_items(self):  # noqa: ANN201
                return []

            def query(self, **kwargs):  # noqa: ANN003, ANN201
                return []

        executor, _ = _make_executor()
        llm = FakeLLMProvider(fixed_response=_llm_json())
        result = perform_research(
            _minimal_request(),
            tool_executor=executor,
            llm_provider=llm,
            knowledge_store=FailingStore(),
        )
        assert result.knowledge_item is None

    def test_query_by_topic_tag_finds_stored_item(self):
        from datetime import date

        ks = InMemoryKnowledgeStore()
        req = _minimal_request(topic_tags=("person_detection", "yolo"), staleness_horizon_days=90)
        _run(request=req, store=ks)
        matches = ks.query(topic_tags=["person_detection"], exclude_stale_as_of=date.today())
        assert len(matches) == 1


# ---------------------------------------------------------------------------
# 9. Architecture boundary
# ---------------------------------------------------------------------------


class TestArchitectureBoundary:
    def test_research_module_does_not_import_urllib_request(self):
        """The graph node must not make network calls directly — only ToolExecutor does."""
        import ast
        import importlib.util
        import pathlib

        src = pathlib.Path(importlib.util.find_spec("cv_agent.graph.research").origin)
        tree = ast.parse(src.read_text())
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("urllib"):
                    violations.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("urllib"):
                        violations.append(alias.name)
        assert violations == [], f"Direct network imports found: {violations}"

    def test_research_module_does_not_import_cv_agent_execution(self):
        """research.py must not bypass the ToolExecutor boundary."""
        import ast
        import importlib.util
        import pathlib

        src = pathlib.Path(importlib.util.find_spec("cv_agent.graph.research").origin)
        tree = ast.parse(src.read_text())
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("cv_agent.execution") or node.module.startswith("cv_agent.skills"):
                    violations.append(node.module)
        assert violations == [], f"Forbidden imports: {violations}"

    def test_invocation_goes_through_tool_executor(self):
        """The FakeInvoker is ONLY callable through ToolExecutor, never directly."""
        _, invoker, _ = _run()
        # Proves the path: perform_research → ToolExecutor → FakeInvoker
        assert invoker.call_count == 1

    def test_unregistered_tool_is_rejected_by_tool_executor_not_bypassed(self):
        """Bypass detection: an empty registry → ToolExecutor produces not_executable,
        which perform_research reports as failed_fetch without ever seeing raw HTML."""
        empty_registry = ToolRegistry()
        executor = ToolExecutor(empty_registry)
        llm = FakeLLMProvider(fixed_response=_llm_json())
        ks = InMemoryKnowledgeStore()
        result = perform_research(
            _minimal_request(),
            tool_executor=executor,
            llm_provider=llm,
            knowledge_store=ks,
        )
        assert result.status == "failed_fetch"
        assert ks.list_items() == []


# ---------------------------------------------------------------------------
# 10. Approval / pin integrity
# ---------------------------------------------------------------------------


class TestApprovalPinIntegrity:
    def test_allowed_tool_requires_no_approval(self):
        """web-research-fetch has approval_policy="allowed" — no request.approved flag needed."""
        result, invoker, _ = _run()
        assert result.status == "stored"
        # The invoker was called — no approval gate blocked it
        assert invoker.call_count == 1

    def test_pin_mismatch_caught_by_tool_executor(self):
        """If the invoker is replaced mid-run, ToolExecutor's pin check fires."""
        registry = ToolRegistry()
        spec = ToolSpec(
            tool_id=ToolId(TOOL_ID),
            name="web-research-fetch",
            description="test",
            transport="http",
            side_effecting=False,
            approval_policy="allowed",
            verified=True,
        )
        registry.register_spec(spec)
        invoker1 = FakeInvoker()
        registry.register_invoker(invoker1)

        # Capture a pin while invoker1 is registered
        pin = registry.pin(ToolId(TOOL_ID))

        # Replace with a new invoker instance — bumps the generation
        registry.register_invoker(FakeInvoker())

        executor = ToolExecutor(registry)
        llm = FakeLLMProvider(fixed_response=_llm_json())
        ks = InMemoryKnowledgeStore()

        # Manually call ToolExecutor with the stale pin to confirm mismatch behaviour
        tr = executor.invoke(
            ToolId(TOOL_ID), ToolRequest(inputs={"url": _URL}, expected_tool_pin=pin)
        )
        assert tr.status == "not_executable"
        assert tr.error is not None
        assert tr.error.category == "tool_mismatch"
        # perform_research itself doesn't supply a pin (approval_policy="allowed"),
        # so a normal perform_research call still goes through even after replacement
        result = perform_research(
            _minimal_request(), tool_executor=executor, llm_provider=llm, knowledge_store=ks
        )
        assert result.status == "stored"

    def test_approval_required_spec_without_pin_blocks_invocation(self):
        """A hypothetical approval_required web-research-fetch must be rejected
        by ToolExecutor without a pin, even if the caller sets approved=True —
        rule E1 from ADR-0003 §10 / ADR-0005 §9."""
        registry = ToolRegistry()
        spec = ToolSpec(
            tool_id=ToolId(TOOL_ID),
            name="web-research-fetch",
            description="test",
            transport="http",
            side_effecting=False,
            approval_policy="approval_required",
            verified=True,
        )
        registry.register_spec(spec)
        registry.register_invoker(FakeInvoker())
        executor = ToolExecutor(registry)

        # perform_research doesn't supply a pin → ToolExecutor rule E1 fires
        llm = FakeLLMProvider(fixed_response=_llm_json())
        ks = InMemoryKnowledgeStore()
        result = perform_research(
            _minimal_request(), tool_executor=executor, llm_provider=llm, knowledge_store=ks
        )
        # ToolExecutor returns "rejected" → perform_research maps this to failed_fetch
        assert result.status == "failed_fetch"
        assert ks.list_items() == []


# ---------------------------------------------------------------------------
# 11. Internal helper unit tests
# ---------------------------------------------------------------------------


class TestInternalHelpers:
    def test_extract_json_valid(self):
        obj = {"a": 1, "b": "x"}
        assert _extract_json(json.dumps(obj)) == obj

    def test_extract_json_with_surrounding_text(self):
        text = "here: " + json.dumps({"claim": "x"}) + " end"
        result = _extract_json(text)
        assert result is not None
        assert result["claim"] == "x"

    def test_extract_json_returns_none_on_garbage(self):
        assert _extract_json("totally not json") is None

    def test_extract_json_empty_string(self):
        assert _extract_json("") is None

    def test_truncate_for_llm_short_text_unchanged(self):
        short = "abc"
        assert _truncate_for_llm(short) == short

    def test_truncate_for_llm_at_limit_not_truncated(self):
        text = "x" * MAX_CONTENT_FOR_LLM
        result = _truncate_for_llm(text)
        assert result == text

    def test_truncate_for_llm_over_limit_is_truncated(self):
        text = "x" * (MAX_CONTENT_FOR_LLM + 100)
        result = _truncate_for_llm(text)
        assert len(result) < len(text)
        assert "[content truncated" in result

    def test_date_accessed_from_full_timestamp(self):
        assert _date_accessed_from_timestamp("2026-09-28T14:32:01Z") == "2026-09-28"

    def test_date_accessed_from_midnight(self):
        assert _date_accessed_from_timestamp("2026-01-01T00:00:00Z") == "2026-01-01"
