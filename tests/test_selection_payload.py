"""ADR-0023 §2.3, §3.5, §5, §7.1 criterion 5 (caps), slice S4b (issue #130): SelectionPayloadV1.

No network, no provider: the builder is pure. The requirements view comes from the real analyzer with
a stub resolver.
"""

from __future__ import annotations

import json
import secrets
from typing import Any, Sequence

import pytest

from cv_agent.config.settings import load_config
from cv_agent.knowledge.models import IngestPath, KnowledgeItem
from cv_agent.llm.errors import PayloadFieldError
from cv_agent.llm.payload import MAX_CLAIMS_PER_CANDIDATE, MAX_CLAIMS_PER_PAYLOAD, build_payload, render
from cv_agent.llm.policy import DataClass, TaskClass
from cv_agent.model_selection import selection_payload as SP
from cv_agent.model_selection.models import CandidateComparison, ConflictDimension, ConflictNote, ModelCandidate
from cv_agent.model_selection.selector import build_candidate, compare_candidates
from cv_agent.requirements.structured import structured_view
from tests.test_llm_select_claims import _item
from tests.test_requirements_structured import _analyzer

REQUEST = (
    "Detect people climbing the perimeter fence at an outdoor prison; "
    "must run on a Jetson edge device in real-time from RTSP cameras."
)


def _view() -> Any:
    return structured_view(_analyzer().analyze(REQUEST))


def _cand(
    cid: str,
    n: int,
    *,
    bench: int = 0,
    source_class: Any = "official_documentation",
    items: Sequence[KnowledgeItem] = (),
    task_support: tuple[str, ...] = ("object_detection",),
    claim_len: int = 20,
    cond_len: int = 10,
    **kw: Any,
) -> ModelCandidate:
    made = tuple(
        _item(f"{cid}-{k:02d}", claim=("c" * claim_len), conditions=("d" * cond_len), source_class=source_class)
        for k in range(n)
    ) + tuple(items)
    return build_candidate(
        candidate_id=cid,
        model_family=kw.get("model_family", "family " + cid),
        task_support=task_support,
        evidence_items=made,
        strengths=kw.get("strengths", ("strong",)),
        limitations=kw.get("limitations", ("weak",)),
        compatibility_constraints=kw.get("compat", ("needs gpu",)),
        benchmark_item_ids=frozenset(f"{cid}-{k:02d}" for k in range(bench)),
    )


def _cmp(cands: Sequence[ModelCandidate], **kw: Any) -> CandidateComparison:
    return compare_candidates(tuple(cands), task_description=kw.pop("task_description", "task"), **kw)


def _build(cands: Sequence[ModelCandidate], **kw: Any) -> tuple[SP.SelectionPayloadV1, Any]:
    cmp_kw = kw.pop("cmp_kw", {})
    return SP.build_selection_payload(_cmp(cands, **cmp_kw), _view(), **kw)


def _sent(p: SP.SelectionPayloadV1) -> list[int]:
    return [len(c.claims) for c in p.candidates]


def _omitted(p: SP.SelectionPayloadV1) -> list[int]:
    return [c.claims_omitted for c in p.candidates]


# ── criterion 5: caps ────────────────────────────────────────────────────────


def test_twelve_eligible_for_one_candidate_send_ten_and_omit_two() -> None:
    p, _ = _build([_cand("a", 12)])
    assert _sent(p) == [MAX_CLAIMS_PER_CANDIDATE] and _omitted(p) == [2] and p.claims_omitted_total == 2


def test_forty_eligible_across_four_candidates_send_thirty() -> None:
    p, _ = _build([_cand(c, 10) for c in "abcd"])
    assert sum(_sent(p)) == MAX_CLAIMS_PER_PAYLOAD == 30


