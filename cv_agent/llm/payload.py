"""
cv_agent.llm.payload — structured hosted payloads (ADR-0023 §2, §3, §5; slice S1, D-095).

Responsibility: own *what may leave the process* for SELECTION and NARRATIVE. A hosted payload is
built only by :func:`build_payload` from a registered, frozen schema whose leaves are enums, issued
vocabulary tokens, bounded numbers, bools, bounded counts and issued :class:`PublicClaim` objects.
Any other ``str`` is rejected, so no user free text can exist in a payload. The payload type, not a
caller label, decides the data classes. Domain schemas live with their owners and register here
from allowlisted modules at import time. Errors name a field path or vocabulary, never a value.

Imports only stdlib, ``llm.policy``, ``llm.errors`` and ``knowledge.models``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import sys
import typing
import weakref
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Literal, Mapping, Optional, Protocol, TypeVar

from cv_agent.llm.errors import PayloadFieldError
from cv_agent.llm.policy import TaskClass

T = TypeVar("T")

VocabOrigin = Literal["code", "packaged_resource"]
SCHEMA_MODULES = frozenset({"cv_agent.requirements.structured", "cv_agent.model_selection.selection_payload"})

# Instances issued by this module's constructors, each with a fingerprint of its fields at issue time.
# A dataclasses.replace copy is not in it; an object mutated after issue no longer matches its fingerprint.
_ISSUED: "weakref.WeakKeyDictionary[Any, tuple[Any, ...]]" = weakref.WeakKeyDictionary()
_VOCABS: dict[str, "Vocabulary"] = {}
_SCHEMAS: dict[tuple[str, int], "_Registered"] = {}


def _fingerprint(obj: Any) -> tuple[Any, ...]:
    """Field names, exact types and values; a Mapping is frozen to sorted items."""
    out = []
    for f in dataclasses.fields(obj):
        v = getattr(obj, f.name)
        out.append((f.name, type(v), tuple(sorted(v.items())) if isinstance(v, Mapping) else v))
    return tuple(out)


def _issue(obj: T) -> T:
    _ISSUED[obj] = _fingerprint(obj)
    return obj


def _is_issued(obj: object, cls: type) -> bool:
    """Exactly ``cls`` (no subclass), issued here, and unchanged since."""
    return type(obj) is cls and obj in _ISSUED and _ISSUED[obj] == _fingerprint(obj)


class Unit(str, Enum):
    """Units are fixed on the schema field, never parsed from or carried in data (§2.2)."""

    MS = "ms"
    FPS = "fps"
    MB = "mb"
    W = "w"
    PX = "px"
    COUNT = "count"
    RATIO = "ratio"


@dataclass(frozen=True)
class Vocabulary:
    """A closed set of tokens defined in code or a packaged resource. ``version`` is the first 12 hex
    characters of the sha256 of the sorted members, so a vocabulary change shows in the payload header."""

    name: str
    version: str
    members: frozenset[str]
    origin: VocabOrigin

    def __post_init__(self) -> None:
        if self.version != _version_of(self.members):
            raise PayloadFieldError(f"vocabulary {self.name!r}: version does not match its members")

    @classmethod
    def of(cls, name: str, members: typing.Iterable[str], origin: VocabOrigin) -> "Vocabulary":
        found = frozenset(members)
        return cls(name, _version_of(found), found, origin)

    def token(self, value: str) -> "VocabToken":
        if type(value) is not str or value not in self.members:
            raise PayloadFieldError(f"value is not a member of vocabulary {self.name!r}")
        return _issue(VocabToken(self.name, value))


def _version_of(members: frozenset[str]) -> str:
    return hashlib.sha256("\n".join(sorted(members)).encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True, eq=False)
class VocabToken:
    """A member of a registered vocabulary. Valid only when issued by :meth:`Vocabulary.token`."""

    vocabulary: str
    value: str


@dataclass(frozen=True)
class Quantity:
    """A finite number with the unit declared on the schema field."""

    value: float
    unit: Unit


@dataclass(frozen=True)
class FieldBounds:
    """Attached with ``field(metadata={"bounds": FieldBounds(...)})``."""

    minimum: Optional[float] = None
    maximum: Optional[float] = None
    max_items: Optional[int] = None  # required for every tuple field
    unit: Optional[Unit] = None  # required for every Quantity field
    vocabulary: Optional[str] = None  # required for every VocabToken field


class PayloadSchema(Protocol):
    SCHEMA_ID: ClassVar[str]
    SCHEMA_VERSION: ClassVar[int]
    TASK_CLASS: ClassVar[TaskClass]
    SYSTEM: ClassVar[str]  # a string literal (AST-checked in slice S5)
    INSTRUCTIONS: ClassVar[str]  # a string literal (AST-checked in slice S5)


@dataclass(frozen=True)
class _Registered:
    """A schema's class and its constants as captured at registration; later reassignment is ignored."""

    cls: type
    task_class: TaskClass
    system: str
    instructions: str


