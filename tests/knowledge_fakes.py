"""Shared fixtures for the knowledge-store tests (ADR-0024): item builder, store openers and clock
poison. Not a test module; the test files import from here, never from each other."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from cv_agent.knowledge.models import IngestPath, ItemId, KnowledgeItem, Provenance
from cv_agent.knowledge.sqlite_store import SqliteKnowledgeStore
from cv_agent.knowledge.store import KNOWLEDGE_FILENAME, KnowledgeWriter


def _store_path(tmp_path: Path) -> Path:
    return tmp_path / "state" / KNOWLEDGE_FILENAME


def _fresh(tmp_path: Path) -> Path:
    path = _store_path(tmp_path)
    SqliteKnowledgeStore.initialise(path)
    return path


_NOW = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)


def _item(
    item_id: str = "research-aaa",
    claim: str = "YOLO11n reaches 39.5 mAP on COCO.",
    *,
    conditions: str | None = "640px, FP16",
    tags: tuple[str, ...] = ("detection", "edge"),
    horizon: int = 90,
    ingest: IngestPath = IngestPath.WEB_FETCH,
    accessed: str = "2026-11-01",
    source_class: Any = "official_documentation",
) -> KnowledgeItem:
    return KnowledgeItem(
        item_id=ItemId(item_id),
        claim=claim,
        conditions=conditions,
        provenance=Provenance(
            url="https://docs.example.org/yolo11",
            source_class=source_class,
            date_published="2026-01-05",
            date_accessed=accessed,
            author_or_org="Example Org",
        ),
        topic_tags=tags,
        staleness_horizon_days=horizon,
        ingest=ingest,
    )


def _open(path: Path, **kw: Any) -> SqliteKnowledgeStore:
    kw.setdefault("now", lambda: _NOW)
    return SqliteKnowledgeStore(path, writer=KnowledgeWriter.RESEARCH_CLI, **kw)


def _rows(path: Path) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT * FROM knowledge_revisions ORDER BY revision_id").fetchall()


class _PoisonedDatetime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> Any:  # type: ignore[override]
        raise AssertionError("the store read a clock")

    @classmethod
    def utcnow(cls) -> Any:
        raise AssertionError("the store read a clock")

    @classmethod
    def today(cls) -> Any:
        raise AssertionError("the store read a clock")


class _PoisonedDate(date):
    @classmethod
    def today(cls) -> Any:
        raise AssertionError("the store read a clock")
