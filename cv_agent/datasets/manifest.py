"""
cv_agent.datasets.manifest — the immutable dataset manifest (one dataset version).

Responsibility: hold, validate and freeze every field docs/DATA.md lists for a
manifest, and refuse to exist unless the recorded split passes every leakage
check. docs/DATA.md: "Every dataset has a version and a manifest" and "The check
result is recorded in the manifest" — so `DatasetManifest` *is* the dataset
version, identified by `(dataset_id, version)`, and its `leakage_report` is
computed at construction and cannot be supplied by a caller.

Immutability is structural: frozen dataclasses, tuples instead of lists, no
mutating method. "Relabel produces a new annotation version, never an in-place
edit" (docs/DATA.md rule 2) is therefore a new manifest with a new `version`
and a `lineage` pointing at its parent — never an update.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cv_agent.datasets.leakage import LeakageError, LeakageReport, check_leakage
from cv_agent.datasets.models import (
    AnnotationRound,
    ClassCount,
    ClassDefinition,
    CollectionConditions,
    DatasetCard,
    DatasetItem,
    DatasetSplit,
    Lineage,
    SplitPolicy,
    as_str_tuple,
    as_tuple,
    reject_duplicates,
    require_nonblank,
    require_timestamp,
    set_field,
)


@dataclass(frozen=True, kw_only=True)
class DatasetManifest:
    """
    One immutable dataset version.

    Field names follow docs/DATA.md's manifest list: `dataset_id`, `version`,
    `created`, `sources`, class definitions (`classes`), `class_distribution`,
    split membership (`splits`, over `items`), `split_policy`,
    `annotation_version`, `annotation_guideline_reference`, `known_issues`,
    `lineage`, `license`, `collection_conditions`; plus the version's dataset
    `card`. `n_items` is derived (`len(items)`), not stored, so it cannot
    disagree with the items. `annotation_rounds` maps each labeling round to
    its guideline for the annotation-round leakage check (ADR-0012 §3).
    """

    dataset_id: str
    version: str
    created: str
    sources: tuple[str, ...]
    classes: tuple[ClassDefinition, ...]
    class_distribution: tuple[ClassCount, ...]
    items: tuple[DatasetItem, ...]
    splits: tuple[DatasetSplit, ...]
    split_policy: SplitPolicy
    annotation_version: str
    annotation_guideline_reference: str
    annotation_rounds: tuple[AnnotationRound, ...]
    license: str
    collection_conditions: CollectionConditions
    card: DatasetCard
    known_issues: tuple[str, ...] = ()
    lineage: Lineage | None = None
    leakage_report: LeakageReport = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "dataset_id",
            "version",
            "annotation_version",
            "annotation_guideline_reference",
            "license",
        ):
            require_nonblank(getattr(self, name), f"DatasetManifest.{name}")
        require_timestamp(self.created, "DatasetManifest.created")

        set_field(self, "sources", as_str_tuple(self.sources, "sources", allow_empty=False))
        set_field(self, "known_issues", as_str_tuple(self.known_issues, "known_issues", allow_empty=True))
        set_field(self, "classes", as_tuple(self.classes, "classes", ClassDefinition))
        set_field(
            self,
            "class_distribution",
            as_tuple(self.class_distribution, "class_distribution", ClassCount),
        )
        set_field(self, "items", as_tuple(self.items, "items", DatasetItem))
        set_field(self, "splits", as_tuple(self.splits, "splits", DatasetSplit))
        set_field(
            self,
            "annotation_rounds",
            as_tuple(self.annotation_rounds, "annotation_rounds", AnnotationRound),
        )
        for name, expected in (
            ("split_policy", SplitPolicy),
            ("collection_conditions", CollectionConditions),
            ("card", DatasetCard),
        ):
            if not isinstance(getattr(self, name), expected):
                raise ValueError(f"{name} must be a {expected.__name__}")
        if self.lineage is not None:
            if not isinstance(self.lineage, Lineage):
                raise ValueError("lineage must be a Lineage or None")
            if self.lineage.parent_version == self.version:
                raise ValueError("a dataset version cannot be its own parent")

        self._validate_classes()
        self._validate_items_and_splits()

        set_field(
            self,
            "leakage_report",
            check_leakage(self.items, self.splits, self.split_policy, self.annotation_rounds),
        )
        if not self.leakage_report.passed:
            raise LeakageError(self.leakage_report)

    def _validate_classes(self) -> None:
        if not self.classes:
            raise ValueError("classes must not be empty: a dataset needs class definitions")
        reject_duplicates((c.name for c in self.classes), "class name")
        defined = {c.name for c in self.classes}
        reject_duplicates((c.class_name for c in self.class_distribution), "class_distribution entry")
        for count in self.class_distribution:
            if count.class_name not in defined:
                raise ValueError(
                    f"class_distribution names undefined class {count.class_name!r}"
                )

    def _validate_items_and_splits(self) -> None:
        if not self.items:
            raise ValueError("items must not be empty")
        reject_duplicates((i.item_id for i in self.items), "item_id")
        if not self.annotation_rounds:
            raise ValueError("annotation_rounds must not be empty")
        reject_duplicates((r.round_id for r in self.annotation_rounds), "annotation round")
        rounds = {r.round_id for r in self.annotation_rounds}
        cameras = set(self.collection_conditions.cameras)
        for it in self.items:
            if it.camera_id not in cameras:
                raise ValueError(
                    f"item {it.item_id!r} uses camera {it.camera_id!r} which is not in "
                    "collection_conditions.cameras"
                )
            if it.annotation_round not in rounds:
                raise ValueError(
                    f"item {it.item_id!r} has annotation_round {it.annotation_round!r} "
                    "which is not declared in annotation_rounds"
                )
        if not self.splits:
            raise ValueError("splits must not be empty")
        reject_duplicates((s.name for s in self.splits), "split name")
        order = self.split_policy.time_order
        if order is not None:
            names = {s.name for s in self.splits}
            unknown = [n for n in order if n not in names]
            if unknown:
                raise ValueError(f"split_policy.time_order names unknown splits {unknown}")

    @property
    def n_items(self) -> int:
        return len(self.items)

    def split_of(self, item_id: str) -> str:
        """Name of the split that holds `item_id`; KeyError if it is not in this dataset."""
        for split in self.splits:
            if item_id in split.item_ids:
                return split.name
        raise KeyError(item_id)
