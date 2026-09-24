"""
cv_agent.datasets.models — the immutable value types a dataset manifest is built from.

Responsibility: typed, fail-closed-at-construction records for the fields
docs/DATA.md names (class definitions, lineage, collection conditions, dataset
card) plus the per-item attributes and split policy the leakage checks in
cv_agent.datasets.leakage need (ADR-0012 §3 records which of those are
interpretations, because docs/DATA.md defines the checks but not the item
schema).

Every record is a frozen dataclass whose sequences are tuples, so a value that
was valid at construction stays valid and hashable. Nothing here reads an image,
computes a hash, or touches storage.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, TypeVar

CameraGoal = Literal["generalize_to_new_cameras", "same_cameras"]
CAMERA_GOALS: tuple[str, ...] = ("generalize_to_new_cameras", "same_cameras")

_HEX = re.compile(r"^[0-9a-fA-F]+$")
_T = TypeVar("_T")


# -- shared validation helpers (also used by cv_agent.datasets.manifest) ------


def set_field(obj: object, name: str, value: Any) -> None:
    """Assign a field on a frozen dataclass during __post_init__ (normalisation only)."""
    object.__setattr__(obj, name, value)


def require_nonblank(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string, got {value!r}")
    return value


def require_timestamp(value: object, field_name: str) -> datetime:
    text = require_nonblank(value, field_name)
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp, got {value!r}") from exc


def require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a bool, got {value!r}")
    return value


def require_nonneg_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer, got {value!r}")
    return value


def as_tuple(value: object, field_name: str, expected: type[_T]) -> tuple[_T, ...]:
    """A real sequence of `expected` instances — never a bare string, never mixed types."""
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise ValueError(f"{field_name} must be a sequence, got {value!r}")
    out = tuple(value)
    for element in out:
        if not isinstance(element, expected):
            raise ValueError(
                f"{field_name} must contain only {expected.__name__} values, got {element!r}"
            )
    return out


def as_str_tuple(value: object, field_name: str, *, allow_empty: bool) -> tuple[str, ...]:
    out = as_tuple(value, field_name, str)
    if not out and not allow_empty:
        raise ValueError(f"{field_name} must not be empty")
    for element in out:
        require_nonblank(element, field_name)
    return out


def reject_duplicates(values: Iterable[str], field_name: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {field_name}: {value!r}")
        seen.add(value)


# -- docs/DATA.md manifest sub-records ---------------------------------------


@dataclass(frozen=True)
class ClassDefinition:
    """
    docs/DATA.md "class definitions (explicit, with edge-case rules)": a class
    is not defined until its edge cases are written down, so `edge_cases` must
    be non-empty. `temporal_boundary` is for event classes (start/end).
    """

    name: str
    definition: str
    edge_cases: tuple[str, ...]
    temporal_boundary: str | None = None

    def __post_init__(self) -> None:
        require_nonblank(self.name, "ClassDefinition.name")
        require_nonblank(self.definition, "ClassDefinition.definition")
        set_field(
            self,
            "edge_cases",
            as_str_tuple(self.edge_cases, "ClassDefinition.edge_cases", allow_empty=False),
        )
        if self.temporal_boundary is not None:
            require_nonblank(self.temporal_boundary, "ClassDefinition.temporal_boundary")


@dataclass(frozen=True)
class ClassCount:
    """One entry of docs/DATA.md's "class distribution"."""

    class_name: str
    count: int

    def __post_init__(self) -> None:
        require_nonblank(self.class_name, "ClassCount.class_name")
        require_nonneg_int(self.count, "ClassCount.count")


@dataclass(frozen=True)
class Lineage:
    """docs/DATA.md "lineage (parent version + transformation)"."""

    parent_version: str
    transformation: str

    def __post_init__(self) -> None:
        require_nonblank(self.parent_version, "Lineage.parent_version")
        require_nonblank(self.transformation, "Lineage.transformation")


@dataclass(frozen=True)
class CollectionConditions:
    """docs/DATA.md "collection conditions (cameras, sites, times, lighting)"."""

    cameras: tuple[str, ...]
    sites: tuple[str, ...] = ()
    times: tuple[str, ...] = ()
    lighting: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        set_field(
            self,
            "cameras",
            as_str_tuple(self.cameras, "CollectionConditions.cameras", allow_empty=False),
        )
        for name in ("sites", "times", "lighting"):
            set_field(
                self,
                name,
                as_str_tuple(
                    getattr(self, name), f"CollectionConditions.{name}", allow_empty=True
                ),
            )


