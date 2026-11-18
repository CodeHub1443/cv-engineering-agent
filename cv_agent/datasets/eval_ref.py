"""
cv_agent.datasets.eval_ref — typed reference to one evaluation dataset version (ADR-0025).

Responsibility: identify the bytes an evaluation ran on. An `EvalDatasetRef` carries
the `(dataset_id, version)` key shared with ADR-0012 `[P§32]`, the layout, the target
and ignore classes, the expected counts, a label fingerprint (`label_digest`, closes
Q69's design) and the hash of the spec file it was loaded from (`spec_sha256`).

It is not a `DatasetManifest`: no items, splits or leakage checks. It does not read
images, measure anything, or convert formats (experiments and dataset ingestion own
those, ADR-0025 section 2).

Implements ADR-0025 sections 3.1 to 3.4 (I3). I4a wires it into the wrapper, recorder
and `verify_run`. Standard library only, enforced by
tests/test_datasets.py. Everything fails closed with `EvalDatasetRefError`.
"""

from __future__ import annotations

import hashlib
import json
import re
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NewType

DatasetId = NewType("DatasetId", str)

_HEX64 = re.compile(r"[0-9a-f]{64}")
_BOM = "﻿"
_PLACEHOLDER = "list_sha256"
_SPEC_KEYS = frozenset(
    {
        "dataset_id", "version", "images_dir", "labels_dir", "list_file", "target_class",
        "ignore_classes", "expected_images", "expected_instances", "ledger_label", "label_digest",
    }
)


class EvalDatasetRefError(ValueError):
    """A spec file or dataset directory does not match the reference (fail closed)."""


def _text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EvalDatasetRefError(f"{name} must be a non-blank string")


