"""
Tests for cv_agent.model_selection — data models and selector functions.

Coverage (per ADR-0014 §7 and task specification):
  1. EvidenceReference construction and from_knowledge_item()
  2. ModelCandidate — valid construction, evidence requirement, benchmark subset
  3. ConflictNote — construction validation
  4. CandidateComparison — empty-candidates rejection
  5. SelectionRecommendation — is_proposal invariant, candidate_id validation
  6. build_candidate() — KnowledgeItems → ModelCandidate
  7. compare_candidates() — gap inference, conflict inclusion
  8. select_candidate() — deterministic with FakeLLMProvider, fail-closed paths
  9. No invented benchmark values
 10. No unauthorized execution (is_proposal always True)
 11. Architecture boundary: cv_agent.model_selection imports no forbidden modules
 12. Incomplete evidence handling
 13. Conflicting evidence handling
 14. Unsupported claims handling (candidate_id not in comparison)
"""

from __future__ import annotations

import importlib
import json
from typing import Any

import pytest

from cv_agent.knowledge.models import ItemId, KnowledgeItem, Provenance
from cv_agent.llm.mock import FakeLLMProvider
from cv_agent.model_selection.models import (
    CandidateComparison,
    ConflictNote,
    EvidenceReference,
    ModelCandidate,
    SelectionRecommendation,
)
from cv_agent.model_selection.selector import (
    build_candidate,
    compare_candidates,
    select_candidate,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _prov(url: str = "https://example.com/paper.html") -> Provenance:
    return Provenance(
        url=url,
        source_class="reputable_benchmark",
        date_published="2026-01-01",
        date_accessed="2026-09-28",
        author_or_org="Example Org",
    )


def _item(
    item_id: str = "item-001",
    claim: str = "YOLOv8n achieves 37.3 mAP on COCO val2017",
    *,
    source_class: str = "reputable_benchmark",
    conditions: str | None = "NVIDIA A100, 640px input",
) -> KnowledgeItem:
    return KnowledgeItem(
        item_id=ItemId(item_id),
        claim=claim,
        conditions=conditions,
        provenance=Provenance(
            url=f"https://example.com/{item_id}.html",
            source_class=source_class,  # type: ignore[arg-type]
            date_published="2026-01-01",
            date_accessed="2026-09-28",
            author_or_org="Example Org",
        ),
        topic_tags=("person_detection",),
        staleness_horizon_days=180,
    )


def _candidate(
    candidate_id: str = "yolov8n",
    *,
    model_family: str = "YOLO-v8",
    items: tuple[KnowledgeItem, ...] | None = None,
    benchmark_item_ids: frozenset[str] = frozenset(),
) -> ModelCandidate:
    if items is None:
        items = (_item(),)
    return build_candidate(
        candidate_id=candidate_id,
        model_family=model_family,
        task_support=("object_detection", "tracking_compatible"),
        evidence_items=items,
        strengths=("Fast inference",),
        limitations=("Small model may miss small objects",),
        compatibility_constraints=("Requires CUDA 11+",),
        benchmark_item_ids=benchmark_item_ids,
    )


def _comparison(
    candidates: tuple[ModelCandidate, ...] | None = None,
) -> CandidateComparison:
    if candidates is None:
        candidates = (_candidate(),)
    return compare_candidates(
        candidates=candidates,
        task_description="Person detection + tracking on CCTV/video, NVIDIA GPU",
    )


def _llm_with_json(**fields: Any) -> FakeLLMProvider:
    """FakeLLM that returns a JSON string with the given fields."""
    return FakeLLMProvider(fixed_response=json.dumps(fields))


# ---------------------------------------------------------------------------
# 1. EvidenceReference
# ---------------------------------------------------------------------------

class TestEvidenceReference:
    def test_from_knowledge_item_preserves_fields(self) -> None:
        item = _item("x-001", "Some claim", source_class="reputable_benchmark")
        ref = EvidenceReference.from_knowledge_item(item)
        assert ref.item_id == "x-001"
        assert ref.claim == "Some claim"
        assert ref.source_class == "reputable_benchmark"
        assert ref.url == "https://example.com/x-001.html"

    def test_from_knowledge_item_evidence_weight_from_source_class(self) -> None:
        item = _item(source_class="peer_reviewed_research")
        ref = EvidenceReference.from_knowledge_item(item)
        assert ref.evidence_weight == "high"

    def test_from_knowledge_item_engineering_blog_is_medium(self) -> None:
        item = _item(source_class="engineering_blog")
        ref = EvidenceReference.from_knowledge_item(item)
        assert ref.evidence_weight == "medium"

    def test_from_knowledge_item_professional_post_is_signal_not_evidence(self) -> None:
        item = _item(source_class="professional_post")
        ref = EvidenceReference.from_knowledge_item(item)
        assert ref.evidence_weight == "signal_not_evidence"

    def test_from_knowledge_item_conditions_preserved(self) -> None:
        item = _item(conditions="T4 GPU, 320px")
        ref = EvidenceReference.from_knowledge_item(item)
        assert ref.conditions == "T4 GPU, 320px"

    def test_from_knowledge_item_none_conditions(self) -> None:
        item = _item(conditions=None)
        ref = EvidenceReference.from_knowledge_item(item)
        assert ref.conditions is None

    def test_blank_item_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="item_id"):
            EvidenceReference(
                item_id="",
                claim="claim",
                conditions=None,
                evidence_weight="high",
                source_class="reputable_benchmark",
                url="https://example.com",
            )

    def test_blank_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="url"):
            EvidenceReference(
                item_id="x",
                claim="claim",
                conditions=None,
                evidence_weight="high",
                source_class="reputable_benchmark",
                url="",
            )


