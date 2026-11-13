"""ADR-0023 §7.1 criterion 1, SELECTION part (slice S4d, issue #132): the selection golden payloads.

``tests/golden/llm_payloads/selection_v1.json`` pins, for the reference comparison and three fixed
requirement inputs that pass the clarification gate, the canonical body, its sha256, the rendered
size, the vocabulary versions and the schema's SYSTEM and INSTRUCTIONS constants. It also pins the
schema *shape*, so a shape change without a ``SCHEMA_VERSION`` bump fails even where the fixed inputs
would not show it. A vocabulary change updates ``vocabulary_versions`` and the bodies in the same PR.
Regenerate deliberately with ``CV_AGENT_REGEN_GOLDEN=1``. The candidate ordinal → candidate_id mapping
is local and is deliberately not pinned. ``shape`` mirrors the narrative golden's helper and adds the
``PublicClaim`` leaf, which that helper does not know.
"""

from __future__ import annotations

import dataclasses
import json
import os
import typing
from enum import Enum
from pathlib import Path
from typing import Any

import pytest

from cv_agent.llm.payload import FieldBounds, PublicClaim, Quantity, VocabToken, build_payload, render
from cv_agent.model_selection.reference_task_research import build_reference_comparison
from cv_agent.model_selection.selection_payload import (
    MAX_INPUT_CHARS,
    SelectionPayloadV1,
    build_selection_payload,
)
from cv_agent.requirements.structured import RequirementsView, structured_view
from tests.test_llm_payload_golden import _dump
from tests.test_requirements_structured import _analyzer

GOLDEN = Path(__file__).parent / "golden" / "llm_payloads" / "selection_v1.json"
CASES: tuple[dict[str, Any], ...] = (
    {
        "name": "mostly_known",
        "request": "Detect people climbing the perimeter fence at an outdoor prison; "
        "must run on a Jetson edge device in real-time from RTSP cameras.",
        "assumptions": {},
    },
    {
        "name": "assumptions",
        "request": "Count people entering the parking area.",
        "assumptions": {"deployment_target": "Jetson Orin at Site 7", "latency_requirement": "real-time at the gate"},
    },
    {
        "name": "tracking",
        "request": "Track workers in the factory on the cloud server, live, with high recall.",
        "assumptions": {},
    },
)


def _type(tp: Any, b: FieldBounds) -> Any:
    if typing.get_origin(tp) is tuple:
        return {"tuple": _type(typing.get_args(tp)[0], b), "max_items": b.max_items}
    if tp is VocabToken:
        return {"token": b.vocabulary}
    if tp is Quantity:
        return {"quantity": b.unit.value if b.unit else None, "min": b.minimum, "max": b.maximum}
    if tp is int:
        return {"int": [b.minimum or 0, b.maximum]}
    if tp is bool:
        return "bool"
    if tp is PublicClaim:
        return {"public_claim": [f.name for f in dataclasses.fields(PublicClaim)]}
    if isinstance(tp, type) and issubclass(tp, Enum):
        return {"enum": tp.__name__, "members": sorted(str(m.value) for m in tp)}
    return shape(tp)


def shape(cls: type) -> dict[str, Any]:
    """Field name -> type and bounds, recursively; the fingerprint the golden pins."""
    hints = typing.get_type_hints(cls)
    return {
        f.name: _type(hints[f.name], f.metadata.get("bounds", FieldBounds()))
        for f in dataclasses.fields(cls)  # type: ignore[arg-type]
    }


def _current() -> dict[str, Any]:
    comparison = build_reference_comparison()
    cases, versions = [], {}
    for case in CASES:
        view = structured_view(_analyzer().analyze(case["request"], assumptions=case["assumptions"] or None))
        built = build_selection_payload(comparison, view)
        assert isinstance(built, tuple), f"golden case {case['name']!r} must pass the clarification gate"
        built_payload = build_payload(built[0])
        versions.update(built_payload.vocabulary_versions)
        system, prompt = render(built_payload)
        cases.append({
            **case,
            "body_json": built_payload.body_json,
            "payload_sha256": built_payload.payload_sha256,
            "rendered_chars": len(system) + len(prompt),
            "data_classes": sorted(c.value for c in built_payload.data_classes),
        })
    return {
        "schema": f"{SelectionPayloadV1.SCHEMA_ID}/{SelectionPayloadV1.SCHEMA_VERSION}",
        "system": SelectionPayloadV1.SYSTEM,
        "instructions": SelectionPayloadV1.INSTRUCTIONS,
        "shape": shape(SelectionPayloadV1),
        "vocabulary_versions": dict(sorted(versions.items())),
        "cases": cases,
    }


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    if os.environ.get("CV_AGENT_REGEN_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(_dump(_current()), encoding="utf-8")
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_golden_is_for_this_schema_version(golden: dict[str, Any]) -> None:
    assert golden["schema"] == "selection/1" == f"selection/{SelectionPayloadV1.SCHEMA_VERSION}", (
        "SCHEMA_VERSION changed: add tests/golden/llm_payloads/selection_v<N>.json for the new version"
    )


def test_shape_change_without_a_version_bump_fails(golden: dict[str, Any]) -> None:
    assert shape(SelectionPayloadV1) == golden["shape"], (
        "SelectionPayloadV1 shape changed without a SCHEMA_VERSION bump"
    )


def test_the_shape_check_catches_an_added_field(golden: dict[str, Any]) -> None:
    variant = dataclasses.make_dataclass(
        "SelectionPayloadV1", [("requirements", RequirementsView), ("extra", bool)], frozen=True
    )
    assert shape(variant) != golden["shape"]


@pytest.mark.parametrize("index", range(len(CASES)))
def test_golden_bodies_hashes_and_sizes(golden: dict[str, Any], index: int) -> None:
    now = _current()
    assert now["vocabulary_versions"] == golden["vocabulary_versions"]
    assert now["cases"][index] == golden["cases"][index]


def test_golden_pins_the_schema_constants(golden: dict[str, Any]) -> None:
    """The logged ``selection/1`` must identify the whole outbound text, so the template constants
    cannot change without a SCHEMA_VERSION bump either."""
    assert (golden["system"], golden["instructions"]) == (SelectionPayloadV1.SYSTEM, SelectionPayloadV1.INSTRUCTIONS)


def test_golden_payloads_fit_the_input_cap_and_carry_public_claims(golden: dict[str, Any]) -> None:
    for case in golden["cases"]:
        assert case["rendered_chars"] <= MAX_INPUT_CHARS
        assert case["data_classes"] == ["project_metadata", "public_web"], case["name"]
        assert "CANARY" not in case["body_json"]
