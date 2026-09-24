"""
cv_agent.datasets — the storage-agnostic Dataset Core (ADR-0012, ROADMAP Phase 5a).

Owns the typed, immutable dataset manifest / version contract from
docs/DATA.md, recorded splits, deterministic leakage checks over supplied
attributes, and a DatasetStore protocol with an in-memory reference
implementation.

Deliberately does not: choose or implement a data/versioning backend (Q10 —
open), read images or compute perceptual hashes (hashes are supplied), acquire
or annotate data, run training or baselines, or wire itself into CVAgent, the
graph or the experiment ledger. It imports only the standard library and itself
— enforced by tests/test_datasets.py's structural tests.
"""

from cv_agent.datasets.leakage import (
    CheckResult,
    LeakageError,
    LeakageFinding,
    LeakageReport,
    check_leakage,
)
from cv_agent.datasets.manifest import DatasetManifest
from cv_agent.datasets.memory_store import InMemoryDatasetStore
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
)
from cv_agent.datasets.store import DatasetStore, DatasetStoreError

__all__ = [
    "AnnotationRound",
    "CheckResult",
    "ClassCount",
    "ClassDefinition",
    "CollectionConditions",
    "DatasetCard",
    "DatasetItem",
    "DatasetManifest",
    "DatasetSplit",
    "DatasetStore",
    "DatasetStoreError",
    "InMemoryDatasetStore",
    "LeakageError",
    "LeakageFinding",
    "LeakageReport",
    "Lineage",
    "SplitPolicy",
    "check_leakage",
]
