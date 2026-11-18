"""ADR-0025 I1: the evaluation dataset reference stub imports and its types are frozen."""

from __future__ import annotations

import dataclasses

import pytest

from cv_agent.datasets.eval_ref import (
    DatasetId,
    EvalDatasetRef,
    EvalDatasetRefError,
)


def make_ref() -> EvalDatasetRef:
    return EvalDatasetRef(
        dataset_id=DatasetId("coco-val2017"),
        version="5k",
        images_dir="images/val2017",
        labels_dir="labels/val2017",
        list_file="val2017.txt",
        target_class=0,
        expected_images=5000,
        expected_instances=10777,
        ledger_label="coco-val2017-5k (val2017.txt sha256 {list_sha256})",
        spec_sha256="0" * 64,
    )


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
