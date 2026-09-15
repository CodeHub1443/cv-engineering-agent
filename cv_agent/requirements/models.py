"""
cv_agent.requirements.models — Structured requirements-analysis domain model.

Central invariant, restated at the type level: KNOWN / UNKNOWN / ASSUMED are
never blurred. A `RequirementField` is `known` only if the analyzer found
text the user actually wrote for it. It is `assumed` only if the *caller*
explicitly supplied that assumption (see `RequirementsAnalyzer.analyze`'s
`assumptions` parameter) — the analyzer itself never invents a value and
promotes a field to `assumed` on its own initiative. Anything else is
`unknown`, and an `unknown` field always carries a clarification question,
never a fabricated default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

InfoStatus = Literal["known", "unknown", "assumed"]


@dataclass(frozen=True)
class RequirementField:
    """One slot of the requirements picture (e.g. deployment_target)."""

    name: str
    status: InfoStatus
    value: str | None
    """The actual text found for this field. None unless status == "known" or
    an explicit assumption was supplied for status == "assumed"."""
    why_it_matters: str
    """Static, field-specific explanation of the engineering consequence of
    this being unknown — not a generic "please provide more info"."""
    source: str = "user_request"
    """Where `value` came from: "user_request" (extracted) or
    "caller_assumption" (explicitly supplied, never invented in-analyzer)."""


@dataclass(frozen=True)
class TaskHypothesis:
    """
    A candidate CV task component the request MIGHT require.

    A hypothesis, not a confirmed requirement — `rationale` states exactly
    why it was proposed (which trigger terms fired), so a human or later
    stage can accept, reject, or investigate it rather than treat it as
    settled.
    """

    task_component: str
    rationale: str
    trigger_terms: tuple[str, ...]
    confidence: float
    """0.0-1.0, proportional to how many distinct trigger terms matched.
    Not a calibrated probability — a ranking signal only."""


@dataclass(frozen=True)
class CapabilityLink:
    """A capability (from the existing registry) relevant to a task hypothesis."""

    task_component: str
    capability_id: str
    status: str
    """The capability's declared registry status (e.g. "planned") — carried
    through so a capability link never implies executability."""
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class ClarificationQuestion:
    """A targeted question generated from one specific unknown field."""

    question: str
    relates_to_field: str
    why_it_matters: str


@dataclass(frozen=True)
class RequirementsAnalysis:
    """The full structured output of one requirements-analysis run."""

    original_request: str
    problem_statement: str
    """A deterministic restatement of the request, not an LLM paraphrase —
    see narrative_summary for the (optional, clearly separate) LLM output."""
    fields: tuple[RequirementField, ...]
    candidate_tasks: tuple[TaskHypothesis, ...]
    capability_links: tuple[CapabilityLink, ...]
    clarification_questions: tuple[ClarificationQuestion, ...]
    assumptions: tuple[str, ...]
    """Human-readable echo of every field with status == "assumed", for a
    quick scan of what this analysis is trusting without confirmation."""
    constraints: tuple[str, ...]
    risks: tuple[str, ...]
    narrative_summary: str | None = None
    """Optional prose summary from the configured LLMProvider. Never a
    source of fact for any other field on this dataclass — purely
    explanatory text, clearly attributable to the LLM call that produced it
    (see RequirementsAnalyzer)."""
    llm_provider: str | None = None
    """provider_name of the LLM used for narrative_summary, or None if no
    provider was configured for this run."""

    @property
    def unknown_field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.status == "unknown")

    @property
    def known_field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.status == "known")

    @property
    def assumed_field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.status == "assumed")
