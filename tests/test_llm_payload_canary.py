"""ADR-0023 §7.1 criterion 2, NARRATIVE part (slice S3c, issue #119). Slice S5 extends this file.

``CANARY-<hex>`` markers (stdlib ``random``, fixed seeds) are put into every free-text input of the
requirements path:
- the request, glued to and around trigger terms and JSON-breaking noise;
- caller assumption values;
- clarification answers, through the real workflow graph;
- the resolver's capability IDs, skill IDs, skill paths and matched terms.

No marker may appear in the template narrative, the payload body, any outbound ``system`` or
``prompt`` (offline mock and hosted ``GovernedProvider``) or any column of the call-log row, with
``store_text = true``. Markers are compared case-insensitively, because the analyzer lower-cases.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Iterable

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from cv_agent.execution.binding import ExecutionBindingRegistry
from cv_agent.execution.executor import SkillExecutor
from cv_agent.graph.workflow import build_requirements_workflow_graph
from cv_agent.requirements.analyzer import RequirementsAnalyzer
from cv_agent.requirements.rules import FIELD_DETECTORS, TASK_HYPOTHESIS_RULES
from cv_agent.skills.inventory import SkillInventory
from tests.test_llm_call_log_payload import governed, rows
from tests.test_requirements_structured import CapturingLLM, StubResolver

SEEDS = range(20)
_TRIGGERS = [t for d in FIELD_DETECTORS for t in d.trigger_terms] + [
    t for r in TASK_HYPOTHESIS_RULES for t in r.trigger_terms
]
_NOISE = ['"', "'", "{", "}", "\n", "\\", ":", ",", "Site 7", "ACME Corp", "ünïcødé", "</s>", "${x}"]


def _marker(rng: random.Random) -> str:
    return f"CANARY-{rng.getrandbits(64):016x}"


def _scenario(seed: int) -> tuple[str, dict[str, str], StubResolver, list[str]]:
    rng = random.Random(seed)
    markers: list[str] = []

    def mark() -> str:
        markers.append(_marker(rng))
        return markers[-1]

    words = []
    for _ in range(rng.randint(2, 10)):
        t, m = rng.choice(_TRIGGERS), mark()
        words += [rng.choice((f"{t}{m}", f"{m}{t}", f"{t} {m}", m)), rng.choice(_NOISE)]
    request = " ".join(words)
    assumptions = {
        d.field_name: f"{rng.choice(d.trigger_terms)} {mark()}" if rng.random() < 0.5 else mark()
        for d in FIELD_DETECTORS
    }
    skill = f"/home/{mark()}/skills/{mark()}"
    return request, assumptions, StubResolver(cap_id=mark(), skill_id=skill, terms=(mark(),)), markers


def _assert_clean(texts: Iterable[Any], markers: list[str]) -> None:
    blob = "\n".join("" if t is None else str(t) for t in texts).lower()
    leaked = [m for m in markers if m.lower() in blob]
    assert not leaked, f"{len(leaked)} marker(s) leaked"


@pytest.mark.parametrize("seed", SEEDS)
def test_template_narrative_carries_no_marker_and_calls_no_llm(seed: int) -> None:
    request, assumptions, resolver, markers = _scenario(seed)
    llm = CapturingLLM("unused")
    result = RequirementsAnalyzer(task_resolver=resolver, llm=llm).analyze(request, assumptions=assumptions)  # type: ignore[arg-type]
    assert llm.requests == [] and result.narrative_source == "template"
    assert markers[0] in result.original_request  # not vacuous: the markers reached the analyzer
    _assert_clean([result.narrative_summary], markers)


@pytest.mark.parametrize("seed", SEEDS)
def test_llm_narrative_carries_no_marker_offline_or_hosted(seed: int, tmp_path: Path) -> None:
    request, assumptions, resolver, markers = _scenario(seed)
    mock = CapturingLLM("prose")
    RequirementsAnalyzer(task_resolver=resolver, llm=mock, narrative="llm").analyze(  # type: ignore[arg-type]
        request, assumptions=assumptions
    )
    gov, adapter, path = governed(tmp_path, store_text=True)
    RequirementsAnalyzer(task_resolver=resolver, llm=gov, narrative="llm").analyze(  # type: ignore[arg-type]
        request, assumptions=assumptions
    )
    (sent,) = adapter.requests
    rendered = mock.last_request
    assert rendered is not None and (rendered.system, rendered.prompt) == (sent.system, sent.prompt)  # parity
    (row,) = rows(path)
    assert row["payload_schema"] == "narrative/1" and row["prompt_text"]  # store_text is on
    _assert_clean([mock.requests[0].payload.body_json, sent.system, sent.prompt, *row.values()], markers)  # type: ignore[union-attr]


def test_clarification_answers_through_the_workflow_carry_no_marker(tmp_path: Path) -> None:
    rng = random.Random(4242)
    gov, adapter, path = governed(tmp_path, store_text=True)
    analyzer = RequirementsAnalyzer(task_resolver=StubResolver(), llm=gov, narrative="llm")  # type: ignore[arg-type]
    registry = ExecutionBindingRegistry()
    graph = build_requirements_workflow_graph(
        requirements_analyzer=analyzer, executor=SkillExecutor(registry),
        skill_inventory=SkillInventory(sources=()), execution_registry=registry, checkpointer=MemorySaver(),
    )
    cfg = {"configurable": {"thread_id": "canary"}}
    initial = {
        "session_id": "canary", "task": "Help with my project.", "steps": [], "requirements_analysis": None,
        "clarification_answers": {}, "execution_inputs": {}, "planning_result": None,
        "execution_input_recovery": None, "pending_execution": None, "approval_decision": None,
        "execution_result": None,
    }
    started = graph.invoke(initial, config=cfg)
    questions = started["__interrupt__"][0].value["questions"]
    markers = [_marker(rng) for _ in questions]
    answers = {q["relates_to_field"]: f"jetson real-time {m}" for q, m in zip(questions, markers)}
    resumed = graph.invoke(Command(resume=answers), config=cfg)
    assert resumed["clarification_answers"] == answers  # the answers really reached the analyzer
    assert len(adapter.requests) == 2  # one narrative call before and one after the answers
    assert '"jetson"' in adapter.requests[1].prompt  # the matched token is admitted; the answer is not
    _assert_clean([r.prompt for r in adapter.requests] + [v for row in rows(path) for v in row.values()], markers)