def _count(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise EvalDatasetRefError(f"{name} must be an integer >= 0")


def _check_template(template: str) -> None:
    """Only the `{list_sha256}` placeholder, with no conversion or format spec, is allowed."""
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise EvalDatasetRefError(f"ledger_label is not a valid template: {exc}") from exc
    for _literal, field, spec, conversion in parsed:
        if field is None:
            continue
        if field != _PLACEHOLDER or spec or conversion:
            raise EvalDatasetRefError(f"ledger_label may only use the plain {{{_PLACEHOLDER}}} placeholder")


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

    def __post_init__(self) -> None:
        for name in ("dataset_id", "version", "images_dir", "labels_dir", "list_file", "ledger_label"):
            _text(name, getattr(self, name))
        for name in ("target_class", "expected_images", "expected_instances"):
            _count(name, getattr(self, name))
        ignored = self.ignore_classes
        if not isinstance(ignored, tuple):
            raise EvalDatasetRefError("ignore_classes must be a tuple of integers")
        for item in ignored:
            _count("ignore_classes item", item)
        if any(a >= b for a, b in zip(ignored, ignored[1:])):
            raise EvalDatasetRefError("ignore_classes must be sorted ascending with no duplicates")
        if self.target_class in ignored:
            raise EvalDatasetRefError("target_class must not be in ignore_classes")
        if not isinstance(self.spec_sha256, str) or not _HEX64.fullmatch(self.spec_sha256):
            raise EvalDatasetRefError("spec_sha256 must be 64 lowercase hex characters")
        if self.label_digest is not None and (
            not isinstance(self.label_digest, str) or not _HEX64.fullmatch(self.label_digest)
        ):
            raise EvalDatasetRefError("label_digest must be None or 64 lowercase hex characters")
        _check_template(self.ledger_label)

    def render_ledger_label(self, *, list_sha256: str) -> str:
        """The `dataset_version` string for the ledger (COCO must match its existing form)."""
        if not isinstance(list_sha256, str) or not _HEX64.fullmatch(list_sha256):
            raise EvalDatasetRefError("list_sha256 must be 64 lowercase hex characters")
        return self.ledger_label.format(list_sha256=list_sha256)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise EvalDatasetRefError("spec has a duplicate key")
    return dict(pairs)


def _reject_constant(name: str) -> Any:
    raise EvalDatasetRefError(f"spec contains the non-JSON constant {name}")


def load_eval_dataset_ref(spec_path: Path) -> EvalDatasetRef:
    """Load `eval_dataset_ref.json`; reject unknown or missing keys; set `spec_sha256`."""
    try:
        raw = Path(spec_path).read_bytes()
    except OSError as exc:
        raise EvalDatasetRefError(f"cannot read spec {spec_path}: {exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant)
    except EvalDatasetRefError:
        raise
    except ValueError as exc:  # UnicodeDecodeError and JSONDecodeError are both ValueErrors
        raise EvalDatasetRefError(f"spec {spec_path} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise EvalDatasetRefError("spec must be a JSON object")
    if "spec_sha256" in data:
        raise EvalDatasetRefError("spec must not contain spec_sha256: it is computed from the file bytes")
    missing, unknown = sorted(_SPEC_KEYS - data.keys()), sorted(data.keys() - _SPEC_KEYS)
    if missing or unknown:
        raise EvalDatasetRefError(f"spec keys do not match: missing {missing}, unknown {unknown}")
    ignored = data["ignore_classes"]
    if not isinstance(ignored, list):
        raise EvalDatasetRefError("ignore_classes must be a JSON list")
    return EvalDatasetRef(
        **{**data, "dataset_id": DatasetId(data["dataset_id"]), "ignore_classes": tuple(ignored)},
        spec_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _inside(root: Path, relative: str, what: str) -> Path:
    try:
        path = (root / relative).resolve()
    except (OSError, ValueError) as exc:
        raise EvalDatasetRefError(f"{what} {relative!r} cannot be resolved: {exc}") from exc
    if not path.is_relative_to(root):
        raise EvalDatasetRefError(f"{what} {relative!r} is outside the dataset root")
    return path


def _read_utf8(path: Path, what: str) -> str:
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvalDatasetRefError(f"cannot read {what} {path}: {exc}") from exc
    if text.startswith(_BOM):
        raise EvalDatasetRefError(f"{what} {path} starts with a UTF-8 BOM")
    return text


def eval_items(ref: EvalDatasetRef, dataset_root: Path) -> tuple[tuple[str, Path, Path], ...]:
    """
    The listed images as `(stem, image_path, label_path)`, sorted by stem (ADR-0025 section 3.3).

    The only reader of the list file: a file starting with a UTF-8 BOM, an entry leaving
    the root and a repeated stem all raise. The label path is `<labels_dir>/<stem>.txt`
    and may not exist; the image path is the list entry resolved under the root.
    """
    try:
        root = Path(dataset_root).resolve(strict=True)
    except OSError as exc:
        raise EvalDatasetRefError(f"dataset root {dataset_root} is not readable: {exc}") from exc
    labels_dir = _inside(root, ref.labels_dir, "labels_dir")
    listing = _read_utf8(_inside(root, ref.list_file, "list_file"), "list file")
    items: dict[str, tuple[str, Path, Path]] = {}
    for line in listing.split("\n"):
        entry = line.strip()
        if not entry:
            continue
        image = _inside(root, entry, "list entry")
        stem = Path(entry).stem
        if stem in items:
            raise EvalDatasetRefError("list file has a duplicate image stem")
        items[stem] = (stem, image, labels_dir / f"{stem}.txt")
    return tuple(items[stem] for stem in sorted(items))


def compute_label_digest(ref: EvalDatasetRef, dataset_root: Path) -> str:
    """
    Compute the label digest of the listed images under `dataset_root` (ADR-0025 section 3.3).

    sha256 over UTF-8 bytes. For each listed image, in lexicographic order of its stem:
    `stem + "\\n"`, then `"<none>\\n"` if `<labels_dir>/<stem>.txt` does not exist, else each
    non-empty label line, whitespace-normalised (`" ".join(line.split())`), sorted, each
    followed by `"\\n"`. An empty label file therefore contributes the stem only. A file
    starting with a UTF-8 BOM, a path leaving the root and a repeated stem all raise.
    This does not compare with `ref.label_digest`; the caller does (I4a).
    """
    digest = hashlib.sha256()
    for stem, _image, label_path in eval_items(ref, dataset_root):
        digest.update(f"{stem}\n".encode())
        if not label_path.exists():
            digest.update(b"<none>\n")
            continue
        normalised = (" ".join(part.split()) for part in _read_utf8(label_path, "label file").split("\n"))
        for text in sorted(line for line in normalised if line):  # duplicate lines both count
            digest.update(f"{text}\n".encode())
    return digest.hexdigest()
