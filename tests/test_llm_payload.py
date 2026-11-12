"""Slice S1 acceptance tests: the structured hosted payload core.

ADR-0023 §7.1 criterion 4 (registration and leaf types); §7.2 S1; D-095; issue #105.
No network, no real key: every store lives under ``tmp_path``, every adapter is a fake.
"""

from __future__ import annotations

import dataclasses
import textwrap
from typing import Any

import pytest

from cv_agent.knowledge.models import IngestPath, KnowledgeItem, Provenance
from cv_agent.llm import payload as P
from cv_agent.llm.errors import PayloadFieldError

ALLOWED_MODULE = "cv_agent.requirements.structured"

_SCHEMA_SRC = '''
from dataclasses import dataclass, field
from typing import ClassVar
from cv_agent.llm.payload import (FieldBounds, Quantity, Unit, VocabToken, Vocabulary,
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


# ── knowledge field ──────────────────────────────────────────────────────────


def test_ingest_defaults_to_unspecified_and_must_be_an_enum() -> None:
    fields = {f.name: f.default for f in dataclasses.fields(KnowledgeItem)}
    assert fields["ingest"] is IngestPath.UNSPECIFIED
    with pytest.raises(ValueError):
        _item(ingest="web_fetch")  # type: ignore[arg-type]


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