_CONSTANT_TYPES: tuple[tuple[str, type], ...] = (
    ("SCHEMA_ID", str), ("SCHEMA_VERSION", int), ("TASK_CLASS", TaskClass), ("SYSTEM", str), ("INSTRUCTIONS", str),
)


# ── registration ─────────────────────────────────────────────────────────────


def _require_registration_site(what: str) -> None:
    """Allow registration only from the top level (import time) of an allowlisted schema module."""
    caller = sys._getframe(2)
    if caller.f_globals.get("__name__") not in SCHEMA_MODULES:
        raise PayloadFieldError(f"{what}: only modules on the schema allowlist may register")
    if caller.f_code.co_name != "<module>":
        raise PayloadFieldError(f"{what}: registration is allowed at import time only")


def register_vocabulary(vocab: Vocabulary) -> Vocabulary:
    _require_registration_site("register_vocabulary")
    if vocab.name in _VOCABS:
        raise PayloadFieldError(f"vocabulary {vocab.name!r} is already registered")
    _VOCABS[vocab.name] = vocab
    return vocab


def _bounds(f: dataclasses.Field[Any]) -> FieldBounds:
    return f.metadata.get("bounds", FieldBounds())


def _is_frozen_dataclass(tp: object) -> bool:
    return isinstance(tp, type) and dataclasses.is_dataclass(tp) and tp.__dataclass_params__.frozen  # type: ignore[attr-defined]


def _check_type(tp: Any, b: FieldBounds, where: str) -> None:
    if typing.get_origin(tp) is tuple:
        args = typing.get_args(tp)
        if len(args) != 2 or args[1] is not Ellipsis or b.max_items is None:
            raise PayloadFieldError(f"{where}: a tuple needs tuple[X, ...] and a declared max_items")
        _check_type(args[0], b, where + "[]")
    elif tp is bool:
        return
    elif isinstance(tp, type) and issubclass(tp, Enum):
        # Only a concrete enum with code-defined members: a bare Enum or a member-less base would accept
        # a runtime-created enum whose value is user text.
        if tp is Enum or len(tp) == 0 or any(type(m.value) not in (str, int) for m in tp):
            raise PayloadFieldError(f"{where}: an enum must be concrete, with str or int members")
    elif tp is int:
        if b.maximum is None:
            raise PayloadFieldError(f"{where}: an int needs a declared maximum")
    elif tp is VocabToken:
        if b.vocabulary not in _VOCABS:
            raise PayloadFieldError(f"{where}: a token needs a registered vocabulary")
    elif tp is Quantity:
        if b.unit is None:
            raise PayloadFieldError(f"{where}: a quantity needs a declared unit")
    elif _is_frozen_dataclass(tp):
        _check_fields(tp)
    else:
        raise PayloadFieldError(f"{where}: type {tp!r} is not allowed in a hosted payload")


def _check_fields(cls: type) -> None:
    hints = typing.get_type_hints(cls)
    for f in dataclasses.fields(cls):
        _check_type(hints[f.name], _bounds(f), f"{cls.__name__}.{f.name}")


def register_schema(cls: type[T]) -> type[T]:
    """Validate a payload schema's annotations and register it (import time, allowlisted modules only)."""
    _require_registration_site("register_schema")
    if not _is_frozen_dataclass(cls):
        raise PayloadFieldError(f"{cls.__name__}: a schema must be a frozen dataclass")
    for name, kind in _CONSTANT_TYPES:
        if type(getattr(cls, name, None)) is not kind:
            raise PayloadFieldError(f"{cls.__name__}: class constant {name} must be a {kind.__name__}")
    _check_fields(cls)
    key = (getattr(cls, "SCHEMA_ID"), getattr(cls, "SCHEMA_VERSION"))
    if key in _SCHEMAS:
        raise PayloadFieldError(f"schema {key[0]}/{key[1]} is already registered")
    _SCHEMAS[key] = _Registered(cls, getattr(cls, "TASK_CLASS"), getattr(cls, "SYSTEM"), getattr(cls, "INSTRUCTIONS"))
    return cls
