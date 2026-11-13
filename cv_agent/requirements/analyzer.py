"""
cv_agent.requirements.analyzer — RequirementsAnalyzer.

    User request -> RequirementsAnalyzer -> RequirementsAnalysis

Deterministic and rule-based at its core (cv_agent.requirements.rules),
matching the same pattern cv_agent.skills.resolver already established for
capability matching, per ADR-0008. The `narrative_summary` is the
deterministic template from cv_agent.requirements.structured by default
(ADR-0023 §3.3 (b)). Only when built with narrative="llm" does the analyzer
call its LLMProvider, and then the request carries `NarrativePayloadV1`
(closed-vocabulary tokens and counts) and nothing else: no request text,
field value, assumption value or ID reaches a provider (ADR-0023 §2, §3.2).
The LLM is never used for extracting or inventing a fact.

Does not execute anything: this module never imports cv_agent.skills.local,
never calls a SkillSource, and never imports cv_agent.execution — even
though ADR-0009's execution boundary now exists and a skill this analyzer
reports on may be genuinely executable (see SkillLink, ADR-0008 §9), that
liveness fact is read secondhand off the Skill/SkillMatch objects the
already-injected TaskResolver returns, never queried directly. Its only
side effect is at most one LLMProvider.complete() call, in narrative="llm"
mode only.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Optional

from cv_agent.llm.base import LLMProvider, LLMRequest
from cv_agent.llm.payload import build_payload
from cv_agent.requirements.models import (
    CapabilityLink,
    ClarificationQuestion,
    NarrativeSource,
    RequirementField,
    RequirementsAnalysis,
    SkillLink,
    TaskHypothesis,
)
from cv_agent.requirements.rules import FIELD_DETECTORS, TASK_HYPOTHESIS_RULES
from cv_agent.requirements.structured import (
    RISK_BEARING_FIELDS,
    NarrativePayloadV1,
    render_template_narrative,
    structured_view,
)
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
        *,
        narrative: NarrativeSource = "template",
    ) -> None:
        if narrative not in ("template", "llm"):
            raise ValueError('narrative must be "template" or "llm"')  # never fall through to the LLM
        if narrative == "llm" and llm is None:
            raise ValueError('narrative="llm" needs an LLMProvider')
        self._resolver = task_resolver
        self._llm = llm
        self._narrative: NarrativeSource = narrative

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
        capability_links, skill_links = self._link_capabilities(request, candidate_tasks)
        clarifications = self._build_clarifications(fields)
        constraint_lines = self._derive_constraints(fields)
        risk_lines = self._derive_risks(fields)
        assumption_lines = tuple(
            f"{f.name} assumed to be {f.value!r} (caller-supplied, not extracted)"
            for f in fields
            if f.status == "assumed"
        )

        analysis = RequirementsAnalysis(
            original_request=request,
            problem_statement=f"The user requests: {request.strip()}",
            fields=fields,
            candidate_tasks=candidate_tasks,
            capability_links=capability_links,
            skill_links=skill_links,
            clarification_questions=clarifications,
            assumptions=assumption_lines,
            constraints=constraint_lines,
            risks=risk_lines,
        )
        return self._with_narrative(analysis)

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
                        terms=matches,
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
                        # Only the field's own vocabulary, re-matched locally (ADR-0023 §3.5 item 3).
                        terms=_find_matches(str(assumptions[detector.field_name]).lower(), detector.trigger_terms),
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

    # ── Capability + skill integration (reuses the existing resolver, never bypasses
    # it, never issues a second resolution pass — one resolve() call per task
    # component supplies both capability_links and skill_links below) ──────────────

    def _link_capabilities(
        self, request: str, candidate_tasks: tuple[TaskHypothesis, ...]
    ) -> tuple[tuple[CapabilityLink, ...], tuple[SkillLink, ...]]:
        links: list[CapabilityLink] = []
        skill_links: list[SkillLink] = []
        seen_caps: set[tuple[str, str]] = set()
        seen_skills: set[tuple[str, str]] = set()
        for task in candidate_tasks:
            query = f"{task.task_component.replace('_', ' ')} {request}"
            result = self._resolver.resolve(query)
            for cap in result.matched_capabilities[:_MAX_CAPABILITY_LINKS_PER_TASK]:
                key = (task.task_component, cap.capability_id)
                if key in seen_caps:
                    continue
                seen_caps.add(key)
                links.append(
                    CapabilityLink(
                        task_component=task.task_component,
                        capability_id=cap.capability_id,
                        status=cap.status,
                        matched_terms=cap.matched_terms,
                    )
                )
            # Same `result` as above — matched_skills is already computed by
            # this one resolve() call; only read, never re-resolved.
            for skill in result.matched_skills:
                skey = (task.task_component, skill.skill_id)
                if skey in seen_skills:
                    continue
                seen_skills.add(skey)
                skill_links.append(
                    SkillLink(
                        task_component=task.task_component,
                        skill_id=skill.skill_id,
                        declared=skill.declared,
                        matched_terms=skill.matched_terms,
                        executable=skill.executable,
                    )
                )
        return tuple(links), tuple(skill_links)

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
        return tuple(
            _RISK_TEXT[f.name]
            for f in fields
            if f.name in RISK_BEARING_FIELDS and f.status == "unknown"
        )

    # ── Narrative (never a source of fact; ADR-0023 §3.3) ────────────────

    def _with_narrative(self, analysis: RequirementsAnalysis) -> RequirementsAnalysis:
        view = structured_view(analysis)
        if self._narrative == "template":
            return dataclasses.replace(
                analysis, narrative_summary=render_template_narrative(view), narrative_source="template"
            )
        assert self._llm is not None  # enforced in __init__
        payload = build_payload(NarrativePayloadV1(view=view))
        response = self._llm.complete(LLMRequest(payload=payload, max_tokens=1024))
        return dataclasses.replace(
            analysis,
            narrative_summary=response.content,
            narrative_source="llm",
            llm_provider=self._llm.provider_name,
        )


_RISK_TEXT: dict[str, str] = {
    "accuracy_requirement": (
        "No stated recall/false-positive tolerance — any model choice "
        "risks being evaluated against the wrong bar later [P§12]."
    ),
    "deployment_target": (
        "No stated deployment target — an architecture chosen now may "
        "turn out to be undeployable on the eventual hardware [P§13]."
    ),
}

_QUESTION_TEMPLATES: dict[str, str] = {
    "operational_objective": "What exactly needs to be detected, tracked, or measured, in observable terms?",
    "environment_context": "What is the physical environment (indoor/outdoor, site type)?",
    "camera_data": "What cameras exist — how many, what FPS/resolution, and how is the feed delivered (RTSP, files, ...)?",
    "deployment_target": "Where will this run — edge device (e.g. Jetson), on-prem server, or cloud?",
    "latency_requirement": "Does this need real-time response, or is post-event analysis acceptable?",
    "accuracy_requirement": "What recall and false-positive tolerance does this application need?",
    "data_availability": "What labeled data already exists, if any, and how much?",
}
