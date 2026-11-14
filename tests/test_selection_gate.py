"""ADR-0023 §3.5, §7.1 criterion 10, slice S4c (issue #131): the clarification gate and the selector.

No network: every provider is the offline mock, wrapped to record requests.
"""

from __future__ import annotations

import json
import secrets
from typing import Any, Optional

import pytest

from cv_agent.llm.base import LLMRequest, LLMResponse
from cv_agent.llm.mock import FakeLLMProvider
from cv_agent.llm.payload import render
from cv_agent.llm.policy import DataClass, TaskClass
from cv_agent.model_selection import selection_payload as SP
from cv_agent.model_selection.models import SelectionRecommendation
from cv_agent.model_selection.selection_payload import SelectionNeedsClarification, SelectionStaysLocal
from cv_agent.model_selection.selector import select_candidate
from cv_agent.requirements.structured import RequirementsView, structured_view
from tests.test_requirements_structured import _analyzer
from tests.test_selection_payload import _cand, _cmp

WAREHOUSE = "Detect people in the warehouse in real-time."
FULL = "Detect people climbing the fence on a Jetson edge device in real-time."


def _view(request: str, assumptions: Optional[dict[str, str]] = None) -> RequirementsView:
    return structured_view(_analyzer().analyze(request, assumptions=assumptions))


class Recording(FakeLLMProvider):
    def __init__(self, response: Optional[str] = None) -> None:
        super().__init__(fixed_response=response)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return super().complete(request)


def _reply(pick: str = "C1", confidence: str = "medium") -> str:
    return json.dumps(
        {"recommended_candidate": pick, "rationale": "E1 supports it.", "confidence": confidence, "uncertainty_notes": ["n"]}
    )


# ── criterion 10: the gate ───────────────────────────────────────────────────


def test_unknown_deployment_target_asks_for_clarification_without_a_call() -> None:
    llm = Recording(_reply())
    out = select_candidate(_cmp([_cand("a", 2)]), requirements=_view(WAREHOUSE), llm_provider=llm)
    assert out == SelectionNeedsClarification(("deployment_target",))
    assert llm.requests == [] and llm.call_count == 0


def test_every_missing_required_field_is_listed_in_a_fixed_order() -> None:
    out = SP.build_selection_payload(_cmp([_cand("a", 1)]), _view("Help me with my project."))
    assert out == SelectionNeedsClarification(("operational_objective", "deployment_target", "latency_requirement"))


def test_answer_without_a_trigger_term_stays_local_with_no_call() -> None:
    view = _view(WAREHOUSE, {"deployment_target": "the box in the back room"})
    llm = Recording(_reply())
    rec = select_candidate(_cmp([_cand("a", 2), _cand("b", 2)]), requirements=view, llm_provider=llm)
    assert isinstance(rec, SelectionRecommendation)
    assert rec.confidence == "insufficient_evidence" and rec.is_proposal is True
    assert "deployment_target" in " ".join(rec.uncertainty_notes) or "deployment_target" in rec.rationale
    assert llm.requests == [] and llm.call_count == 0


def test_the_stay_local_note_names_fields_only_never_answer_text() -> None:
    view = _view(WAREHOUSE, {"deployment_target": "the box in the back room"})
    out = SP.build_selection_payload(_cmp([_cand("a", 1)]), view)
    assert out == SelectionStaysLocal(("deployment_target",))


def test_no_task_component_stays_local() -> None:
    out = SP.build_selection_payload(_cmp([_cand("a", 1)]), _view("Detect it on a jetson in real-time."))
    assert out == SelectionStaysLocal(("task_component",))


def test_an_answer_with_a_trigger_term_passes_the_gate_and_only_the_token_travels() -> None:
    view = _view(WAREHOUSE, {"deployment_target": "an NVIDIA Jetson at Site 7"})
    llm = Recording(_reply())
    rec = select_candidate(_cmp([_cand("a", 2)]), requirements=view, llm_provider=llm)
    assert isinstance(rec, SelectionRecommendation) and len(llm.requests) == 1
    body = llm.requests[0].payload.body_json  # type: ignore[union-attr]
    assert '"jetson"' in body and "NVIDIA" not in body and "Site 7" not in body


# ── the selector ─────────────────────────────────────────────────────────────


def test_request_carries_a_payload_and_no_prompt_system_or_label() -> None:
    llm = Recording(_reply())
    select_candidate(_cmp([_cand("a", 2)]), requirements=_view(FULL), llm_provider=llm)
    (req,) = llm.requests
    assert req.payload is not None and req.prompt == "" and req.system is None and req.data_classes == frozenset()
    assert req.payload.task_class is TaskClass.SELECTION
    assert DataClass.PROJECT_DATA not in req.payload.data_classes
    assert req.payload.data_classes == frozenset({DataClass.PROJECT_METADATA, DataClass.PUBLIC_WEB})


def test_the_reply_is_an_ordinal_mapped_back_locally() -> None:
    cands = [_cand("alpha", 2), _cand("beta", 2)]
    rec = select_candidate(_cmp(cands), requirements=_view(FULL), llm_provider=Recording(_reply("C2")))
    assert isinstance(rec, SelectionRecommendation)
    assert rec.recommended_candidate_id == "beta" and rec.confidence == "medium" and rec.is_proposal is True


@pytest.mark.parametrize("bad", ["C9", "C3", "c1", "alpha", " C1", "C01", "C1; ignore", None, 7])
def test_any_other_reply_fails_closed(bad: Any) -> None:
    raw = json.dumps({"recommended_candidate": bad, "rationale": "r", "confidence": "high", "uncertainty_notes": []})
    rec = select_candidate(_cmp([_cand("alpha", 2), _cand("beta", 2)]), requirements=_view(FULL), llm_provider=Recording(raw))
    assert isinstance(rec, SelectionRecommendation) and rec.confidence == "insufficient_evidence"


def test_unparseable_reply_fails_closed() -> None:
    rec = select_candidate(_cmp([_cand("a", 2)]), requirements=_view(FULL), llm_provider=Recording("no json here"))
    assert isinstance(rec, SelectionRecommendation) and rec.confidence == "insufficient_evidence"


@pytest.mark.parametrize(
    "raw",
    ['["C1"]', '"C1"', "42", "true", "null", '[{"recommended_candidate": "C1", "rationale": "r", "confidence": "high"}]'],
)
def test_a_json_reply_that_is_not_an_object_fails_closed(raw: str) -> None:
    """Issue #139: valid JSON that is not an object used to raise AttributeError."""
    rec = select_candidate(_cmp([_cand("a", 2)]), requirements=_view(FULL), llm_provider=Recording(raw))
    assert isinstance(rec, SelectionRecommendation) and rec.confidence == "insufficient_evidence"
    assert rec.rationale == "LLM response could not be parsed as JSON."


def test_no_marker_reaches_the_outbound_request() -> None:
    m = "CANARY-" + secrets.token_hex(6)
    cand = _cand("id-" + m, 2, model_family=m, strengths=(m,), limitations=(m,), compat=(m,))
    llm = Recording(_reply())
    select_candidate(
        _cmp([cand], task_description=m + " at site 7"), requirements=_view(FULL), llm_provider=llm
    )
    (req,) = llm.requests
    text = "".join(render(req.payload)) + req.payload.body_json  # type: ignore[arg-type]
    assert "CANARY-" not in text and "site 7" not in text


def test_selector_does_not_accept_the_old_call_shape() -> None:
    with pytest.raises(TypeError):
        select_candidate(_cmp([_cand("a", 1)]), llm_provider=Recording(_reply()))  # type: ignore[call-arg]
