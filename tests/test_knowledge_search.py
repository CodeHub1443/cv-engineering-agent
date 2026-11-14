"""ADR-0024 slice K1c: ``KnowledgeQuery``, ``matches``, ``search`` and in-memory parity (criteria 6-9).

Every test uses ``tmp_path`` only, no network, no ``.env``; connections are closed before teardown (Q53).
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from cv_agent.knowledge import models as knowledge_models
from cv_agent.knowledge import sqlite_store
from cv_agent.knowledge import store as knowledge_store
from cv_agent.knowledge.models import IngestPath, KnowledgeItem
from cv_agent.knowledge.sqlite_store import SqliteKnowledgeStore
from cv_agent.knowledge.store import (
    InMemoryKnowledgeStore,
    KnowledgeQuery,
    KnowledgeWriter,
    RetrievalKeys,
    StoredItem,
    matches,
)
from cv_agent.llm.payload import PublicClaim
from tests.test_knowledge_sqlite_store import _fresh, _item, _open, _PoisonedDate, _PoisonedDatetime, _rows

AS_OF = date(2026, 11, 14)


def _with_url(item: KnowledgeItem, url: str) -> KnowledgeItem:
    return dataclasses.replace(item, provenance=dataclasses.replace(item.provenance, url=url))


def _both(tmp_path: Path, rows: list[tuple[KnowledgeItem, RetrievalKeys]]) -> tuple[InMemoryKnowledgeStore, SqliteKnowledgeStore]:
    mem, sql = InMemoryKnowledgeStore(), _open(_fresh(tmp_path))
    for item, keys in rows:
        mem.put(item, keys=keys)
        sql.put(item, keys=keys)
    return mem, sql


# --- criterion 7: normalisation ------------------------------------------------------------------


@pytest.mark.parametrize("name", ["yolo11n", "YOLO11N", " yolo11n "])
def test_a_stored_name_is_found_by_any_spelling(tmp_path: Path, name: str) -> None:
    mem, sql = _both(tmp_path, [(_item(), RetrievalKeys(model_names=("YOLO11n",)))])
    for store in (mem, sql):
        assert [s.item.item_id for s in store.search(KnowledgeQuery(as_of=AS_OF, model_names=(name,)))] == ["research-aaa"]


def test_a_prefix_does_not_match(tmp_path: Path) -> None:
    mem, sql = _both(tmp_path, [(_item(), RetrievalKeys(model_names=("YOLO11n",)))])
    for store in (mem, sql):
        assert store.search(KnowledgeQuery(as_of=AS_OF, model_names=("yolo11",))) == []


@pytest.mark.parametrize("bad", ["yolo 11n", ""])
def test_a_non_token_raises_at_write_and_read(bad: str) -> None:
    with pytest.raises(ValueError):
        RetrievalKeys(model_names=(bad,))
    with pytest.raises(ValueError):
        KnowledgeQuery(as_of=AS_OF, model_names=(bad,))
    with pytest.raises(ValueError):
        KnowledgeQuery(as_of=AS_OF, metric=bad)


def test_the_metric_is_found_case_insensitively(tmp_path: Path) -> None:
    mem, sql = _both(tmp_path, [(_item(), RetrievalKeys(metric="mAP50-95"))])
    for store in (mem, sql):
        assert len(store.search(KnowledgeQuery(as_of=AS_OF, metric="map50-95"))) == 1
        assert store.search(KnowledgeQuery(as_of=AS_OF, metric="map50")) == []


def test_query_arguments_are_type_checked() -> None:
    with pytest.raises(TypeError):
        KnowledgeQuery(as_of=AS_OF, model_names="yolo11n")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        KnowledgeQuery(as_of=AS_OF, topic_tags="detection")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        KnowledgeQuery(as_of="2026-11-14")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        InMemoryKnowledgeStore().search("detection")  # type: ignore[arg-type]


def test_model_names_semantics(tmp_path: Path) -> None:
    rows = [
        (_item("a"), RetrievalKeys(model_names=("yolo11n", "rtdetr"))),
        (_item("b"), RetrievalKeys()),
    ]
    mem, sql = _both(tmp_path, rows)
    for store in (mem, sql):
        ids = lambda q: [s.item.item_id for s in store.search(q)]  # noqa: E731
        assert ids(KnowledgeQuery(as_of=AS_OF)) == ["a", "b"]  # an empty tuple is no filter
        assert ids(KnowledgeQuery(as_of=AS_OF, model_names=("rtdetr", "other"))) == ["a"]  # any-of
        assert ids(KnowledgeQuery(as_of=AS_OF, model_names=("other",))) == []  # nameless "b" never matches


# --- criterion 8: include_stale ------------------------------------------------------------------


def test_include_stale(tmp_path: Path) -> None:
    mem, sql = _both(tmp_path, [(_item("old", accessed="2026-01-01", horizon=30), RetrievalKeys()), (_item("new"), RetrievalKeys())])
    for store in (mem, sql):
        assert [s.item.item_id for s in store.search(KnowledgeQuery(as_of=AS_OF))] == ["new"]
        both = store.search(KnowledgeQuery(as_of=AS_OF, include_stale=True))
        assert [(s.item.item_id, s.stale) for s in both] == [("new", False), ("old", True)]
    assert len(_rows(sql.path)) == 2  # the stale row still exists


def test_the_horizon_boundary_is_not_stale(tmp_path: Path) -> None:
    mem, sql = _both(tmp_path, [(_item(accessed="2026-10-15", horizon=30), RetrievalKeys())])  # exactly 30 days
    for store in (mem, sql):
        assert [s.stale for s in store.search(KnowledgeQuery(as_of=AS_OF))] == [False]
        assert store.search(KnowledgeQuery(as_of=date(2026, 11, 15))) == []  # 31 days


def test_search_never_reads_a_clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _fresh(tmp_path)
    _open(path).put(_item(accessed="2026-11-01", horizon=10))

    def no_clock() -> datetime:
        raise AssertionError("the injected clock was read")

    store = _open(path, now=no_clock)
    mem = InMemoryKnowledgeStore()
    mem.put(_item(accessed="2026-11-01", horizon=10))
    fresh_q, stale_q = KnowledgeQuery(as_of=date(2026, 11, 12)), KnowledgeQuery(as_of=date(2026, 11, 12), include_stale=True)
    for module in (sqlite_store, knowledge_store, knowledge_models):
        if hasattr(module, "datetime"):
            monkeypatch.setattr(module, "datetime", _PoisonedDatetime)
        if hasattr(module, "date"):
            monkeypatch.setattr(module, "date", _PoisonedDate)
    for s in (store, mem):
        assert s.search(fresh_q) == []
        assert [x.stale for x in s.search(stale_q)] == [True]


# --- criterion 9: parity -------------------------------------------------------------------------


def _fixture() -> list[tuple[KnowledgeItem, RetrievalKeys]]:
    return [
        (_item("e", tags=("detection",), source_class="peer_reviewed_research"), RetrievalKeys(model_names=("YOLO11n",), metric="mAP50-95")),
        (_item("b", tags=("detection", "edge")), RetrievalKeys(model_names=("yolo11n", "rtdetr"), metric="latency")),
        (_item("d", tags=("segmentation",), source_class="engineering_blog", ingest=IngestPath.PROJECT_INPUT), RetrievalKeys(model_names=("sam2",))),
        (_item("a", accessed="2026-01-01", horizon=30), RetrievalKeys(model_names=("yolo11n",), metric="map50-95")),
        (_item("c", ingest=IngestPath.CURATED_REFERENCE), RetrievalKeys()),
        (_item("f", tags=("detection", "edge", "jetson"), ingest=IngestPath.UNSPECIFIED), RetrievalKeys(metric="latency")),
    ]


_QUERIES: list[dict[str, Any]] = [
    {},
    {"include_stale": True},
    {"topic_tags": ("detection",)},
    {"topic_tags": ("detection", "edge"), "include_stale": True},
    {"topic_tags": ("nothing",)},
    {"model_names": ("YOLO11n",)},
    {"model_names": ("yolo11n", "sam2"), "include_stale": True},
    {"metric": "MAP50-95", "include_stale": True},
    {"metric": "latency"},
    {"source_classes": frozenset({"engineering_blog", "peer_reviewed_research"})},
    {"ingest": frozenset({IngestPath.PROJECT_INPUT, IngestPath.UNSPECIFIED})},
    {"model_names": ("yolo11n",), "metric": "latency", "topic_tags": ("edge",)},
]


def _view(stored: list[StoredItem]) -> list[tuple[Any, Any, bool]]:
    return [(s.item, s.keys, s.stale) for s in stored]


@pytest.mark.parametrize("kw", _QUERIES, ids=lambda kw: ",".join(kw) or "all")
def test_in_memory_and_sqlite_search_agree(tmp_path: Path, kw: dict[str, Any]) -> None:
    mem, sql = _both(tmp_path, _fixture())
    q = KnowledgeQuery(as_of=AS_OF, **kw)
    m, s = mem.search(q), sql.search(q)
    assert _view(m) == _view(s)  # identical items in identical order
    assert [x.item.item_id for x in s] == sorted(x.item.item_id for x in s)
    assert all(matches(x.item, x.keys, q) for x in s)


def test_the_protocol_query_agrees_as_sets(tmp_path: Path) -> None:
    mem, sql = _both(tmp_path, _fixture())
    for tags in (None, ["detection"], ["detection", "edge"]):
        assert set(i.item_id for i in mem.query(topic_tags=tags)) == set(i.item_id for i in sql.query(topic_tags=tags))


# --- recorded vs unrecorded stores ---------------------------------------------------------------


def test_the_in_memory_store_reports_unrecorded() -> None:
    mem = InMemoryKnowledgeStore()
    mem.put(_item())
    mem.put(_item(claim="changed"))
    (s,) = mem.search(KnowledgeQuery(as_of=AS_OF))
    assert (s.writer, s.recorded_at, s.revision) == (None, None, 2)  # None = not recorded; revision = put count


def test_the_sqlite_store_always_sets_writer_and_recorded_at(tmp_path: Path) -> None:
    _, sql = _both(tmp_path, _fixture())
    for s in [*sql.search(KnowledgeQuery(as_of=AS_OF, include_stale=True)), *sql.history("a", as_of=AS_OF)]:
        assert s.writer is KnowledgeWriter.RESEARCH_CLI and isinstance(s.recorded_at, str) and s.recorded_at.endswith("Z")


# --- criterion 6: eligibility unchanged ----------------------------------------------------------

_PRIVATE = ["http://10.0.0.5/x", "http://localhost/x", "file:///etc/passwd", "http://intranet/x", "http://010.0.0.5./x"]


def _verdict(item: KnowledgeItem) -> Any:
    return PublicClaim.from_item(item, ordinal=1, is_benchmark=False)


def test_storage_never_changes_what_the_builder_decides(tmp_path: Path) -> None:
    originals = [
        _item("p-input", ingest=IngestPath.PROJECT_INPUT),
        _item("p-unspec", ingest=IngestPath.UNSPECIFIED),
        _item("p-post", source_class="professional_post"),
        *(_with_url(_item(f"p-url{i}"), u) for i, u in enumerate(_PRIVATE)),
        _item("control", ingest=IngestPath.WEB_FETCH),
    ]
    mem, sql = _both(tmp_path, [(i, RetrievalKeys()) for i in originals])
    for store in (mem, sql):
        reloaded = {s.item.item_id: s.item for s in store.search(KnowledgeQuery(as_of=AS_OF, include_stale=True))}
        for original in originals:
            before, after = _verdict(original), _verdict(reloaded[original.item_id])
            assert type(before) is type(after) and (before == after or isinstance(before, PublicClaim))
        assert isinstance(_verdict(reloaded["control"]), PublicClaim)
        assert not any(isinstance(_verdict(reloaded[i.item_id]), PublicClaim) for i in originals if i.item_id != "control")


def test_an_ingest_filter_does_not_change_eligibility(tmp_path: Path) -> None:
    _, sql = _both(tmp_path, [(_item("x", ingest=IngestPath.PROJECT_INPUT), RetrievalKeys())])
    (plain,) = sql.search(KnowledgeQuery(as_of=AS_OF))
    assert sql.search(KnowledgeQuery(as_of=AS_OF, ingest=frozenset({IngestPath.WEB_FETCH}))) == []
    (filtered,) = sql.search(KnowledgeQuery(as_of=AS_OF, ingest=frozenset({IngestPath.PROJECT_INPUT})))
    assert _verdict(plain.item) == _verdict(filtered.item)