# ---------------------------------------------------------------------------
# 2. ModelCandidate
# ---------------------------------------------------------------------------

class TestModelCandidate:
    def test_valid_construction(self) -> None:
        c = _candidate()
        assert c.candidate_id == "yolov8n"
        assert c.model_family == "YOLO-v8"
        assert len(c.evidence_references) == 1

    def test_empty_evidence_rejected(self) -> None:
        with pytest.raises(ValueError, match="evidence_references"):
            ModelCandidate(
                candidate_id="yolov8n",
                model_family="YOLO-v8",
                task_support=("detection",),
                strengths=("Fast",),
                limitations=(),
                compatibility_constraints=(),
                evidence_references=(),
                benchmark_evidence=(),
            )

    def test_empty_task_support_rejected(self) -> None:
        ref = EvidenceReference.from_knowledge_item(_item())
        with pytest.raises(ValueError, match="task_support"):
            ModelCandidate(
                candidate_id="yolov8n",
                model_family="YOLO-v8",
                task_support=(),
                strengths=(),
                limitations=(),
                compatibility_constraints=(),
                evidence_references=(ref,),
                benchmark_evidence=(),
            )

    def test_benchmark_evidence_must_be_subset_of_evidence_references(self) -> None:
        ref_a = EvidenceReference.from_knowledge_item(_item("a"))
        ref_b = EvidenceReference.from_knowledge_item(_item("b"))
        with pytest.raises(ValueError, match="subset of evidence_references"):
            ModelCandidate(
                candidate_id="yolov8n",
                model_family="YOLO-v8",
                task_support=("detection",),
                strengths=(),
                limitations=(),
                compatibility_constraints=(),
                evidence_references=(ref_a,),
                benchmark_evidence=(ref_b,),  # not in evidence_references
            )

    def test_benchmark_evidence_subset_ok(self) -> None:
        item_a = _item("a")
        item_b = _item("b")
        c = build_candidate(
            candidate_id="yolov8n",
            model_family="YOLO-v8",
            task_support=("detection",),
            evidence_items=(item_a, item_b),
            strengths=(),
            limitations=(),
            compatibility_constraints=(),
            benchmark_item_ids=frozenset({"a"}),
        )
        assert len(c.benchmark_evidence) == 1
        assert c.benchmark_evidence[0].item_id == "a"
        assert len(c.evidence_references) == 2

    def test_blank_candidate_id_rejected(self) -> None:
        ref = EvidenceReference.from_knowledge_item(_item())
        with pytest.raises(ValueError, match="candidate_id"):
            ModelCandidate(
                candidate_id="  ",
                model_family="YOLO-v8",
                task_support=("detection",),
                strengths=(),
                limitations=(),
                compatibility_constraints=(),
                evidence_references=(ref,),
                benchmark_evidence=(),
            )


