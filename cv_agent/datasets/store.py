"""
cv_agent.datasets.store — the storage-agnostic DatasetStore boundary.

Responsibility: the contract any place that keeps dataset manifests must honor.
It says nothing about *where* or *how* — no path, no file format, no database,
no blob or versioning backend. docs/DATA.md leaves that undecided (OPEN_QUESTIONS
Q10), and this module does not decide it: a concrete backend, when one is chosen,
implements this Protocol in its own module.

Only manifests (metadata) pass through this boundary. The data files themselves
are not handled here.
"""

from __future__ import annotations

from typing import Protocol

from cv_agent.datasets.manifest import DatasetManifest


class DatasetStoreError(Exception):
    """
    Raised when a store refuses or fails an operation (duplicate version, unknown
    lineage parent, a value that is not a manifest, a failing backend).

    Callers must not treat it as "not found" — that is `get_manifest()` returning
    `None`. Deliberately not a ValueError: the argument was well-formed; the
    store's state forbids the write.
    """


class DatasetStore(Protocol):
    """
    Contract for keeping immutable dataset manifests, keyed by `(dataset_id, version)`.

    Required behavior of every implementation:

    - `put_manifest` never overwrites: writing a key that already exists raises
      `DatasetStoreError` and leaves the stored manifest untouched (a dataset
      version is immutable; a change is a new version).
    - `put_manifest` requires the manifest's `lineage.parent_version`, when
      present, to already be stored under the same `dataset_id`; otherwise it
      raises `DatasetStoreError`.
    - A failed `put_manifest` leaves the store exactly as it was.
    - `get_manifest` returns the exact manifest that was stored, or `None` when
      no such `(dataset_id, version)` exists.
    - `list_versions` returns version strings for one dataset in the order they
      were stored (so a parent always precedes its children); an unknown
      `dataset_id` gives `()`.
    """

    def put_manifest(self, manifest: DatasetManifest) -> None: ...

    def get_manifest(self, dataset_id: str, version: str) -> DatasetManifest | None: ...

    def list_versions(self, dataset_id: str) -> tuple[str, ...]: ...
