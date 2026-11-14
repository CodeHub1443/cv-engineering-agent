"""ADR-0024 §3.7, §7.1 criterion 13, slice K4 (issue #153): SELECTION reads stored evidence.

No network, no .env, no LLM: the builder is pure, and the stores are InMemoryKnowledgeStore or a tmp
SqliteKnowledgeStore.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from cv_agent.knowledge.models import IngestPath, ItemId, KnowledgeItem, Provenance
from cv_agent.knowledge.store import InMemoryKnowledgeStore, RetrievalKeys
from cv_agent.model_selection.reference_task_research import build_reference_comparison
from cv_agent.model_selection.selection_payload import SelectionPayloadV1, build_selection_payload
from cv_agent.model_selection.selector import build_candidate, compare_candidates
from cv_agent.model_selection.stored_evidence import attach_stored_evidence, evidence_for_candidate
from cv_agent.requirements.structured import structured_view
from tests.knowledge_fakes import _fresh, _open
from tests.test_requirements_structured import _analyzer

AS_OF = date(2026, 11, 11)
_VIEW = structured_view(
    _analyzer().analyze(
        "Detect people climbing the perimeter fence at an outdoor prison; "
        "must run on a Jetson edge device in real-time from RTSP cameras."
    )
)


def _it(
    item_id: str,
    claim: str = "a stored claim",
    *,
    url: str = "https://docs.example.org/page",
    ingest: IngestPath = IngestPath.WEB_FETCH,
    accessed: str = "2026-11-01",
    horizon: int = 180,
) -> KnowledgeItem:
    return KnowledgeItem(
        item_id=ItemId(item_id),
        claim=claim,
        conditions=None,
        provenance=Provenance(
            url=url,
            source_class="official_documentation",
            date_published="2026-01-05",
            date_accessed=accessed,
            author_or_org="Example Org",
        ),
        topic_tags=("detection",),
        staleness_horizon_days=horizon,
        ingest=ingest,
    )


def _mem(*rows: tuple[KnowledgeItem, tuple[str, ...]]) -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore()
    for item, names in rows:
        store.put(item, keys=RetrievalKeys(model_names=names))
    return store


def _ids(items: Any) -> list[str]:
    return [str(i.item_id) for i in items]


# --- the join (OQ3) ---------------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_join_is_exact_after_normalisation(backend: str, tmp_path: Path) -> None:
    rows = [(_it("s-yolo11n"), ("YOLO11n",)), (_it("s-yolo11"), ("yolo11",)), (_it("s-other"), ("rtdetr-r50",))]
    if backend == "memory":
        store: Any = _mem(*rows)
    else:
        store = _open(_fresh(tmp_path))
        for item, names in rows:
            store.record(item, keys=RetrievalKeys(model_names=names))
    for spelling in ("yolo11n", "YOLO11N", " yolo11n "):
        assert _ids(evidence_for_candidate(store, spelling, as_of=AS_OF)) == ["s-yolo11n"]
    assert _ids(evidence_for_candidate(store, "yolo11", as_of=AS_OF)) == ["s-yolo11"]


def test_results_are_in_item_id_order() -> None:
    store = _mem((_it("s-b"), ("m",)), (_it("s-a"), ("m",)), (_it("s-c"), ("m",)))
    assert _ids(evidence_for_candidate(store, "m", as_of=AS_OF)) == ["s-a", "s-b", "s-c"]


def test_an_invalid_candidate_id_means_no_stored_evidence() -> None:
    store = _mem((_it("s-a"), ("m",)))
    assert evidence_for_candidate(store, "yolo 11n", as_of=AS_OF) == ()
    assert evidence_for_candidate(store, "", as_of=AS_OF) == ()


def test_an_invalid_candidate_id_does_not_break_selection() -> None:
    odd = build_candidate(
        candidate_id="yolo 11n", model_family="f", task_support=("object_detection",),
        evidence_items=(_it("c-1", "curated"),), strengths=("s",), limitations=("l",),
        compatibility_constraints=("c",),
    )
    (out,) = attach_stored_evidence((odd,), _mem((_it("s-a"), ("m",))), as_of=AS_OF)
    assert out == odd
    built = build_selection_payload(compare_candidates((out,), task_description="t"), _VIEW)
    assert isinstance(built, tuple)


# --- staleness --------------------------------------------------------------------------------------


def test_stale_items_are_excluded_by_default_with_an_injected_as_of() -> None:
    store = _mem((_it("s-old", accessed="2026-11-01", horizon=10), ("m",)))
    assert _ids(evidence_for_candidate(store, "m", as_of=date(2026, 11, 11))) == ["s-old"]
    assert evidence_for_candidate(store, "m", as_of=date(2026, 11, 12)) == ()


def test_there_is_no_include_stale_option() -> None:
    import inspect

    for fn in (evidence_for_candidate, attach_stored_evidence):
        assert "include_stale" not in inspect.signature(fn).parameters


# --- criterion 13 and eligibility -------------------------------------------------------------------


def test_project_input_and_unspecified_items_are_returned_not_dropped() -> None:
    store = _mem(
        (_it("s-1", ingest=IngestPath.PROJECT_INPUT), ("yolo11n",)),
        (_it("s-2"), ("yolo11n",)),
        (_it("s-3", ingest=IngestPath.UNSPECIFIED), ("yolo11n",)),
        (_it("s-4"), ("rtdetr-r50",)),
    )
    assert _ids(evidence_for_candidate(store, "yolo11n", as_of=AS_OF)) == ["s-1", "s-2", "s-3"]


def test_stored_project_input_or_unspecified_never_reaches_a_payload() -> None:
    base = build_selection_payload(build_reference_comparison(), _VIEW)
    assert isinstance(base, tuple)
    store = _mem(
        (_it("s-1", "PROJECT-INPUT-SECRET-7", ingest=IngestPath.PROJECT_INPUT, url="https://a.example.org/1"), ("yolo11n",)),
        (_it("s-2", "UNSPECIFIED-SECRET-8", ingest=IngestPath.UNSPECIFIED, url="https://a.example.org/2"), ("yolo11n",)),
        (_it("s-3", "CONTROL-WEB-FETCH-9", url="https://a.example.org/3"), ("yolo11n",)),
    )
    built = build_selection_payload(build_reference_comparison(evidence=store, as_of=AS_OF), _VIEW)
    assert isinstance(built, tuple)
    from cv_agent.llm.payload import build_payload

    body = build_payload(built[0]).body_json
    assert "PROJECT-INPUT-SECRET-7" not in body and "UNSPECIFIED-SECRET-8" not in body
    assert "CONTROL-WEB-FETCH-9" in body
    assert built[0].candidates[0].claims_excluded == base[0].candidates[0].claims_excluded + 2


# --- combining curated and stored -------------------------------------------------------------------


def test_curated_wins_on_item_id_and_on_url_plus_claim() -> None:
    base = build_reference_comparison().candidates[0]
    first = base.evidence_references[0]
    store = _mem(
        (_it(first.item_id, "a different claim under a curated id"), ("yolo11n",)),
        (_it("s-dupe", first.claim, url=first.url), ("yolo11n",)),
        (_it("s-new", "a new claim"), ("yolo11n",)),
    )
    (out, *_) = build_reference_comparison(evidence=store, as_of=AS_OF).candidates
    assert [r.item_id for r in out.evidence_references] == [r.item_id for r in base.evidence_references] + ["s-new"]
    assert out.evidence_references[0].claim == first.claim


def test_stored_duplicates_keep_the_first_by_item_id() -> None:
    store = _mem((_it("s-b", "same"), ("m",)), (_it("s-a", "same"), ("m",)))
    cand = build_candidate(
        candidate_id="m", model_family="f", task_support=("object_detection",),
        evidence_items=(_it("c-1", "curated", url="https://c.example.org/x"),), strengths=("s",),
        limitations=("l",), compatibility_constraints=("c",),
    )
    (out,) = attach_stored_evidence((cand,), store, as_of=AS_OF)
    assert [r.item_id for r in out.evidence_references] == ["c-1", "s-a"]


def test_stored_items_are_not_benchmark_evidence() -> None:
    base = build_reference_comparison()
    store = _mem((_it("s-new", "a new claim"), ("yolo11n",)), (_it("s-peo", "another"), ("nvidia-peoplenet",)))
    out = build_reference_comparison(evidence=store, as_of=AS_OF)
    assert [c.benchmark_evidence for c in out.candidates] == [c.benchmark_evidence for c in base.candidates]
    built = build_selection_payload(out, _VIEW)
    assert isinstance(built, tuple)
    # PeopleNet had no benchmark evidence and a stored item does not give it any
    assert built[0].candidates[2].has_benchmark_evidence is False


# --- caps over the combined set ---------------------------------------------------------------------


def _synthetic(cid: str, curated: int) -> Any:
    return build_candidate(
        candidate_id=cid, model_family="f", task_support=("object_detection",),
        evidence_items=tuple(_it(f"{cid}-c{k:02d}", f"cur {k}", url=f"https://c.example.org/{cid}/{k}") for k in range(curated)),
        strengths=("s",), limitations=("l",), compatibility_constraints=("c",),
    )


def _stored_for(cid: str, n: int) -> list[tuple[KnowledgeItem, tuple[str, ...]]]:
    return [(_it(f"{cid}-s{k:02d}", f"sto {k}", url=f"https://s.example.org/{cid}/{k}"), (cid,)) for k in range(n)]


def test_n_cap_applies_to_the_combined_set() -> None:
    store = _mem(*_stored_for("cand-a", 6))
    (cand,) = attach_stored_evidence((_synthetic("cand-a", 7),), store, as_of=AS_OF)
    assert len(cand.evidence_references) == 13
    built = build_selection_payload(compare_candidates((cand,), task_description="t"), _VIEW)
    assert isinstance(built, tuple)
    block = built[0].candidates[0]
    assert (len(block.claims), block.claims_omitted) == (10, 3)


def test_m_cap_and_water_fill_apply_to_the_combined_set() -> None:
    ids = ["cand-a", "cand-b", "cand-c", "cand-d"]
    store = _mem(*[row for cid in ids for row in _stored_for(cid, 5)])
    cands = attach_stored_evidence(tuple(_synthetic(cid, 5) for cid in ids), store, as_of=AS_OF)
    built = build_selection_payload(compare_candidates(cands, task_description="t"), _VIEW)
    assert isinstance(built, tuple) and isinstance(built[0], SelectionPayloadV1)
    assert [len(b.claims) for b in built[0].candidates] == [8, 8, 7, 7]
    assert sum(len(b.claims) for b in built[0].candidates) == 30


# --- unchanged behaviour ----------------------------------------------------------------------------


def test_an_empty_store_gives_a_byte_identical_payload() -> None:
    from cv_agent.llm.payload import build_payload

    def body(cmp: Any) -> str:
        built = build_selection_payload(cmp, _VIEW)
        assert isinstance(built, tuple)
        return build_payload(built[0]).body_json

    assert body(build_reference_comparison(evidence=InMemoryKnowledgeStore(), as_of=AS_OF)) == body(build_reference_comparison())


def test_evidence_without_as_of_is_a_type_error() -> None:
    with pytest.raises(TypeError):
        build_reference_comparison(evidence=InMemoryKnowledgeStore())
    with pytest.raises(TypeError):
        build_reference_comparison(as_of=AS_OF)