# ---------------------------------------------------------------------------
# 3. ConflictNote
# ---------------------------------------------------------------------------

class TestConflictNote:
    def test_valid_construction(self) -> None:
        cn = ConflictNote(
            first_item_id="a",
            second_item_id="b",
            dimension="mAP on COCO",
            note="Source A says 37.3; Source B says 39.1 (different input resolutions)",
        )
        assert cn.first_item_id == "a"
        assert cn.dimension == "mAP on COCO"

    def test_blank_dimension_rejected(self) -> None:
        with pytest.raises(ValueError, match="dimension"):
            ConflictNote(
                first_item_id="a",
                second_item_id="b",
                dimension="",
                note="note",
            )

    def test_blank_note_rejected(self) -> None:
        with pytest.raises(ValueError, match="note"):
            ConflictNote(
                first_item_id="a",
                second_item_id="b",
                dimension="mAP",
                note="",
            )


# ---------------------------------------------------------------------------
# 4. CandidateComparison
# ---------------------------------------------------------------------------

class TestCandidateComparison:
    def test_empty_candidates_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            CandidateComparison(
                task_description="Person detection",
                candidates=(),
                research_gaps=(),
                conflicting_evidence=(),
            )

    def test_blank_task_description_rejected(self) -> None:
        c = _candidate()
        with pytest.raises(ValueError, match="task_description"):
            CandidateComparison(
                task_description="",
                candidates=(c,),
                research_gaps=(),
                conflicting_evidence=(),
            )

    def test_valid_with_one_candidate(self) -> None:
        cmp = _comparison()
        assert len(cmp.candidates) == 1

    def test_multiple_candidates_preserved(self) -> None:
        c1 = _candidate("yolov8n")
        c2 = _candidate("rtdetr-r50", model_family="RT-DETR", items=(_item("rt-001"),))
        cmp = _comparison((c1, c2))
        assert len(cmp.candidates) == 2


# ---------------------------------------------------------------------------
# 5. SelectionRecommendation — is_proposal invariant
# ---------------------------------------------------------------------------

class TestSelectionRecommendation:
    def _minimal_comparison(self) -> CandidateComparison:
        return _comparison()

    def test_is_proposal_defaults_to_true(self) -> None:
        cmp = self._minimal_comparison()
        rec = SelectionRecommendation(
            recommended_candidate_id="yolov8n",
            comparison=cmp,
            rationale="Evidence shows fast inference.",
            confidence="medium",
            uncertainty_notes=(),
        )
        assert rec.is_proposal is True

    def test_is_proposal_invariant_cannot_be_false(self) -> None:
        """ADR-0014 §7 acceptance test — is_proposal=False must raise ValueError."""
        cmp = self._minimal_comparison()
        with pytest.raises(ValueError, match="is_proposal"):
            SelectionRecommendation(
                recommended_candidate_id="yolov8n",
                comparison=cmp,
                rationale="Evidence shows fast inference.",
                confidence="medium",
                uncertainty_notes=(),
                is_proposal=False,
            )

    def test_recommended_candidate_id_must_be_in_comparison(self) -> None:
        cmp = self._minimal_comparison()
        with pytest.raises(ValueError, match="recommended_candidate_id"):
            SelectionRecommendation(
                recommended_candidate_id="nonexistent-model",
                comparison=cmp,
                rationale="Rationale.",
                confidence="low",
                uncertainty_notes=(),
            )

    def test_invalid_confidence_rejected(self) -> None:
        cmp = self._minimal_comparison()
        with pytest.raises(ValueError, match="confidence"):
            SelectionRecommendation(
                recommended_candidate_id="yolov8n",
                comparison=cmp,
                rationale="Rationale.",
                confidence="very_high",  # type: ignore[arg-type]
                uncertainty_notes=(),
            )

    def test_blank_rationale_rejected(self) -> None:
        cmp = self._minimal_comparison()
        with pytest.raises(ValueError, match="rationale"):
            SelectionRecommendation(
                recommended_candidate_id="yolov8n",
                comparison=cmp,
                rationale="",
                confidence="medium",
                uncertainty_notes=(),
            )

    def test_valid_construction(self) -> None:
        cmp = _comparison((_candidate("rtdetr-r50", model_family="RT-DETR"),))
        rec = SelectionRecommendation(
            recommended_candidate_id="rtdetr-r50",
            comparison=cmp,
            rationale="Strong benchmark evidence at high resolution.",
            confidence="high",
            uncertainty_notes=("No CCTV-specific benchmark found.",),
        )
        assert rec.recommended_candidate_id == "rtdetr-r50"
        assert rec.is_proposal is True
        assert rec.confidence == "high"

    def test_no_unauthorized_execution(self) -> None:
        """A SelectionRecommendation carries no callable that could trigger execution."""
        cmp = self._minimal_comparison()
        rec = SelectionRecommendation(
            recommended_candidate_id="yolov8n",
            comparison=cmp,
            rationale="Fast.",
            confidence="medium",
            uncertainty_notes=(),
        )
        # No run(), execute(), download(), or similar method must exist
        for attr_name in dir(rec):
            if attr_name.startswith("_"):
                continue
            assert attr_name not in (
                "run", "execute", "download", "train", "infer", "invoke"
            ), f"Unexpected callable attribute: {attr_name!r}"


