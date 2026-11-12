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
import ipaddress
import json
import math
import re
import sys
import typing
import weakref
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Literal, Mapping, Optional, Protocol, TypeVar
from urllib.parse import urlsplit

from cv_agent.knowledge.models import IngestPath, KnowledgeItem, Provenance, source_class_weight
from cv_agent.llm.errors import LLMPayloadMisuseError, PayloadFieldError
from cv_agent.llm.policy import DataClass, TaskClass

T = TypeVar("T")

VocabOrigin = Literal["code", "packaged_resource"]
SCHEMA_MODULES = frozenset({"cv_agent.requirements.structured", "cv_agent.model_selection.selection_payload"})
# D-095: an explicit allowlist, not derived from SourceClass. professional_post and any new class are out.
WEB_SOURCE_CLASSES: frozenset[str] = frozenset(
    {
        "peer_reviewed_research",
        "official_documentation",
        "official_repository_or_release_notes",
        "reputable_benchmark",
        "engineering_blog",
        "community_discussion",
        "model_zoo_or_leaderboard",
    }
)
MAX_CLAIM_CHARS = 300
MAX_CONDITIONS_CHARS = 150
MAX_CLAIMS_PER_CANDIDATE = 10  # N; applied by select_claims (slice S4)
MAX_CLAIMS_PER_PAYLOAD = 30  # M; applied by select_claims (slice S4)
_RESERVED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa", ".corp", ".intranet")
_WEB_INGEST = frozenset({IngestPath.WEB_FETCH, IngestPath.CURATED_REFERENCE})
_NUMERIC_LABEL = re.compile(r"0x[0-9a-f]*|[0-9]+")  # inet_aton forms: 127.1, 0xa.0.0.5, 010.0.0.5

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


class ExclusionReason(str, Enum):
    NO_PROVENANCE = "no_provenance"
    NON_PUBLIC_URL = "non_public_url"
    SOURCE_CLASS_NOT_ALLOWED = "source_class_not_allowed"
    INGEST_NOT_ALLOWED = "ingest_not_allowed"


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


def _is_public_url(url: object) -> bool:
    if type(url) is not str:
        return False
    try:
        parts = urlsplit(url)
        host = parts.hostname
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not host or "@" in parts.netloc:
        return False
    host = host.lower().rstrip(".")
    # An IDN must arrive as punycode: this blocks fullwidth and ideographic-dot look-alikes of a reserved name.
    if not host.isascii():
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) < 2 or not all(labels) or _NUMERIC_LABEL.fullmatch(labels[-1]):  # no public TLD is numeric
        return False
    return host != "localhost" and not host.endswith(_RESERVED_SUFFIXES)


@dataclass(frozen=True, eq=False)
class PublicClaim:
    """Public-web text admitted to a payload (§2.3). Created only by :meth:`from_item`."""

    ordinal: int
    claim: str
    conditions: Optional[str]
    source_class: str
    evidence_weight: str
    is_benchmark: bool

    @classmethod
    def from_item(cls, item: object, *, ordinal: int, is_benchmark: bool) -> "PublicClaim | ExclusionReason":
        """The §2.3 eligibility checks, in order. An ineligible item is excluded, never raised.

        Types are checked exactly (no subclass, no duck typing), so an object cannot pass a check by
        overriding equality. The evidence weight is derived from the source class, never read from the
        item. A bad ``ordinal`` or ``is_benchmark`` is a caller bug and raises ``PayloadFieldError``.
        Always builds a :class:`PublicClaim`, even when called on a subclass.
        """
        if type(ordinal) is not int or not 1 <= ordinal <= MAX_CLAIMS_PER_PAYLOAD or type(is_benchmark) is not bool:
            raise PayloadFieldError("PublicClaim: ordinal must be an int in 1..M and is_benchmark a bool")
        # §2.3 item 1: a well-formed stored item with provenance.
        if type(item) is not KnowledgeItem or type(item.provenance) is not Provenance:
            return ExclusionReason.NO_PROVENANCE
        claim, conditions, prov = item.claim, item.conditions, item.provenance
        if type(claim) is not str or not (conditions is None or type(conditions) is str):
            return ExclusionReason.NO_PROVENANCE
        if not _is_public_url(prov.url):
            return ExclusionReason.NON_PUBLIC_URL
        if type(prov.source_class) is not str or prov.source_class not in WEB_SOURCE_CLASSES:
            return ExclusionReason.SOURCE_CLASS_NOT_ALLOWED
        if type(item.ingest) is not IngestPath or item.ingest not in _WEB_INGEST:
            return ExclusionReason.INGEST_NOT_ALLOWED
        return _issue(
            PublicClaim(
                ordinal=ordinal,
                claim=claim[:MAX_CLAIM_CHARS],
                conditions=None if conditions is None else conditions[:MAX_CONDITIONS_CHARS],
                source_class=prov.source_class,
                evidence_weight=source_class_weight(prov.source_class),
                is_benchmark=is_benchmark,
            )
        )


