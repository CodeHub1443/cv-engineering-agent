"""
cv_agent.model_selection.stored_evidence — which stored items back which candidate (ADR-0024 §3.7, K4).

Responsibility: join a candidate to the fresh items a knowledge store holds for it, by an exact match
on the candidate id after the single key normalisation rule (OQ3), and merge them with the candidate's
code-defined (curated) evidence. It owns no storage and no eligibility: it receives an object with
``search`` (it never opens a file), it does not filter on ``ingest`` or ``source_class`` (the payload
builder's ``PublicClaim.from_item`` excludes and counts), and it adds no cap (the builder's N, M and
water-fill run over the merged set). It never reads a clock: ``as_of`` is passed in.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from cv_agent.knowledge.models import KnowledgeItem
from cv_agent.knowledge.store import KnowledgeQuery, StoredItem
from cv_agent.model_selection.models import EvidenceReference, ModelCandidate


class StoredEvidenceSource(Protocol):
    """Anything with ``search``: ``SqliteKnowledgeStore`` or ``InMemoryKnowledgeStore``."""

    def search(self, query: KnowledgeQuery) -> list[StoredItem]: ...


def evidence_for_candidate(
    source: StoredEvidenceSource, candidate_id: str, *, as_of: date, topic_tags: tuple[str, ...] = ()
) -> tuple[KnowledgeItem, ...]:
    """The fresh items keyed to ``candidate_id``, in ``item_id`` order. Stale items are never included.

    A candidate id that is not an identifier token has no stored evidence (``()``), not an error.
    A store failure (``KnowledgeStoreError``) propagates: selection fails closed.
    """
    try:
        query = KnowledgeQuery(as_of=as_of, topic_tags=topic_tags, model_names=(candidate_id,))
    except ValueError:
        return ()
    return tuple(stored.item for stored in source.search(query))


def attach_stored_evidence(
    candidates: tuple[ModelCandidate, ...], source: StoredEvidenceSource, *, as_of: date
) -> tuple[ModelCandidate, ...]:
    """Each candidate's curated references first, then its stored items in ``item_id`` order.

    A stored item is dropped when its ``item_id`` or its exact ``(url, claim)`` is already present
    (curated wins). Stored items are not benchmark evidence: ``benchmark_evidence`` is unchanged.
    """
    out = []
    for cand in candidates:
        refs = list(cand.evidence_references)
        ids = {r.item_id for r in refs}
        pairs = {(r.url, r.claim) for r in refs}
        for item in evidence_for_candidate(source, cand.candidate_id, as_of=as_of):
            pair = (item.provenance.url, item.claim)
            if str(item.item_id) in ids or pair in pairs:
                continue
            ids.add(str(item.item_id))
            pairs.add(pair)
            refs.append(EvidenceReference.from_knowledge_item(item))
        out.append(
            ModelCandidate(
                candidate_id=cand.candidate_id,
                model_family=cand.model_family,
                task_support=cand.task_support,
                strengths=cand.strengths,
                limitations=cand.limitations,
                compatibility_constraints=cand.compatibility_constraints,
                evidence_references=tuple(refs),
                benchmark_evidence=cand.benchmark_evidence,
            )
        )
    return tuple(out)


__all__ = ["StoredEvidenceSource", "attach_stored_evidence", "evidence_for_candidate"]
