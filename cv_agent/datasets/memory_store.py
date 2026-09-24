"""
cv_agent.datasets.memory_store — in-memory reference DatasetStore.

Responsibility: the smallest correct implementation of the DatasetStore contract,
for deterministic tests and as the reference a future backend is checked against.
It is not durable and is not a backend choice: nothing survives the process, and
it carries no path, file or database concept (Q10 stays open).

State lives on the instance; nothing is module-global, so two stores never share
data.
"""

from __future__ import annotations

from cv_agent.datasets.manifest import DatasetManifest
from cv_agent.datasets.store import DatasetStoreError


class InMemoryDatasetStore:
    def __init__(self) -> None:
        self._manifests: dict[tuple[str, str], DatasetManifest] = {}

    def put_manifest(self, manifest: DatasetManifest) -> None:
        if not isinstance(manifest, DatasetManifest):
            raise DatasetStoreError(
                f"only a DatasetManifest can be stored, got {type(manifest).__name__}"
            )
        key = (manifest.dataset_id, manifest.version)
        if key in self._manifests:
            raise DatasetStoreError(
                f"dataset version {manifest.dataset_id!r}/{manifest.version!r} already exists; "
                "versions are immutable — publish a new version instead"
            )
        if manifest.lineage is not None:
            parent = (manifest.dataset_id, manifest.lineage.parent_version)
            if parent not in self._manifests:
                raise DatasetStoreError(
                    f"lineage parent {manifest.lineage.parent_version!r} of "
                    f"{manifest.dataset_id!r}/{manifest.version!r} is not stored "
                    "under the same dataset_id"
                )
        self._manifests[key] = manifest

    def get_manifest(self, dataset_id: str, version: str) -> DatasetManifest | None:
        return self._manifests.get((dataset_id, version))

    def list_versions(self, dataset_id: str) -> tuple[str, ...]:
        return tuple(v for (d, v) in self._manifests if d == dataset_id)
