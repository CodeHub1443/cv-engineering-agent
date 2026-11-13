"""ADR-0023 §2.3, §7.1 criteria 3 (knowledge path) and 5 (per-candidate cap), slice S4a.

``select_claims`` is the only way knowledge items become payload claims: it applies the eligibility
checks of ``PublicClaim.from_item``, the deterministic §2.3 order and the per-candidate cap.
"""

from __future__ import annotations

import secrets
from typing import Any

import pytest

from cv_agent.knowledge.models import IngestPath, ItemId, KnowledgeItem, Provenance
from cv_agent.llm.errors import PayloadFieldError
from cv_agent.llm.payload import (
    MAX_CLAIM_CHARS,
    MAX_CONDITIONS_CHARS,
    ExclusionReason,
    claim_order_key,
    select_claims,
)

OK_URL = "https://docs.example.org/page"


def _item(
    item_id: str = "a",
    *,
    claim: str = "claim text",
    conditions: str | None = "cond text",
    url: str = OK_URL,
    source_class: Any = "official_documentation",
    ingest: IngestPath = IngestPath.WEB_FETCH,
) -> KnowledgeItem:
    return KnowledgeItem(
        item_id=ItemId(item_id),
        claim=claim,
        conditions=conditions,
        provenance=Provenance(
            url=url,
            source_class=source_class,
            date_published="2026-01-01",
            date_accessed="2026-09-28",
            author_or_org="Org",
        ),
        topic_tags=("t",),
        staleness_horizon_days=180,
        ingest=ingest,
    )


def _marker() -> str:
    return "CANARY-" + secrets.token_hex(6)


def _texts(claims: Any) -> str:
    return " ".join(f"{c.claim} {c.conditions}" for c in claims)


# ── criterion 3, knowledge path ──────────────────────────────────────────────


def _bad_cases() -> list[tuple[str, object, ExclusionReason]]:
    m = _marker
    cases: list[tuple[str, object, ExclusionReason]] = [
        ("project_input", _item(claim=m(), conditions=m(), ingest=IngestPath.PROJECT_INPUT), ExclusionReason.INGEST_NOT_ALLOWED),
        ("unspecified", _item(claim=m(), conditions=m(), ingest=IngestPath.UNSPECIFIED), ExclusionReason.INGEST_NOT_ALLOWED),
        ("professional_post", _item(claim=m(), conditions=m(), source_class="professional_post"), ExclusionReason.SOURCE_CLASS_NOT_ALLOWED),
        ("none", None, ExclusionReason.NO_PROVENANCE),
    ]
    duck = type("Duck", (), {"claim": m(), "conditions": m(), "provenance": None, "ingest": IngestPath.WEB_FETCH})()
    cases.append(("duck", duck, ExclusionReason.NO_PROVENANCE))
    for url in (
        "file:///etc/passwd",
        "http://10.0.0.5/x",
        "http://intranet/x",
        "https://cam.site.local/x",
        "https://user:pw@example.com/x",
    ):
        cases.append((url, _item(claim=m(), conditions=m(), url=url), ExclusionReason.NON_PUBLIC_URL))
    return cases


@pytest.mark.parametrize("name,item,reason", _bad_cases(), ids=[c[0] for c in _bad_cases()])
def test_ineligible_items_are_excluded_and_counted(name: str, item: object, reason: ExclusionReason) -> None:
    claims, omitted, excluded = select_claims([(item, False)], per_candidate=10, start_ordinal=1)
    assert claims == () and omitted == 0
    assert dict(excluded) == {reason: 1}


def test_no_marker_from_any_ineligible_item_is_returned() -> None:
    cases = _bad_cases()
    control = _item("control", claim="C" * 400, conditions="D" * 400)
    items = [(c[1], False) for c in cases] + [(control, False)]
    claims, omitted, excluded = select_claims(items, per_candidate=10, start_ordinal=1)
    assert "CANARY-" not in _texts(claims)
    assert sum(excluded.values()) == len(cases) and omitted == 0
    assert [(c.claim, c.conditions) for c in claims] == [("C" * MAX_CLAIM_CHARS, "D" * MAX_CONDITIONS_CHARS)]


