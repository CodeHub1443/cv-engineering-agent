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

A second invariant, added by ADR-0008 §9: `SkillLink.executable` is a LIVE
fact about the calling `CVAgent`'s execution registry at analysis time, not
a permanent property of the skill — see `SkillLink`'s own docstring.
"""

from __future__ import annotations

from dataclasses import dataclass
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
class SkillLink:
    """
    A skill the resolver matched while answering one task component's query
    — scoped to `task_component`, the same join key `CapabilityLink` uses,
    deliberately NOT nested inside `CapabilityLink`.

    `TaskResolver.resolve()`'s own `SkillMatch` is not attributed to one
    specific capability within a single resolve() call: a skill can be
    matched purely by keyword overlap against discovered skill metadata
    (`declared=False`), independent of any capability's declared
    `relevant_skills`, and a declared skill can be declared by more than
    one matched capability at once. Embedding `matched_skills` inside
    `CapabilityLink` would therefore either drop the undeclared matches or
    fabricate a specific capability attribution the resolver never made.
    `task_component` is the honest join key both collections actually
    share — a caller wanting "capability X's skills" reads both tuples for
    the same `task_component` rather than being handed a false 1:1 edge.
    """

    task_component: str
    skill_id: str
    declared: bool
    """Mirrors `SkillMatch.declared` verbatim — True if a matched
    capability's `relevant_skills` declared this skill; False if it was
    matched purely by keyword overlap against discovered skill metadata."""
    matched_terms: tuple[str, ...]
    executable: bool
    """Copied verbatim from `SkillMatch.executable` at analysis time — True
    only if the `CVAgent`/`SkillInventory` this analysis ran against had a
    verified, registered execution binding for this skill_id *at that
    moment*. This is NOT a permanent property of the installed skill: the
    same skill_id can be `executable=False` in one analysis and
    `executable=True` in another, purely depending on what the calling
    `CVAgent`'s execution registry had registered when `analyze()` ran. A
    discovered `SKILL.md` alone never makes this True — see
    `cv_agent.skills.models.Skill.executable` and ADR-0007 §9."""


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
    skill_links: tuple[SkillLink, ...]
    """Skills the resolver matched while answering each task component's
    query — see `SkillLink`'s own docstring for why this is a separate,
    task_component-scoped collection rather than nested inside
    `capability_links`. This module (`RequirementsAnalyzer`) never decides
    which skill should execute and never ranks these beyond the order the
    resolver itself already produced — see ADR-0008 §2/§9."""
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
