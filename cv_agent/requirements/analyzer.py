"""
cv_agent.requirements.analyzer — RequirementsAnalyzer.

    User request -> RequirementsAnalyzer -> RequirementsAnalysis

Deterministic and rule-based at its core (cv_agent.requirements.rules),
matching the same pattern cv_agent.skills.resolver already established for
capability matching. An LLMProvider is optional and, when supplied, is used
for exactly one thing: a prose `narrative_summary` — never for extracting or
inventing a fact. This keeps every structured field reproducible and
testable against cv_agent.llm.mock.FakeLLMProvider without a live provider,
per ADR-0008.

Does not execute anything: this module never imports cv_agent.skills.local,
never calls a SkillSource, and never touches an execution boundary (which
does not exist yet — see docs/state/STATUS.md). Its only side effect is at
most one LLMProvider.complete() call.
"""

from __future__ import annotations

import re
from typing import Optional

from cv_agent.llm.base import LLMProvider, LLMRequest
from cv_agent.requirements.models import (
    CapabilityLink,
    ClarificationQuestion,
    RequirementField,
    RequirementsAnalysis,
    TaskHypothesis,
)
from cv_agent.requirements.rules import FIELD_DETECTORS, TASK_HYPOTHESIS_RULES
from cv_agent.skills.resolver import TaskResolver

_MAX_CAPABILITY_LINKS_PER_TASK = 3


