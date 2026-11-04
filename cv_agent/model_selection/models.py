"""
cv_agent.model_selection.models — frozen data types for model-selection output.

All types validate themselves at construction (fail-closed).
No scoring or ranking system — evidence-based representation only.

Boundary: imports from cv_agent.knowledge.models only.
See ADR-0014 §2/§5.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cv_agent.knowledge.models import EvidenceWeight, KnowledgeItem, SourceClass

SelectionConfidence = Literal[
    "high",
    "medium",
    "low",
    "insufficient_evidence",
]

_VALID_CONFIDENCE: frozenset[str] = frozenset(
    {"high", "medium", "low", "insufficient_evidence"}
)


def _require_nonblank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string, got {value!r}")


@dataclass(frozen=True)
class EvidenceReference:
    """Lightweight reference to a KnowledgeItem backing a claim about a candidate.

    Created via EvidenceReference.from_knowledge_item() — evidence_weight is
    taken from the item's fixed source-class mapping, never independently
    overridable (ADR-0006 §4 / docs/RESEARCH_POLICY.md §3).
    """

    item_id: str
    claim: str
    conditions: str | None
    evidence_weight: EvidenceWeight
    source_class: SourceClass
    url: str

    def __post_init__(self) -> None:
        _require_nonblank(self.item_id, "EvidenceReference.item_id")
        _require_nonblank(self.claim, "EvidenceReference.claim")
        _require_nonblank(self.url, "EvidenceReference.url")

    @classmethod
    def from_knowledge_item(cls, item: KnowledgeItem) -> "EvidenceReference":
        """Build an EvidenceReference from a stored KnowledgeItem.

        evidence_weight is derived from the item's source_class via the fixed
        table in cv_agent.knowledge.models — the caller cannot override it.
        """
        return cls(
            item_id=str(item.item_id),
            claim=item.claim,
            conditions=item.conditions,
            evidence_weight=item.evidence_weight(),
            source_class=item.provenance.source_class,
            url=item.provenance.url,
        )


@dataclass(frozen=True)
class ModelCandidate:
    """A model family/variant under consideration for a CV task.

    Requires at least one evidence_reference — a candidate with zero evidence
    cannot be constructed.  benchmark_evidence items must all appear in
    evidence_references (validated at construction).
    """

    candidate_id: str
    model_family: str
    task_support: tuple[str, ...]
    strengths: tuple[str, ...]
    limitations: tuple[str, ...]
    compatibility_constraints: tuple[str, ...]
    evidence_references: tuple[EvidenceReference, ...]
    benchmark_evidence: tuple[EvidenceReference, ...]

    def __post_init__(self) -> None:
        _require_nonblank(self.candidate_id, "ModelCandidate.candidate_id")
        _require_nonblank(self.model_family, "ModelCandidate.model_family")
        if not isinstance(self.task_support, tuple) or len(self.task_support) == 0:
            raise ValueError("ModelCandidate.task_support must be a non-empty tuple")
        if not isinstance(self.evidence_references, tuple) or len(self.evidence_references) == 0:
            raise ValueError(
                "ModelCandidate.evidence_references must be a non-empty tuple — "
                "a candidate with zero evidence cannot be constructed"
            )
        # benchmark_evidence must be a subset of evidence_references
        ref_ids = {r.item_id for r in self.evidence_references}
        for bref in self.benchmark_evidence:
            if bref.item_id not in ref_ids:
                raise ValueError(
                    f"ModelCandidate.benchmark_evidence item {bref.item_id!r} "
                    "is not in evidence_references — benchmark_evidence must be "
                    "a subset of evidence_references"
                )


@dataclass(frozen=True)
class ConflictNote:
    """Documents a disagreement between two evidence references.

    Preserved exactly as supplied — the selector detects conflicts, but
    interpreting them is left to the reasoning layer (select_candidate).
    """

    first_item_id: str
    second_item_id: str
    dimension: str
    note: str

    def __post_init__(self) -> None:
        _require_nonblank(self.first_item_id, "ConflictNote.first_item_id")
        _require_nonblank(self.second_item_id, "ConflictNote.second_item_id")
        _require_nonblank(self.dimension, "ConflictNote.dimension")
        _require_nonblank(self.note, "ConflictNote.note")


@dataclass(frozen=True)
class CandidateComparison:
    """Evidence-based side-by-side of model candidates. No scoring or ranking.

    Fails at construction if candidates is empty — a comparison with zero
    candidates is not meaningful.
    """

    task_description: str
    candidates: tuple[ModelCandidate, ...]
    research_gaps: tuple[str, ...]
    conflicting_evidence: tuple[ConflictNote, ...]

    def __post_init__(self) -> None:
        _require_nonblank(self.task_description, "CandidateComparison.task_description")
        if not isinstance(self.candidates, tuple) or len(self.candidates) == 0:
            raise ValueError(
                "CandidateComparison.candidates must be a non-empty tuple"
            )


@dataclass(frozen=True)
class SelectionRecommendation:
    """A proposed model candidate. Always a proposal — never an execution auth.

    is_proposal is invariant True; __post_init__ raises ValueError if a caller
    attempts to set it to False.  recommended_candidate_id must match the
    candidate_id of exactly one entry in comparison.candidates.
    """

    recommended_candidate_id: str
    comparison: CandidateComparison
    rationale: str
    confidence: SelectionConfidence
    uncertainty_notes: tuple[str, ...]
    is_proposal: bool = True

    def __post_init__(self) -> None:
        # Invariant: is_proposal is always True — enforced here, never caller-settable
        if self.is_proposal is not True:
            raise ValueError(
                "SelectionRecommendation.is_proposal must be True — "
                "a SelectionRecommendation is always a proposal, never an "
                "execution authorization (ADR-0014 §3)"
            )
        _require_nonblank(
            self.recommended_candidate_id,
            "SelectionRecommendation.recommended_candidate_id",
        )
        _require_nonblank(self.rationale, "SelectionRecommendation.rationale")
        if self.confidence not in _VALID_CONFIDENCE:
            raise ValueError(
                f"SelectionRecommendation.confidence must be one of "
                f"{sorted(_VALID_CONFIDENCE)!r}, got {self.confidence!r}"
            )
        # recommended_candidate_id must appear in comparison.candidates
        candidate_ids = {c.candidate_id for c in self.comparison.candidates}
        if self.recommended_candidate_id not in candidate_ids:
            raise ValueError(
                f"SelectionRecommendation.recommended_candidate_id "
                f"{self.recommended_candidate_id!r} is not in comparison.candidates "
                f"(available: {sorted(candidate_ids)!r})"
            )
