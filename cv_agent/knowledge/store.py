"""
cv_agent.knowledge.store — KnowledgeStore protocol and the in-memory reference impl.

No durable backend ships here (ADR-0006 §3/§8) — picking one (files/SQLite/a
service) is an explicit future decision, mirroring OPEN_QUESTIONS.md's Q16 gap for
the experiment ledger.
"""

from __future__ import annotations

from datetime import date
from typing import Collection, Protocol

from cv_agent.knowledge.models import ItemId, KnowledgeItem, SourceClass


class KnowledgeStore(Protocol):
    """Deterministic storage/retrieval for KnowledgeItems. No embeddings, no ranking."""

    def put(self, item: KnowledgeItem) -> None: ...

    def get(self, item_id: ItemId) -> KnowledgeItem | None: ...

    def list_items(self) -> list[KnowledgeItem]: ...

    def query(
        self,
        *,
        topic_tags: Collection[str] | None = None,
        source_class: SourceClass | None = None,
        exclude_stale_as_of: date | None = None,
    ) -> list[KnowledgeItem]: ...


class InMemoryKnowledgeStore:
    """Reference KnowledgeStore implementation. In-process only — not durable across
    restarts. See ADR-0006 §8's revisit trigger for the future durable-backend
    decision.
    """

    def __init__(self) -> None:
        self._items: dict[ItemId, KnowledgeItem] = {}

    def put(self, item: KnowledgeItem) -> None:
        self._items[item.item_id] = item

    def get(self, item_id: ItemId) -> KnowledgeItem | None:
        return self._items.get(item_id)

    def list_items(self) -> list[KnowledgeItem]:
        return list(self._items.values())

    def query(
        self,
        *,
        topic_tags: Collection[str] | None = None,
        source_class: SourceClass | None = None,
        exclude_stale_as_of: date | None = None,
    ) -> list[KnowledgeItem]:
        wanted_tags = set(topic_tags) if topic_tags is not None else None
        results: list[KnowledgeItem] = []
        for item in self._items.values():
            if wanted_tags is not None and not wanted_tags.issubset(set(item.topic_tags)):
                continue
            if source_class is not None and item.provenance.source_class != source_class:
                continue
            if exclude_stale_as_of is not None and item.is_stale(exclude_stale_as_of):
                continue
            results.append(item)
        return results
