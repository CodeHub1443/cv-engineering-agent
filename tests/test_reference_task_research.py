"""
Integration tests for cv_agent.model_selection.reference_task_research.

Coverage:
  1. Knowledge store populated with real provenance (real URLs, real dates)
  2. Correct number of items and candidates
  3. All KnowledgeItems have valid Provenance (construction-time validation)
  4. Benchmark evidence correctly identified per candidate
  5. Research gaps inferred for PeopleNet (no confirmed benchmarks)
  6. Conflict notes present and well-formed
  7. SelectionRecommendation is always a proposal (is_proposal=True)
  8. Recommended candidate is one of the three known candidates
  9. No synthetic/placeholder evidence in the production research path
 10. Evidence weights reflect source class (official_doc=high, peer_reviewed=high)
 11. Access date is the research session date (2026-09-28)
 12. Deterministic: same store and candidates produced on repeated calls
"""

from __future__ import annotations

import json

from cv_agent.knowledge.models import ItemId
from cv_agent.llm.mock import FakeLLMProvider
from cv_agent.model_selection.reference_task_research import (
    _ACCESS_DATE,
    _ALL_EVIDENCE,
    build_reference_candidates,
    build_reference_comparison,
    build_reference_knowledge_store,
    run_reference_selection,
)
from cv_agent.model_selection.selector import select_candidate

# ---------------------------------------------------------------------------
# Known candidate IDs for the reference task
# ---------------------------------------------------------------------------

_KNOWN_CANDIDATES = {"yolo11n", "rtdetr-r50", "nvidia-peoplenet"}


# ---------------------------------------------------------------------------
# 1. Knowledge store
# ---------------------------------------------------------------------------

class TestReferenceKnowledgeStore:
    def test_store_contains_all_evidence_items(self) -> None:
        store = build_reference_knowledge_store()
        items = store.list_items()
        assert len(items) == len(_ALL_EVIDENCE)

    def test_all_items_have_real_url_provenance(self) -> None:
        store = build_reference_knowledge_store()
        for item in store.list_items():
            url = item.provenance.url
            assert url.startswith("https://"), (
                f"Item {item.item_id!r} has non-https URL: {url!r}"
            )

    def test_all_items_access_date_is_research_session(self) -> None:
        store = build_reference_knowledge_store()
        for item in store.list_items():
            assert item.provenance.date_accessed == _ACCESS_DATE, (
                f"Item {item.item_id!r} has wrong access date: "
                f"{item.provenance.date_accessed!r}"
            )

    def test_all_items_have_nonempty_author_or_org(self) -> None:
        store = build_reference_knowledge_store()
        for item in store.list_items():
            assert item.provenance.author_or_org.strip(), (
                f"Item {item.item_id!r} has blank author_or_org"
            )

    def test_no_placeholder_item_ids(self) -> None:
        """Evidence must not use synthetic IDs like 'test-item-001'."""
        store = build_reference_knowledge_store()
        for item in store.list_items():
            iid = str(item.item_id)
            assert iid not in ("test-item-001", "item-001", "synthetic"), (
                f"Synthetic item ID found: {iid!r}"
            )

    def test_deterministic_on_repeated_calls(self) -> None:
        store1 = build_reference_knowledge_store()
        store2 = build_reference_knowledge_store()
        ids1 = {str(i.item_id) for i in store1.list_items()}
        ids2 = {str(i.item_id) for i in store2.list_items()}
        assert ids1 == ids2

    def test_official_documentation_items_have_high_weight(self) -> None:
        store = build_reference_knowledge_store()
        for item in store.list_items():
            if item.provenance.source_class == "official_documentation":
                assert item.evidence_weight() == "high", (
                    f"Item {item.item_id!r}: official_documentation should be 'high', "
                    f"got {item.evidence_weight()!r}"
                )

    def test_peer_reviewed_items_have_high_weight(self) -> None:
        store = build_reference_knowledge_store()
        for item in store.list_items():
            if item.provenance.source_class == "peer_reviewed_research":
                assert item.evidence_weight() == "high"

    def test_yolov8_items_present(self) -> None:
        store = build_reference_knowledge_store()
        item = store.get(ItemId("yolov8-bench-n"))
        assert item is not None
        assert "37.3 mAP" in item.claim

    def test_yolo11_items_present(self) -> None:
        store = build_reference_knowledge_store()
        item = store.get(ItemId("yolo11-bench-n"))
        assert item is not None
        assert "39.5 mAP" in item.claim

    def test_rtdetr_items_present(self) -> None:
        store = build_reference_knowledge_store()
        item = store.get(ItemId("rtdetr-paper-r50-coco"))
        assert item is not None
        assert "53.1%" in item.claim
        assert item.provenance.source_class == "peer_reviewed_research"

    def test_peoplenet_items_present(self) -> None:
        store = build_reference_knowledge_store()
        item = store.get(ItemId("peoplenet-description"))
        assert item is not None
        assert "PeopleNet" in item.claim

    def test_bytetrack_items_present(self) -> None:
        store = build_reference_knowledge_store()
        item = store.get(ItemId("bytetrack-paper"))
        assert item is not None
        assert "ByteTrack" in item.claim


