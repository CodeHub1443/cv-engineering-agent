"""
cv_agent.model_selection.selector — build candidates, compare, and select.

Three public functions, each pure and dependency-injected:

  build_candidate()      KnowledgeItems → ModelCandidate
  compare_candidates()   (ModelCandidate, ...) → CandidateComparison
  select_candidate()     CandidateComparison + RequirementsView + LLMProvider → SelectionRecommendation

No network calls.  No execution.  No model downloads.
The LLM is used ONLY in select_candidate() to synthesize a rationale from
evidence already present in the CandidateComparison — it is never asked to
invent benchmarks or introduce new candidates ([P§29.3], [P§35]).

What the LLM sees is a typed SelectionPayloadV1 (ADR-0023): structured fields, local candidate
ordinals and verbatim public claims only — never a free-text prompt, never a candidate_id.

Boundary: imports from cv_agent.knowledge.models, cv_agent.llm.{base, payload} and
cv_agent.model_selection.*; the one exception outside is cv_agent.requirements.structured, and only
RequirementsView (ADR-0023 §3.1). A structural test enforces this (tests/test_selector_boundary.py).
See ADR-0014 §3/§5 and ADR-0023 §3.5.
"""

from __future__ import annotations

import json
import re

from cv_agent.knowledge.models import KnowledgeItem
from cv_agent.llm.base import LLMProvider, LLMRequest
from cv_agent.llm.payload import build_payload
from cv_agent.model_selection.models import (
    CandidateComparison,
    ConflictDimension,
    ConflictNote,
    EvidenceReference,
    ModelCandidate,
    SelectionRecommendation,
)
from cv_agent.model_selection.selection_payload import (
    SelectionNeedsClarification,
    SelectionStaysLocal,
    build_selection_payload,
)
from cv_agent.requirements.structured import RequirementsView

_ORDINAL = re.compile(r"C[1-8]")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> object:
    text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _nonempty_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_candidate(
    *,
    candidate_id: str,
    model_family: str,
    task_support: tuple[str, ...],
    evidence_items: tuple[KnowledgeItem, ...],
    strengths: tuple[str, ...],
    limitations: tuple[str, ...],
    compatibility_constraints: tuple[str, ...],
    benchmark_item_ids: frozenset[str] = frozenset(),
) -> ModelCandidate:
    """Build a ModelCandidate from KnowledgeItems.

    All evidence_items become EvidenceReferences.  Items whose item_id
    appears in benchmark_item_ids are also placed in benchmark_evidence.

    Raises ValueError (propagated from ModelCandidate.__post_init__) if
    evidence_items is empty — a candidate with zero evidence cannot be built.
    """
    refs: tuple[EvidenceReference, ...] = tuple(
        EvidenceReference.from_knowledge_item(item) for item in evidence_items
    )
    bench: tuple[EvidenceReference, ...] = tuple(
        r for r in refs if r.item_id in benchmark_item_ids
    )
    return ModelCandidate(
        candidate_id=candidate_id,
        model_family=model_family,
        task_support=task_support,
        strengths=strengths,
        limitations=limitations,
        compatibility_constraints=compatibility_constraints,
        evidence_references=refs,
        benchmark_evidence=bench,
    )


def compare_candidates(
    candidates: tuple[ModelCandidate, ...],
    *,
    task_description: str,
    known_conflicts: tuple[tuple, ...] = (),
) -> CandidateComparison:
    """Produce a CandidateComparison from already-built candidates.

    known_conflicts: tuples of (item_id_1, item_id_2, dimension, note) and an optional fifth
    element, a ConflictDimension for the hosted payload (default OTHER; the prose stays local).

    research_gaps are inferred deterministically:
    - A candidate with no benchmark_evidence contributes a gap noting the
      absence of benchmarks for that candidate.
    - Candidates with no evidence for hardware-compatibility constraints
      (i.e. compatibility_constraints is empty) contribute a gap.

    Raises ValueError (from CandidateComparison.__post_init__) if candidates
    is empty.
    """
    gaps: list[str] = []
    for c in candidates:
        if not c.benchmark_evidence:
            gaps.append(
                f"No benchmark evidence found for {c.candidate_id} "
                f"({c.model_family}) — performance claims unverified."
            )
        if not c.compatibility_constraints:
            gaps.append(
                f"No hardware-compatibility evidence found for {c.candidate_id} "
                f"({c.model_family}) — deployment constraints unknown."
            )

    conflict_notes: tuple[ConflictNote, ...] = tuple(
        ConflictNote(
            first_item_id=a,
            second_item_id=b,
            dimension=dim,
            note=note,
            dimension_kind=(kind[0] if kind else ConflictDimension.OTHER),
        )
        for a, b, dim, note, *kind in known_conflicts
    )

    return CandidateComparison(
        task_description=task_description,
        candidates=candidates,
        research_gaps=tuple(gaps),
        conflicting_evidence=conflict_notes,
    )