@dataclass(frozen=True)
class DatasetCard:
    """docs/DATA.md "Dataset card": shipped with every version, every part required."""

    contents: str
    collection_method: str
    intended_task: str
    known_biases: str
    must_not_claim: str

    def __post_init__(self) -> None:
        for name in (
            "contents",
            "collection_method",
            "intended_task",
            "known_biases",
            "must_not_claim",
        ):
            require_nonblank(getattr(self, name), f"DatasetCard.{name}")


@dataclass(frozen=True)
class AnnotationRound:
    """A labeling round and the guideline it was labeled under (docs/DATA.md leakage table)."""

    round_id: str
    guideline_ref: str

    def __post_init__(self) -> None:
        require_nonblank(self.round_id, "AnnotationRound.round_id")
        require_nonblank(self.guideline_ref, "AnnotationRound.guideline_ref")


# -- per-item attributes and recorded splits ---------------------------------


@dataclass(frozen=True)
class DatasetItem:
    """
    One dataset member and exactly the attributes the leakage checks read.

    `item_id` is opaque — an explicit id or a content hash, as docs/DATA.md's
    "split membership (hashes or explicit lists)" allows. `perceptual_hash` is
    a hex string *supplied by the caller*; this package never derives one.
    `subject_ids` is `None` when unknown and `()` when known to be empty (the
    two are different to the subject check). `timestamp` is ISO-8601 and only
    needed when the split policy declares a time order.
    """

    item_id: str
    segment_id: str
    camera_id: str
    annotation_round: str
    timestamp: str | None = None
    subject_ids: tuple[str, ...] | None = None
    perceptual_hash: str | None = None

    def __post_init__(self) -> None:
        for name in ("item_id", "segment_id", "camera_id", "annotation_round"):
            require_nonblank(getattr(self, name), f"DatasetItem.{name}")
        if self.timestamp is not None:
            require_timestamp(self.timestamp, "DatasetItem.timestamp")
        if self.subject_ids is not None:
            set_field(
                self,
                "subject_ids",
                as_str_tuple(self.subject_ids, "DatasetItem.subject_ids", allow_empty=True),
            )
        if self.perceptual_hash is not None:
            text = require_nonblank(self.perceptual_hash, "DatasetItem.perceptual_hash")
            if not _HEX.match(text):
                raise ValueError(
                    f"DatasetItem.perceptual_hash must be a hex string, got {text!r}"
                )


@dataclass(frozen=True)
class DatasetSplit:
    """One recorded split: its name and the exact ids of its members (docs/DATA.md rule 3)."""

    name: str
    item_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        require_nonblank(self.name, "DatasetSplit.name")
        ids = as_str_tuple(self.item_ids, "DatasetSplit.item_ids", allow_empty=False)
        reject_duplicates(ids, "DatasetSplit.item_ids entry")
        set_field(self, "item_ids", ids)


@dataclass(frozen=True)
class SplitPolicy:
    """
    docs/DATA.md "split policy", made checkable.

    `description` is the prose policy. The other fields are the explicit
    declarations the leakage table requires the author to make ("state which
    goal applies"): `camera_goal`; `time_order` (split names, earliest first,
    or None if the data has no motion/time dimension); `subject_isolation`
    (Re-ID / tracking tasks); `allow_mixed_annotation_guidelines` (mixing must
    be explicit, never silent); `max_hamming_distance` (0 = identical supplied
    hashes only — a looser tolerance is a deliberate, recorded choice).
    """

    description: str
    camera_goal: CameraGoal
    time_order: tuple[str, ...] | None = None
    subject_isolation: bool = False
    allow_mixed_annotation_guidelines: bool = False
    max_hamming_distance: int = 0

    def __post_init__(self) -> None:
        require_nonblank(self.description, "SplitPolicy.description")
        if self.camera_goal not in CAMERA_GOALS:
            raise ValueError(
                f"SplitPolicy.camera_goal must be one of {CAMERA_GOALS}, got {self.camera_goal!r}"
            )
        if self.time_order is not None:
            order = as_str_tuple(self.time_order, "SplitPolicy.time_order", allow_empty=False)
            if len(order) < 2:
                raise ValueError("SplitPolicy.time_order needs at least two split names")
            reject_duplicates(order, "SplitPolicy.time_order entry")
            set_field(self, "time_order", order)
        require_bool(self.subject_isolation, "SplitPolicy.subject_isolation")
        require_bool(
            self.allow_mixed_annotation_guidelines,
            "SplitPolicy.allow_mixed_annotation_guidelines",
        )
        require_nonneg_int(self.max_hamming_distance, "SplitPolicy.max_hamming_distance")
