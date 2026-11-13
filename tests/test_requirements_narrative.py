"""ADR-0023 slice S3b: the analyzer's narrative (ADR-0023 §3.3; issue #121).

The default narrative is the deterministic offline template built from the structured view; the
optional narrative="llm" path sends ``NarrativePayloadV1`` and nothing else. No network.
"""

from __future__ import annotations

import pytest

from cv_agent.requirements import analyzer as analyzer_module
from cv_agent.requirements import structured as S
from tests.test_requirements_structured import CapturingLLM, _analyzer


def test_risk_fields_match_the_analyzers_risk_text() -> None:
    assert set(analyzer_module._RISK_TEXT) == S.RISK_BEARING_FIELDS



def test_template_is_the_default_and_makes_no_llm_call() -> None:
    llm = CapturingLLM("should not be used")
    result = _analyzer(llm).analyze("Detect intruders near the fence at Site Alpha, Jetson edge box.")
    assert llm.requests == []
    assert result.narrative_source == "template" and result.llm_provider is None
    assert result.narrative_summary == S.render_template_narrative(S.structured_view(result))
    assert "Site Alpha" not in result.narrative_summary and "intruders" not in result.narrative_summary


def test_template_is_deterministic_and_names_fields_terms_and_counts() -> None:
    first = _analyzer().analyze("Detect people at the prison on a Jetson.").narrative_summary
    second = _analyzer().analyze("Detect people at the prison on a Jetson.").narrative_summary
    assert first == second
    assert first is not None
    assert "deployment_target [jetson]" in first and "environment_context [prison]" in first
    assert "Unknown fields: camera_data, latency_requirement, accuracy_requirement, data_availability." in first


def test_llm_mode_sends_only_the_narrative_payload() -> None:
    llm = CapturingLLM("prose")
    result = _analyzer(llm, narrative="llm").analyze("Detect people at Site Alpha on a Jetson.")
    assert len(llm.requests) == 1
    req = llm.requests[0]
    assert req.prompt == "" and req.system is None and req.data_classes == frozenset()
    assert req.payload is not None and req.payload.schema_id == "narrative"
    assert "Site Alpha" not in req.payload.body_json
    assert (result.narrative_summary, result.narrative_source, result.llm_provider) == ("prose", "llm", "mock")


def test_llm_mode_without_a_provider_is_refused() -> None:
    with pytest.raises(ValueError):
        _analyzer(None, narrative="llm")


@pytest.mark.parametrize("mode", ["Template", "none", "", None])
def test_an_unknown_narrative_mode_is_refused_not_sent(mode: object) -> None:
    """Review D1: a typo must not fall through to the LLM branch (fail closed)."""
    with pytest.raises(ValueError):
        _analyzer(CapturingLLM("x"), narrative=mode)
