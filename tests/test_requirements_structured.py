"""ADR-0023 slice S3a: requirements structured view, NarrativePayloadV1 and the template renderer.

ADR-0023 §2.1-§2.2, §3.3 (b), §5 (``requirements/structured.py``); issue #120. No network: the
resolver is a stub and every provider is the offline mock.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Optional

import pytest

import cv_agent.llm.payload as P
from cv_agent.llm.base import LLMRequest, LLMResponse
from cv_agent.llm.errors import PayloadFieldError
from cv_agent.llm.mock import FakeLLMProvider
from cv_agent.llm.policy import DataClass, TaskClass
from cv_agent.requirements import structured as S
from cv_agent.requirements.analyzer import RequirementsAnalyzer
from cv_agent.requirements.rules import FIELD_DETECTORS, TASK_HYPOTHESIS_RULES
from cv_agent.skills.resolver import CapabilityMatch, ResolutionResult, SkillMatch


class StubResolver:
    """Fixed matches for every query, so nothing depends on the packaged registry."""

    def __init__(self, cap_id: str = "cap.detect", skill_id: str = "skill.a", terms: tuple[str, ...] = ()) -> None:
        self._caps = (
            CapabilityMatch(cap_id, 1.0, terms, "available"),
            CapabilityMatch(cap_id + ".b", 0.5, terms, "planned"),
        )
        self._skills = (SkillMatch(skill_id, 1.0, terms, declared=True, discovered=True, executable=False),)

    def resolve(self, query: str) -> ResolutionResult:
        return ResolutionResult(query, self._caps, self._skills, (), (), ())


class CapturingLLM(FakeLLMProvider):
    def __init__(self, response: Optional[str] = None) -> None:
        super().__init__(fixed_response=response)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return super().complete(request)


def _analyzer(llm: Any = None, **kw: Any) -> RequirementsAnalyzer:
    return RequirementsAnalyzer(task_resolver=StubResolver(), llm=llm, **kw)  # type: ignore[arg-type]


def _field(view: S.RequirementsView, name: str) -> S.FieldView:
    return next(f for f in view.fields if f.name.value == name)


# ── vocabularies ─────────────────────────────────────────────────────────────


def test_requirement_vocabularies_are_registered_from_the_rules() -> None:
    expected = {
        "requirement_field": {d.field_name for d in FIELD_DETECTORS},
        "requirement_trigger": {t for d in FIELD_DETECTORS for t in d.trigger_terms},
        "task_component": {r.task_component for r in TASK_HYPOTHESIS_RULES},
    }
    for name, members in expected.items():
        vocab = P._VOCABS[name]
        assert vocab.members == frozenset(members) and vocab.origin == "code"
        assert vocab.version == P.Vocabulary.of(name, members, "code").version


def test_narrative_schema_is_registered_with_literal_constants() -> None:
    reg = P._SCHEMAS[("narrative", 1)]
    assert reg.cls is S.NarrativePayloadV1 and reg.task_class is TaskClass.NARRATIVE
    assert reg.system == S.NarrativePayloadV1.SYSTEM and reg.instructions == S.NarrativePayloadV1.INSTRUCTIONS


# ── matched trigger terms ────────────────────────────────────────────────────


def test_known_fields_keep_their_matched_trigger_terms() -> None:
    result = _analyzer().analyze("Detect intruders outdoors on a Jetson edge box in real-time.")
    terms = {f.name: f.terms for f in result.fields}
    assert terms["deployment_target"] == ("jetson", "edge")
    assert terms["latency_requirement"] == ("real-time",)
    assert terms["camera_data"] == ()


def test_assumption_values_become_terms_only_through_the_field_vocabulary() -> None:
    result = _analyzer().analyze(
        "Detect people.",
        assumptions={"deployment_target": "Jetson Orin at Site 7", "latency_requirement": "whatever the client says"},
    )
    by_name = {f.name: f for f in result.fields}
    assert by_name["deployment_target"].status == "assumed" and by_name["deployment_target"].terms == ("jetson",)
    assert by_name["latency_requirement"].status == "assumed" and by_name["latency_requirement"].terms == ()


def test_negation_is_read_as_the_keyword_detector_reads_it() -> None:
    """Documented loss (ADR-0023 §3.3): "not outdoor" still matches ``outdoor``."""
    result = _analyzer().analyze("Detect people, not outdoor.")
    assert next(f for f in result.fields if f.name == "environment_context").terms == ("outdoor",)


# ── the view ─────────────────────────────────────────────────────────────────


def _leaves(obj: Any) -> list[Any]:
    if isinstance(obj, tuple):
        return [x for v in obj for x in _leaves(v)]
    if isinstance(obj, (P.VocabToken, P.Quantity, Enum)) or type(obj) in (int, bool):
        return [obj]
    assert dataclasses.is_dataclass(obj), f"unexpected leaf {type(obj)!r}"
    return [x for f in dataclasses.fields(obj) for x in _leaves(getattr(obj, f.name))]


def test_view_holds_only_tokens_enums_numbers_and_counts() -> None:
    analysis = _analyzer().analyze(
        "Detect people climbing the fence at the prison; RTSP cameras.", assumptions={"deployment_target": "edge"}
    )
    view = S.structured_view(analysis)
    leaves = _leaves(view)
    assert leaves and not any(type(x) is str for x in leaves)
    text = repr(view)
    for secret in ("climbing the fence", "RTSP cameras", "cap.detect", "skill.a"):
        assert secret not in text


def test_view_counts_links_questions_and_risks() -> None:
    view = S.structured_view(_analyzer().analyze("Detect people."))
    assert (view.capability_links, view.capability_links_available) == (2, 1)
    assert (view.skill_links, view.skill_links_executable, view.skill_links_declared) == (1, 0, 1)
    assert view.open_questions == 6
    assert [t.value for t in view.risk_fields] == ["deployment_target", "accuracy_requirement"]
    assert _field(view, "operational_objective").status is S.FieldStatus.KNOWN


def test_view_keeps_only_terms_of_the_fields_own_vocabulary() -> None:
    analysis = _analyzer().analyze("Detect people.")
    tampered = dataclasses.replace(
        analysis,
        fields=tuple(dataclasses.replace(f, terms=("jetson", "outdoor")) if f.name == "deployment_target" else f
                     for f in analysis.fields),
    )
    assert [t.value for t in _field(S.structured_view(tampered), "deployment_target").terms] == ["jetson"]


def test_counts_are_clamped_to_the_declared_maximum() -> None:
    analysis = _analyzer().analyze("Detect people.")
    many = dataclasses.replace(analysis, capability_links=analysis.capability_links * 600)
    assert S.structured_view(many).capability_links == S.MAX_COUNT


# ── the payload ──────────────────────────────────────────────────────────────


def test_narrative_payload_is_project_metadata_only() -> None:
    view = S.structured_view(_analyzer().analyze("Detect people on a Jetson."))
    payload = P.build_payload(S.NarrativePayloadV1(view=view))
    assert (payload.schema_id, payload.schema_version, payload.task_class) == ("narrative", 1, TaskClass.NARRATIVE)
    assert payload.data_classes == frozenset({DataClass.PROJECT_METADATA})
    assert set(payload.vocabulary_versions) == {"requirement_field", "requirement_trigger", "task_component"}


@pytest.mark.parametrize("bad_term", ["CANARY-free-text", P.VocabToken("requirement_trigger", "jetson")])
def test_a_raw_string_or_unissued_token_in_the_view_is_refused(bad_term: Any) -> None:
    view = S.structured_view(_analyzer().analyze("Detect people on a Jetson."))
    fv = dataclasses.replace(view.fields[0], terms=(bad_term,))
    bad = dataclasses.replace(view, fields=(fv,) + view.fields[1:])
    with pytest.raises(PayloadFieldError) as info:
        P.build_payload(S.NarrativePayloadV1(view=bad))
    assert "CANARY" not in str(info.value)

