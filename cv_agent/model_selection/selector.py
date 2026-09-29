"""
cv_agent.model_selection.selector — build candidates, compare, and select.

Three public functions, each pure and dependency-injected:

  build_candidate()      KnowledgeItems → ModelCandidate
  compare_candidates()   (ModelCandidate, ...) → CandidateComparison
  select_candidate()     CandidateComparison + LLMProvider → SelectionRecommendation

No network calls.  No execution.  No model downloads.
The LLM is used ONLY in select_candidate() to synthesize a rationale from
evidence already present in the CandidateComparison — it is never asked to
invent benchmarks or introduce new candidates ([P§29.3], [P§35]).

Boundary: imports from cv_agent.knowledge.models and cv_agent.llm.base only
(structural test enforces this — see tests/test_model_selection.py).
See ADR-0014 §3/§5.
"""

from __future__ import annotations

import json

from cv_agent.knowledge.models import KnowledgeItem
from cv_agent.llm.base import LLMProvider, LLMRequest
from cv_agent.model_selection.models import (
    CandidateComparison,
    ConflictNote,
    EvidenceReference,
    ModelCandidate,
    SelectionRecommendation,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# LLM prompt kept small — evidence text is summarised to CLAIM + CONDITIONS only;
# full fetched HTML is never re-sent here.
_MAX_EVIDENCE_ITEMS_PER_CANDIDATE = 20
_MAX_CLAIM_CHARS = 300

_SELECTION_SYSTEM = (
    "You are a structured model-selection reasoning engine for a computer vision "
    "engineering system.  You read evidence gathered from real sources and return "
    "ONLY a JSON object.  Never add prose outside the JSON.  "
    "Never invent benchmark numbers, hardware conditions, or model variants not "
    "present in the evidence.  Return null for any field you cannot support from "
    "the evidence."
)

_SELECTION_PROMPT = """\
Task: {task_description}

You are choosing between the following model candidates for this task.
Each candidate lists the evidence gathered from real sources.

{candidates_text}

Research gaps (evidence that was NOT found):
{gaps_text}

Conflicting evidence:
{conflicts_text}

Select the single best candidate for the task based only on the evidence above.
Return ONLY a JSON object with exactly these four keys:

{{
  "recommended_candidate_id": "<one of: {candidate_id_list}>",
  "rationale": "<1-3 sentence rationale citing specific evidence claims above>",
  "confidence": "<one of: high, medium, low, insufficient_evidence>",
  "uncertainty_notes": ["<note 1>", "<note 2>"]
}}

Rules:
- recommended_candidate_id MUST be one of the listed candidate IDs.
- rationale MUST cite claims from the evidence above.  Never add numbers not \
in the evidence.
- confidence = "insufficient_evidence" if the evidence is too sparse to decide.
- uncertainty_notes = [] if there are none.
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _truncate_claim(claim: str) -> str:
    if len(claim) <= _MAX_CLAIM_CHARS:
        return claim
    return claim[:_MAX_CLAIM_CHARS] + "…"


def _format_evidence_ref(ref: EvidenceReference) -> str:
    parts = [f"  [{ref.source_class} / {ref.evidence_weight}] {_truncate_claim(ref.claim)}"]
    if ref.conditions:
        parts.append(f"    conditions: {ref.conditions}")
    parts.append(f"    source: {ref.url}")
    return "\n".join(parts)


def _format_candidate_for_prompt(candidate: ModelCandidate) -> str:
    lines: list[str] = [
        f"=== {candidate.candidate_id} (family: {candidate.model_family}) ===",
        f"Task support: {', '.join(candidate.task_support)}",
    ]
    if candidate.strengths:
        lines.append("Strengths:")
        lines.extend(f"  - {s}" for s in candidate.strengths)
    if candidate.limitations:
        lines.append("Limitations:")
        lines.extend(f"  - {lim}" for lim in candidate.limitations)
    if candidate.compatibility_constraints:
        lines.append("Compatibility constraints:")
        lines.extend(f"  - {c}" for c in candidate.compatibility_constraints)
    # Evidence (cap to avoid extremely long prompts)
    refs = candidate.evidence_references[:_MAX_EVIDENCE_ITEMS_PER_CANDIDATE]
    if refs:
        lines.append("Evidence:")
        lines.extend(_format_evidence_ref(r) for r in refs)
    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
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
    known_conflicts: tuple[tuple[str, str, str, str], ...] = (),
) -> CandidateComparison:
    """Produce a CandidateComparison from already-built candidates.

    known_conflicts: tuples of (item_id_1, item_id_2, dimension, note).

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
        )
        for a, b, dim, note in known_conflicts
    )

    return CandidateComparison(
        task_description=task_description,
        candidates=candidates,
        research_gaps=tuple(gaps),
        conflicting_evidence=conflict_notes,
    )