@pytest.mark.parametrize(
    "eligible,sent,omitted",
    [
        ((10, 10, 10, 10), [8, 8, 7, 7], [2, 2, 3, 3]),
        ((10, 3), [10, 3], [0, 0]),
        ((10,) * 8, [4, 4, 4, 4, 4, 4, 3, 3], [6, 6, 6, 6, 6, 6, 7, 7]),
    ],
)
def test_water_fill_split(eligible: tuple[int, ...], sent: list[int], omitted: list[int]) -> None:
    p, _ = _build([_cand(f"c{i}", n) for i, n in enumerate(eligible)])
    assert _sent(p) == sent and _omitted(p) == omitted
    assert p.claims_omitted_total == sum(omitted)
    # E-ordinals run 1..total in candidate order.
    flat = [c.ordinal for blk in p.candidates for c in blk.claims]
    assert flat == list(range(1, sum(sent) + 1))


def test_water_fill_keeps_the_best_ranked_within_each_candidate() -> None:
    cand = _cand("a", 12, bench=1)  # a-00 is benchmark evidence
    p, _ = _build([cand])
    assert p.candidates[0].claims[0].is_benchmark is True
    assert [c.is_benchmark for c in p.candidates[0].claims[1:]] == [False] * 9


def test_more_than_eight_candidates_is_refused_before_any_payload() -> None:
    with pytest.raises(ValueError):
        _build([_cand(f"c{i}", 1) for i in range(9)])


# ── size guard ───────────────────────────────────────────────────────────────


def _chars(p: SP.SelectionPayloadV1) -> int:
    system, prompt = render(build_payload(p))
    return len(system) + len(prompt)


def test_worst_case_plain_payload_is_under_the_input_cap() -> None:
    """8 candidates, 30 claims of full length: the measured worst case for plain text."""
    p, _ = _build([_cand(f"c{i}", 10, claim_len=300, cond_len=150) for i in range(8)])
    assert sum(_sent(p)) == 30 and p.claims_omitted_total == 50
    assert _chars(p) <= SP.MAX_INPUT_CHARS - 2_000, _chars(p)  # ADR §2.3: margin kept


def test_escape_heavy_payload_drops_whole_claims_to_fit() -> None:
    quote = '"'
    cands = [
        _cand(f"c{i}", 10, claim_len=300, cond_len=150) for i in range(8)
    ]
    cands = [
        build_candidate(
            candidate_id=c.candidate_id, model_family="f", task_support=("x",),
            evidence_items=tuple(
                _item(f"{c.candidate_id}-{k:02d}", claim=quote * 300, conditions=quote * 150) for k in range(10)
            ),
            strengths=(), limitations=(), compatibility_constraints=(),
        )
        for c in cands
    ]
    p, _ = _build(cands)
    assert _chars(p) <= SP.MAX_INPUT_CHARS
    sent = sum(_sent(p))
    assert 0 < sent < 30, sent
    assert [c.ordinal for b in p.candidates for c in b.claims] == list(range(1, sent + 1))
    assert all(len(c.claim) == 300 for b in p.candidates for c in b.claims)  # never truncated mid-claim
    assert p.claims_omitted_total == 80 - sent


def test_guard_drops_the_globally_lowest_ranked_claim_first() -> None:
    a = _cand("a", 3)
    b = _cand("b", 2, items=(_item("b-weak", source_class="community_discussion"),))
    full, _ = _build([a, b])
    assert _sent(full) == [3, 3]
    p, _ = _build([a, b], max_input_chars=_chars(full) - 1)
    assert _sent(p) == [3, 2] and _omitted(p) == [0, 1]
    assert {c.evidence_weight for c in p.candidates[1].claims} == {"high"}


def test_input_cap_constant_matches_the_gateway_default() -> None:
    assert SP.MAX_INPUT_CHARS == load_config().llm.budget.max_input_chars


def test_cannot_fit_even_without_claims_is_an_error() -> None:
    with pytest.raises(PayloadFieldError):
        _build([_cand("a", 1)], max_input_chars=10)


# ── leaks and structure ──────────────────────────────────────────────────────


