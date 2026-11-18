"""
cv_agent.datasets.eval_ref — typed reference to one evaluation dataset version (ADR-0025).

Responsibility: identify the bytes an evaluation ran on. An `EvalDatasetRef` carries
the `(dataset_id, version)` key shared with ADR-0012 `[P§32]`, the layout, the target
and ignore classes, the expected counts, a label fingerprint (`label_digest`, closes
Q69's design) and the hash of the spec file it was loaded from (`spec_sha256`).

It is not a `DatasetManifest`: no items, splits or leakage checks. It does not read
images, measure anything, or convert formats (experiments and dataset ingestion own
those, ADR-0025 section 2).

INTERFACE STUBS ONLY (CLAUDE.md section 5): every body raises NotImplementedError.
There are no callers; I3 implements, I4 wires. Standard library only, enforced by
tests/test_datasets.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NewType

DatasetId = NewType("DatasetId", str)


class EvalDatasetRefError(ValueError):
    """A spec file or dataset directory does not match the reference (fail closed)."""


@dataclass(frozen=True, kw_only=True)
class EvalDatasetRef:
    """
    One evaluation dataset version.

    `label_digest` is sha256 over the images ordered lexicographically by stem; each
    image contributes its stem, a newline, then its sorted whitespace-normalised label
    lines (an empty label file: the stem only; a missing label file: the stem plus
    `<none>`). `spec_sha256` is sha256 of the raw bytes of `eval_dataset_ref.json` and
    must be recorded in run notes `[P§25]`.
    """

    dataset_id: DatasetId
    version: str
    images_dir: str
    labels_dir: str
    list_file: str
    target_class: int
    expected_images: int
    expected_instances: int
    ledger_label: str
    spec_sha256: str
    ignore_classes: tuple[int, ...] = ()
    label_digest: str | None = None

    def render_ledger_label(self, *, list_sha256: str) -> str:
        """The `dataset_version` string for the ledger (COCO must match its existing form)."""
        raise NotImplementedError("I3: ADR-0025 section 3.4")


def load_eval_dataset_ref(spec_path: Path) -> EvalDatasetRef:
    """Load `eval_dataset_ref.json`; reject unknown or missing keys; set `spec_sha256`."""
    raise NotImplementedError("I3: ADR-0025 section 3.2")


def compute_label_digest(ref: EvalDatasetRef, dataset_root: Path) -> str:
    """Compute the label digest of the listed images under `dataset_root`."""
    raise NotImplementedError("I3: ADR-0025 section 3.3")
