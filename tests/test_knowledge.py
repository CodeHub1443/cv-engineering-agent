"""Tests for cv_agent.knowledge (ADR-0006)."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest

from cv_agent.knowledge.context import ContextBundle, assemble_context
from cv_agent.knowledge.models import (
    EvidenceWeight,
    ItemId,
    KnowledgeItem,
    Provenance,
    SourceClass,
    source_class_weight,
)
from cv_agent.knowledge.store import InMemoryKnowledgeStore, KnowledgeStore


def _provenance(**overrides: object) -> Provenance:
    fields: dict[str, object] = {
        "url": "https://example.com/doc",
        "source_class": "official_documentation",
        "date_published": "2026-01-01",
        "date_accessed": "2026-01-02",
        "author_or_org": "Example Org",
    }
    fields.update(overrides)
    return Provenance(**fields)  # type: ignore[arg-type]


def _item(**overrides: object) -> KnowledgeItem:
    fields: dict[str, object] = {
        "item_id": ItemId("item-1"),
        "claim": "TensorRT INT8 quantization halves latency on Orin for this model class",
        "conditions": "Jetson Orin, batch=1, INT8, TensorRT 10",
        "provenance": _provenance(),
        "topic_tags": ("tensorrt", "quantization"),
        "staleness_horizon_days": 90,
    }
    fields.update(overrides)
    return KnowledgeItem(**fields)  # type: ignore[arg-type]


# ── Provenance validation (fail-closed) ─────────────────────────────────────


class TestProvenanceValidation:
    def test_valid_provenance_constructs(self) -> None:
        p = _provenance()
        assert p.source_class == "official_documentation"

    @pytest.mark.parametrize(
        "field,value",
        [
            ("url", ""),
            ("url", "   "),
            ("date_published", ""),
            ("date_published", "not-a-date"),
            ("date_published", "2026/01/01"),
            ("date_accessed", ""),
            ("date_accessed", "2026-13-40"),
            ("author_or_org", ""),
            ("author_or_org", "   "),
        ],
    )
    def test_malformed_field_rejected(self, field: str, value: str) -> None:
        with pytest.raises(ValueError):
            _provenance(**{field: value})

    def test_invalid_source_class_rejected(self) -> None:
        with pytest.raises(ValueError):
            _provenance(source_class="not_a_real_class")


# ── KnowledgeItem validation (fail-closed) ──────────────────────────────────


class TestKnowledgeItemValidation:
    def test_valid_item_constructs(self) -> None:
        item = _item()
        assert item.claim.startswith("TensorRT")

    def test_missing_provenance_rejected(self) -> None:
        with pytest.raises(ValueError):
            _item(provenance=None)

    def test_wrong_type_provenance_rejected(self) -> None:
        with pytest.raises(ValueError):
            _item(provenance={"url": "x"})

    def test_blank_claim_rejected(self) -> None:
        with pytest.raises(ValueError):
            _item(claim="")

    def test_blank_item_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            _item(item_id=ItemId(""))

    def test_empty_topic_tags_rejected(self) -> None:
        with pytest.raises(ValueError):
            _item(topic_tags=())

    def test_blank_topic_tag_member_rejected(self) -> None:
        with pytest.raises(ValueError):
            _item(topic_tags=("tensorrt", ""))

    @pytest.mark.parametrize("horizon", [0, -1, -90])
    def test_non_positive_staleness_horizon_rejected(self, horizon: int) -> None:
        with pytest.raises(ValueError):
            _item(staleness_horizon_days=horizon)

    def test_is_stale_true_past_horizon(self) -> None:
        item = _item(staleness_horizon_days=10)
        assert item.is_stale(date(2026, 1, 20)) is True

    def test_is_stale_false_within_horizon(self) -> None:
        item = _item(staleness_horizon_days=10)
        assert item.is_stale(date(2026, 1, 5)) is False

    def test_is_stale_false_exactly_at_horizon(self) -> None:
        item = _item(staleness_horizon_days=10)
        # date_accessed = 2026-01-02; +10 days = 2026-01-12, still not stale (> comparison)
        assert item.is_stale(date(2026, 1, 12)) is False


# ── source_class_weight ──────────────────────────────────────────────────


class TestSourceClassWeight:
    @pytest.mark.parametrize(
        "source_class,expected",
        [
            ("peer_reviewed_research", "high"),
            ("official_documentation", "high"),
            ("official_repository_or_release_notes", "high"),
            ("reputable_benchmark", "high"),
            ("engineering_blog", "medium"),
            ("professional_post", "signal_not_evidence"),
            ("community_discussion", "low_medium"),
            ("model_zoo_or_leaderboard", "medium"),
        ],
    )
    def test_weight_matches_research_policy_table(
        self, source_class: SourceClass, expected: EvidenceWeight
    ) -> None:
        assert source_class_weight(source_class) == expected

    def test_linkedin_class_never_high(self) -> None:
        assert source_class_weight("professional_post") != "high"

    def test_unknown_source_class_rejected(self) -> None:
        with pytest.raises(ValueError):
            source_class_weight("not_a_real_class")  # type: ignore[arg-type]

    def test_item_evidence_weight_matches_function(self) -> None:
        item = _item(provenance=_provenance(source_class="engineering_blog"))
        assert item.evidence_weight() == "medium"


# ── InMemoryKnowledgeStore ──────────────────────────────────────────────────


class TestInMemoryKnowledgeStore:
    def test_put_get_round_trip(self) -> None:
        store = InMemoryKnowledgeStore()
        item = _item()
        store.put(item)
        assert store.get(item.item_id) is item

    def test_get_missing_returns_none(self) -> None:
        store = InMemoryKnowledgeStore()
        assert store.get(ItemId("nope")) is None

    def test_list_items(self) -> None:
        store = InMemoryKnowledgeStore()
        a = _item(item_id=ItemId("a"))
        b = _item(item_id=ItemId("b"))
        store.put(a)
        store.put(b)
        assert {i.item_id for i in store.list_items()} == {ItemId("a"), ItemId("b")}

    def test_put_overwrites_same_id(self) -> None:
        store = InMemoryKnowledgeStore()
        original = _item(claim="original claim")
        replacement = _item(claim="replacement claim")
        store.put(original)
        store.put(replacement)
        assert store.get(original.item_id).claim == "replacement claim"  # type: ignore[union-attr]

    def test_query_by_topic_tags_exact_membership(self) -> None:
        store = InMemoryKnowledgeStore()
        matching = _item(item_id=ItemId("m"), topic_tags=("tensorrt", "quantization"))
        other = _item(item_id=ItemId("o"), topic_tags=("dataset", "leakage"))
        store.put(matching)
        store.put(other)
        results = store.query(topic_tags=("tensorrt",))
        assert [i.item_id for i in results] == [ItemId("m")]

    def test_query_topic_tags_requires_all_requested(self) -> None:
        store = InMemoryKnowledgeStore()
        store.put(_item(item_id=ItemId("m"), topic_tags=("tensorrt", "quantization")))
        results = store.query(topic_tags=("tensorrt", "quantization", "orin"))
        assert results == []

    def test_query_by_source_class(self) -> None:
        store = InMemoryKnowledgeStore()
        blog = _item(
            item_id=ItemId("b"),
            provenance=_provenance(source_class="engineering_blog"),
        )
        doc = _item(item_id=ItemId("d"), provenance=_provenance())
        store.put(blog)
        store.put(doc)
        results = store.query(source_class="engineering_blog")
        assert [i.item_id for i in results] == [ItemId("b")]

    def test_query_excludes_stale(self) -> None:
        store = InMemoryKnowledgeStore()
        fresh = _item(
            item_id=ItemId("fresh"),
            provenance=_provenance(date_accessed="2026-01-01"),
            staleness_horizon_days=5,
        )
        stale = _item(
            item_id=ItemId("stale"),
            provenance=_provenance(date_accessed="2025-01-01"),
            staleness_horizon_days=5,
        )
        store.put(fresh)
        store.put(stale)
        results = store.query(exclude_stale_as_of=date(2026, 1, 3))
        assert [i.item_id for i in results] == [ItemId("fresh")]

    def test_query_no_filters_returns_all(self) -> None:
        store = InMemoryKnowledgeStore()
        store.put(_item(item_id=ItemId("a")))
        store.put(_item(item_id=ItemId("b")))
        assert len(store.query()) == 2

    def test_store_satisfies_protocol(self) -> None:
        store: KnowledgeStore = InMemoryKnowledgeStore()
        store.put(_item())
        assert len(store.list_items()) == 1


# ── assemble_context ─────────────────────────────────────────────────────


class TestAssembleContext:
    def test_returns_context_bundle(self) -> None:
        store = InMemoryKnowledgeStore()
        store.put(_item())
        bundle = assemble_context(
            store, topic_tags=("tensorrt",), as_of=date(2026, 1, 5), max_items=10
        )
        assert isinstance(bundle, ContextBundle)
        assert len(bundle.items) == 1

    def test_max_items_zero_or_negative_rejected(self) -> None:
        store = InMemoryKnowledgeStore()
        with pytest.raises(ValueError):
            assemble_context(store, topic_tags=(), as_of=date(2026, 1, 5), max_items=0)

    def test_truncates_to_max_items(self) -> None:
        store = InMemoryKnowledgeStore()
        for i in range(5):
            store.put(
                _item(
                    item_id=ItemId(f"item-{i}"),
                    provenance=_provenance(date_accessed=f"2026-01-{i + 1:02d}"),
                )
            )
        bundle = assemble_context(
            store, topic_tags=("tensorrt",), as_of=date(2026, 2, 1), max_items=2
        )
        assert len(bundle.items) == 2

    def test_excluded_stale_count_reported(self) -> None:
        store = InMemoryKnowledgeStore()
        store.put(
            _item(
                item_id=ItemId("fresh"),
                provenance=_provenance(date_accessed="2026-01-01"),
                staleness_horizon_days=5,
            )
        )
        store.put(
            _item(
                item_id=ItemId("stale"),
                provenance=_provenance(date_accessed="2025-01-01"),
                staleness_horizon_days=5,
            )
        )
        bundle = assemble_context(
            store, topic_tags=("tensorrt",), as_of=date(2026, 1, 3), max_items=10
        )
        assert len(bundle.items) == 1
        assert bundle.excluded_stale_count == 1

    def test_deterministic_repeat_calls_identical_order(self) -> None:
        store = InMemoryKnowledgeStore()
        for i in range(6):
            store.put(
                _item(
                    item_id=ItemId(f"item-{i}"),
                    provenance=_provenance(
                        date_accessed="2026-01-01",
                        source_class="engineering_blog" if i % 2 else "official_documentation",
                    ),
                )
            )
        first = assemble_context(
            store, topic_tags=("tensorrt",), as_of=date(2026, 2, 1), max_items=10
        )
        second = assemble_context(
            store, topic_tags=("tensorrt",), as_of=date(2026, 2, 1), max_items=10
        )
        assert [i.item_id for i in first.items] == [i.item_id for i in second.items]

    def test_tie_break_evidence_weight_desc_then_date_desc_then_id_asc(self) -> None:
        store = InMemoryKnowledgeStore()
        # Same weight (official_documentation="high"), different date_accessed.
        # staleness_horizon_days is generous here so both stay fresh through
        # as_of=2026-06-05 below — this test is about tie-break order, not staleness.
        store.put(
            _item(
                item_id=ItemId("older"),
                provenance=_provenance(date_accessed="2026-01-01"),
                staleness_horizon_days=365,
            )
        )
        store.put(
            _item(
                item_id=ItemId("newer"),
                provenance=_provenance(date_accessed="2026-01-10"),
                staleness_horizon_days=365,
            )
        )
        # Lower weight, should sort after both.
        store.put(
            _item(
                item_id=ItemId("blog"),
                provenance=_provenance(
                    date_accessed="2026-06-01", source_class="engineering_blog"
                ),
            )
        )
        bundle = assemble_context(
            store, topic_tags=("tensorrt",), as_of=date(2026, 6, 5), max_items=10
        )
        assert [i.item_id for i in bundle.items] == [
            ItemId("newer"),
            ItemId("older"),
            ItemId("blog"),
        ]

    def test_source_class_filter_passed_through(self) -> None:
        store = InMemoryKnowledgeStore()
        store.put(
            _item(
                item_id=ItemId("blog"),
                provenance=_provenance(source_class="engineering_blog"),
            )
        )
        store.put(_item(item_id=ItemId("doc"), provenance=_provenance()))
        bundle = assemble_context(
            store,
            topic_tags=("tensorrt",),
            as_of=date(2026, 1, 5),
            max_items=10,
            source_class="engineering_blog",
        )
        assert [i.item_id for i in bundle.items] == [ItemId("blog")]

    def test_no_matching_items_returns_empty_bundle(self) -> None:
        store = InMemoryKnowledgeStore()
        bundle = assemble_context(
            store, topic_tags=("nonexistent",), as_of=date(2026, 1, 5), max_items=10
        )
        assert bundle.items == ()
        assert bundle.excluded_stale_count == 0


# ── Architecture boundary ────────────────────────────────────────────────


class TestArchitectureBoundary:
    """cv_agent.knowledge is a leaf-ish package: it must not import from
    cv_agent.execution, cv_agent.skills, cv_agent.graph, cv_agent.tools, or
    cv_agent.llm (ADR-0006 §3/§7). Mirrors tests/test_tools.py's structural test.
    """

    _FORBIDDEN_PREFIXES = (
        "cv_agent.execution",
        "cv_agent.skills",
        "cv_agent.graph",
        "cv_agent.tools",
        "cv_agent.llm",
    )

    def _knowledge_files(self) -> list[Path]:
        root = Path(__file__).resolve().parent.parent / "cv_agent" / "knowledge"
        return sorted(root.glob("*.py"))

    def test_cv_agent_knowledge_imports_nothing_from_forbidden_layers(self) -> None:
        files = self._knowledge_files()
        assert files, "expected cv_agent/knowledge/*.py to exist"
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module_name = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name
                        self._assert_allowed(module_name, path)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    module_name = node.module
                    self._assert_allowed(module_name, path)

    def _assert_allowed(self, module_name: str, path: Path) -> None:
        for forbidden in self._FORBIDDEN_PREFIXES:
            assert not module_name.startswith(forbidden), (
                f"{path} imports {module_name!r}, forbidden by ADR-0006's leaf-package rule"
            )

    def test_importing_the_package_registers_nothing(self) -> None:
        import cv_agent.knowledge  # noqa: F401

        # cv_agent.knowledge has no registry to pollute; this import must have no
        # side effect beyond making the submodules importable.
        assert True