def _find_matches(text_lower: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(t for t in terms if t in text_lower)


def _extract_sentence(request: str, term: str) -> str:
    """Return the sentence/clause of `request` containing `term`, as the
    field's value — the user's own words, not a reinterpretation."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", request):
        if term in sentence.lower():
            return sentence.strip()
    return request.strip()


class RequirementsAnalyzer:
    """
    Turns a natural-language CV request into a structured
    RequirementsAnalysis: known/unknown/assumed fields, candidate CV task
    hypotheses with stated rationale, links into the existing capability
    registry (via the existing TaskResolver — never bypassed), and targeted
    clarification questions for whatever is unknown.
    """

    def __init__(
        self,
        task_resolver: TaskResolver,
        llm: Optional[LLMProvider] = None,
    ) -> None:
        self._resolver = task_resolver
        self._llm = llm

    def analyze(
        self,
        request: str,
        *,
        assumptions: Optional[dict[str, str]] = None,
    ) -> RequirementsAnalysis:
        """
        Args:
            request: The user's natural-language CV problem statement.
            assumptions: Explicit, caller-supplied values for named fields
                (must match a FieldDetector.field_name). This is the ONLY
                way a field can become "assumed" — the analyzer never
                promotes an unknown field to assumed on its own.
        """
        assumptions = assumptions or {}
        text_lower = request.lower()

        fields = self._detect_fields(request, text_lower, assumptions)
        candidate_tasks = self._detect_task_hypotheses(text_lower)
        capability_links = self._link_capabilities(request, candidate_tasks)
        clarifications = self._build_clarifications(fields)
        constraint_lines = self._derive_constraints(fields)
        risk_lines = self._derive_risks(fields)
        assumption_lines = tuple(
            f"{f.name} assumed to be {f.value!r} (caller-supplied, not extracted)"
            for f in fields
            if f.status == "assumed"
        )

        narrative_summary = None
        llm_provider_name = None
        if self._llm is not None:
            narrative_summary = self._generate_narrative(
                request, fields, candidate_tasks, clarifications
            )
            llm_provider_name = self._llm.provider_name

        return RequirementsAnalysis(
            original_request=request,
            problem_statement=f"The user requests: {request.strip()}",
            fields=fields,
            candidate_tasks=candidate_tasks,
            capability_links=capability_links,
            clarification_questions=clarifications,
            assumptions=assumption_lines,
            constraints=constraint_lines,
            risks=risk_lines,
            narrative_summary=narrative_summary,
            llm_provider=llm_provider_name,
        )

    # ── Field detection ──────────────────────────────────────────────────

    def _detect_fields(
        self, request: str, text_lower: str, assumptions: dict[str, str]
    ) -> tuple[RequirementField, ...]:
        fields: list[RequirementField] = []
        for detector in FIELD_DETECTORS:
            matches = _find_matches(text_lower, detector.trigger_terms)
            if matches:
                fields.append(
                    RequirementField(
                        name=detector.field_name,
                        status="known",
                        value=_extract_sentence(request, matches[0]),
                        why_it_matters=detector.why_it_matters,
                        source="user_request",
                    )
                )
            elif detector.field_name in assumptions:
                fields.append(
                    RequirementField(
                        name=detector.field_name,
                        status="assumed",
                        value=assumptions[detector.field_name],
                        why_it_matters=detector.why_it_matters,
                        source="caller_assumption",
                    )
                )
            else:
                fields.append(
                    RequirementField(
                        name=detector.field_name,
                        status="unknown",
                        value=None,
                        why_it_matters=detector.why_it_matters,
                        source="user_request",
                    )
                )
        return tuple(fields)

    # ── Task decomposition ───────────────────────────────────────────────

    def _detect_task_hypotheses(self, text_lower: str) -> tuple[TaskHypothesis, ...]:
        hypotheses: list[TaskHypothesis] = []
        for rule in TASK_HYPOTHESIS_RULES:
            matches = _find_matches(text_lower, rule.trigger_terms)
            if not matches:
                continue
            confidence = min(1.0, len(matches) / len(rule.trigger_terms) + 0.25)
            hypotheses.append(
                TaskHypothesis(
                    task_component=rule.task_component,
                    rationale=rule.rationale_template.format(term=matches[0]),
                    trigger_terms=matches,
                    confidence=round(confidence, 2),
                )
            )
        hypotheses.sort(key=lambda h: (-h.confidence, h.task_component))
        return tuple(hypotheses)

    # ── Capability integration (reuses the existing resolver, never bypasses it) ──

    def _link_capabilities(
        self, request: str, candidate_tasks: tuple[TaskHypothesis, ...]
    ) -> tuple[CapabilityLink, ...]:
        links: list[CapabilityLink] = []
        seen: set[tuple[str, str]] = set()
        for task in candidate_tasks:
            query = f"{task.task_component.replace('_', ' ')} {request}"
            result = self._resolver.resolve(query)
            for cap in result.matched_capabilities[:_MAX_CAPABILITY_LINKS_PER_TASK]:
                key = (task.task_component, cap.capability_id)
                if key in seen:
                    continue
                seen.add(key)
                links.append(
                    CapabilityLink(
                        task_component=task.task_component,
                        capability_id=cap.capability_id,
                        status=cap.status,
                        matched_terms=cap.matched_terms,
                    )
                )
        return tuple(links)

    # ── Clarification questions ──────────────────────────────────────────

    def _build_clarifications(
        self, fields: tuple[RequirementField, ...]
    ) -> tuple[ClarificationQuestion, ...]:
        questions: list[ClarificationQuestion] = []
        for f in fields:
            if f.status != "unknown":
                continue
            questions.append(
                ClarificationQuestion(
                    question=_QUESTION_TEMPLATES.get(
                        f.name, f"Can you provide details on {f.name.replace('_', ' ')}?"
                    ),
                    relates_to_field=f.name,
                    why_it_matters=f.why_it_matters,
                )
            )
        return tuple(questions)

    # ── Constraints / risks (derived only from already-computed field status) ──

    def _derive_constraints(self, fields: tuple[RequirementField, ...]) -> tuple[str, ...]:
        relevant = {"deployment_target", "latency_requirement", "accuracy_requirement"}
        return tuple(
            f"{f.name}: {f.value}"
            for f in fields
            if f.name in relevant and f.status in ("known", "assumed") and f.value
        )

    def _derive_risks(self, fields: tuple[RequirementField, ...]) -> tuple[str, ...]:
        risk_bearing = {
            "accuracy_requirement": (
                "No stated recall/false-positive tolerance — any model choice "
                "risks being evaluated against the wrong bar later [P§12]."
            ),
            "deployment_target": (
                "No stated deployment target — an architecture chosen now may "
                "turn out to be undeployable on the eventual hardware [P§13]."
            ),
        }
        return tuple(
            risk_bearing[f.name]
            for f in fields
            if f.name in risk_bearing and f.status == "unknown"
        )

    # ── Optional LLM narrative (never a source of fact) ──────────────────

    def _generate_narrative(
        self,
        request: str,
        fields: tuple[RequirementField, ...],
        candidate_tasks: tuple[TaskHypothesis, ...],
        clarifications: tuple[ClarificationQuestion, ...],
    ) -> str:
        assert self._llm is not None
        known = ", ".join(f.name for f in fields if f.status == "known") or "none"
        unknown = ", ".join(f.name for f in fields if f.status == "unknown") or "none"
        tasks = ", ".join(t.task_component for t in candidate_tasks) or "none identified"
        prompt = (
            "Summarize this CV engineering requirements analysis in prose.\n"
            f"Request: {request}\n"
            f"Known fields: {known}\n"
            f"Unknown fields: {unknown}\n"
            f"Candidate task components: {tasks}\n"
            f"Open questions: {len(clarifications)}\n"
        )
        response = self._llm.complete(LLMRequest(prompt=prompt))
        return response.content


_QUESTION_TEMPLATES: dict[str, str] = {
    "operational_objective": "What exactly needs to be detected, tracked, or measured, in observable terms?",
    "environment_context": "What is the physical environment (indoor/outdoor, site type)?",
    "camera_data": "What cameras exist — how many, what FPS/resolution, and how is the feed delivered (RTSP, files, ...)?",
    "deployment_target": "Where will this run — edge device (e.g. Jetson), on-prem server, or cloud?",
    "latency_requirement": "Does this need real-time response, or is post-event analysis acceptable?",
    "accuracy_requirement": "What recall and false-positive tolerance does this application need?",
    "data_availability": "What labeled data already exists, if any, and how much?",
}