@dataclass(frozen=True, eq=False)
class HostedPayload:
    """The only thing a structured-only request may carry. Issued only by :func:`build_payload`."""

    schema_id: str
    schema_version: int
    task_class: TaskClass
    vocabulary_versions: Mapping[str, str]
    body_json: str
    payload_sha256: str
    data_classes: frozenset[DataClass] = field(default=frozenset())


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
    elif tp is bool or tp is PublicClaim:
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


# ── building ─────────────────────────────────────────────────────────────────


def _encode(v: Any, tp: Any, b: FieldBounds, where: str, seen: dict[str, Any]) -> Any:
    bad = PayloadFieldError(f"{where}: illegal value for a hosted payload")
    # Every check is on the exact type: a subclass could override __len__, __eq__ or add fields.
    if typing.get_origin(tp) is tuple:
        if type(v) is not tuple or len(v) > (b.max_items or 0):
            raise bad
        return [_encode(x, typing.get_args(tp)[0], b, f"{where}[{i}]", seen) for i, x in enumerate(v)]
    if tp is bool:
        if type(v) is not bool:
            raise bad
        return v
    if tp is int:
        if type(v) is not int or not (b.minimum or 0) <= v <= (b.maximum or 0):
            raise bad
        return v
    if tp is VocabToken:
        vocab = _VOCABS.get(b.vocabulary or "")
        if not (_is_issued(v, VocabToken) and vocab and v.vocabulary == vocab.name and v.value in vocab.members):
            raise bad
        seen["versions"][vocab.name] = vocab.version
        return v.value
    if tp is Quantity:
        ok = type(v) is Quantity and v.unit is b.unit and type(v.value) in (int, float) and math.isfinite(v.value)
        if not ok or (b.minimum is not None and v.value < b.minimum) or (b.maximum is not None and v.value > b.maximum):
            raise bad
        return {"unit": v.unit.value, "value": v.value}
    if tp is PublicClaim:
        if not _is_issued(v, PublicClaim):
            raise bad
        seen["claims"] += 1
        return {
            "claim": v.claim, "conditions": v.conditions, "evidence_weight": v.evidence_weight,
            "is_benchmark": v.is_benchmark, "ordinal": v.ordinal, "source_class": v.source_class,
        }
    if isinstance(tp, type) and issubclass(tp, Enum):
        if type(v) is not tp:
            raise bad
        return v.value
    if type(v) is not tp:  # a nested frozen dataclass: walked by its registered annotation, not its runtime type
        raise bad
    return _encode_obj(v, tp, seen)


def _encode_obj(obj: Any, cls: type, seen: dict[str, Any]) -> dict[str, Any]:
    hints = typing.get_type_hints(cls)
    return {
        f.name: _encode(getattr(obj, f.name), hints[f.name], _bounds(f), f"{cls.__name__}.{f.name}", seen)
        for f in dataclasses.fields(cls)
    }


def build_payload(instance: Any) -> HostedPayload:
    """Validate ``instance`` leaf by leaf and issue a :class:`HostedPayload`; ``PayloadFieldError`` otherwise."""
    cls = type(instance)
    found = next(((k, r) for k, r in _SCHEMAS.items() if r.cls is cls), None)  # exact class, not a subclass
    if found is None:
        raise PayloadFieldError(f"{cls.__name__}: not a registered payload schema")
    (schema_id, schema_version), reg = found
    seen: dict[str, Any] = {"versions": {}, "claims": 0}
    body = json.dumps(
        _encode_obj(instance, cls, seen), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    classes = {DataClass.PROJECT_METADATA} | ({DataClass.PUBLIC_WEB} if seen["claims"] else set())
    return _issue(
        HostedPayload(
            schema_id=schema_id,
            schema_version=schema_version,
            task_class=reg.task_class,
            vocabulary_versions=MappingProxyType(dict(seen["versions"])),
            body_json=body,
            payload_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            data_classes=frozenset(classes),
        )
    )


def render(payload: HostedPayload) -> tuple[str, str]:
    """``(system, prompt)``: the schema's constants as captured at registration, plus the canonical body.
    Nothing else varies. Anything but an issued, unmodified payload of a registered schema is misuse."""
    if not _is_issued(payload, HostedPayload):
        raise LLMPayloadMisuseError("payload was not issued by build_payload for a registered schema")
    reg = _SCHEMAS.get((payload.schema_id, payload.schema_version))
    if reg is None or reg.task_class is not payload.task_class:
        raise LLMPayloadMisuseError("payload was not issued by build_payload for a registered schema")
    return reg.system, f"{reg.instructions}\n\n{payload.body_json}"