# ---------------------------------------------------------------------------
# 6. build_candidate()
# ---------------------------------------------------------------------------

class TestBuildCandidate:
    def test_all_items_become_evidence_references(self) -> None:
        items = (_item("a"), _item("b"), _item("c"))
        c = build_candidate(
            candidate_id="model-x",
            model_family="FamilyX",
            task_support=("detection",),
            evidence_items=items,
            strengths=(),
            limitations=(),
            compatibility_constraints=(),
        )
        assert len(c.evidence_references) == 3
        assert {r.item_id for r in c.evidence_references} == {"a", "b", "c"}

    def test_benchmark_ids_subset_only(self) -> None:
        items = (_item("bench-1"), _item("general-1"))
        c = build_candidate(
            candidate_id="model-x",
            model_family="FamilyX",
            task_support=("detection",),
            evidence_items=items,
            strengths=(),
            limitations=(),
            compatibility_constraints=(),
            benchmark_item_ids=frozenset({"bench-1"}),
        )
        assert len(c.benchmark_evidence) == 1
        assert c.benchmark_evidence[0].item_id == "bench-1"

    def test_unknown_benchmark_id_silently_excluded(self) -> None:
        # An item_id in benchmark_item_ids that is not in evidence_items is
        # simply not added (no error from build_candidate; ModelCandidate
        # validates only that benchmark_evidence is a subset of evidence_references,
        # which is trivially satisfied if the unknown id maps to nothing).
        items = (_item("a"),)
        c = build_candidate(
            candidate_id="model-x",
            model_family="FamilyX",
            task_support=("detection",),
            evidence_items=items,
            strengths=(),
            limitations=(),
            compatibility_constraints=(),
            benchmark_item_ids=frozenset({"nonexistent-id"}),
        )
        assert len(c.benchmark_evidence) == 0

    def test_empty_evidence_items_raises(self) -> None:
        with pytest.raises(ValueError, match="evidence_references"):
            build_candidate(
                candidate_id="model-x",
                model_family="FamilyX",
                task_support=("detection",),
                evidence_items=(),
                strengths=(),
                limitations=(),
                compatibility_constraints=(),
            )

    def test_evidence_weight_inherited_from_source_class(self) -> None:
        item = _item(source_class="peer_reviewed_research")
        c = build_candidate(
            candidate_id="m",
            model_family="F",
            task_support=("detection",),
            evidence_items=(item,),
            strengths=(),
            limitations=(),
            compatibility_constraints=(),
        )
        assert c.evidence_references[0].evidence_weight == "high"


# ---------------------------------------------------------------------------
# 7. compare_candidates()
# ---------------------------------------------------------------------------

