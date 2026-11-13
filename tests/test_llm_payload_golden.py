"""ADR-0023 §7.1 criterion 1, NARRATIVE part (slice S3c, issue #119): the narrative golden payloads.

``tests/golden/llm_payloads/narrative_v1.json`` pins, for three fixed requirement inputs, the canonical
body, its sha256, the vocabulary versions, the template narrative and the schema's SYSTEM and
INSTRUCTIONS constants. It also pins the schema *shape*
(every field path with its type and bounds), so a shape change without a ``SCHEMA_VERSION`` bump fails
even where the fixed inputs would not show it. A vocabulary change updates ``vocabulary_versions`` and
the bodies in the same PR. Regenerate deliberately with ``CV_AGENT_REGEN_GOLDEN=1``.
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

from cv_agent.llm.payload import FieldBounds, Quantity, VocabToken, build_payload
from cv_agent.requirements.structured import (
    NarrativePayloadV1,
    RequirementsView,
    render_template_narrative,
    structured_view,
)
from tests.test_requirements_structured import _analyzer

GOLDEN = Path(__file__).parent / "golden" / "llm_payloads" / "narrative_v1.json"
CASES: tuple[dict[str, Any], ...] = (
    {
        "name": "mostly_known",
        "request": "Detect people climbing the perimeter fence at an outdoor prison; "
        "must run on a Jetson edge device in real-time from RTSP cameras.",
        "assumptions": {},
    },
    {
        "name": "assumptions",
        "request": "Count vehicles entering the parking area.",
        "assumptions": {"deployment_target": "Jetson Orin at Site 7", "latency_requirement": "whatever is cheapest"},
    },
    {"name": "vague", "request": "Help me with my project.", "assumptions": {}},
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
    cases, versions = [], {}
    for case in CASES:
        view = structured_view(_analyzer().analyze(case["request"], assumptions=case["assumptions"] or None))
        payload = build_payload(NarrativePayloadV1(view=view))
        versions.update(payload.vocabulary_versions)
        cases.append({**case, "body_json": payload.body_json, "payload_sha256": payload.payload_sha256,
                      "template": render_template_narrative(view)})
    return {
        "schema": f"{NarrativePayloadV1.SCHEMA_ID}/{NarrativePayloadV1.SCHEMA_VERSION}",
        "system": NarrativePayloadV1.SYSTEM,
        "instructions": NarrativePayloadV1.INSTRUCTIONS,
        "shape": shape(NarrativePayloadV1),
        "vocabulary_versions": dict(sorted(versions.items())),
        "cases": cases,
    }


def _dump(g: dict[str, Any]) -> str:
    """One line per top-level key and per case, so a change shows as a one-line diff."""
    head = [f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in g.items() if k != "cases"]
    cases = ",\n".join(f"    {json.dumps(c, ensure_ascii=False)}" for c in g["cases"])
    return "{\n" + ",\n".join(head) + ',\n  "cases": [\n' + cases + "\n  ]\n}\n"


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    if os.environ.get("CV_AGENT_REGEN_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(_dump(_current()), encoding="utf-8")
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_golden_is_for_this_schema_version(golden: dict[str, Any]) -> None:
    assert golden["schema"] == "narrative/1" == f"narrative/{NarrativePayloadV1.SCHEMA_VERSION}", (
        "SCHEMA_VERSION changed: add tests/golden/llm_payloads/narrative_v<N>.json for the new version"
    )


def test_shape_change_without_a_version_bump_fails(golden: dict[str, Any]) -> None:
    assert shape(NarrativePayloadV1) == golden["shape"], (
        "NarrativePayloadV1 shape changed without a SCHEMA_VERSION bump"
    )


def test_the_shape_check_catches_an_added_field(golden: dict[str, Any]) -> None:
    variant = dataclasses.make_dataclass(
        "NarrativePayloadV1", [("view", RequirementsView), ("extra", bool)], frozen=True
    )
    assert shape(variant) != golden["shape"]


@pytest.mark.parametrize("index", range(len(CASES)))
def test_golden_bodies_hashes_and_templates(golden: dict[str, Any], index: int) -> None:
    now = _current()
    assert now["vocabulary_versions"] == golden["vocabulary_versions"]
    assert now["cases"][index] == golden["cases"][index]


def test_golden_pins_the_schema_constants(golden: dict[str, Any]) -> None:
    """Review D4: the logged ``narrative/1`` must identify the whole outbound text, so the template
    constants cannot change without a SCHEMA_VERSION bump either."""
    assert (golden["system"], golden["instructions"]) == (NarrativePayloadV1.SYSTEM, NarrativePayloadV1.INSTRUCTIONS)