# ---------------------------------------------------------------------------
# 2. Candidates
# ---------------------------------------------------------------------------

class TestReferenceTaskCandidates:
    def test_three_candidates_returned(self) -> None:
        store = build_reference_knowledge_store()
        candidates = build_reference_candidates(store)
        assert len(candidates) == 3

    def test_candidate_ids_are_known(self) -> None:
        store = build_reference_knowledge_store()
        candidates = build_reference_candidates(store)
        ids = {c.candidate_id for c in candidates}
        assert ids == _KNOWN_CANDIDATES

    def test_yolo11n_has_benchmark_evidence(self) -> None:
        store = build_reference_knowledge_store()
        candidates = build_reference_candidates(store)
        yolo = next(c for c in candidates if c.candidate_id == "yolo11n")
        assert len(yolo.benchmark_evidence) >= 1
        claims = {r.claim for r in yolo.benchmark_evidence}
        assert any("39.5 mAP" in c for c in claims)

    def test_rtdetr_has_benchmark_evidence(self) -> None:
        store = build_reference_knowledge_store()
        candidates = build_reference_candidates(store)
        rt = next(c for c in candidates if c.candidate_id == "rtdetr-r50")
        assert len(rt.benchmark_evidence) >= 1
        claims = {r.claim for r in rt.benchmark_evidence}
        assert any("53.1%" in c for c in claims)

    def test_peoplenet_has_no_benchmark_evidence(self) -> None:
        """PeopleNet's NGC page renders metrics via JS — not extractable statically."""
        store = build_reference_knowledge_store()
        candidates = build_reference_candidates(store)
        pn = next(c for c in candidates if c.candidate_id == "nvidia-peoplenet")
        assert len(pn.benchmark_evidence) == 0

    def test_all_evidence_references_have_real_urls(self) -> None:
        store = build_reference_knowledge_store()
        candidates = build_reference_candidates(store)
        for c in candidates:
            for ref in c.evidence_references:
                assert ref.url.startswith("https://"), (
                    f"Candidate {c.candidate_id!r} has non-https evidence URL: {ref.url!r}"
                )

    def test_benchmark_evidence_is_subset_of_evidence_references(self) -> None:
        store = build_reference_knowledge_store()
        candidates = build_reference_candidates(store)
        for c in candidates:
            ref_ids = {r.item_id for r in c.evidence_references}
            for bref in c.benchmark_evidence:
                assert bref.item_id in ref_ids, (
                    f"Candidate {c.candidate_id!r}: benchmark item {bref.item_id!r} "
                    "not in evidence_references"
                )

    def test_yolo11n_has_tracking_evidence(self) -> None:
        store = build_reference_knowledge_store()
        candidates = build_reference_candidates(store)
        yolo = next(c for c in candidates if c.candidate_id == "yolo11n")
        tracking_items = [
            r for r in yolo.evidence_references
            if "bytetrack" in r.item_id.lower() or "track" in r.item_id.lower()
        ]
        assert len(tracking_items) >= 1, "YOLO11n should include ByteTrack evidence"

    def test_deterministic_on_repeated_calls(self) -> None:
        store = build_reference_knowledge_store()
        c1 = build_reference_candidates(store)
        c2 = build_reference_candidates(store)
        assert [c.candidate_id for c in c1] == [c.candidate_id for c in c2]