class TestCompareCandidates:
    def test_empty_candidates_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            compare_candidates((), task_description="some task")

    def test_gaps_inferred_for_no_benchmark_evidence(self) -> None:
        # Candidate has no benchmark items → gap recorded
        c = _candidate()  # no benchmark_item_ids → no benchmark_evidence
        cmp = compare_candidates((c,), task_description="Person detection")
        assert any("benchmark evidence" in g for g in cmp.research_gaps)

    def test_gaps_inferred_for_no_compatibility_constraints(self) -> None:
        item = _item()
        c = build_candidate(
            candidate_id="m",
            model_family="F",
            task_support=("detection",),
            evidence_items=(item,),
            strengths=(),
            limitations=(),
            compatibility_constraints=(),  # empty → gap
        )
        cmp = compare_candidates((c,), task_description="Person detection")
        assert any("hardware-compatibility" in g for g in cmp.research_gaps)

    def test_known_conflicts_included(self) -> None:
        c = _candidate()
        cmp = compare_candidates(
            (c,),
            task_description="Person detection",
            known_conflicts=(
                ("item-a", "item-b", "mAP on COCO", "Different resolutions"),
            ),
        )
        assert len(cmp.conflicting_evidence) == 1
        assert cmp.conflicting_evidence[0].first_item_id == "item-a"

    def test_no_gaps_when_both_present(self) -> None:
        item = _item("bench-1")
        c = build_candidate(
            candidate_id="m",
            model_family="F",
            task_support=("detection",),
            evidence_items=(item,),
            strengths=(),
            limitations=(),
            compatibility_constraints=("Requires CUDA 11+",),
            benchmark_item_ids=frozenset({"bench-1"}),
        )
        cmp = compare_candidates((c,), task_description="Task")
        # No gaps for this candidate (has both benchmark and compatibility)
        assert not any("m" in g for g in cmp.research_gaps)

    def test_multiple_candidates_preserved(self) -> None:
        c1 = _candidate("a")
        c2 = _candidate("b", items=(_item("b-1"),))
        cmp = compare_candidates((c1, c2), task_description="Task")
        assert len(cmp.candidates) == 2


# ---------------------------------------------------------------------------
# 8. select_candidate() — happy path and fail-closed paths
# ---------------------------------------------------------------------------

