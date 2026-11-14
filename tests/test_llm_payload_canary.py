"""ADR-0023 §7.1 criteria 2 and 3 (slices S3c and S5, issues #119 and #140): the cross-path canary suite.
Slice S5 added the SELECTION call site and the knowledge path (bottom of this file).

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

import dataclasses
import json
import random
from pathlib import Path
from typing import Any, Iterable, Optional

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from cv_agent.capabilities.registry import CapabilityRegistry
from cv_agent.execution.binding import ExecutionBindingRegistry
from cv_agent.execution.executor import SkillExecutor
from cv_agent.graph.workflow import build_requirements_workflow_graph
from cv_agent.requirements.analyzer import RequirementsAnalyzer
from cv_agent.requirements.rules import FIELD_DETECTORS, TASK_HYPOTHESIS_RULES
from cv_agent.knowledge.models import IngestPath
from cv_agent.llm.payload import ExclusionReason, rank_eligible
from cv_agent.model_selection.models import ConflictDimension
from cv_agent.model_selection.selector import build_candidate, compare_candidates, select_candidate
from cv_agent.requirements.structured import structured_view
from cv_agent.skills.inventory import SkillInventory
from cv_agent.skills.local import LocalSkillSource
from cv_agent.skills.resolver import TaskResolver
from tests.test_llm_call_log_payload import governed, rows
from tests.test_llm_select_claims import _item
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


# ── SELECTION (ADR-0023 §7.1 criteria 2 and 3, slice S5, issue #140) ─────────

FULL = "Detect people climbing the fence on a Jetson edge device in real-time."
_REPLY = json.dumps({"recommended_candidate": "C1", "rationale": "E1.", "confidence": "low", "uncertainty_notes": []})


def _selection_scenario(seed: int) -> tuple[Any, dict[str, str], list[str]]:
    """A comparison with a marker in every free-text input of the selector, and an eligible conflict."""
    rng = random.Random(1000 + seed)
    markers: list[str] = []

    def mark() -> str:
        markers.append(_marker(rng))
        return f"{rng.choice(_NOISE)}{markers[-1]}{rng.choice(_NOISE)}"

    cands = []
    for i in range(rng.randint(1, 3)):
        items = tuple(_item(f"c{i}-{k}") for k in range(rng.randint(1, 3)))
        cands.append(build_candidate(
            candidate_id=mark(), model_family=mark(), task_support=(mark(), "object_detection"),
            evidence_items=items, strengths=(mark(),), limitations=(mark(),), compatibility_constraints=(mark(),),
            benchmark_item_ids=frozenset({items[0].item_id}),
        ))
    first, second = cands[0].evidence_references[0].item_id, cands[-1].evidence_references[-1].item_id
    cmp = compare_candidates(
        tuple(cands), task_description=mark(),
        known_conflicts=((first, second, mark(), mark(), ConflictDimension.OTHER),),
    )
    assumptions = {d.field_name: f"{rng.choice(d.trigger_terms)} {mark()}" for d in FIELD_DETECTORS}
    return cmp, assumptions, markers


def _view_of(request: str, resolver: Any = None, assumptions: Optional[dict[str, str]] = None) -> Any:
    analyzer = RequirementsAnalyzer(task_resolver=resolver or StubResolver(), llm=None)  # type: ignore[arg-type]
    return structured_view(analyzer.analyze(request, assumptions=assumptions))


def _run_selection(cmp: Any, view: Any, tmp_path: Path, markers: list[str]) -> str:
    """Offline mock and hosted governed provider; returns the body sent."""
    mock = CapturingLLM(_REPLY)
    assert select_candidate(cmp, requirements=view, llm_provider=mock).is_proposal  # type: ignore[union-attr]
    gov, adapter, path = governed(tmp_path, "selection", store_text=True)
    select_candidate(cmp, requirements=view, llm_provider=gov)
    (sent,), (row,) = adapter.requests, rows(path)
    rendered = mock.last_request
    assert rendered is not None and (rendered.system, rendered.prompt) == (sent.system, sent.prompt)  # parity
    assert row["payload_schema"] == "selection/1" and row["prompt_text"]
    body = mock.requests[0].payload.body_json  # type: ignore[union-attr]
    _assert_clean([body, sent.system, sent.prompt, *row.values()], markers)
    return str(body)


@pytest.mark.parametrize("seed", SEEDS)
def test_selection_carries_no_marker_offline_or_hosted(seed: int, tmp_path: Path) -> None:
    cmp, assumptions, markers = _selection_scenario(seed)
    _run_selection(cmp, _view_of(FULL, assumptions=assumptions), tmp_path, markers)


def test_selection_after_clarification_answers_carries_no_marker(tmp_path: Path) -> None:
    rng = random.Random(777)
    markers = [_marker(rng) for _ in range(2)]
    answers = {"deployment_target": f"jetson {markers[0]}", "latency_requirement": f"real-time {markers[1]}"}
    cmp, _, more = _selection_scenario(0)
    _run_selection(cmp, _view_of("Detect people in the warehouse.", assumptions=answers), tmp_path, markers + more)


def _resolver_with_markers(tmp_path: Path, rng: random.Random, markers: list[str]) -> TaskResolver:
    """A real resolver over a non-packaged registry and a discovered skill, all named by markers."""
    cap_id, skill_id = _marker(rng), _marker(rng)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"version": "x", "capabilities": [{
        "id": cap_id, "name": f"Detect people {cap_id}", "category": "perception",
        "description": "detect people jetson edge real-time", "relevant_skills": [skill_id],
        "applicable_task_types": ["detection"], "status": "available", "risk_level": "low",
    }]}), encoding="utf-8")
    skill_dir = tmp_path / "skills" / skill_id
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {skill_id}\ndescription: detect people jetson\n---\n", encoding="utf-8")
    markers += [cap_id, skill_id, str(skill_dir)]
    return TaskResolver(
        capability_registry=CapabilityRegistry(registry),
        skill_inventory=SkillInventory(sources=(LocalSkillSource(roots=(tmp_path / "skills",)),)),
    )


def test_resolver_ids_from_a_non_packaged_registry_and_skills_carry_no_marker(tmp_path: Path) -> None:
    markers: list[str] = []
    resolver = _resolver_with_markers(tmp_path, random.Random(99), markers)
    assert any(m in str(resolver.resolve(FULL)) for m in markers)  # not vacuous: the resolver returns them
    gov, adapter, path = governed(tmp_path, store_text=True)
    result = RequirementsAnalyzer(task_resolver=resolver, llm=gov, narrative="llm").analyze(FULL)  # type: ignore[arg-type]
    (sent,), (row,) = adapter.requests, rows(path)
    _assert_clean([result.narrative_summary, sent.system, sent.prompt, *row.values()], markers)
    cmp, _, more = _selection_scenario(1)
    (tmp_path / "sel").mkdir()
    _run_selection(cmp, _view_of(FULL, resolver), tmp_path / "sel", markers + more)


# criterion 3: the knowledge path. Each bad item is excluded and counted; the control is sent.
_CONTROL_CLAIM = "control claim " + "x" * 400
_BAD_ITEMS: dict[str, tuple[dict[str, Any], ExclusionReason]] = {
    "project_input": ({"ingest": IngestPath.PROJECT_INPUT}, ExclusionReason.INGEST_NOT_ALLOWED),
    "unspecified": ({"ingest": IngestPath.UNSPECIFIED}, ExclusionReason.INGEST_NOT_ALLOWED),
    "professional_post": ({"source_class": "professional_post"}, ExclusionReason.SOURCE_CLASS_NOT_ALLOWED),
    **{
        f"url_{i}": ({"url": u}, ExclusionReason.NON_PUBLIC_URL)
        for i, u in enumerate((
            "file:///etc/passwd", "http://10.0.0.5/x", "http://intranet/x",
            "https://cam.site.local/x", "https://user:pw@example.com/x",
        ))
    },
}


@pytest.mark.parametrize("case", [*_BAD_ITEMS, "no_provenance"])
def test_knowledge_path_excludes_counts_and_never_sends_the_marker(case: str, tmp_path: Path) -> None:
    marker = _marker(random.Random(5))
    control = _item("ok", claim=_CONTROL_CLAIM, url="https://docs.example.org/page")
    kw, reason = _BAD_ITEMS.get(case, ({}, ExclusionReason.NO_PROVENANCE))
    bad = _item("bad", claim=marker, conditions=marker, **{"url": "https://docs.example.org/b", **kw})
    cand = build_candidate(candidate_id="a", model_family="f", task_support=("object_detection",), evidence_items=(control, bad),
                           strengths=(), limitations=(), compatibility_constraints=(), benchmark_item_ids=frozenset())
    if case == "no_provenance":  # a reference with no stored item behind it fails closed
        ok_ref, bad_ref = cand.evidence_references
        cand = dataclasses.replace(cand, evidence_references=(ok_ref, dataclasses.replace(bad_ref, source_item=None)))
    pairs = [(r.source_item if r.source_item is not None else r, False) for r in cand.evidence_references]
    assert dict(rank_eligible(pairs)[1]) == {reason: 1}
    cmp = compare_candidates((cand,), task_description="t")
    body = _run_selection(cmp, _view_of(FULL), tmp_path, [marker])
    assert json.loads(body)["candidates"][0]["claims_excluded"] == 1
    assert _CONTROL_CLAIM[:300] in body and _CONTROL_CLAIM[:301] not in body  # sent verbatim, truncated
