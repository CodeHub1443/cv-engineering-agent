# ADR-0014: Model Selection

- **Status:** Accepted
- **Date:** 2026-09-28
- **Layer:** reasoning
- **Canon:** `[P§5]`, `[P§11]`, `[P§15]`, `[P§16]`, `[P§17]`, `[P§18]`, `[P§19]`, `[P§23]`, `[P§29.1]`, `[P§29.2]`, `[P§29.3]`, `[P§29.4]`, `[P§34]`, `[P§35]`
- **Supersedes / Superseded by:** —
- **Issue:** #— (Model Selection milestone, reference task: person detection + tracking)

## 1. Context

D-043 (2026-09-28) resolved `OPEN_QUESTIONS.md` Q24: the reference project is **Person
Detection + Tracking**. The owner's explicit instruction is that "the Agent must research
and select the model/approach itself — it must not be hardcoded to YOLO."

The research path is complete (ADR-0005 §13 `web-research-fetch`, `cv_agent.graph.research.
perform_research`, ADR-0006 `KnowledgeStore`/`KnowledgeItem`, ADR-0002 `LLMProvider`).
No module in the codebase is responsible for:
- Representing a candidate model with evidence
- Comparing candidates against task requirements
- Producing a justified, evidence-backed model-selection proposal

No existing ADR grants this responsibility. The canon rule `[P§29.1]` requires problem
characterisation before a model is proposed; `[P§29.3]` requires quantitative comparison
against a baseline before claiming improvement; `[P§34]` requires a clean boundary
statement before any new subsystem is added.

The architecture's hard constraint: the model selection must be a **proposal**, not an
execution authorization. No model download, no inference, no training begins as a
consequence of this module's output.

## 2. Responsibility (required — `[P§34]`)

- **This owns:** Converting a set of KnowledgeItems (fetched and stored by the research
  path) into a structured, evidence-backed model candidate comparison and a justified
  selection proposal.
- **This does NOT own:**
  - Fetching evidence from the web — owned by `cv_agent.tools.web_research` +
    `cv_agent.graph.research` (ADR-0005/ADR-0003).
  - Storing/retrieving KnowledgeItems — owned by `cv_agent.knowledge` (ADR-0006).
  - LLM reasoning infrastructure — owned by `cv_agent.llm` (ADR-0002).
  - Task requirements analysis — owned by `cv_agent.requirements` (ADR-0008).
  - Executing a model, downloading weights, or starting training — owned by
    `cv_agent.execution` / `cv_agent.execution.jobs` (ADR-0009, ADR-0013).
  - Tracking experiment results — owned by `cv_agent.experiments` (ADR-0011).
  - Authorizing any action — owned by the approval interrupt in the orchestration
    graph (ADR-0003 §10).
- **Why this responsibility does not belong to an existing component:**
  - `cv_agent.requirements` analyses a task request; it does not know about specific
    model families, benchmarks, or hardware compatibility.
  - `cv_agent.knowledge` is a storage layer; it does not reason about which items
    favour which candidate.
  - `cv_agent.graph.research` acquires and stores a single KnowledgeItem per call;
    it does not aggregate evidence across candidates or produce a comparison.

## 3. Decision

Add a new reasoning-layer package `cv_agent/model_selection/` with two modules:

- `models.py` — frozen data classes: `EvidenceReference`, `ModelCandidate`,
  `ConflictNote`, `CandidateComparison`, `SelectionRecommendation`. All fail-closed at
  construction. `is_proposal` on `SelectionRecommendation` is invariant `True` —
  enforced by `__post_init__`, never caller-settable.
- `selector.py` — pure, dependency-injected functions that consume `KnowledgeItem`
  sequences and an `LLMProvider` to build candidates, compare them, and produce a
  recommendation. No scoring/ranking system; evidence-based comparison only.

The module imports from `cv_agent.knowledge.models` and `cv_agent.llm.base` only.
It does not import from `cv_agent.execution`, `cv_agent.skills`, `cv_agent.graph`,
or `cv_agent.tools`. A structural test enforces this.

## 4. Alternatives considered

| Alternative | Evidence for | Evidence against | Why not chosen |
|---|---|---|---|
| Embed model selection inside `RequirementsAnalyzer` | No new module | Conflates task analysis (what do you need) with candidate research (which models exist) — `[P§34]` violation; breaks `[P§19]`'s layer separation | Layer leakage |
| Add model selection to the LangGraph `AgentState` and `workflow.py` | Closer to existing orchestration | Changes `AgentState` shape (ADR required anyway); couples a data-structure concern to the graph topology; blocks testing the data model independently | Premature coupling to orchestration |
| Let the LLM hallucinate candidates from memory | Simpler build | Violates `[P§29.3]` (no quantitative comparison), `[P§29.10]` (newer ≠ better), `[P§35]` (silent invention) | Directly prohibited by canon |

## 5. Interface