def test_no_free_text_reaches_the_payload() -> None:
    m = {k: "CANARY-" + secrets.token_hex(6) for k in "tcfslgdnuvpw"}
    bad = [
        _item("p1", claim=m["p"], conditions=m["p"], ingest=IngestPath.PROJECT_INPUT),
        _item("p2", claim=m["w"], conditions=m["w"], source_class="professional_post"),
        _item("p3", claim=m["u"], conditions=m["u"], url="https://cam.site.local/" + m["u"]),
    ]
    cand = _cand(
        "id-" + m["c"], 2, items=bad, model_family=m["f"], strengths=(m["s"],), limitations=(m["l"],),
        compat=(m["g"],), task_support=("tao_fine_tuning_" + m["t"], "person_detection"),
    )
    other = _cand("other", 1)
    note = ConflictNote("other-00", "id-" + m["c"] + "-00", m["d"], m["n"], ConflictDimension.HARDWARE)
    p, mapping = _build([cand, other], cmp_kw={"task_description": m["t"] + " site 7", "known_conflicts": ()})
    p2 = SP.build_selection_payload(
        CandidateComparison(
            task_description=m["t"], candidates=(cand, other),
            research_gaps=(m["v"],), conflicting_evidence=(note,),
        ),
        _view(),
    )[0]
    for payload in (p, p2):
        built = build_payload(payload)
        text = "".join(render(built)) + built.body_json
        assert "CANARY-" not in text
    assert mapping[1] == "id-" + m["c"] and mapping[2] == "other"  # kept local only
    assert p.candidates[0].claims_excluded == 3
    assert [t.value for t in p.candidates[0].task_support] == ["person_detection"]
    assert p.candidates[0].task_support_unrecognised == 1


def test_data_classes_follow_the_claims() -> None:
    p, _ = _build([_cand("a", 2)])
    built = build_payload(p)
    assert built.data_classes == frozenset({DataClass.PROJECT_METADATA, DataClass.PUBLIC_WEB})
    assert built.task_class is TaskClass.SELECTION and (built.schema_id, built.schema_version) == ("selection", 1)
    none_ok = build_candidate(
        candidate_id="n", model_family="f", task_support=("x",),
        evidence_items=(_item("z", ingest=IngestPath.UNSPECIFIED),),
        strengths=(), limitations=(), compatibility_constraints=(),
    )
    p2, _ = _build([none_ok])
    b2 = build_payload(p2)
    assert b2.data_classes == frozenset({DataClass.PROJECT_METADATA}) and p2.candidates[0].claims == ()


def test_reference_less_evidence_is_excluded_not_trusted() -> None:
    """A reference with no source_item cannot prove provenance, so it is excluded as no_provenance."""
    import dataclasses

    cand = _cand("a", 2)
    stripped = dataclasses.replace(cand, evidence_references=tuple(
        dataclasses.replace(r, source_item=None) for r in cand.evidence_references
    ))
    p, _ = _build([stripped])
    assert p.candidates[0].claims == () and p.candidates[0].claims_excluded == 2


def test_flags_and_conflicts() -> None:
    a = _cand("a", 2, bench=1, compat=())
    b = _cand("b", 2, bench=1)
    notes = (
        ("a-00", "b-00", "free text dim", "free text note", ConflictDimension.HARDWARE),
        ("a-00", "zzz-unsent", "x", "y"),  # names an item that was not sent: dropped
        ("a-00", "a-00", "x", "y"),  # same item twice: dropped
    )
    p, mapping = _build([a, b], cmp_kw={"known_conflicts": notes})
    assert [c.has_benchmark_evidence for c in p.candidates] == [True, True]
    assert [c.has_compatibility_evidence for c in p.candidates] == [False, True]
    (ref,) = p.conflicts
    first_a = p.candidates[0].claims[0].ordinal
    first_b = p.candidates[1].claims[0].ordinal
    assert (ref.first, ref.second, ref.dimension) == (first_a, first_b, ConflictDimension.HARDWARE)
    assert dict(mapping) == {1: "a", 2: "b"}
    assert "a-00" not in build_payload(p).body_json


def test_four_tuple_conflicts_default_to_other() -> None:
    p, _ = _build([_cand("a", 1), _cand("b", 1)], cmp_kw={"known_conflicts": (("a-00", "b-00", "d", "n"),)})
    assert [c.dimension for c in p.conflicts] == [ConflictDimension.OTHER]


def test_body_is_canonical_json() -> None:
    p, _ = _build([_cand("a", 2)])
    built = build_payload(p)
    assert json.loads(built.body_json)["candidates"][0]["ordinal"] == 1
    assert build_payload(p).payload_sha256 == built.payload_sha256  # deterministic