def test_control_item_is_sent_verbatim_when_short() -> None:
    (c,), _, excluded = select_claims(
        [(_item(claim="exact claim", conditions=None), False)], per_candidate=3, start_ordinal=4
    )
    assert (c.claim, c.conditions, c.ordinal) == ("exact claim", None, 4) and not excluded


# ── criterion 5, per candidate ───────────────────────────────────────────────


def test_twelve_eligible_send_ten_and_omit_two() -> None:
    items = [(_item(f"i{n:02d}"), False) for n in range(12)]
    claims, omitted, excluded = select_claims(items, per_candidate=10, start_ordinal=1)
    assert len(claims) == 10 and omitted == 2 and not excluded
    assert [c.ordinal for c in claims] == list(range(1, 11))


def test_excluded_items_do_not_count_as_omitted() -> None:
    items = [(_item("a"), False), (_item("b", ingest=IngestPath.UNSPECIFIED), False)]
    claims, omitted, excluded = select_claims(items, per_candidate=1, start_ordinal=1)
    assert len(claims) == 1 and omitted == 0 and dict(excluded) == {ExclusionReason.INGEST_NOT_ALLOWED: 1}


def test_per_candidate_zero_only_counts() -> None:
    claims, omitted, _ = select_claims([(_item("a"), False), (_item("b"), False)], per_candidate=0, start_ordinal=1)
    assert claims == () and omitted == 2


def test_bad_arguments_raise() -> None:
    with pytest.raises(PayloadFieldError):
        select_claims([], per_candidate=-1, start_ordinal=1)
    with pytest.raises(PayloadFieldError):
        select_claims([(_item(), False)], per_candidate=1, start_ordinal=31)


# ── §2.3 order: benchmark, then weight, then item_id ─────────────────────────


def test_order_is_benchmark_then_weight_then_item_id() -> None:
    items = [
        (_item("z-high", claim="z-high", source_class="official_documentation"), False),
        (_item("b-low", claim="b-low", source_class="community_discussion"), False),
        (_item("a-low", claim="a-low", source_class="community_discussion"), False),
        (_item("m-medium", claim="m-medium", source_class="engineering_blog"), False),
        (_item("y-bench-low", claim="y-bench-low", source_class="community_discussion"), True),
        (_item("x-bench-high", claim="x-bench-high", source_class="reputable_benchmark"), True),
    ]
    claims, omitted, _ = select_claims(items, per_candidate=10, start_ordinal=1)
    assert omitted == 0
    # The claim text equals the item_id here, so the order is readable directly.
    assert [c.claim for c in sorted(claims, key=lambda c: c.ordinal)] == [
        "x-bench-high", "y-bench-low", "z-high", "m-medium", "a-low", "b-low",
    ]


def test_claim_order_key_is_the_shared_global_key() -> None:
    bench = claim_order_key(_item("z", source_class="community_discussion"), True)
    plain_high = claim_order_key(_item("a", source_class="official_documentation"), False)
    plain_low = claim_order_key(_item("a", source_class="community_discussion"), False)
    assert bench < plain_high < plain_low


def test_cap_keeps_the_best_ranked_and_is_input_order_independent() -> None:
    a = [(_item(f"i{n}", claim=f"i{n}", source_class="community_discussion"), False) for n in range(3)]
    b = (_item("bench", claim="bench", source_class="reputable_benchmark"), True)
    first, _, _ = select_claims([*a, b], per_candidate=2, start_ordinal=1)
    second, _, _ = select_claims([b, *reversed(a)], per_candidate=2, start_ordinal=1)
    assert [c.claim for c in first] == [c.claim for c in second] == ["bench", "i0"]
