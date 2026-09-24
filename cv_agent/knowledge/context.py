"""
cv_agent.knowledge.context — bounded, deterministic context assembly (ADR-0006).

assemble_context() is the one function a reasoning node reads from. It performs
exact-match retrieval, a staleness cutoff, and a fully deterministic tie-break —
never a learned or fuzzy relevance ranking ([P§19]: RAG provides knowledge, the LLM
provides reasoning, they do not merge).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Collection

from cv_agent.knowledge.models import EvidenceWeight, KnowledgeItem, SourceClass
from cv_agent.knowledge.store import KnowledgeStore

_WEIGHT_RANK: dict[EvidenceWeight, int] = {
    "high": 3,
    "medium": 2,
    "low_medium": 1,
    "signal_not_evidence": 0,
}


@dataclass(frozen=True)
class ContextBundle:
    items: tuple[KnowledgeItem, ...]
    assembled_at: str
    query_topic_tags: tuple[str, ...]
    excluded_stale_count: int


def _sort_key(item: KnowledgeItem) -> tuple[int, int, str]:
    accessed = datetime.strptime(item.provenance.date_accessed, "%Y-%m-%d").date()
    return (
        -_WEIGHT_RANK[item.evidence_weight()],
        -accessed.toordinal(),
        str(item.item_id),
    )


def assemble_context(
    store: KnowledgeStore,
    *,
    topic_tags: Collection[str],
    as_of: date,
    max_items: int,
    source_class: SourceClass | None = None,
) -> ContextBundle:
    if max_items <= 0:
        raise ValueError(f"max_items must be > 0, got {max_items!r}")

    matched = store.query(topic_tags=topic_tags, source_class=source_class)
    fresh = [item for item in matched if not item.is_stale(as_of)]
    excluded_stale_count = len(matched) - len(fresh)

    fresh.sort(key=_sort_key)
    selected = tuple(fresh[:max_items])

    return ContextBundle(
        items=selected,
        assembled_at=datetime.now(timezone.utc).isoformat(),
        query_topic_tags=tuple(topic_tags),
        excluded_stale_count=excluded_stale_count,
    )