# ---------------------------------------------------------------------------
# 3. Comparison
# ---------------------------------------------------------------------------

class TestReferenceComparison:
    def test_comparison_has_three_candidates(self) -> None:
        cmp = build_reference_comparison()
        assert len(cmp.candidates) == 3

    def test_research_gap_for_peoplenet_benchmarks(self) -> None:
        cmp = build_reference_comparison()
        gap_text = " ".join(cmp.research_gaps)
        assert "peoplenet" in gap_text.lower() or "nvidia-peoplenet" in gap_text.lower(), (
            "Expected a research gap for PeopleNet missing benchmarks"
        )

    def test_hardware_comparison_conflict_present(self) -> None:
        cmp = build_reference_comparison()
        dimensions = [cn.dimension for cn in cmp.conflicting_evidence]
        assert any("hardware" in d.lower() for d in dimensions), (
            f"Expected hardware comparison conflict; got: {dimensions!r}"
        )

    def test_model_scale_conflict_present(self) -> None:
        cmp = build_reference_comparison()
        dimensions = [cn.dimension for cn in cmp.conflicting_evidence]
        assert any("scale" in d.lower() or "backbone" in d.lower() or "nano" in d.lower()
                   for d in dimensions), (
            f"Expected model-scale conflict; got: {dimensions!r}"
        )

    def test_task_description_mentions_cctv(self) -> None:
        cmp = build_reference_comparison()
        assert "CCTV" in cmp.task_description or "cctv" in cmp.task_description.lower()

    def test_task_description_mentions_tracking(self) -> None:
        cmp = build_reference_comparison()
        assert "tracking" in cmp.task_description.lower()


# ---------------------------------------------------------------------------
# 4. Selection
# ---------------------------------------------------------------------------

def _evidence_based_llm(recommended_candidate_id: str = "yolo11n") -> FakeLLMProvider:
    """FakeLLM that returns a JSON response citing real evidence from the comparison."""
    return FakeLLMProvider(
        fixed_response=json.dumps({
            "recommended_candidate_id": recommended_candidate_id,
            "rationale": (
                "YOLO11n achieves 39.5 mAP on COCO val2017 at 1.5 ms TensorRT latency "
                "with 2.6M parameters (official Ultralytics docs). Native ByteTrack/BoT-SORT "
                "integration is documented for YOLO11. RT-DETR-R50 has higher COCO AP "
                "(53.1%, peer-reviewed arXiv paper) but uses a ResNet-50 backbone "
                "(significantly larger) and its FPS benchmark (T4 GPU) is not comparable "
                "to YOLO11n's A100 TRT latency. PeopleNet has no confirmed benchmark evidence "
                "from static HTML extraction of the NGC page."
            ),
            "confidence": "medium",
            "uncertainty_notes": [
                "COCO benchmark is general objects; CCTV-specific person performance unknown.",
                "Hardware benchmarks for YOLO11n and RT-DETR are not comparable (A100 vs T4).",
                "PeopleNet metrics not extractable from NGC page (JavaScript rendering).",
                "YOLO11n AGPL-3.0 licence requires legal review for commercial deployment.",
            ],
        })
    )