def _insufficient(
    comparison: CandidateComparison, rationale: str, notes: tuple[str, ...]
) -> SelectionRecommendation:
    """A fail-closed recommendation. The first candidate is a placeholder, NOT a real recommendation:
    the caller must inspect confidence and notes."""
    return SelectionRecommendation(
        recommended_candidate_id=comparison.candidates[0].candidate_id,
        comparison=comparison,
        rationale=rationale,
        confidence="insufficient_evidence",
        uncertainty_notes=notes,
        is_proposal=True,
    )


def select_candidate(
    comparison: CandidateComparison,
    *,
    requirements: RequirementsView,
    llm_provider: LLMProvider,
) -> SelectionRecommendation | SelectionNeedsClarification:
    """Reason over the evidence to produce a justified SelectionRecommendation.

    The LLM is given only a SelectionPayloadV1 built from comparison.candidates and the structured
    requirements — it cannot introduce new benchmarks, new candidates, or new conditions
    ([P§29.3], [P§35]) and never receives free text (ADR-0023 §3.5).

    If a required field is unknown, returns SelectionNeedsClarification without calling the LLM. If a
    required field has no admissible term after clarification, or there is no task component, returns
    a local recommendation with confidence="insufficient_evidence" and no call.

    Fail-closed: if the LLM names anything but a listed candidate ordinal (C1..Cn), the recommendation
    is confidence="insufficient_evidence" and the raw response (first 400 chars) is placed in
    uncertainty_notes for the caller to inspect. The first candidate is a placeholder — this is NOT a
    real recommendation; the caller must inspect confidence and notes.
    """
    built = build_selection_payload(comparison, requirements)
    if isinstance(built, SelectionNeedsClarification):
        return built
    if isinstance(built, SelectionStaysLocal):
        return _insufficient(
            comparison,
            "Required requirement fields have no admissible term, so no hosted call was made.",
            ("Unresolved: " + ", ".join(built.unresolved),),
        )
    payload, ordinals = built

    llm_response = llm_provider.complete(LLMRequest(payload=build_payload(payload), max_tokens=1024))

    extracted = _extract_json(llm_response.content)

    # --- Fail-closed: unparseable LLM response ---
    if not isinstance(extracted, dict):
        return _insufficient(
            comparison,
            "LLM response could not be parsed as JSON.",
            ("LLM extraction failed — raw response (first 400 chars): " + repr(llm_response.content[:400]),),
        )

    raw_pick = _nonempty_str(extracted.get("recommended_candidate"))
    raw_rationale = _nonempty_str(extracted.get("rationale"))
    raw_confidence = _nonempty_str(extracted.get("confidence"))
    raw_notes_list = extracted.get("uncertainty_notes")

    # --- Fail-closed: not a listed candidate ordinal ---
    chosen = ordinals.get(int(raw_pick[1:])) if raw_pick and _ORDINAL.fullmatch(raw_pick) else None
    if chosen is None:
        return _insufficient(
            comparison,
            "LLM did not name a listed candidate — falling back to first candidate as placeholder.",
            (
                f"LLM named {raw_pick!r}; valid candidates are C1..C{len(ordinals)}. "
                "Raw response (first 400 chars): " + repr(llm_response.content[:400]),
            ),
        )

    # --- Normalise confidence ---
    _valid_conf = {"high", "medium", "low", "insufficient_evidence"}
    confidence = raw_confidence if raw_confidence in _valid_conf else "insufficient_evidence"

    # --- Normalise uncertainty_notes ---
    notes: tuple[str, ...]
    if isinstance(raw_notes_list, list):
        notes = tuple(str(n) for n in raw_notes_list if str(n).strip())
    else:
        notes = ()

    return SelectionRecommendation(
        recommended_candidate_id=chosen,
        comparison=comparison,
        rationale=raw_rationale or "No rationale provided by LLM.",
        confidence=confidence,  # type: ignore[arg-type]
        uncertainty_notes=notes,
        is_proposal=True,
    )
