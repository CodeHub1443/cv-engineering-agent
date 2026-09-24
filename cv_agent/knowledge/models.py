"""
cv_agent.knowledge.models — Provenance, KnowledgeItem, and source-class weighting.

Every type here validates itself at construction (fail-closed): a KnowledgeItem
cannot exist without well-formed Provenance. See ADR-0006 §3/§5.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, NewType

SourceClass = Literal[
    "peer_reviewed_research",
    "official_documentation",
    "official_repository_or_release_notes",
    "reputable_benchmark",
    "engineering_blog",
    "professional_post",
    "community_discussion",
    "model_zoo_or_leaderboard",
]

EvidenceWeight = Literal["high", "medium", "low_medium", "signal_not_evidence"]

# Verbatim from docs/RESEARCH_POLICY.md's source-class/evidence-weight table.
# Fixed and not independently settable per item — see ADR-0006 §3/§4 (the
# "per-item evidence_weight override" alternative was rejected precisely so a
# professional_post can never silently claim "high" weight).
_SOURCE_CLASS_WEIGHTS: dict[SourceClass, EvidenceWeight] = {
    "peer_reviewed_research": "high",
    "official_documentation": "high",
    "official_repository_or_release_notes": "high",
    "reputable_benchmark": "high",
    "engineering_blog": "medium",
    "professional_post": "signal_not_evidence",
    "community_discussion": "low_medium",
    "model_zoo_or_leaderboard": "medium",
}


def source_class_weight(source_class: SourceClass) -> EvidenceWeight:
    """Return the fixed evidence weight for a source class (docs/RESEARCH_POLICY.md)."""
    if source_class not in _SOURCE_CLASS_WEIGHTS:
        raise ValueError(f"Unknown source_class: {source_class!r}")
    return _SOURCE_CLASS_WEIGHTS[source_class]


ItemId = NewType("ItemId", str)


def _require_nonblank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string, got {value!r}")


def _require_iso_date(value: str, field_name: str) -> None:
    _require_nonblank(value, field_name)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be an ISO 8601 date (YYYY-MM-DD), got {value!r}"
        ) from exc


@dataclass(frozen=True)
class Provenance:
    """Required on every KnowledgeItem — see docs/RESEARCH_POLICY.md's provenance
    fields (URL, author/org, source class, date published, date accessed) and its
    rule: "A stored item missing provenance or date is deleted, not kept."
    """

    url: str
    source_class: SourceClass
    date_published: str
    date_accessed: str
    author_or_org: str

    def __post_init__(self) -> None:
        _require_nonblank(self.url, "Provenance.url")
        if self.source_class not in _SOURCE_CLASS_WEIGHTS:
            raise ValueError(f"Provenance.source_class is invalid: {self.source_class!r}")
        _require_iso_date(self.date_published, "Provenance.date_published")
        _require_iso_date(self.date_accessed, "Provenance.date_accessed")
        _require_nonblank(self.author_or_org, "Provenance.author_or_org")


@dataclass(frozen=True)
class KnowledgeItem:
    """A single stored claim. Cannot be constructed without valid Provenance."""

    item_id: ItemId
    claim: str
    conditions: str | None
    provenance: Provenance
    topic_tags: tuple[str, ...]
    staleness_horizon_days: int

    def __post_init__(self) -> None:
        _require_nonblank(str(self.item_id), "KnowledgeItem.item_id")
        _require_nonblank(self.claim, "KnowledgeItem.claim")
        if not isinstance(self.provenance, Provenance):
            raise ValueError("KnowledgeItem.provenance must be a Provenance instance")
        if not isinstance(self.topic_tags, tuple) or len(self.topic_tags) == 0:
            raise ValueError("KnowledgeItem.topic_tags must be a non-empty tuple")
        for tag in self.topic_tags:
            _require_nonblank(tag, "KnowledgeItem.topic_tags member")
        if self.staleness_horizon_days <= 0:
            raise ValueError(
                "KnowledgeItem.staleness_horizon_days must be > 0, got "
                f"{self.staleness_horizon_days!r}"
            )

    def evidence_weight(self) -> EvidenceWeight:
        return source_class_weight(self.provenance.source_class)

    def is_stale(self, as_of: date) -> bool:
        accessed = datetime.strptime(self.provenance.date_accessed, "%Y-%m-%d").date()
        return (as_of - accessed).days > self.staleness_horizon_days
