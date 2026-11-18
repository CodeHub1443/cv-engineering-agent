"""ADR-0025 I3: EvalDatasetRef validation, strict spec loader, ledger label and label digest."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from cv_agent.datasets.eval_ref import (
    DatasetId,
    EvalDatasetRef,
    EvalDatasetRefError,
    compute_label_digest,
    load_eval_dataset_ref,
)

REPO = Path(__file__).resolve().parent.parent
COCO_SPEC = REPO / "docs" / "datasets" / "coco-val2017-person.eval_dataset_ref.json"
# Full sha256 of the restored val2017.txt: docs/experiments/EXP-20261116-01-proposal.md:14
# (the prefix 4d010d0d is also in docs/state/EXPERIMENTS.md:462).
COCO_LIST_SHA = "4d010d0d7200a7b9176acd164d36c9769350a2e41661152f2cf8ba16c9e2aa73"
COCO_LABEL = f"coco-val2017-5k (val2017.txt sha256 {COCO_LIST_SHA})"

SPEC: dict[str, Any] = {
    "dataset_id": "tiny",
    "version": "v1",
    "images_dir": "images",
    "labels_dir": "labels",
    "list_file": "list.txt",
    "target_class": 0,
    "ignore_classes": [],
    "expected_images": 2,
    "expected_instances": 1,
    "ledger_label": "tiny-v1 (list sha256 {list_sha256})",
    "label_digest": None,
}


def make_ref(**overrides: Any) -> EvalDatasetRef:
    fields: dict[str, Any] = {
        **{k: v for k, v in SPEC.items() if k != "ignore_classes"},
        "dataset_id": DatasetId("tiny"),
        "ignore_classes": (),
        "spec_sha256": "0" * 64,
    }
    fields.update(overrides)
    return EvalDatasetRef(**fields)


def write_spec(tmp_path: Path, **overrides: Any) -> Path:
    spec = {**SPEC, **overrides}
    spec = {k: v for k, v in spec.items() if v is not ...}  # `...` drops a key
    path = tmp_path / "eval_dataset_ref.json"
    path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return path


def make_dataset(root: Path, labels: dict[str, str | bytes | None], order: list[str] | None = None) -> None:
    """`labels` maps stem to label-file text (None: no label file). `order` is the list-file order."""
    (root / "images").mkdir(parents=True, exist_ok=True)
    (root / "labels").mkdir(parents=True, exist_ok=True)
    stems = order if order is not None else list(labels)
    (root / "list.txt").write_text("".join(f"./images/{s}.jpg\n" for s in stems), encoding="utf-8")
    for stem, text in labels.items():
        if text is None:
            continue
        data = text if isinstance(text, bytes) else text.encode("utf-8")
        (root / "labels" / f"{stem}.txt").write_bytes(data)


# ── I1 (kept): frozen types ────────────────────────────────────────────────────────────────────


def test_reference_is_frozen_including_spec_sha256() -> None:
    ref = make_ref()
    for attr in ("version", "spec_sha256", "label_digest", "ignore_classes"):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(ref, attr, "x")


def test_defaults() -> None:
    ref = make_ref()
    assert ref.ignore_classes == ()
    assert ref.label_digest is None


def test_error_is_a_value_error() -> None:
    assert issubclass(EvalDatasetRefError, ValueError)


# ── __post_init__ ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "overrides",
    [
        {"dataset_id": DatasetId("")},
        {"dataset_id": DatasetId("  ")},
        {"version": ""},
        {"images_dir": " "},
        {"labels_dir": ""},
        {"list_file": ""},
        {"ledger_label": ""},
        {"expected_images": -1},
        {"expected_instances": -1},
        {"expected_images": True},
        {"expected_images": 1.5},
        {"target_class": -1},
        {"target_class": True},
        {"target_class": 7, "ignore_classes": (7, 8)},
        {"ignore_classes": (8, 7)},
        {"ignore_classes": (7, 7)},
        {"ignore_classes": [7, 8]},
        {"ignore_classes": (True,)},
        {"spec_sha256": "0" * 63},
        {"spec_sha256": "A" * 64},
        {"spec_sha256": "g" * 64},
        {"label_digest": "A" * 64},
        {"label_digest": "ab"},
    ],
)
def test_invalid_fields_are_refused(overrides: dict[str, Any]) -> None:
    with pytest.raises(EvalDatasetRefError):
        make_ref(**overrides)


def test_valid_optional_fields_are_accepted() -> None:
    ref = make_ref(ignore_classes=(7, 8, 12), label_digest="a" * 64)
    assert ref.ignore_classes == (7, 8, 12)
    assert ref.label_digest == "a" * 64


# ── load_eval_dataset_ref ──────────────────────────────────────────────────────────────────────


def test_load_reads_every_field_and_hashes_the_raw_bytes(tmp_path: Path) -> None:
    path = write_spec(tmp_path, ignore_classes=[7, 8], label_digest="b" * 64)
    ref = load_eval_dataset_ref(path)
    assert ref.dataset_id == "tiny" and ref.version == "v1"
    assert ref.ignore_classes == (7, 8) and ref.label_digest == "b" * 64
    assert ref.expected_images == 2 and ref.target_class == 0
    assert ref.spec_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_spec_sha256_changes_with_whitespace_only_edits(tmp_path: Path) -> None:
    path = write_spec(tmp_path)
    first = load_eval_dataset_ref(path).spec_sha256
    path.write_bytes(path.read_bytes() + b"\n")
    assert load_eval_dataset_ref(path).spec_sha256 != first


@pytest.mark.parametrize("key", sorted(SPEC))
def test_missing_key_is_refused(tmp_path: Path, key: str) -> None:
    with pytest.raises(EvalDatasetRefError, match=key):
        load_eval_dataset_ref(write_spec(tmp_path, **{key: ...}))


def test_unknown_key_is_refused(tmp_path: Path) -> None:
    with pytest.raises(EvalDatasetRefError, match="surprise"):
        load_eval_dataset_ref(write_spec(tmp_path, surprise=1))


def test_spec_sha256_inside_the_json_is_refused(tmp_path: Path) -> None:
    with pytest.raises(EvalDatasetRefError, match="spec_sha256"):
        load_eval_dataset_ref(write_spec(tmp_path, spec_sha256="0" * 64))


def test_duplicate_keys_are_refused(tmp_path: Path) -> None:
    path = write_spec(tmp_path)
    text = path.read_text(encoding="utf-8").replace('"version": "v1",', '"version": "v1", "version": "v2",')
    path.write_text(text, encoding="utf-8")
    with pytest.raises(EvalDatasetRefError, match="duplicate"):
        load_eval_dataset_ref(path)


@pytest.mark.parametrize("text", ["[]", "42", "not json", "", '{"a": NaN}'])
def test_malformed_json_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "eval_dataset_ref.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(EvalDatasetRefError):
        load_eval_dataset_ref(path)


def test_bom_and_missing_file_are_refused(tmp_path: Path) -> None:
    path = write_spec(tmp_path)
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    with pytest.raises(EvalDatasetRefError):
        load_eval_dataset_ref(path)
    with pytest.raises(EvalDatasetRefError):
        load_eval_dataset_ref(tmp_path / "nope.json")


def test_unsorted_ignore_classes_in_a_spec_are_refused_not_sorted(tmp_path: Path) -> None:
    with pytest.raises(EvalDatasetRefError):
        load_eval_dataset_ref(write_spec(tmp_path, ignore_classes=[8, 7]))


def test_ignore_classes_must_be_a_list(tmp_path: Path) -> None:
    with pytest.raises(EvalDatasetRefError):
        load_eval_dataset_ref(write_spec(tmp_path, ignore_classes="7"))


# ── render_ledger_label ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "template",
    ["{other}", "{}", "{0}", "{list_sha256!r}", "{list_sha256:>9}", "{list_sha256", "x}", "{list_sha256.upper}"],
)
def test_template_accepts_only_the_list_sha256_placeholder(template: str) -> None:
    with pytest.raises(EvalDatasetRefError):
        make_ref(ledger_label=template)


def test_render_fills_the_placeholder_and_keeps_escaped_braces() -> None:
    ref = make_ref(ledger_label="x {{literal}} {list_sha256}")
    assert ref.render_ledger_label(list_sha256="a" * 64) == "x {literal} " + "a" * 64


@pytest.mark.parametrize("bad", ["", "a" * 63, "A" * 64, "z" * 64])
def test_render_refuses_a_malformed_list_hash(bad: str) -> None:
    with pytest.raises(EvalDatasetRefError):
        make_ref().render_ledger_label(list_sha256=bad)


# ── compute_label_digest ───────────────────────────────────────────────────────────────────────


def test_digest_golden_bytes(tmp_path: Path) -> None:
    make_dataset(tmp_path, {"b": "0 1 2 3 4\n", "a": None})
    expected = hashlib.sha256(b"a\n<none>\nb\n0 1 2 3 4\n").hexdigest()
    assert compute_label_digest(make_ref(), tmp_path) == expected


def test_digest_is_independent_of_list_file_order(tmp_path: Path) -> None:
    labels: dict[str, str | bytes | None] = {"a": "0 1 2 3 4\n", "b": "0 5 6 7 8\n", "c": None}
    make_dataset(tmp_path / "x", labels, order=["a", "b", "c"])
    make_dataset(tmp_path / "y", labels, order=["c", "b", "a"])
    assert compute_label_digest(make_ref(), tmp_path / "x") == compute_label_digest(make_ref(), tmp_path / "y")


def test_digest_is_independent_of_line_order_and_whitespace(tmp_path: Path) -> None:
    make_dataset(tmp_path / "x", {"a": "0 1 2 3 4\n0 5 6 7 8\n"})
    make_dataset(tmp_path / "y", {"a": "0  5\t6 7 8 \n\n  0 1 2 3 4\r\n"})
    assert compute_label_digest(make_ref(), tmp_path / "x") == compute_label_digest(make_ref(), tmp_path / "y")


def test_empty_and_missing_label_files_differ(tmp_path: Path) -> None:
    make_dataset(tmp_path / "empty", {"a": ""})
    make_dataset(tmp_path / "missing", {"a": None})
    make_dataset(tmp_path / "blank", {"a": "  \n\n"})
    empty = compute_label_digest(make_ref(), tmp_path / "empty")
    assert empty != compute_label_digest(make_ref(), tmp_path / "missing")
    assert empty == hashlib.sha256(b"a\n").hexdigest()
    assert compute_label_digest(make_ref(), tmp_path / "blank") == empty


def test_duplicate_label_lines_are_not_collapsed(tmp_path: Path) -> None:
    make_dataset(tmp_path, {"a": "0 1 2 3 4\n0 1 2 3 4\n"})
    assert compute_label_digest(make_ref(), tmp_path) == hashlib.sha256(b"a\n0 1 2 3 4\n0 1 2 3 4\n").hexdigest()


def test_digest_changes_when_a_label_changes(tmp_path: Path) -> None:
    make_dataset(tmp_path / "x", {"a": "0 1 2 3 4\n"})
    make_dataset(tmp_path / "y", {"a": "0 1 2 3 5\n"})
    assert compute_label_digest(make_ref(), tmp_path / "x") != compute_label_digest(make_ref(), tmp_path / "y")


def test_digest_does_not_compare_with_the_ref_digest(tmp_path: Path) -> None:
    make_dataset(tmp_path, {"a": "0 1 2 3 4\n"})
    assert len(compute_label_digest(make_ref(label_digest="f" * 64), tmp_path)) == 64


def test_label_file_with_a_bom_is_refused(tmp_path: Path) -> None:
    make_dataset(tmp_path, {"a": b"\xef\xbb\xbf0 1 2 3 4\n"})
    with pytest.raises(EvalDatasetRefError, match="BOM"):
        compute_label_digest(make_ref(), tmp_path)


def test_list_file_with_a_bom_is_refused(tmp_path: Path) -> None:
    make_dataset(tmp_path, {"a": "0 1 2 3 4\n"})
    (tmp_path / "list.txt").write_bytes(b"\xef\xbb\xbf./images/a.jpg\n")
    with pytest.raises(EvalDatasetRefError, match="BOM"):
        compute_label_digest(make_ref(), tmp_path)


def test_non_utf8_label_file_is_refused(tmp_path: Path) -> None:
    make_dataset(tmp_path, {"a": b"\xff\xfe0 1\n"})
    with pytest.raises(EvalDatasetRefError):
        compute_label_digest(make_ref(), tmp_path)


def test_list_entry_escaping_the_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    make_dataset(root, {"a": "0 1 2 3 4\n"})
    (root / "list.txt").write_text("../outside.jpg\n", encoding="utf-8")
    with pytest.raises(EvalDatasetRefError, match="outside"):
        compute_label_digest(make_ref(), root)


def test_absolute_list_entry_outside_the_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    make_dataset(root, {"a": "0 1 2 3 4\n"})
    (root / "list.txt").write_text(str(tmp_path / "elsewhere.jpg") + "\n", encoding="utf-8")
    with pytest.raises(EvalDatasetRefError, match="outside"):
        compute_label_digest(make_ref(), root)


def test_labels_dir_or_list_file_escaping_the_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    make_dataset(root, {"a": "0 1 2 3 4\n"})
    with pytest.raises(EvalDatasetRefError, match="outside"):
        compute_label_digest(make_ref(labels_dir="../labels"), root)
    with pytest.raises(EvalDatasetRefError, match="outside"):
        compute_label_digest(make_ref(list_file="../list.txt"), root)


def test_duplicate_stems_and_missing_inputs_are_refused(tmp_path: Path) -> None:
    make_dataset(tmp_path, {"a": "0 1 2 3 4\n"})
    (tmp_path / "list.txt").write_text("./images/a.jpg\n./other/a.png\n", encoding="utf-8")
    with pytest.raises(EvalDatasetRefError, match="duplicate"):
        compute_label_digest(make_ref(), tmp_path)
    with pytest.raises(EvalDatasetRefError):
        compute_label_digest(make_ref(), tmp_path / "no-such-root")
    (tmp_path / "list.txt").unlink()
    with pytest.raises(EvalDatasetRefError):
        compute_label_digest(make_ref(), tmp_path)


def test_label_path_that_is_a_directory_is_refused(tmp_path: Path) -> None:
    make_dataset(tmp_path, {"a": None})
    (tmp_path / "labels" / "a.txt").mkdir()
    with pytest.raises(EvalDatasetRefError):
        compute_label_digest(make_ref(), tmp_path)


# ── the COCO spec ──────────────────────────────────────────────────────────────────────────────


def test_coco_spec_loads_with_the_documented_values() -> None:
    ref = load_eval_dataset_ref(COCO_SPEC)
    assert (ref.dataset_id, ref.version) == ("coco-val2017", "5k")
    assert (ref.images_dir, ref.labels_dir, ref.list_file) == ("images/val2017", "labels/val2017", "val2017.txt")
    assert (ref.target_class, ref.ignore_classes) == (0, ())
    assert (ref.expected_images, ref.expected_instances) == (5000, 10777)
    assert ref.label_digest is None  # computed on the Linux PC (I4 records it)
    assert ref.spec_sha256 == hashlib.sha256(COCO_SPEC.read_bytes()).hexdigest()


def test_coco_ledger_label_reproduces_the_existing_string_byte_for_byte() -> None:
    assert COCO_LIST_SHA.startswith("4d010d0d") and len(COCO_LIST_SHA) == 64
    ref = load_eval_dataset_ref(COCO_SPEC)
    assert ref.render_ledger_label(list_sha256=COCO_LIST_SHA) == COCO_LABEL
    # Tie the expectation to the recorder's own f-string (read as text; experiments is not imported).
    source = (REPO / "cv_agent" / "experiments" / "evaluation_records.py").read_text(encoding="utf-8")
    assert 'dataset_version=f"coco-val2017-5k (val2017.txt sha256 {run.val_txt_sha256})"' in source