class TestSelectCandidate:
    def _valid_json(self, candidate_id: str = "yolov8n") -> str:
        return json.dumps({
            "recommended_candidate_id": candidate_id,
            "rationale": "Benchmark evidence shows fast inference on NVIDIA GPU.",
            "confidence": "medium",
            "uncertainty_notes": ["No CCTV-specific benchmark found."],
        })

    def test_valid_response_produces_recommendation(self) -> None:
        cmp = _comparison()
        llm = FakeLLMProvider(fixed_response=self._valid_json("yolov8n"))
        rec = select_candidate(cmp, llm_provider=llm)
        assert rec.recommended_candidate_id == "yolov8n"
        assert rec.confidence == "medium"
        assert rec.is_proposal is True
        assert llm.call_count == 1

    def test_is_proposal_always_true_from_selector(self) -> None:
        cmp = _comparison()
        llm = FakeLLMProvider(fixed_response=self._valid_json())
        rec = select_candidate(cmp, llm_provider=llm)
        assert rec.is_proposal is True

    def test_llm_called_exactly_once(self) -> None:
        cmp = _comparison((_candidate("a"), _candidate("b", items=(_item("b"),))))
        llm = FakeLLMProvider(fixed_response=self._valid_json("a"))
        select_candidate(cmp, llm_provider=llm)
        assert llm.call_count == 1

    def test_deterministic_with_fixed_llm(self) -> None:
        cmp = _comparison()
        llm = FakeLLMProvider(fixed_response=self._valid_json())
        rec1 = select_candidate(cmp, llm_provider=llm)
        rec2 = select_candidate(cmp, llm_provider=llm)
        assert rec1.recommended_candidate_id == rec2.recommended_candidate_id
        assert rec1.confidence == rec2.confidence

    def test_unknown_candidate_id_from_llm_falls_back_to_insufficient(self) -> None:
        """ADR-0014 §7 acceptance test — fail-closed when LLM names wrong candidate."""
        cmp = _comparison()
        llm = FakeLLMProvider(fixed_response=json.dumps({
            "recommended_candidate_id": "nonexistent-model-xyz",
            "rationale": "Best ever.",
            "confidence": "high",
            "uncertainty_notes": [],
        }))
        rec = select_candidate(cmp, llm_provider=llm)
        assert rec.confidence == "insufficient_evidence"
        assert "nonexistent-model-xyz" in rec.uncertainty_notes[0]

    def test_no_invented_benchmark_values(self) -> None:
        """The selector must not introduce benchmark numbers absent from evidence."""
        # The LLM (fake) is given only the evidence in comparison.candidates.
        # The test verifies the rationale does NOT contain numbers from outside
        # the evidence by checking it comes from the LLM's fixed_response only.
        cmp = _comparison()
        llm_rationale = "Benchmark evidence shows fast inference on NVIDIA GPU."
        llm = FakeLLMProvider(fixed_response=json.dumps({
            "recommended_candidate_id": "yolov8n",
            "rationale": llm_rationale,
            "confidence": "medium",
            "uncertainty_notes": [],
        }))
        rec = select_candidate(cmp, llm_provider=llm)
        # rationale comes from LLM — which we control here via fixed_response
        # The selector must not have added any number not in the prompt
        assert rec.rationale == llm_rationale

    def test_unparseable_llm_response_falls_back_to_insufficient(self) -> None:
        cmp = _comparison()
        llm = FakeLLMProvider(fixed_response="This is not JSON at all.")
        rec = select_candidate(cmp, llm_provider=llm)
        assert rec.confidence == "insufficient_evidence"

    def test_invalid_confidence_from_llm_becomes_insufficient(self) -> None:
        cmp = _comparison()
        llm = FakeLLMProvider(fixed_response=json.dumps({
            "recommended_candidate_id": "yolov8n",
            "rationale": "Some rationale.",
            "confidence": "extremely_high",
            "uncertainty_notes": [],
        }))
        rec = select_candidate(cmp, llm_provider=llm)
        assert rec.confidence == "insufficient_evidence"

    def test_multi_candidate_comparison(self) -> None:
        c1 = _candidate("yolov8n")
        c2 = _candidate(
            "rtdetr-r50",
            model_family="RT-DETR",
            items=(_item("rt-001", "RT-DETR achieves 53.1 mAP on COCO val2017"),),
        )
        cmp = compare_candidates((c1, c2), task_description="Person detection")
        llm = FakeLLMProvider(fixed_response=json.dumps({
            "recommended_candidate_id": "rtdetr-r50",
            "rationale": "Higher mAP evidence.",
            "confidence": "low",
            "uncertainty_notes": ["Latency not benchmarked."],
        }))
        rec = select_candidate(cmp, llm_provider=llm)
        assert rec.recommended_candidate_id == "rtdetr-r50"
        assert rec.confidence == "low"

    def test_insufficient_evidence_path(self) -> None:
        """A comparison with all research_gaps should still produce a result."""
        c = _candidate()  # no benchmark_evidence → gap inferred
        cmp = compare_candidates((c,), task_description="Task")
        assert cmp.research_gaps  # gaps were inferred
        llm = FakeLLMProvider(fixed_response=json.dumps({
            "recommended_candidate_id": "yolov8n",
            "rationale": "Only candidate.",
            "confidence": "insufficient_evidence",
            "uncertainty_notes": ["No benchmark evidence found."],
        }))
        rec = select_candidate(cmp, llm_provider=llm)
        assert rec.confidence == "insufficient_evidence"
        assert rec.is_proposal is True

    def test_conflicting_evidence_preserved_in_comparison(self) -> None:
        c1 = _candidate("a")
        c2 = _candidate("b", items=(_item("b"),))
        cmp = compare_candidates(
            (c1, c2),
            task_description="Task",
            known_conflicts=(("a-1", "b-1", "mAP", "Different hardware"),),
        )
        llm = FakeLLMProvider(fixed_response=json.dumps({
            "recommended_candidate_id": "a",
            "rationale": "Chose despite conflict.",
            "confidence": "low",
            "uncertainty_notes": ["Conflicting mAP evidence."],
        }))
        rec = select_candidate(cmp, llm_provider=llm)
        assert len(rec.comparison.conflicting_evidence) == 1
        assert rec.confidence == "low"

    def test_uncertainty_notes_empty_list(self) -> None:
        cmp = _comparison()
        llm = FakeLLMProvider(fixed_response=json.dumps({
            "recommended_candidate_id": "yolov8n",
            "rationale": "Fast.",
            "confidence": "high",
            "uncertainty_notes": [],
        }))
        rec = select_candidate(cmp, llm_provider=llm)
        assert rec.uncertainty_notes == ()

    def test_null_uncertainty_notes_from_llm(self) -> None:
        cmp = _comparison()
        llm = FakeLLMProvider(fixed_response=json.dumps({
            "recommended_candidate_id": "yolov8n",
            "rationale": "Fast.",
            "confidence": "high",
            "uncertainty_notes": None,
        }))
        rec = select_candidate(cmp, llm_provider=llm)
        assert rec.uncertainty_notes == ()