class TestReferenceTaskSelection:
    def test_recommendation_is_proposal(self) -> None:
        rec = run_reference_selection(_evidence_based_llm())
        assert rec.is_proposal is True

    def test_recommended_candidate_is_valid(self) -> None:
        rec = run_reference_selection(_evidence_based_llm())
        assert rec.recommended_candidate_id in _KNOWN_CANDIDATES

    def test_confidence_is_valid_value(self) -> None:
        rec = run_reference_selection(_evidence_based_llm())
        assert rec.confidence in ("high", "medium", "low", "insufficient_evidence")

    def test_rationale_is_nonempty(self) -> None:
        rec = run_reference_selection(_evidence_based_llm())
        assert rec.rationale.strip()

    def test_uncertainty_notes_preserve_benchmark_incompatibility(self) -> None:
        rec = run_reference_selection(_evidence_based_llm())
        notes_text = " ".join(rec.uncertainty_notes)
        # At least one note should acknowledge the hardware incompatibility
        assert any(
            kw in notes_text
            for kw in ("hardware", "A100", "T4", "comparable", "GPU")
        ), f"Expected hardware incompatibility note; got: {rec.uncertainty_notes!r}"

    def test_no_execution_triggered(self) -> None:
        """is_proposal=True and no execution-related attributes."""
        rec = run_reference_selection(_evidence_based_llm())
        assert rec.is_proposal is True
        for attr in ("run", "execute", "download", "train", "infer"):
            assert not hasattr(rec, attr), f"Unexpected callable attr: {attr!r}"

    def test_comparison_embedded_in_recommendation(self) -> None:
        rec = run_reference_selection(_evidence_based_llm())
        assert len(rec.comparison.candidates) == 3
        cand_ids = {c.candidate_id for c in rec.comparison.candidates}
        assert cand_ids == _KNOWN_CANDIDATES

    def test_fail_closed_on_unknown_candidate(self) -> None:
        """If LLM returns an unknown candidate_id, confidence=insufficient_evidence."""
        bad_llm = FakeLLMProvider(fixed_response=json.dumps({
            "recommended_candidate_id": "nonexistent-model",
            "rationale": "Best ever.",
            "confidence": "high",
            "uncertainty_notes": [],
        }))
        cmp = build_reference_comparison()
        rec = select_candidate(cmp, llm_provider=bad_llm)
        assert rec.confidence == "insufficient_evidence"

    def test_deterministic_with_fixed_llm(self) -> None:
        llm = _evidence_based_llm()
        rec1 = run_reference_selection(llm)
        llm2 = _evidence_based_llm()
        rec2 = run_reference_selection(llm2)
        assert rec1.recommended_candidate_id == rec2.recommended_candidate_id
        assert rec1.confidence == rec2.confidence


# ---------------------------------------------------------------------------
# 5. No synthetic evidence in production path
# ---------------------------------------------------------------------------

class TestNoSyntheticEvidence:
    def test_all_urls_are_real_domains(self) -> None:
        """Evidence URLs must be from real, authoritative domains."""
        store = build_reference_knowledge_store()
        known_domains = {
            "docs.ultralytics.com",
            "arxiv.org",
            "catalog.ngc.nvidia.com",
            "docs.nvidia.com",
            "github.com",
        }
        for item in store.list_items():
            url = item.provenance.url
            assert any(domain in url for domain in known_domains), (
                f"Item {item.item_id!r} URL {url!r} is not from a known authoritative domain"
            )

    def test_benchmark_numbers_have_conditions(self) -> None:
        """Every benchmark EvidenceReference must carry a conditions string."""
        store = build_reference_knowledge_store()
        candidates = build_reference_candidates(store)
        for c in candidates:
            for ref in c.benchmark_evidence:
                assert ref.conditions is not None and ref.conditions.strip(), (
                    f"Candidate {c.candidate_id!r}: benchmark item {ref.item_id!r} "
                    "has no conditions string — benchmark conditions must be preserved"
                )

    def test_yolov8n_benchmark_claim_has_numeric_values(self) -> None:
        store = build_reference_knowledge_store()
        item = store.get(ItemId("yolov8-bench-n"))
        assert item is not None
        assert "37.3" in item.claim, "YOLOv8n benchmark claim must include real mAP value"

    def test_rtdetr_benchmark_claim_has_numeric_values(self) -> None:
        store = build_reference_knowledge_store()
        item = store.get(ItemId("rtdetr-paper-r50-coco"))
        assert item is not None
        assert "53.1" in item.claim
        assert "108" in item.claim

    def test_peoplenet_missing_benchmark_documented_not_fabricated(self) -> None:
        """PeopleNet benchmark absence must be documented as a gap, not filled with invented numbers."""
        store = build_reference_knowledge_store()
        candidates = build_reference_candidates(store)
        pn = next(c for c in candidates if c.candidate_id == "nvidia-peoplenet")
        # No benchmark_evidence
        assert len(pn.benchmark_evidence) == 0
        # The evidence should document WHY (JavaScript rendering issue)
        evidence_claims = [r.claim for r in pn.evidence_references]
        assert any(
            "JavaScript" in c
            or "static HTML" in c
            or "not confirmed" in c
            or "dynamically" in c
            or "not extracted" in c
            for c in evidence_claims
        ), (
            "PeopleNet evidence should document the metric-extraction limitation"
        )