def select_candidate(
    comparison: CandidateComparison,
    *,
    llm_provider: LLMProvider,
) -> SelectionRecommendation:
    """Reason over the evidence to produce a justified SelectionRecommendation.

    The LLM is given only the evidence already in comparison.candidates — it
    cannot introduce new benchmarks, new candidates, or new conditions
    ([P§29.3], [P§35]).

    Fail-closed: if the LLM names a candidate_id not in comparison.candidates,
    the recommendation is confidence="insufficient_evidence" and the raw LLM
    response (first 400 chars) is placed in uncertainty_notes for the caller
    to inspect.  A new SelectionRecommendation is built with the first listed
    candidate_id as the placeholder — this is NOT a real recommendation; the
    caller must inspect confidence and notes.
    """
    candidate_ids: list[str] = [c.candidate_id for c in comparison.candidates]

    candidates_text = "\n\n".join(
        _format_candidate_for_prompt(c) for c in comparison.candidates
    )
    gaps_text = (
        "\n".join(f"- {g}" for g in comparison.research_gaps)
        if comparison.research_gaps
        else "(none recorded)"
    )
    conflicts_text = (
        "\n".join(
            f"- {cn.dimension}: {cn.first_item_id} vs {cn.second_item_id}: {cn.note}"
            for cn in comparison.conflicting_evidence
        )
        if comparison.conflicting_evidence
        else "(none recorded)"
    )

    prompt = _SELECTION_PROMPT.format(
        task_description=comparison.task_description,
        candidates_text=candidates_text,
        gaps_text=gaps_text,
        conflicts_text=conflicts_text,
        candidate_id_list=", ".join(candidate_ids),
    )

    llm_response = llm_provider.complete(
        LLMRequest(
            prompt=prompt,
            system=_SELECTION_SYSTEM,
            max_tokens=1024,
            temperature=0.0,
        )
    )

    extracted = _extract_json(llm_response.content)

    # --- Fail-closed: unparseable LLM response ---
    if extracted is None:
        return SelectionRecommendation(
            recommended_candidate_id=candidate_ids[0],
            comparison=comparison,
            rationale="LLM response could not be parsed as JSON.",
            confidence="insufficient_evidence",
            uncertainty_notes=(
                "LLM extraction failed — raw response (first 400 chars): "
                + repr(llm_response.content[:400]),
            ),
            is_proposal=True,
        )

    raw_id = _nonempty_str(extracted.get("recommended_candidate_id"))
    raw_rationale = _nonempty_str(extracted.get("rationale"))
    raw_confidence = _nonempty_str(extracted.get("confidence"))
    raw_notes_list = extracted.get("uncertainty_notes")

    # --- Fail-closed: recommended candidate not in comparison ---
    if raw_id not in candidate_ids:
        return SelectionRecommendation(
            recommended_candidate_id=candidate_ids[0],
            comparison=comparison,
            rationale=(
                "LLM recommended a candidate_id not in comparison.candidates — "
                "falling back to first candidate as placeholder."
            ),
            confidence="insufficient_evidence",
            uncertainty_notes=(
                f"LLM named {raw_id!r}; valid ids are {candidate_ids!r}. "
                "Raw response (first 400 chars): "
                + repr(llm_response.content[:400]),
            ),
            is_proposal=True,
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
        recommended_candidate_id=raw_id,
        comparison=comparison,
        rationale=raw_rationale or "No rationale provided by LLM.",
        confidence=confidence,  # type: ignore[arg-type]
        uncertainty_notes=notes,
        is_proposal=True,
    )