# ---------------------------------------------------------------------------
# 9. Reference task: person detection + tracking candidates
# ---------------------------------------------------------------------------

class TestReferenceTaskCandidates:
    """
    Builds a minimal multi-candidate comparison reflecting the reference task.
    All evidence is synthetic (no real network calls).
    Verifies that the model-selection flow produces a SelectionRecommendation
    that is a proposal and references one of the known candidates.
    """

    def _make_yolo_candidate(self) -> ModelCandidate:
        items = (
            _item(
                "yolo-coco",
                "YOLOv8n achieves 37.3 mAP on COCO val2017",
                source_class="reputable_benchmark",
                conditions="NVIDIA A100, 640px, batch 32",
            ),
            _item(
                "yolo-tao",
                "NVIDIA TAO Toolkit supports YOLOv8 fine-tuning and export",
                source_class="official_documentation",
                conditions="Requires NVIDIA GPU; TensorRT export supported",
            ),
        )
        return build_candidate(
            candidate_id="yolov8n",
            model_family="YOLO-v8",
            task_support=("object_detection", "tracking_compatible", "real_time"),
            evidence_items=items,
            strengths=("State-of-art speed/accuracy trade-off", "NVIDIA TAO support"),
            limitations=("Anchor-free but may miss small/dense objects"),
            compatibility_constraints=("NVIDIA GPU; CUDA 11+; TensorRT 8+"),
            benchmark_item_ids=frozenset({"yolo-coco"}),
        )

    def _make_rtdetr_candidate(self) -> ModelCandidate:
        items = (
            _item(
                "rtdetr-coco",
                "RT-DETR-R50 achieves 53.1 mAP on COCO val2017",
                source_class="peer_reviewed_research",
                conditions="NVIDIA A100, 640px",
            ),
            _item(
                "rtdetr-latency",
                "RT-DETR-R50 runs at 108 FPS on T4 GPU",
                source_class="reputable_benchmark",
                conditions="NVIDIA T4 GPU, TensorRT, FP16",
            ),
        )
        return build_candidate(
            candidate_id="rtdetr-r50",
            model_family="RT-DETR",
            task_support=("object_detection", "tracking_compatible"),
            evidence_items=items,
            strengths=("High mAP", "Transformer-based; no NMS needed"),
            limitations=("Higher memory footprint than YOLO-v8n", "Slower than YOLO at same scale"),
            compatibility_constraints=("NVIDIA GPU; TensorRT support via ONNX export"),
            benchmark_item_ids=frozenset({"rtdetr-coco", "rtdetr-latency"}),
        )

    def _make_tao_candidate(self) -> ModelCandidate:
        items = (
            _item(
                "tao-detectnet",
                "NVIDIA TAO DetectNet_v2 is optimised for real-time CCTV person detection",
                source_class="official_documentation",
                conditions="NVIDIA DeepStream; requires TAO Toolkit license",
            ),
        )
        return build_candidate(
            candidate_id="tao-detectnetv2",
            model_family="NVIDIA-TAO",
            task_support=("object_detection", "real_time", "nvidia_native"),
            evidence_items=items,
            strengths=("Native NVIDIA/DeepStream integration", "Optimised for low-resource CCTV"),
            limitations=("Less community documentation", "TAO license required"),
            compatibility_constraints=("NVIDIA GPU; NVIDIA DeepStream; TAO Toolkit"),
        )

    def test_reference_task_produces_proposal(self) -> None:
        c1 = self._make_yolo_candidate()
        c2 = self._make_rtdetr_candidate()
        c3 = self._make_tao_candidate()

        cmp = compare_candidates(
            (c1, c2, c3),
            task_description=(
                "High-performance real-time person detection and tracking on "
                "CCTV/video, NVIDIA GPU, low-resource constraints"
            ),
            known_conflicts=(
                (
                    "yolo-coco",
                    "rtdetr-coco",
                    "mAP on COCO val2017",
                    "YOLO reports 37.3; RT-DETR reports 53.1; "
                    "different model sizes (nano vs R50) — not directly comparable",
                ),
            ),
        )
        assert len(cmp.candidates) == 3
        assert len(cmp.conflicting_evidence) == 1

        # Use a fake LLM that recommends the YOLO candidate
        llm = FakeLLMProvider(fixed_response=json.dumps({
            "recommended_candidate_id": "yolov8n",
            "rationale": (
                "YOLOv8n achieves 37.3 mAP with NVIDIA TAO support and runs "
                "in real-time; benchmark shows feasibility for CCTV use case."
            ),
            "confidence": "medium",
            "uncertainty_notes": [
                "Benchmark is on general COCO, not CCTV-specific data.",
                "RT-DETR has higher mAP but is a larger model.",
            ],
        }))

        rec = select_candidate(cmp, llm_provider=llm)

        assert rec.is_proposal is True
        assert rec.recommended_candidate_id in {"yolov8n", "rtdetr-r50", "tao-detectnetv2"}
        assert rec.recommended_candidate_id == "yolov8n"
        assert "37.3 mAP" in rec.rationale
        assert rec.confidence == "medium"
        assert len(rec.uncertainty_notes) == 2