```python
# module: cv_agent.model_selection.models

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from cv_agent.knowledge.models import EvidenceWeight, KnowledgeItem, SourceClass

SelectionConfidence = Literal[
    "high",
    "medium",
    "low",
    "insufficient_evidence",
]


@dataclass(frozen=True)
class EvidenceReference:
    """Lightweight reference to a KnowledgeItem backing a claim about a candidate.

    Created via EvidenceReference.from_knowledge_item() — never constructed
    directly from arbitrary strings; the evidence_weight is copied from the
    item's fixed source-class weighting, never independently settable.
    """

    item_id: str
    claim: str
    conditions: str | None
    evidence_weight: EvidenceWeight
    source_class: SourceClass
    url: str

    @classmethod
    def from_knowledge_item(cls, item: KnowledgeItem) -> "EvidenceReference": ...


@dataclass(frozen=True)
class ModelCandidate:
    """A model family/variant under consideration for a CV task.

    Strengths, limitations, and constraints are backed by evidence_references —
    the selector enforces this: no claim without a corresponding EvidenceReference.
    benchmark_evidence must be a subset of evidence_references.
    """

    candidate_id: str
    model_family: str
    task_support: tuple[str, ...]
    strengths: tuple[str, ...]
    limitations: tuple[str, ...]
    compatibility_constraints: tuple[str, ...]
    evidence_references: tuple[EvidenceReference, ...]
    benchmark_evidence: tuple[EvidenceReference, ...]


@dataclass(frozen=True)
class ConflictNote:
    """Documents a disagreement between two evidence references."""

    first_item_id: str
    second_item_id: str
    dimension: str
    note: str


@dataclass(frozen=True)
class CandidateComparison:
    """Evidence-based side-by-side of model candidates. No scoring or ranking.

    Fails at construction if candidates is empty.
    """

    task_description: str
    candidates: tuple[ModelCandidate, ...]
    research_gaps: tuple[str, ...]
    conflicting_evidence: tuple[ConflictNote, ...]


@dataclass(frozen=True)
class SelectionRecommendation:
    """A proposed model candidate. Always a proposal — never an execution auth.

    is_proposal is invariant True; __post_init__ raises ValueError if a caller
    attempts to set it to False.  recommended_candidate_id must appear in
    comparison.candidates.
    """

    recommended_candidate_id: str
    comparison: CandidateComparison
    rationale: str
    confidence: SelectionConfidence
    uncertainty_notes: tuple[str, ...]
    is_proposal: bool = True
```

```python
# module: cv_agent.model_selection.selector

from cv_agent.knowledge.models import KnowledgeItem
from cv_agent.llm.base import LLMProvider
from cv_agent.model_selection.models import (
    CandidateComparison,
    ModelCandidate,
    SelectionRecommendation,
)


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

    All evidence_items become EvidenceReferences; only those whose item_id
    appears in benchmark_item_ids are also placed in benchmark_evidence.
    """
    ...


def compare_candidates(
    candidates: tuple[ModelCandidate, ...],
    *,
    task_description: str,
    known_conflicts: tuple[tuple[str, str, str, str], ...] = (),
) -> CandidateComparison:
    """Produce a CandidateComparison from already-built candidates.

    known_conflicts: tuples of (item_id_1, item_id_2, dimension, note).
    research_gaps are inferred deterministically from candidates with no
    benchmark_evidence and from missing hardware-compatibility evidence.
    """
    ...


def select_candidate(
    comparison: CandidateComparison,
    *,
    llm_provider: LLMProvider,
) -> SelectionRecommendation:
    """Reason over the evidence to produce a justified SelectionRecommendation.

    The LLM is asked to:
    1. Name the recommended candidate_id (must be in comparison.candidates).
    2. Write a rationale citing specific evidence claims.
    3. State confidence (high/medium/low/insufficient_evidence).
    4. List uncertainty notes.

    Fail-closed: if the LLM names a candidate_id not in comparison, the
    selection is marked confidence="insufficient_evidence" and the raw
    LLM output is placed in uncertainty_notes for the caller to inspect.
    No benchmark values are added to any field; the LLM is given only the
    evidence already in comparison.candidates.
    """
    ...
```

## 6. Consequences

- **Enables:**
  - The reference task (person detection + tracking) can be researched and a model
    proposal produced without hardcoding YOLO or any other family.
  - Model selection can be unit-tested independently of the research path (by
    constructing `KnowledgeItem`s directly in tests).
  - The proposal can be reviewed/overridden by the project owner before any
    execution binding is triggered.
- **Makes harder:**
  - Wiring the proposal into the orchestration graph (a future task, separate ADR if
    it changes `AgentState`).
- **Costs (build, runtime, GPU, $):**
  - One LLM call per `select_candidate()` invocation. With `claude-sonnet-5`, cost
    is proportional to the total evidence text passed. The bounded `MAX_CONTENT_FOR_LLM`
    constant in `cv_agent.graph.research` limits per-item content; the number of
    candidates and evidence items scales the prompt. No GPU use; no model download.
- **Migration / blast radius if reversed:**
  - `cv_agent.model_selection` is a pure data/reasoning layer; reversing it removes
    the proposal output but leaves all existing layers intact.

## 7. Acceptance test

```python
# tests/test_model_selection.py::TestSelectionRecommendation::test_is_proposal_invariant
recommendation = SelectionRecommendation(
    recommended_candidate_id="yolov8n",
    comparison=comparison_with_yolov8n,
    rationale="...",
    confidence="medium",
    uncertainty_notes=(),
    is_proposal=False,  # attempt to set False
)
# must raise ValueError at construction — is_proposal is invariant True
```

```python
# tests/test_model_selection.py::TestSelectCandidate::test_no_invented_benchmarks
# LLM fake returns a candidate_id not in comparison.candidates:
# select_candidate returns confidence="insufficient_evidence", not a fabricated entry
```

## 8. Revisit trigger

- A future ADR wires `SelectionRecommendation` into `AgentState`: revisit whether the
  `is_proposal` invariant needs to be replaced by a state-machine transition.
- The first baseline run (`[P§29.2]`) produces a measured result: if it contradicts the
  proposal, the selection logic should be reviewed.
- If the LLM model changes (ADR-0002 §9): re-evaluate whether the prompt in
  `selector.py` produces reliable structured output with the new model.
