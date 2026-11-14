"""
cv_agent.knowledge.store — KnowledgeStore protocol and the in-memory reference impl.

The durable backend is ``cv_agent.knowledge.sqlite_store`` (ADR-0024, answering
ADR-0006 §8). This module stays backend-neutral: the Protocol, the in-memory reference
implementation, and the small types a durable backend shares (filename, error, writer).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Collection, Final, Protocol

from cv_agent.knowledge.models import ItemId, KnowledgeItem, SourceClass

KNOWLEDGE_FILENAME: Final = "knowledge.sqlite"
# One identifier-token rule for retrieval keys (ADR-0024 §3.3). graph/research.py adopts it in K3.
RETRIEVAL_KEY_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+:-]{0,63}")


class KnowledgeStoreError(Exception):
    """The durable store is missing, of another schema version, corrupt, busy or unwritable.

    Never means "no data" (that is ``get() -> None``). Messages carry the init or migrate hint.
    """


class KnowledgeWriter(str, Enum):
    """Who wrote a revision (ADR-0024 §5). CURATED_REFERENCE is added only if curated items move in."""

    RESEARCH_CLI = "research_cli"


def normalise_key(value: str) -> str:
    """The single key rule, applied at write and read: strip, token fullmatch (else ValueError), lower."""
    if not isinstance(value, str):
        raise ValueError(f"retrieval key must be a string, got {value!r}")
    stripped = value.strip()
    if RETRIEVAL_KEY_PATTERN.fullmatch(stripped) is None:
        raise ValueError(f"retrieval key {value!r} is not an identifier token ({RETRIEVAL_KEY_PATTERN.pattern})")
    return stripped.lower()


@dataclass(frozen=True)
class RetrievalKeys:
    """Store-level retrieval metadata recorded next to a revision (ADR-0024 §3.3); not a KnowledgeItem field."""

    model_names: tuple[str, ...] = ()
    metric: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.model_names, str):
            raise TypeError("RetrievalKeys.model_names must be a sequence of names, not a bare string")
        names = tuple(dict.fromkeys(normalise_key(n) for n in self.model_names))  # first occurrence wins
        object.__setattr__(self, "model_names", names)
        if self.metric is not None:
            object.__setattr__(self, "metric", normalise_key(self.metric))


@dataclass(frozen=True)
class StoredItem:
    """One stored revision: the item, its keys, and when/by whom it was recorded."""

    item: KnowledgeItem
    keys: RetrievalKeys
    revision: int
    recorded_at: str  # UTC ISO 8601 'Z'
    writer: KnowledgeWriter
    stale: bool  # item.is_stale(as_of) for the as_of the caller passed


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