# ---------------------------------------------------------------------------
# 10. Architecture boundary
# ---------------------------------------------------------------------------

class TestArchitectureBoundary:
    """cv_agent.model_selection must not import forbidden modules (ADR-0014 §2)."""

    _FORBIDDEN_PREFIXES = (
        "cv_agent.execution",
        "cv_agent.skills",
        "cv_agent.graph",
        "cv_agent.tools",
        "cv_agent.runtime",
    )

    def _imported_modules(self, module_name: str) -> set[str]:
        mod = importlib.import_module(module_name)
        src = mod.__file__ or ""
        # Read the source and look for import statements
        with open(src) as f:
            lines = f.readlines()
        imported: set[str] = set()
        for line in lines:
            line = line.strip()
            if line.startswith("from ") or line.startswith("import "):
                # Extract the module being imported
                parts = line.split()
                if parts[0] == "from" and len(parts) >= 2:
                    imported.add(parts[1])
                elif parts[0] == "import" and len(parts) >= 2:
                    imported.add(parts[1])
        return imported

    def test_models_does_not_import_forbidden_modules(self) -> None:
        imported = self._imported_modules("cv_agent.model_selection.models")
        for prefix in self._FORBIDDEN_PREFIXES:
            for mod in imported:
                assert not mod.startswith(prefix), (
                    f"cv_agent.model_selection.models imports {mod!r}, "
                    f"which is forbidden (prefix {prefix!r}) — ADR-0014 §2"
                )

    def test_selector_does_not_import_forbidden_modules(self) -> None:
        imported = self._imported_modules("cv_agent.model_selection.selector")
        for prefix in self._FORBIDDEN_PREFIXES:
            for mod in imported:
                assert not mod.startswith(prefix), (
                    f"cv_agent.model_selection.selector imports {mod!r}, "
                    f"which is forbidden (prefix {prefix!r}) — ADR-0014 §2"
                )
