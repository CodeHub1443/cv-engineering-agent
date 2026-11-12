"""Slice S1 acceptance tests: the structured hosted payload core.

ADR-0023 §7.1 criteria 3 (PublicClaim unit cases) and 4; §7.2 S1; D-095; issues #105, #110.
No network, no real key: every store lives under ``tmp_path``, every adapter is a fake.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import textwrap
from types import SimpleNamespace
from typing import Any

import pytest

from cv_agent.knowledge.models import IngestPath, KnowledgeItem, Provenance
from cv_agent.llm import payload as P
from cv_agent.llm.errors import LLMPayloadMisuseError, PayloadFieldError

ER = P.ExclusionReason
ALLOWED_MODULE = "cv_agent.requirements.structured"

_SCHEMA_SRC = '''
from dataclasses import dataclass, field
from typing import ClassVar
from cv_agent.llm.payload import (FieldBounds, PublicClaim, Quantity, Unit, VocabToken, Vocabulary,
                                  register_schema, register_vocabulary)
from cv_agent.llm.policy import TaskClass

register_vocabulary(Vocabulary.of("task_component", {"detection", "tracking"}, "code"))

@register_schema
@dataclass(frozen=True)
class Demo:
    SCHEMA_ID: ClassVar[str] = "demo"
    SCHEMA_VERSION: ClassVar[int] = 1
    TASK_CLASS: ClassVar[TaskClass] = TaskClass.NARRATIVE
    SYSTEM: ClassVar[str] = "SYS"
    INSTRUCTIONS: ClassVar[str] = "INSTR"
    tasks: tuple[VocabToken, ...] = field(metadata={"bounds": FieldBounds(max_items=2, vocabulary="task_component")})
    fps: Quantity = field(metadata={"bounds": FieldBounds(minimum=0, maximum=240, unit=Unit.FPS)})
    count: int = field(metadata={"bounds": FieldBounds(maximum=8)})
    claims: tuple[PublicClaim, ...] = field(default=(), metadata={"bounds": FieldBounds(max_items=3)})
'''

_BAD_SRC = '''
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Optional
from cv_agent.llm.payload import register_schema
from cv_agent.llm.policy import TaskClass

class Empty(str, Enum):
    pass

@register_schema
@dataclass(frozen=True)
class Bad:
    SCHEMA_ID: ClassVar[str] = "bad"
    SCHEMA_VERSION: ClassVar[int] = 1
    TASK_CLASS: ClassVar[TaskClass] = TaskClass.NARRATIVE
    SYSTEM: ClassVar[str] = "s"
    INSTRUCTIONS: ClassVar[str] = "i"
    x: {ann}
'''


def _define(src: str, module: str = ALLOWED_MODULE) -> dict[str, Any]:
    ns: dict[str, Any] = {"__name__": module}
    # dont_inherit: this file's `from __future__ import annotations` must not stringify the schema's types
    exec(compile(textwrap.dedent(src), "<schema>", "exec", dont_inherit=True), ns)
    return ns


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(P, "_SCHEMAS", {})
    monkeypatch.setattr(P, "_VOCABS", {})


@pytest.fixture
def demo(_fresh_registry: None) -> dict[str, Any]:
    return _define(_SCHEMA_SRC)


def _item(
    *,
    url: str = "https://docs.example.org/a",
    source_class: Any = "official_documentation",
    ingest: IngestPath = IngestPath.WEB_FETCH,
) -> KnowledgeItem:
    prov = Provenance(
        url=url, source_class=source_class, date_published="2026-01-01", date_accessed="2026-11-12", author_or_org="Org"
    )
    return KnowledgeItem(
        item_id="i1",  # type: ignore[arg-type]
        claim="CANARY-1 " + "x" * 400,
        conditions="CANARY-2 " + "y" * 200,
        provenance=prov,
        topic_tags=("t",),
        staleness_horizon_days=30,
        ingest=ingest,
    )


def _inst(demo: dict[str, Any], **over: Any) -> Any:
    kw: dict[str, Any] = {
        "tasks": (P._VOCABS["task_component"].token("detection"),),
        "fps": P.Quantity(30, P.Unit.FPS),
        "count": 2,
    }
    kw.update(over)
    return demo["Demo"](**kw)


def _claim() -> P.PublicClaim:
    claim = P.PublicClaim.from_item(_item(), ordinal=1, is_benchmark=False)
    assert isinstance(claim, P.PublicClaim)
    return claim


# ── knowledge field ──────────────────────────────────────────────────────────


def test_ingest_defaults_to_unspecified_and_must_be_an_enum() -> None:
    fields = {f.name: f.default for f in dataclasses.fields(KnowledgeItem)}
    assert fields["ingest"] is IngestPath.UNSPECIFIED
    with pytest.raises(ValueError):
        _item(ingest="web_fetch")  # type: ignore[arg-type]


# ── criterion 3: PublicClaim eligibility units ───────────────────────────────

_BAD_URLS = [
    "file:///etc/passwd",
    "http://10.0.0.5/x",
    "http://[::1]/x",
    "http://intranet/x",
    "http://localhost/x",
    "https://cam.site.local/x",
    "https://user:pw@example.com/x",
    "ftp://docs.example.org/x",
    "docs.example.org/x",
    "http://10.0.0.5./x",  # trailing dot on an IP literal
    "http://0xa.0.0.5/x",  # inet_aton forms: hex, short, octal
    "http://127.1/x",
    "http://010.0.0.5/x",
    "https://cam.site.local。/x",  # ideographic full stop
    "https://cam.site.ｌｏｃａｌ/x",  # fullwidth "local"
]


@pytest.mark.parametrize(
    "kw,reason",
    [
        ({"ingest": IngestPath.PROJECT_INPUT}, ER.INGEST_NOT_ALLOWED),
        ({"ingest": IngestPath.UNSPECIFIED}, ER.INGEST_NOT_ALLOWED),
        ({"source_class": "professional_post"}, ER.SOURCE_CLASS_NOT_ALLOWED),
        *[({"url": u}, ER.NON_PUBLIC_URL) for u in _BAD_URLS],
    ],
)
def test_public_claim_excludes_with_the_right_reason(kw: dict[str, Any], reason: P.ExclusionReason) -> None:
    assert P.PublicClaim.from_item(_item(**kw), ordinal=1, is_benchmark=False) is reason


def test_public_claim_without_provenance_is_excluded_not_raised() -> None:
    obj = SimpleNamespace(claim="CANARY", conditions=None, provenance=None, ingest=IngestPath.WEB_FETCH)
    assert P.PublicClaim.from_item(obj, ordinal=1, is_benchmark=False) is ER.NO_PROVENANCE


@pytest.mark.parametrize("ingest", [IngestPath.WEB_FETCH, IngestPath.CURATED_REFERENCE])
def test_eligible_claim_is_verbatim_and_truncated(ingest: IngestPath) -> None:
    item = _item(ingest=ingest)
    claim = P.PublicClaim.from_item(item, ordinal=3, is_benchmark=True)
    assert isinstance(claim, P.PublicClaim)
    assert claim.claim == item.claim[:300] and len(claim.claim) == 300
    assert item.conditions is not None and claim.conditions == item.conditions[:150]
    assert (claim.ordinal, claim.is_benchmark, claim.source_class) == (3, True, "official_documentation")


class _Sneaky(str):
    """A str subclass that claims to equal every allowlisted source class."""

    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return hash("official_documentation")


def _tampered(attr: str) -> tuple[KnowledgeItem, P.ExclusionReason]:
    item = _item()
    if attr == "source_class":
        object.__setattr__(item.provenance, "source_class", _Sneaky("CANARY-sc"))
        return item, ER.SOURCE_CLASS_NOT_ALLOWED
    if attr == "ingest":
        object.__setattr__(item, "ingest", "web_fetch")  # a plain str equal to the str-Enum member
        return item, ER.INGEST_NOT_ALLOWED
    object.__setattr__(item, "claim", 5)  # malformed item: refused first, whatever its ingest
    object.__setattr__(item, "ingest", IngestPath.PROJECT_INPUT)
    return item, ER.NO_PROVENANCE


@pytest.mark.parametrize("attr", ["source_class", "ingest", "claim"])
def test_eligibility_uses_exact_types_not_equality(attr: str) -> None:
    item, reason = _tampered(attr)
    assert P.PublicClaim.from_item(item, ordinal=1, is_benchmark=False) is reason


def test_only_a_real_knowledge_item_is_eligible_and_its_weight_comes_from_the_source_class() -> None:
    real = _item()
    duck = SimpleNamespace(
        claim="c", conditions=None, provenance=real.provenance, ingest=IngestPath.WEB_FETCH,
        evidence_weight=lambda: "CANARY-ew",
    )
    assert P.PublicClaim.from_item(duck, ordinal=1, is_benchmark=False) is ER.NO_PROVENANCE
    object.__setattr__(real, "evidence_weight", lambda: "CANARY-ew")  # instance attribute shadows the method
    claim = P.PublicClaim.from_item(real, ordinal=1, is_benchmark=False)
    assert isinstance(claim, P.PublicClaim) and claim.evidence_weight == "high"


@pytest.mark.parametrize(
    "ordinal,is_benchmark", [("CANARY-ord", False), (True, False), (0, False), (31, False), (1, "CANARY-b"), (1, 1)]
)
def test_claim_ordinal_and_benchmark_flag_are_typed_and_bounded(ordinal: Any, is_benchmark: Any) -> None:
    with pytest.raises(PayloadFieldError) as info:
        P.PublicClaim.from_item(_item(), ordinal=ordinal, is_benchmark=is_benchmark)
    assert "CANARY" not in str(info.value)


def test_a_claim_subclass_cannot_be_issued() -> None:
    @dataclasses.dataclass(frozen=True, eq=False)
    class Evil(P.PublicClaim):
        pass

    assert type(Evil.from_item(_item(), ordinal=1, is_benchmark=False)) is P.PublicClaim


# ── criterion 4: registration and builder rejections ─────────────────────────


@pytest.mark.parametrize("ann", ["str", "float", "dict", "Any", "Optional[int]", "list[int]", "Enum", "Empty"])
def test_register_rejects_a_disallowed_annotation(ann: str) -> None:
    with pytest.raises(PayloadFieldError):  # a bare or member-less Enum would accept any runtime enum's value
        _define(_BAD_SRC.format(ann=ann))


@pytest.mark.parametrize(
    "old,new",
    [
        ('SYSTEM: ClassVar[str] = "s"', "SYSTEM: ClassVar[str] = 12345"),
        ('INSTRUCTIONS: ClassVar[str] = "i"', "INSTRUCTIONS: ClassVar[str] = None"),
        ("TASK_CLASS: ClassVar[TaskClass] = TaskClass.NARRATIVE", 'TASK_CLASS: ClassVar[TaskClass] = "narrative"'),
        ("SCHEMA_VERSION: ClassVar[int] = 1", 'SCHEMA_VERSION: ClassVar[int] = "1"'),
        ('SCHEMA_ID: ClassVar[str] = "bad"', "SCHEMA_ID: ClassVar[str] = 7"),
    ],
)
def test_register_requires_typed_schema_constants(old: str, new: str) -> None:
    src = _BAD_SRC.format(ann="bool")
    assert old in src
    with pytest.raises(PayloadFieldError):
        _define(src.replace(old, new))


def test_register_from_a_non_allowlisted_module_is_refused() -> None:
    with pytest.raises(PayloadFieldError, match="allowlist"):
        _define(_SCHEMA_SRC, module="tests.rogue")


def test_register_after_import_time_is_refused() -> None:
    src = (
        "from cv_agent.llm.payload import Vocabulary, register_vocabulary\n"
        "def late():\n    register_vocabulary(Vocabulary.of('late', {'a'}, 'code'))\n"
        "late()\n"
    )
    with pytest.raises(PayloadFieldError, match="import time"):
        _define(src)


def test_registration_captures_the_constants_and_issues_member_tokens(demo: dict[str, Any]) -> None:
    reg = P._SCHEMAS[("demo", 1)]
    assert (reg.cls, reg.system, reg.instructions, reg.task_class.value) == (demo["Demo"], "SYS", "INSTR", "narrative")
    tok = P._VOCABS["task_component"].token("detection")
    assert (tok.vocabulary, tok.value) == ("task_component", "detection") and P._is_issued(tok, P.VocabToken)
    assert not P._is_issued(P.VocabToken("task_component", "detection"), P.VocabToken)


def test_token_outside_the_vocabulary_is_refused_without_echo(demo: dict[str, Any]) -> None:
    with pytest.raises(PayloadFieldError) as info:
        P._VOCABS["task_component"].token("CANARY-zzz")
    assert "CANARY-zzz" not in str(info.value)


@pytest.mark.parametrize("bad", ["strings", "forged", "replaced"])
def test_a_bare_str_or_unissued_token_is_refused(demo: dict[str, Any], bad: str) -> None:
    good = P._VOCABS["task_component"].token("detection")
    tasks = {
        "strings": ("CANARY-leak",),
        "forged": (P.VocabToken("task_component", "detection"),),
        "replaced": (dataclasses.replace(good, value="CANARY-leak"),),
    }[bad]
    with pytest.raises(PayloadFieldError) as info:
        P.build_payload(_inst(demo, tasks=tasks))
    assert "CANARY-leak" not in str(info.value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 241, -1])
def test_quantity_must_be_finite_and_in_bounds(demo: dict[str, Any], value: float) -> None:
    with pytest.raises(PayloadFieldError):
        P.build_payload(_inst(demo, fps=P.Quantity(value, P.Unit.FPS)))


def test_quantity_unit_must_match_the_schema_field(demo: dict[str, Any]) -> None:
    with pytest.raises(PayloadFieldError):
        P.build_payload(_inst(demo, fps=P.Quantity(30, P.Unit.MS)))


def test_tuple_over_max_items_and_str_for_int_are_refused(demo: dict[str, Any]) -> None:
    tok = P._VOCABS["task_component"].token("tracking")
    with pytest.raises(PayloadFieldError):
        P.build_payload(_inst(demo, tasks=(tok, tok, tok)))
    with pytest.raises(PayloadFieldError):
        P.build_payload(_inst(demo, count="CANARY-5"))
    with pytest.raises(PayloadFieldError):
        P.build_payload(_inst(demo, count=9))


def test_a_forged_claim_is_refused(demo: dict[str, Any]) -> None:
    forged = dataclasses.replace(_claim(), claim="CANARY-forged")
    with pytest.raises(PayloadFieldError):
        P.build_payload(_inst(demo, claims=(forged,)))


def test_build_is_canonical_and_render_uses_the_schema_constants(demo: dict[str, Any]) -> None:
    payload = P.build_payload(_inst(demo))
    assert payload.body_json == json.dumps(json.loads(payload.body_json), sort_keys=True, separators=(",", ":"))
    assert payload.payload_sha256 == hashlib.sha256(payload.body_json.encode("utf-8")).hexdigest()
    assert payload.vocabulary_versions == {"task_component": P._VOCABS["task_component"].version}
    assert (payload.schema_id, payload.schema_version, payload.task_class.value) == ("demo", 1, "narrative")
    assert P.render(payload) == ("SYS", "INSTR\n\n" + payload.body_json)


_NESTED_SRC = '''
from dataclasses import dataclass, field
from typing import ClassVar
from cv_agent.llm.payload import FieldBounds, register_schema
from cv_agent.llm.policy import TaskClass

@dataclass(frozen=True)
class Inner:
    n: int = field(metadata={"bounds": FieldBounds(maximum=3)})

@register_schema
@dataclass(frozen=True)
class Outer:
    SCHEMA_ID: ClassVar[str] = "outer"
    SCHEMA_VERSION: ClassVar[int] = 1
    TASK_CLASS: ClassVar[TaskClass] = TaskClass.NARRATIVE
    SYSTEM: ClassVar[str] = "S"
    INSTRUCTIONS: ClassVar[str] = "I"
    inner: Inner
'''


def test_a_nested_value_is_checked_against_the_registered_annotation() -> None:
    ns = _define(_NESTED_SRC)
    inner = ns["Inner"]

    @dataclasses.dataclass(frozen=True)
    class Wider(inner):  # type: ignore[valid-type,misc]
        big: int = dataclasses.field(default=10**12, metadata={"bounds": P.FieldBounds(maximum=10**12)})

    assert P.build_payload(ns["Outer"](inner=inner(n=1))).body_json == '{"inner":{"n":1}}'
    with pytest.raises(PayloadFieldError):
        P.build_payload(ns["Outer"](inner=Wider(n=1)))


def test_a_tuple_subclass_cannot_hide_its_length(demo: dict[str, Any]) -> None:
    class Liar(tuple):  # type: ignore[type-arg]
        def __len__(self) -> int:
            return 0

    tok = P._VOCABS["task_component"].token("tracking")
    with pytest.raises(PayloadFieldError):
        P.build_payload(_inst(demo, tasks=Liar((tok, tok, tok))))


def test_an_object_mutated_after_issue_is_refused(demo: dict[str, Any]) -> None:
    claim, token = _claim(), P._VOCABS["task_component"].token("detection")
    object.__setattr__(claim, "claim", "CANARY-mutated")
    with pytest.raises(PayloadFieldError):
        P.build_payload(_inst(demo, claims=(claim,)))
    object.__setattr__(token, "value", "tracking")
    with pytest.raises(PayloadFieldError):
        P.build_payload(_inst(demo, tasks=(token,)))
    payload = P.build_payload(_inst(demo))
    object.__setattr__(payload, "body_json", "CANARY-mutated")
    with pytest.raises(LLMPayloadMisuseError):
        P.render(payload)


def test_render_uses_the_constants_captured_at_registration(demo: dict[str, Any]) -> None:
    payload = P.build_payload(_inst(demo))
    demo["Demo"].SYSTEM = 12345
    demo["Demo"].INSTRUCTIONS = "CANARY-instr"
    assert P.render(payload) == ("SYS", "INSTR\n\n" + payload.body_json)


def test_render_refuses_anything_but_an_issued_payload() -> None:
    with pytest.raises(LLMPayloadMisuseError):
        P.render(SimpleNamespace(schema_id="demo", schema_version=1, body_json="CANARY"))  # type: ignore[arg-type]
